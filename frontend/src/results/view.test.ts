// What the results screen shows. Two kinds of test: small analyses written by hand, so that every
// number is the one the test says; and the real analysis of each demo household (a JSON snapshot of
// what the backend returns, see the note in ../form/mapping.test.ts), which keeps the hand-written
// types honest and checks what must hold for any household.

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { describe, it } from 'node:test'
import type {
  AnalysisResult,
  Confidence,
  ExplanationFact,
  Portfolio,
  PortfolioDelta,
  PortfolioEvaluation,
  Range,
  Recommendation,
  Role,
  Strength,
} from '../api/results.ts'
import type { MobilityOptionSummary } from '../api/types.ts'
import { buildResultsView, effectsSentence } from './view.ts'

function fixture<T>(name: string): T {
  return JSON.parse(
    readFileSync(new URL(`../form/fixtures/${name}`, import.meta.url), 'utf-8'),
  ) as T
}

const options = fixture<MobilityOptionSummary[]>('mobility_options.json')
const analyses = fixture<Record<string, AnalysisResult>>('analyses.json')

// --- an analysis written by hand ---------------------------------------------------------

const point = (value: number): Range => ({ low: value, expected: value, high: value })
const spread = (low: number, expected: number, high: number): Range => ({ low, expected, high })

function evaluation(
  id: string,
  cost: number,
  hoursPerYear: number,
  comfort: number,
  carKm: number,
  delta: PortfolioDelta | null,
  confidence: Confidence = 'MEDIUM',
): PortfolioEvaluation {
  return {
    portfolio_id: id,
    annual_cost: spread(cost - 400, cost, cost + 500),
    annual_travel_hours: point(hoursPerYear),
    comfort: point(comfort),
    flexibility: point(7),
    car_km_per_year: point(carKm),
    co2_kg_per_year: point(1000),
    private_vehicles_owned: 1,
    delta,
    confidence,
    data_quality_notes: [],
  }
}

function delta(saving: number, extraHours: number, comfort: number): PortfolioDelta {
  return {
    cost: spread(-saving - 300, -saving, -saving + 300),
    travel_hours: point(extraHours),
    perceived_hours: point(extraHours),
    comfort: point(comfort),
    flexibility: point(0),
    car_km: point(0),
    co2_kg: point(0),
    saving_per_extra_hour: saving > 0 && extraHours > 1 ? saving / extraHours : null,
  }
}

function portfolio(id: string, name: string, items: [string, number][], description?: string): Portfolio {
  return {
    id,
    name,
    origin: id === 'current' ? 'CURRENT' : 'GENERATED',
    items: items.map(([option_id, quantity]) => ({
      option_id,
      holder_id: null,
      quantity,
      profile_ref: null,
    })),
    description: description ?? null,
    changes: [],
  }
}

function fact(code: string, values: Record<string, number | string> = {}): ExplanationFact {
  return { code, values }
}

function recommendation(
  id: string,
  roles: Role[],
  strength: Strength,
  d: PortfolioDelta | null,
  facts: [ExplanationFact, string][],
): Recommendation {
  return {
    portfolio_id: id,
    roles,
    category: id === 'current' ? 'KEEP_CURRENT' : 'REDUCE_VEHICLES',
    strength,
    delta: d,
    change_penalty: d ? 400 : null,
    net_benefit: d ? spread(800, 1200, 1500) : null,
    facts: facts.map(([f]) => f),
    explanation: facts.map(([, sentence]) => sentence),
    confidence: 'MEDIUM',
  }
}

const OPTION_ROWS = [
  { id: 'car_small_petrol', name: 'Utilitaria a benzina', type: 'CAR_SMALL_PETROL', mode: 'CAR', ownership: 'OWNED' },
  { id: 'e_bike', name: 'E-bike', type: 'E_BIKE', mode: 'E_BIKE', ownership: 'OWNED' },
  { id: 'pt_pass', name: 'Abbonamento urbano', type: 'PT_ANNUAL', mode: 'PUBLIC_TRANSPORT', ownership: 'SUBSCRIPTION' },
  { id: 'taxi', name: 'Taxi', type: 'TAXI', mode: 'TAXI', ownership: 'PAY_PER_USE' },
  { id: 'walking', name: 'A piedi', type: 'WALKING', mode: 'WALK', ownership: 'FREE' },
].map((row) => ({ ...row, min_age: null, max_age: null })) as MobilityOptionSummary[]

function handmade(headline: 'current' | 'saver'): AnalysisResult {
  const saver = delta(3000, 60, -1.2)
  const quick = delta(-500, -40, 0.3)
  const reasons: [ExplanationFact, string][] = [
    [fact('verdict', { strength: 'STRONG_OPPORTUNITY' }), 'È un’opportunità forte.'],
    [fact('changes', { text: 'x' }), 'Cosa cambia: x.'],
    [fact('saving'), 'Risparmi circa 3.000 € l’anno.'],
    [fact('dropped_item_cost'), 'L’auto ti costa oggi circa 4.000 € l’anno.'],
    [fact('second_car_needed'), 'Una seconda auto serve solo per 40 giorni l’anno.'],
    [fact('services_cost'), 'Useresti taxi per circa 300 € l’anno.'],
    [fact('extra_time'), 'Passeresti circa 60 ore in più.'],
    [fact('comfort'), 'Il comfort scende.'],
    [fact('saving_per_extra_hour'), 'Risparmi circa 50 € per ogni ora in più.'],
    [fact('net_benefit'), 'Il vantaggio netto è di circa 1.200 € l’anno.'],
    [fact('environment'), 'Km in auto: da 6.000 a 0.'],
    [fact('confidence', { level: 'MEDIUM' }), 'Affidabilità della stima: media.'],
  ]
  return {
    profile_id: 'test',
    scenario: null,
    parameters_version: 'v',
    portfolios: [
      portfolio('current', 'Situazione attuale', [
        ['car_small_petrol', 1],
        ['pt_pass', 2],
        ['taxi', 1],
        ['walking', 1],
      ]),
      portfolio('saver', 'Senza auto', [['pt_pass', 2], ['e_bike', 1], ['taxi', 1]], 'Vendere «Utilitaria a benzina».'),
      portfolio('quick', 'Con scooter', [['car_small_petrol', 1]], 'Acquistare «Scooter».'),
    ],
    current: evaluation('current', 5000, 500, 7, 6000, null),
    evaluations: [
      evaluation('saver', 2000, 560, 5.8, 0, saver),
      evaluation('quick', 5500, 460, 7.3, 5000, quick),
    ],
    rejected: [
      {
        portfolio_id: 'x',
        name: 'Senza auto e senza abbonamenti',
        description: null,
        issues: [
          { mission_id: 'm', severity: 'BLOCKING', code: 'NO_OPTION', message: 'Primo motivo.' },
          { mission_id: 'm', severity: 'BLOCKING', code: 'NO_OPTION', message: 'Secondo motivo.' },
          { mission_id: 'm', severity: 'BLOCKING', code: 'NO_OPTION', message: 'Terzo motivo.' },
        ],
      },
    ],
    recommendations: {
      headline_portfolio_id: headline,
      pareto_portfolio_ids: [],
      accuracy_hints: [{ field: 'car1.annual_km', message: 'Indica i km.', reduction_eur: 300 }],
      recommendations: [
        recommendation('current', ['CURRENT'], 'KEEP_CURRENT', null, [[fact('current_cost'), 'Costa 5.000 €.']]),
        recommendation('quick', ['FASTEST'], 'KEEP_CURRENT', quick, reasons.slice(0, 4)),
        recommendation('saver', ['CHEAPEST', 'BALANCED'], 'STRONG_OPPORTUNITY', saver, reasons),
      ],
    },
  }
}

// --- the answer ---------------------------------------------------------------------------

describe('the verdict', () => {
  it('says to change when an alternative is worth it, and leads with the saving', () => {
    const { verdict } = buildResultsView(handmade('saver'), OPTION_ROWS)
    assert.equal(verdict.keep, false)
    assert.equal(verdict.title, 'Ti conviene cambiare.')
    assert.equal(verdict.hero.value, '3.000 €')
    assert.equal(verdict.hero.label, 'di risparmio ogni anno')
    assert.equal(verdict.hero.range, 'tra 2.700 e 3.300 €')
    assert.equal(verdict.pickId, 'saver')
    assert.equal(verdict.action, 'Vendere «Utilitaria a benzina».')
    assert.equal(verdict.strength?.label, 'Ottima opportunità')
  })

  it('says what it costs in time, in words', () => {
    const { verdict } = buildResultsView(handmade('saver'), OPTION_ROWS)
    assert.equal(verdict.lead, 'Risparmi circa 3.000 € l’anno e passi circa 60 ore in più in viaggio.')
  })

  it('says to keep what you have, with today’s cost as the figure', () => {
    const { verdict } = buildResultsView(handmade('current'), OPTION_ROWS)
    assert.equal(verdict.keep, true)
    assert.equal(verdict.title, 'Tieni la configurazione che hai.')
    assert.equal(verdict.hero.value, '5.000 €')
    assert.equal(verdict.hero.label, 'è quanto ti costa oggi ogni anno')
    assert.match(verdict.lead, /Abbiamo confrontato 2 alternative e ne abbiamo scartate 1/)
    assert.equal(verdict.pickId, null)
    assert.equal(verdict.action, null)
  })

  it('leads with the time saved when the pick costs money but gives time back', () => {
    const result = handmade('saver')
    const pick = result.recommendations.recommendations.find((r) => r.portfolio_id === 'saver')!
    pick.delta = delta(-200, -70, 0.4)
    const { verdict } = buildResultsView(result, OPTION_ROWS)
    assert.equal(verdict.hero.value, '70 ore')
    assert.equal(verdict.hero.label, 'di viaggio in meno ogni anno')
  })

  it('leads with the time given back when the money saved is small', () => {
    const result = handmade('saver')
    const pick = result.recommendations.recommendations.find((r) => r.portfolio_id === 'saver')!
    pick.delta = delta(75, -18, 0.3)
    const { verdict } = buildResultsView(result, OPTION_ROWS)
    assert.equal(verdict.hero.value, '18 ore')
    assert.equal(verdict.hero.label, 'di viaggio in meno ogni anno')
  })

  it('has a sentence for every combination of money and time', () => {
    assert.equal(effectsSentence(delta(0, 0, 0)), 'Costo e tempo restano quasi gli stessi.')
    assert.equal(effectsSentence(delta(900, 0, 0)), 'Risparmi circa 900 € l’anno.')
    assert.equal(effectsSentence(delta(-600, -30, 0)), 'Spendi circa 600 € in più l’anno e passi circa 30 ore in meno in viaggio.')
    assert.equal(effectsSentence(delta(0, 1, 0)), 'Costo e tempo restano quasi gli stessi.')
  })
})

// --- today and the cards ------------------------------------------------------------------

describe('what you have today', () => {
  it('lists vehicles and passes, not walking or the services everybody has', () => {
    const { today } = buildResultsView(handmade('saver'), OPTION_ROWS)
    assert.deepEqual(
      today.composition.map((item) => item.text),
      ['Utilitaria a benzina', '2 × Abbonamento urbano'],
    )
  })

  it('shows the range of the cost, and the weakest link of the confidence', () => {
    const { today } = buildResultsView(handmade('saver'), OPTION_ROWS)
    assert.equal(today.metrics[0]!.value, '5.000 €')
    assert.equal(today.metrics[0]!.detail, 'tra 4.600 e 5.500 €')
    assert.equal(today.metrics[0]!.change, null)
    assert.equal(today.confidence.label, 'Media')
  })
})

describe('the cards', () => {
  const view = buildResultsView(handmade('saver'), OPTION_ROWS)

  it('lead with the pick, then keep the order of the recommendations', () => {
    assert.deepEqual(view.cards.map((c) => c.id), ['saver', 'quick'])
    assert.equal(view.cards[0]!.isPick, true)
    assert.equal(view.cards[1]!.isPick, false)
  })

  it('name the roles in plain words', () => {
    assert.deepEqual(view.cards[0]!.roles, ['Più economica', 'Miglior equilibrio'])
    assert.deepEqual(view.cards[1]!.roles, ['Più veloce'])
  })

  it('show what the alternative would be made of', () => {
    assert.deepEqual(
      view.cards[0]!.composition.map((i) => i.text),
      ['E-bike', '2 × Abbonamento urbano'],
    )
  })

  it('put every change against today, coloured by whether it is good for the household', () => {
    const [cost, time, comfort] = view.cards[0]!.metrics
    assert.deepEqual(cost!.change, { text: '−3.000 €', tone: 'good' })
    assert.deepEqual(time!.change, { text: '+60 h', tone: 'bad' })
    assert.deepEqual(comfort!.change, { text: '−1,2', tone: 'bad' })
    const [quickCost, quickTime, quickComfort] = view.cards[1]!.metrics
    assert.equal(quickCost!.change?.tone, 'bad') // it costs more
    assert.equal(quickTime!.change?.tone, 'good')
    assert.equal(quickComfort!.change?.tone, 'good')
  })

  it('call a change too small to matter neutral', () => {
    const result = handmade('saver')
    const small = delta(10, 1, 0.02)
    result.evaluations[0]!.delta = small
    result.recommendations.recommendations.find((r) => r.portfolio_id === 'saver')!.delta = small
    const card = buildResultsView(result, OPTION_ROWS).cards.find((c) => c.id === 'saver')!
    assert.deepEqual(card.metrics.map((m) => m.change?.tone), ['neutral', 'neutral', 'neutral'])
  })

  it('weigh it all in one sentence, then give the reasons, a few at a time', () => {
    const card = view.cards[0]!
    assert.equal(card.bottomLine, 'Il vantaggio netto è di circa 1.200 € l’anno.')
    // not repeated: the verdict, what changes, the figures already on the card, the confidence
    assert.deepEqual(card.reasons, [
      'L’auto ti costa oggi circa 4.000 € l’anno.',
      'Una seconda auto serve solo per 40 giorni l’anno.',
    ])
    assert.deepEqual(card.moreReasons, [
      'Useresti taxi per circa 300 € l’anno.',
      'Risparmi circa 50 € per ogni ora in più.',
      'Km in auto: da 6.000 a 0.',
    ])
  })

  it('say how strongly it is recommended', () => {
    assert.equal(view.cards[0]!.strength.label, 'Ottima opportunità')
    assert.equal(view.cards[1]!.strength.label, 'Non conviene')
    assert.equal(view.cards[1]!.strength.level, 0)
  })
})

// --- the comparison -----------------------------------------------------------------------

describe('the charts and the table', () => {
  const view = buildResultsView(handmade('saver'), OPTION_ROWS)

  it('compare cost, time and comfort, today first', () => {
    assert.deepEqual(view.charts.map((c) => c.id), ['cost', 'hours', 'comfort'])
    for (const chart of view.charts) {
      assert.equal(chart.rows[0]!.label, 'Oggi')
      assert.equal(chart.rows[0]!.tone, 'today')
      assert.equal(chart.rows.length, 3)
    }
  })

  it('mark the pick and name the rest by their role', () => {
    const cost = view.charts[0]!
    assert.deepEqual(cost.rows.map((r) => r.label), ['Oggi', 'Più economica', 'Più veloce'])
    assert.deepEqual(cost.rows.map((r) => r.tone), ['today', 'pick', 'option'])
  })

  it('scale the bars from zero, comfort out of ten', () => {
    const [cost, hoursChart, comfort] = view.charts
    assert.equal(cost!.max, 5500)
    assert.equal(hoursChart!.max, 560)
    assert.equal(comfort!.max, 10)
  })

  it('carry the figure, and the difference from today in the tooltip', () => {
    const row = view.charts[0]!.rows[1]!
    assert.equal(row.display, '2.000 €')
    assert.equal(row.title, 'Senza auto: 2.000 € (−3.000 € rispetto a oggi)')
    assert.equal(view.charts[0]!.rows[0]!.title, 'La tua situazione oggi: 5.000 €')
  })

  it('give the same numbers as a table', () => {
    assert.deepEqual(view.table.map((r) => r.label), ['Oggi', 'Più economica', 'Più veloce'])
    assert.deepEqual(view.table[1], {
      id: 'saver',
      label: 'Più economica',
      name: 'Senza auto',
      cost: '2.000 €',
      hours: '560 h',
      comfort: '5,8',
      carKm: '0 km',
    })
  })
})

describe('what did not work, and how sure we are', () => {
  const view = buildResultsView(handmade('saver'), OPTION_ROWS)

  it('gives at most two reasons for a rejected setup', () => {
    assert.deepEqual(view.rejected, [
      { id: 'x', name: 'Senza auto e senza abbonamenti', reasons: ['Primo motivo.', 'Secondo motivo.'] },
    ])
  })

  it('passes on what would make the estimate better', () => {
    assert.deepEqual(view.hints, ['Indica i km.'])
  })
})

describe('when there is nothing to compare', () => {
  it('says so, and keeps what you have', () => {
    const result = handmade('current')
    result.evaluations = []
    result.rejected = []
    result.recommendations.recommendations = [result.recommendations.recommendations[0]!]
    const view = buildResultsView(result, OPTION_ROWS)
    assert.equal(view.cards.length, 0)
    assert.equal(view.verdict.keep, true)
    assert.match(view.verdict.lead, /Non abbiamo trovato alternative praticabili/)
  })
})

// --- the real analyses ---------------------------------------------------------------------

describe('the demo households, as the backend analyses them', () => {
  for (const [name, result] of Object.entries(analyses)) {
    describe(name, () => {
      const view = buildResultsView(result, options)

      it('has an answer, today, and the figures a person reads', () => {
        assert.ok(view.verdict.title.length > 0)
        assert.match(view.verdict.hero.value, /^[\d.]+ (€|ore|ora)$/)
        assert.equal(view.today.metrics.length, 3)
        assert.equal(view.charts.length, 3)
      })

      it('shows each alternative once, with the three figures against today', () => {
        const ids = view.cards.map((card) => card.id)
        assert.equal(new Set(ids).size, ids.length)
        for (const card of view.cards) {
          assert.equal(card.metrics.length, 3)
          assert.ok(card.metrics.every((metric) => metric.change !== null), card.id)
          assert.ok(card.name.length > 0 && card.action.length > 0)
        }
      })

      it('puts the pick first, and only if the answer is to change', () => {
        assert.equal(view.verdict.keep, view.verdict.pickId === null)
        if (view.verdict.pickId) assert.equal(view.cards[0]!.id, view.verdict.pickId)
        assert.equal(view.cards.filter((card) => card.isPick).length, view.verdict.keep ? 0 : 1)
      })

      it('charts the same portfolios as the cards, today first', () => {
        for (const chart of view.charts) {
          assert.deepEqual(chart.rows.map((r) => r.id), ['current', ...view.cards.map((c) => c.id)])
          assert.ok(chart.rows.every((r) => r.value >= 0 && r.display.length > 0))
        }
        assert.equal(view.table.length, view.cards.length + 1)
      })

      it('never prints a decimal for money, nor an unrounded figure', () => {
        const texts = [
          view.verdict.lead,
          view.verdict.hero.value,
          ...view.cards.flatMap((c) => [...c.reasons, ...c.moreReasons, c.bottomLine ?? '']),
          ...view.table.flatMap((r) => [r.cost, r.hours, r.carKm]),
        ]
        for (const text of texts) assert.doesNotMatch(text, /\d,\d\d\b/, text)
      })

      it('lists the setups that cannot work, each with a reason', () => {
        assert.equal(view.rejected.length, result.rejected.length)
        for (const entry of view.rejected) assert.ok(entry.reasons.length > 0, entry.name)
      })
    })
  }

  it('tells the family that needs two cars to keep them', () => {
    const view = buildResultsView(analyses.family_two_cars!, options)
    assert.equal(view.verdict.keep, true)
    assert.ok(view.rejected.length > 0)
  })

  it('tells the single who barely uses the car to consider giving it up', () => {
    const view = buildResultsView(analyses.urban_single!, options)
    assert.equal(view.verdict.keep, false)
    assert.equal(view.verdict.title, 'Ti conviene cambiare.')
  })
})
