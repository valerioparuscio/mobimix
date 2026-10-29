// The "what if" panel without a browser: what the sliders offer, what is sent, how the assumptions
// and the change of answer are worded.

import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import {
  answerChange,
  CONTROLS,
  describeActive,
  isNeutral,
  NEUTRAL_SCENARIO,
  parseScenario,
  sameScenario,
  signedPercent,
  toBody,
} from './scenario.ts'
import type { ResultsView } from './view.ts'

describe('what the sliders hold', () => {
  it('starts neutral, and anything moved is not', () => {
    assert.equal(isNeutral(NEUTRAL_SCENARIO), true)
    assert.equal(isNeutral({ ...NEUTRAL_SCENARIO, fuelPct: 5 }), false)
    assert.equal(isNeutral({ ...NEUTRAL_SCENARIO, ebikeSubsidy: 50 }), false)
  })

  it('compares two settings', () => {
    assert.equal(sameScenario(NEUTRAL_SCENARIO, { ...NEUTRAL_SCENARIO }), true)
    assert.equal(sameScenario(NEUTRAL_SCENARIO, { ...NEUTRAL_SCENARIO, carKmPct: -5 }), false)
  })

  it('offers each control within the bounds the server accepts', () => {
    // backend/app/models/scenario.py: remote 0-4, fuel -50%..+100%, parking -100%..+200%,
    // car km -50%..+100%, e-bike 0-2,000 EUR
    const server = {
      remoteDays: [0, 4],
      fuelPct: [-50, 100],
      parkingPct: [-100, 200],
      carKmPct: [-50, 100],
      ebikeSubsidy: [0, 2000],
    } as const
    assert.deepEqual(CONTROLS.map((c) => c.key).sort(), Object.keys(server).sort())
    for (const control of CONTROLS) {
      const [low, high] = server[control.key]
      assert.ok(control.min >= low && control.max <= high, control.key)
      assert.ok(control.min <= 0 && control.max > 0, `${control.key} must be able to stay as it is`)
      assert.equal((control.max - control.min) % control.step, 0, `${control.key} step`)
    }
  })
})

describe('what is sent', () => {
  it('turns the percentages into fractions', () => {
    assert.deepEqual(
      toBody({ remoteDays: 2, fuelPct: 20, parkingPct: -100, carKmPct: -15, ebikeSubsidy: 400 }),
      {
        extra_remote_days_per_week: 2,
        fuel_price_change: 0.2,
        parking_cost_change: -1,
        car_km_change: -0.15,
        ebike_subsidy_eur: 400,
      },
    )
  })

  it('is all zeros for the neutral scenario', () => {
    assert.deepEqual(Object.values(toBody(NEUTRAL_SCENARIO)), [0, 0, 0, 0, 0])
  })
})

describe('the words', () => {
  it('signs percentages with a real minus', () => {
    assert.equal(signedPercent(20), '+20%')
    assert.equal(signedPercent(-10), '−10%')
    assert.equal(signedPercent(0), '0%')
  })

  it('says nothing about what has not changed', () => {
    assert.deepEqual(describeActive(NEUTRAL_SCENARIO), [])
  })

  it('names each assumption that has', () => {
    assert.deepEqual(
      describeActive({ remoteDays: 1, fuelPct: 30, parkingPct: -100, carKmPct: -10, ebikeSubsidy: 500 }),
      [
        '1 giorno in più da remoto',
        'carburante +30%',
        'parcheggio gratis',
        'km in auto −10%',
        'incentivo e-bike 500 €',
      ],
    )
    assert.deepEqual(describeActive({ ...NEUTRAL_SCENARIO, remoteDays: 3, parkingPct: 50 }), [
      '3 giorni in più da remoto',
      'parcheggio +50%',
    ])
  })

  it('reads each value as a person would', () => {
    const show = (key: string, value: number) => CONTROLS.find((c) => c.key === key)!.show(value)
    assert.equal(show('remoteDays', 0), 'Come adesso')
    assert.equal(show('remoteDays', 1), '+1 giorno a settimana')
    assert.equal(show('remoteDays', 2), '+2 giorni a settimana')
    assert.equal(show('fuelPct', 0), 'Come oggi')
    assert.equal(show('parkingPct', -100), 'Gratis')
    assert.equal(show('ebikeSubsidy', 0), 'Nessuno')
    assert.equal(show('ebikeSubsidy', 450), '450 €')
  })
})

describe('a link for development', () => {
  it('reads the assumptions from text', () => {
    assert.deepEqual(parseScenario('remoteDays:2,fuelPct:30'), {
      ...NEUTRAL_SCENARIO,
      remoteDays: 2,
      fuelPct: 30,
    })
  })

  it('keeps each one within its slider', () => {
    assert.equal(parseScenario('fuelPct:500').fuelPct, 50)
    assert.equal(parseScenario('parkingPct:-500').parkingPct, -100)
    assert.equal(parseScenario('remoteDays:-1').remoteDays, 0)
  })

  it('ignores what it cannot read', () => {
    assert.deepEqual(parseScenario(null), NEUTRAL_SCENARIO)
    assert.deepEqual(parseScenario('nonsense,fuelPct:abc,:3,unknown:4'), NEUTRAL_SCENARIO)
  })
})

// --- when the answer changes ----------------------------------------------------------------------

function view(keep: boolean, pickId: string | null, pickName: string | null): ResultsView {
  return {
    verdict: { keep, pickId },
    cards: pickId ? [{ id: pickId, name: pickName, isPick: true }] : [],
  } as unknown as ResultsView
}

describe('the answer against the one without assumptions', () => {
  it('says nothing while the answer is to keep what you have', () => {
    assert.equal(answerChange(view(true, null, null), view(true, null, null)), null)
  })

  it('says when a change becomes worth it', () => {
    assert.equal(
      answerChange(view(true, null, null), view(false, 'x', 'Senza auto')),
      'Con queste ipotesi la risposta cambia: ora ti conviene «Senza auto».',
    )
  })

  it('says when it stops being worth it', () => {
    assert.equal(
      answerChange(view(false, 'x', 'Senza auto'), view(true, null, null)),
      'Con queste ipotesi la risposta cambia: non conviene più cambiare.',
    )
  })

  it('says when another change becomes the best one', () => {
    assert.equal(
      answerChange(view(false, 'x', 'Senza auto'), view(false, 'y', 'Con e-bike')),
      'Con queste ipotesi la scelta migliore cambia: ora «Con e-bike».',
    )
  })

  it('says nothing when the best change stays the same', () => {
    assert.equal(answerChange(view(false, 'x', 'A'), view(false, 'x', 'A')), null)
  })
})
