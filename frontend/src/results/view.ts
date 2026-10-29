// From the analysis to what the results screen shows: plain-language labels, rounded figures,
// the order of the cards, the rows of the charts. Pure functions, no React: the screen only
// lays out what this returns, and the tests read the same thing.

import type {
  AnalysisResult,
  Category,
  Confidence,
  PortfolioDelta,
  PortfolioEvaluation,
  Portfolio,
  Recommendation,
  Role,
  Strength,
} from '../api/results.ts'
import type { MobilityOptionSummary } from '../api/types.ts'
import {
  euroRange,
  euros,
  hours,
  hoursInText,
  kilometres,
  score,
  signedEuros,
  signedHours,
  signedScore,
} from './format.ts'

export type Tone = 'good' | 'bad' | 'neutral'

export const ROLE_LABELS: Record<Role, string> = {
  CURRENT: 'Oggi',
  CHEAPEST: 'Più economica',
  BALANCED: 'Miglior equilibrio',
  FASTEST: 'Più veloce',
  MOST_COMFORTABLE: 'Più comoda',
}

/** How strongly a change is recommended, in words a person would use; `level` drives the badge. */
export const STRENGTH_LABELS: Record<Strength, { label: string; level: 0 | 1 | 2 | 3 }> = {
  KEEP_CURRENT: { label: 'Non conviene', level: 0 },
  SMALL_IMPROVEMENT: { label: 'Piccolo miglioramento', level: 1 },
  CONSIDER_CHANGE: { label: 'Da valutare', level: 2 },
  STRONG_OPPORTUNITY: { label: 'Ottima opportunità', level: 3 },
}

export const CATEGORY_LABELS: Record<Category, string> = {
  KEEP_CURRENT: 'Resta com’è',
  OPTIMIZE_USAGE: 'Usa meglio quello che hai',
  CHANGE_SUBSCRIPTION: 'Cambia abbonamento',
  ADD_ASSET: 'Aggiungi un mezzo',
  REPLACE_VEHICLE: 'Sostituisci un veicolo',
  REDUCE_VEHICLES: 'Riduci i veicoli',
  CHANGE_PORTFOLIO: 'Cambia assetto',
}

export const CONFIDENCE_LABELS: Record<Confidence, { label: string; level: 1 | 2 | 3 }> = {
  LOW: { label: 'Bassa', level: 1 },
  MEDIUM: { label: 'Media', level: 2 },
  HIGH: { label: 'Alta', level: 3 },
}

// --- the pieces ---------------------------------------------------------------------------

export interface Change {
  text: string
  tone: Tone
}

export interface Metric {
  label: string
  value: string
  /** The uncertainty, where it is worth saying ("tra 4.150 e 5.900 €"). */
  detail: string | null
  /** Against today; none for today itself. */
  change: Change | null
}

export interface CompositionItem {
  icon: string
  text: string
}

export interface CardView {
  id: string
  roles: string[]
  isPick: boolean
  name: string
  /** What the household would do ("Vendere «…»; acquistare «…»"). */
  action: string
  category: string
  strength: { label: string; level: 0 | 1 | 2 | 3 }
  composition: CompositionItem[]
  metrics: Metric[]
  carKm: string
  /** The sentence that weighs it all ("Contando anche il tempo… il vantaggio netto è…"). */
  bottomLine: string | null
  reasons: string[]
  moreReasons: string[]
  confidence: { label: string; level: 1 | 2 | 3 }
}

export interface TodayView {
  composition: CompositionItem[]
  metrics: Metric[]
  carKm: string
  notes: string[]
  confidence: { label: string; level: 1 | 2 | 3 }
}

export interface VerdictView {
  keep: boolean
  title: string
  lead: string
  /** What changes, if something does. */
  action: string | null
  hero: { value: string; label: string; range: string | null }
  pickId: string | null
  strength: { label: string; level: 0 | 1 | 2 | 3 } | null
}

export interface BarRow {
  id: string
  label: string
  name: string
  value: number
  display: string
  tone: 'today' | 'option' | 'pick'
  /** For the tooltip: the name and the figure against today. */
  title: string
}

export interface ChartView {
  id: 'cost' | 'hours' | 'comfort'
  title: string
  caption: string
  rows: BarRow[]
  max: number
}

export interface TableRow {
  id: string
  label: string
  name: string
  cost: string
  hours: string
  comfort: string
  carKm: string
}

export interface ResultsView {
  verdict: VerdictView
  today: TodayView
  cards: CardView[]
  charts: ChartView[]
  table: TableRow[]
  rejected: { id: string; name: string; reasons: string[] }[]
  hints: string[]
}

// --- helpers --------------------------------------------------------------------------------

const ICONS: Record<string, string> = {
  CAR: '🚗',
  MOTORCYCLE: '🛵',
  BICYCLE: '🚲',
  E_BIKE: '⚡',
  PUBLIC_TRANSPORT: '🚇',
  RAIL: '🚆',
}

function iconFor(option: MobilityOptionSummary | undefined): string {
  return (option && ICONS[option.mode]) || '•'
}

/** The vehicles and passes of a portfolio. Walking and the pay-per-use services every
 * household has the same way are left out: they are not what is being decided. */
export function composition(
  portfolio: Portfolio,
  options: Map<string, MobilityOptionSummary>,
): CompositionItem[] {
  const counts = new Map<string, number>()
  for (const item of portfolio.items) {
    const option = options.get(item.option_id)
    if (option?.ownership !== 'OWNED' && option?.ownership !== 'SUBSCRIPTION') continue
    counts.set(item.option_id, (counts.get(item.option_id) ?? 0) + item.quantity)
  }
  const items = [...counts].map(([id, count]) => {
    const option = options.get(id)
    return { option, text: `${count > 1 ? `${count} × ` : ''}${option?.name ?? id}` }
  })
  // vehicles first, then subscriptions
  items.sort(
    (a, b) =>
      Number(a.option?.ownership === 'SUBSCRIPTION') -
      Number(b.option?.ownership === 'SUBSCRIPTION'),
  )
  return items.map(({ option, text }) => ({ icon: iconFor(option), text }))
}

function sign(value: number, goodWhenNegative: boolean, scale: number): Tone {
  if (Math.abs(value) < scale) return 'neutral'
  return value < 0 === goodWhenNegative ? 'good' : 'bad'
}

function metricsOf(
  evaluation: PortfolioEvaluation,
  delta: PortfolioDelta | null,
  withRange: boolean,
): Metric[] {
  const cost = evaluation.annual_cost
  const costChange =
    delta === null
      ? null
      : { text: signedEuros(delta.cost.expected), tone: sign(delta.cost.expected, true, 25) }
  const hoursChange =
    delta === null
      ? null
      : {
          text: signedHours(delta.travel_hours.expected),
          tone: sign(delta.travel_hours.expected, true, 2),
        }
  const comfortChange =
    delta === null
      ? null
      : {
          text: signedScore(delta.comfort.expected),
          tone: sign(delta.comfort.expected, false, 0.1),
        }
  return [
    {
      label: withRange ? 'Costo ogni anno' : 'Costo l’anno',
      value: euros(cost.expected),
      detail: withRange ? euroRange(cost.low, cost.high) : null,
      change: costChange,
    },
    {
      label: withRange ? 'Tempo in viaggio' : 'Ore in viaggio',
      value: withRange
        ? `${hours(evaluation.annual_travel_hours.expected)} l’anno`
        : hours(evaluation.annual_travel_hours.expected),
      detail: null,
      change: hoursChange,
    },
    {
      label: 'Comfort',
      value: withRange
        ? `${score(evaluation.comfort.expected)} su 10`
        : `${score(evaluation.comfort.expected)}/10`,
      detail: null,
      change: comfortChange,
    },
  ]
}

function carKmLine(current: PortfolioEvaluation, other: PortfolioEvaluation | null): string {
  if (other === null) return `Km in auto: ${kilometres(current.car_km_per_year.expected)} l’anno`
  return `Km in auto: da ${kilometres(current.car_km_per_year.expected)} a ${kilometres(other.car_km_per_year.expected)}`
}

/** What a candidate does to the household's money and time, as one sentence. */
export function effectsSentence(delta: PortfolioDelta): string {
  const parts: string[] = []
  const money = delta.cost.expected
  if (money <= -50) parts.push(`risparmi circa ${euros(money)} l’anno`)
  else if (money >= 50) parts.push(`spendi circa ${euros(money)} in più l’anno`)
  const time = delta.travel_hours.expected
  if (time >= 2) parts.push(`passi circa ${hoursInText(time)} in più in viaggio`)
  else if (time <= -2) parts.push(`passi circa ${hoursInText(time)} in meno in viaggio`)
  if (parts.length === 0) return 'Costo e tempo restano quasi gli stessi.'
  const sentence = parts.join(' e ')
  return `${sentence[0]!.toUpperCase()}${sentence.slice(1)}.`
}

// The facts worth showing under a card, in the order the explanation tells them. The ones the card
// already shows as figures (saving, time, comfort) and the verdict line are left out.
const REASON_CODES = [
  'dropped_item_cost',
  'second_car_needed',
  'services_cost',
  'saving_per_extra_hour',
  'not_worth_the_time',
  'tiny_gain',
  'environment',
]

function reasonsOf(recommendation: Recommendation): { bottomLine: string | null; lines: string[] } {
  let bottomLine: string | null = null
  const lines: string[] = []
  recommendation.facts.forEach((fact, index) => {
    const sentence = recommendation.explanation[index]
    if (sentence === undefined) return
    if (fact.code === 'net_benefit') bottomLine = sentence
    else if (REASON_CODES.includes(fact.code)) lines.push(sentence)
  })
  return { bottomLine, lines }
}

const MAX_REASONS = 2

// --- the whole screen ------------------------------------------------------------------------

export function buildResultsView(
  result: AnalysisResult,
  optionList: MobilityOptionSummary[],
): ResultsView {
  const options = new Map(optionList.map((option) => [option.id, option]))
  const portfolios = new Map(result.portfolios.map((portfolio) => [portfolio.id, portfolio]))
  const evaluations = new Map<string, PortfolioEvaluation>([
    [result.current.portfolio_id, result.current],
    ...result.evaluations.map((evaluation) => [evaluation.portfolio_id, evaluation] as const),
  ])
  const set = result.recommendations
  const current = result.current
  const todayPortfolio = portfolios.get(current.portfolio_id)

  const alternatives = set.recommendations.filter((r) => r.portfolio_id !== current.portfolio_id)
  const pick = alternatives.find((r) => r.portfolio_id === set.headline_portfolio_id) ?? null

  const cards: CardView[] = alternatives.flatMap((recommendation) => {
    const portfolio = portfolios.get(recommendation.portfolio_id)
    const evaluation = evaluations.get(recommendation.portfolio_id)
    if (!portfolio || !evaluation) return []
    const { bottomLine, lines } = reasonsOf(recommendation)
    return [
      {
        id: portfolio.id,
        roles: recommendation.roles.map((role) => ROLE_LABELS[role]),
        isPick: recommendation.portfolio_id === pick?.portfolio_id,
        name: portfolio.name,
        action: portfolio.description ?? portfolio.name,
        category: CATEGORY_LABELS[recommendation.category],
        strength: STRENGTH_LABELS[recommendation.strength],
        composition: composition(portfolio, options),
        metrics: metricsOf(evaluation, recommendation.delta ?? evaluation.delta, false),
        carKm: carKmLine(current, evaluation),
        bottomLine,
        reasons: lines.slice(0, MAX_REASONS),
        moreReasons: lines.slice(MAX_REASONS),
        confidence: CONFIDENCE_LABELS[recommendation.confidence],
      },
    ]
  })

  cards.sort((a, b) => Number(b.isPick) - Number(a.isPick)) // the pick leads; the sort is stable

  return {
    verdict: verdictOf(result, pick, alternatives.length),
    today: {
      composition: todayPortfolio ? composition(todayPortfolio, options) : [],
      metrics: metricsOf(current, null, true),
      carKm: carKmLine(current, null),
      notes: current.data_quality_notes,
      confidence: CONFIDENCE_LABELS[current.confidence],
    },
    cards,
    charts: chartsOf(result, cards, evaluations, pick?.portfolio_id ?? null),
    table: tableOf(result, cards, evaluations),
    rejected: result.rejected.map((entry) => ({
      id: entry.portfolio_id,
      name: entry.name,
      reasons: entry.issues.slice(0, 2).map((issue) => issue.message),
    })),
    hints: set.accuracy_hints.map((hint) => hint.message),
  }
}

function verdictOf(
  result: AnalysisResult,
  pick: Recommendation | null,
  alternativeCount: number,
): VerdictView {
  const current = result.current
  if (pick === null || pick.delta === null) {
    const discarded = result.rejected.length
    const compared = result.evaluations.length
    const rejectedNote =
      discarded > 0 ? ` e ne abbiamo scartate ${discarded} che non funzionerebbero` : ''
    return {
      keep: true,
      title: 'Tieni la configurazione che hai.',
      lead:
        compared > 0
          ? `Abbiamo confrontato ${compared} alternative${rejectedNote}: nessuna vale il disturbo di cambiare.`
          : alternativeCount === 0
            ? 'Non abbiamo trovato alternative praticabili per la vostra situazione.'
            : 'Nessuna alternativa vale il disturbo di cambiare.',
      action: null,
      hero: {
        value: euros(current.annual_cost.expected),
        label: 'è quanto ti costa oggi ogni anno',
        range: euroRange(current.annual_cost.low, current.annual_cost.high),
      },
      pickId: null,
      strength: null,
    }
  }

  const delta = pick.delta
  const portfolio = result.portfolios.find((p) => p.id === pick.portfolio_id)
  const saving = -delta.cost.expected
  const titles: Record<Strength, string> = {
    KEEP_CURRENT: 'Tieni la configurazione che hai.',
    SMALL_IMPROVEMENT: 'Puoi migliorare un poco.',
    CONSIDER_CHANGE: 'Vale la pena pensarci.',
    STRONG_OPPORTUNITY: 'Ti conviene cambiare.',
  }
  // The figure to lead with is the real gain: money if it is worth a headline, else the time given back
  const time = delta.travel_hours.expected
  const moneyHero = {
    value: euros(saving),
    label: 'di risparmio ogni anno',
    range: euroRange(-delta.cost.high, -delta.cost.low),
  }
  const timeHero = {
    value: hoursInText(time),
    label: 'di viaggio in meno ogni anno',
    range: null,
  }
  let hero: VerdictView['hero']
  if (saving >= 150) hero = moneyHero
  else if (time <= -5) hero = timeHero
  else if (saving >= 50) hero = moneyHero
  else if (time <= -2) hero = timeHero
  else {
    hero = {
      value: euros(pick.net_benefit?.expected ?? 0),
      label: 'di vantaggio ogni anno',
      range: null,
    }
  }
  return {
    keep: false,
    title: titles[pick.strength],
    lead: effectsSentence(delta),
    action: portfolio?.description ?? portfolio?.name ?? null,
    hero,
    pickId: pick.portfolio_id,
    strength: STRENGTH_LABELS[pick.strength],
  }
}

function shortLabel(card: CardView): string {
  return card.roles[0] ?? 'Consigliata'
}

function chartsOf(
  result: AnalysisResult,
  cards: CardView[],
  evaluations: Map<string, PortfolioEvaluation>,
  pickId: string | null,
): ChartView[] {
  const current = result.current
  const entries = [
    { id: current.portfolio_id, label: 'Oggi', name: 'La tua situazione oggi', tone: 'today' as const },
    ...cards.map((card) => ({
      id: card.id,
      label: shortLabel(card),
      name: card.name,
      tone: (card.id === pickId ? 'pick' : 'option') as 'pick' | 'option',
    })),
  ]

  function chart(
    id: ChartView['id'],
    title: string,
    caption: string,
    value: (e: PortfolioEvaluation) => number,
    display: (v: number) => string,
    delta: (v: number, base: number) => string,
    fixedMax: number | null,
  ): ChartView {
    const base = value(current)
    const rows = entries.flatMap((entry): BarRow[] => {
      const evaluation = evaluations.get(entry.id)
      if (!evaluation) return []
      const v = value(evaluation)
      const against = entry.tone === 'today' ? '' : ` (${delta(v, base)} rispetto a oggi)`
      return [
        {
          id: entry.id,
          label: entry.label,
          name: entry.name,
          value: v,
          display: display(v),
          tone: entry.tone,
          title: `${entry.name}: ${display(v)}${against}`,
        },
      ]
    })
    return {
      id,
      title,
      caption,
      rows,
      max: fixedMax ?? Math.max(...rows.map((row) => row.value), 1),
    }
  }

  return [
    chart(
      'cost',
      'Quanto spendi',
      'euro l’anno, tutto compreso',
      (e) => e.annual_cost.expected,
      euros,
      (v, base) => signedEuros(v - base),
      null,
    ),
    chart(
      'hours',
      'Quanto tempo passi in viaggio',
      'ore l’anno, di tutta la famiglia',
      (e) => e.annual_travel_hours.expected,
      hours,
      (v, base) => signedHours(v - base),
      null,
    ),
    chart(
      'comfort',
      'Quanto viaggi comodo',
      'da 0 a 10, più è alto meglio è',
      (e) => e.comfort.expected,
      (v) => score(v),
      (v, base) => signedScore(v - base),
      10,
    ),
  ]
}

function tableOf(
  result: AnalysisResult,
  cards: CardView[],
  evaluations: Map<string, PortfolioEvaluation>,
): TableRow[] {
  const entries = [
    { id: result.current.portfolio_id, label: 'Oggi', name: 'La tua situazione oggi' },
    ...cards.map((card) => ({ id: card.id, label: shortLabel(card), name: card.name })),
  ]
  return entries.flatMap((entry) => {
    const e = evaluations.get(entry.id)
    if (!e) return []
    return [
      {
        id: entry.id,
        label: entry.label,
        name: entry.name,
        cost: euros(e.annual_cost.expected),
        hours: hours(e.annual_travel_hours.expected),
        comfort: score(e.comfort.expected),
        carKm: kilometres(e.car_km_per_year.expected),
      },
    ]
  })
}
