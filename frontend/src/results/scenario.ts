// The "what if" panel, without React: which assumptions can be changed, how they are worded, what is
// sent to the server (`POST /api/scenario`, backend/app/models/scenario.py) and how the new answer
// is compared with the old one. Pure functions, tested without a browser.

import type { ScenarioBody } from '../api/results.ts'
import type { ResultsView } from './view.ts'

/** What the sliders hold, in the units a person reads them in. */
export interface ScenarioValues {
  /** Days a week more than today working from home. */
  remoteDays: number
  /** Percent change of the price of petrol and diesel. */
  fuelPct: number
  /** Percent change of what a car costs to park. */
  parkingPct: number
  /** Percent change of the kilometres the cars drive. */
  carKmPct: number
  /** Euro incentive on a new e-bike. */
  ebikeSubsidy: number
}

export type ScenarioKey = keyof ScenarioValues

export const NEUTRAL_SCENARIO: ScenarioValues = {
  remoteDays: 0,
  fuelPct: 0,
  parkingPct: 0,
  carKmPct: 0,
  ebikeSubsidy: 0,
}

export function sameScenario(a: ScenarioValues, b: ScenarioValues): boolean {
  return (Object.keys(NEUTRAL_SCENARIO) as ScenarioKey[]).every((key) => a[key] === b[key])
}

export function isNeutral(values: ScenarioValues): boolean {
  return (Object.keys(NEUTRAL_SCENARIO) as ScenarioKey[]).every(
    (key) => values[key] === NEUTRAL_SCENARIO[key],
  )
}

/** What is sent to the server: the changes as fractions. */
export function toBody(values: ScenarioValues): ScenarioBody {
  return {
    extra_remote_days_per_week: values.remoteDays,
    fuel_price_change: values.fuelPct / 100,
    parking_cost_change: values.parkingPct / 100,
    car_km_change: values.carKmPct / 100,
    ebike_subsidy_eur: values.ebikeSubsidy,
  }
}

const MINUS = '−'

export function signedPercent(value: number): string {
  if (value === 0) return '0%'
  return `${value < 0 ? MINUS : '+'}${Math.abs(value)}%`
}

export interface ControlDef {
  key: ScenarioKey
  label: string
  /** One line saying what the control does, for someone who has not read the manual. */
  hint: string
  min: number
  max: number
  step: number
  /** The value as the person reads it. */
  show: (value: number) => string
  /** The same, as a phrase for the list of assumptions ("benzina +20%"); null if unchanged. */
  phrase: (value: number) => string | null
  /** The text under the two ends of the slider. */
  ends: [string, string]
}

export const CONTROLS: ControlDef[] = [
  {
    key: 'remoteDays',
    label: 'Lavoro da casa',
    hint: 'Giorni in più a settimana da remoto, per chi si sposta per lavoro.',
    min: 0,
    max: 4,
    step: 1,
    show: (v) => (v === 0 ? 'Come adesso' : `+${v} ${v === 1 ? 'giorno' : 'giorni'} a settimana`),
    phrase: (v) => (v === 0 ? null : `${v} ${v === 1 ? 'giorno' : 'giorni'} in più da remoto`),
    ends: ['Come adesso', '+4 giorni'],
  },
  {
    key: 'fuelPct',
    label: 'Prezzo del carburante',
    hint: 'Benzina e gasolio. L’elettricità non cambia.',
    min: -30,
    max: 50,
    step: 5,
    show: (v) => (v === 0 ? 'Come oggi' : signedPercent(v)),
    phrase: (v) => (v === 0 ? null : `carburante ${signedPercent(v)}`),
    ends: ['−30%', '+50%'],
  },
  {
    key: 'parkingPct',
    label: 'Costo del parcheggio',
    hint: 'Per le auto che hai e per una che compri.',
    min: -100,
    max: 100,
    step: 10,
    show: (v) => (v === 0 ? 'Come oggi' : v === -100 ? 'Gratis' : signedPercent(v)),
    phrase: (v) => (v === 0 ? null : v === -100 ? 'parcheggio gratis' : `parcheggio ${signedPercent(v)}`),
    ends: ['Gratis', '+100%'],
  },
  {
    key: 'carKmPct',
    label: 'Km fatti con l’auto',
    hint: 'Cambia quanto costa oggi l’auto, e quindi quanto si risparmia a venderla. Gli spostamenti restano gli stessi.',
    min: -50,
    max: 50,
    step: 5,
    show: (v) => (v === 0 ? 'Come oggi' : signedPercent(v)),
    phrase: (v) => (v === 0 ? null : `km in auto ${signedPercent(v)}`),
    ends: ['−50%', '+50%'],
  },
  {
    key: 'ebikeSubsidy',
    label: 'Incentivo per l’e-bike',
    hint: 'Uno sconto sull’acquisto di una nuova e-bike.',
    min: 0,
    max: 1000,
    step: 50,
    show: (v) => (v === 0 ? 'Nessuno' : `${v} €`),
    phrase: (v) => (v === 0 ? null : `incentivo e-bike ${v} €`),
    ends: ['Nessuno', '1.000 €'],
  },
]

/** The assumptions that differ from today, as short phrases. */
export function describeActive(values: ScenarioValues): string[] {
  return CONTROLS.flatMap((control) => {
    const phrase = control.phrase(values[control.key])
    return phrase === null ? [] : [phrase]
  })
}

/** What the new answer says against the old one, if it is a different answer; else null. */
export function answerChange(base: ResultsView, now: ResultsView): string | null {
  const pickName = (view: ResultsView) => view.cards.find((card) => card.isPick)?.name
  if (base.verdict.keep && now.verdict.keep) return null
  if (base.verdict.keep) {
    return `Con queste ipotesi la risposta cambia: ora ti conviene «${pickName(now) ?? 'cambiare'}».`
  }
  if (now.verdict.keep) {
    return 'Con queste ipotesi la risposta cambia: non conviene più cambiare.'
  }
  if (base.verdict.pickId !== now.verdict.pickId) {
    return `Con queste ipotesi la scelta migliore cambia: ora «${pickName(now) ?? 'un’altra'}».`
  }
  return null
}

/** "remoteDays:2,fuelPct:30" -> values, each kept within what its slider offers. For development
 * links such as /?demo=urban_single&whatif=fuelPct:30; anything unreadable is ignored. */
export function parseScenario(text: string | null): ScenarioValues {
  const values = { ...NEUTRAL_SCENARIO }
  for (const part of (text ?? '').split(',')) {
    const [key, raw] = part.split(':')
    const control = CONTROLS.find((c) => c.key === key)
    const number = Number(raw)
    if (control === undefined || raw === undefined || Number.isNaN(number)) continue
    values[control.key] = Math.min(control.max, Math.max(control.min, number))
  }
  return values
}
