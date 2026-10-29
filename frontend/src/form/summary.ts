// Plain-language recap of the answers, shown before the analysis. Pure: no DOM.

import type { BandGroup, MobilityOptionSummary, QuestionnaireConfig } from '../api/types.ts'
import { AREA_LABELS, FREQUENCY_LABELS, OCCUPATION_LABELS, TWO_WHEELS_LABELS } from './labels.ts'
import { worksOrStudies } from './rules.ts'
import type { AdultForm, FormState, NumericForm, StepId } from './types.ts'
import { BAND_GROUPS } from './types.ts'

export interface SummarySection {
  step: StepId
  title: string
  lines: string[]
}

const NOT_KNOWN = 'non so (lo stimiamo noi)'

function format(value: number): string {
  return value.toLocaleString('it-IT')
}

export function numericLabel(value: NumericForm, group: BandGroup): string {
  switch (value.kind) {
    case 'unknown':
      return NOT_KNOWN
    case 'band':
      return group.bands.find((band) => band.id === value.bandId)?.label ?? NOT_KNOWN
    case 'exact':
      return value.value === null ? NOT_KNOWN : format(value.value)
    case 'range':
      return `circa ${format(value.low)} – ${format(value.high)}`
  }
}

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`
}

/** Only said when the adult answered: 'Dipende' is the default and adds nothing. */
function twoWheelsNote(adult: AdultForm): string {
  if (adult.twoWheels === 'UNSURE') return ''
  return `, bici, e-bike e scooter: ${TWO_WHEELS_LABELS[adult.twoWheels].toLowerCase()}`
}

export function describeForm(
  form: FormState,
  config: QuestionnaireConfig,
  options: MobilityOptionSummary[],
): SummarySection[] {
  const nameOf = (id: string | null) =>
    id === null ? 'tipo non scelto' : (options.find((option) => option.id === id)?.name ?? id)
  const label = (field: keyof typeof BAND_GROUPS, value: NumericForm) => {
    const group = config.groups[BAND_GROUPS[field]]
    return group ? numericLabel(value, group) : NOT_KNOWN
  }

  const work = form.adults.map((adult, index) => {
    const who = `Adulto ${index + 1}`
    const twoWheels = twoWheelsNote(adult)
    if (!worksOrStudies(adult)) {
      return `${who}: ${OCCUPATION_LABELS[adult.occupation].toLowerCase()}${twoWheels}`
    }
    const remote =
      adult.remoteDaysPerWeek > 0 ? ` (${adult.remoteDaysPerWeek} da remoto)` : ''
    const punctual = adult.timeCritical ? ', arrivo a orario preciso' : ''
    return (
      `${who}: ${OCCUPATION_LABELS[adult.occupation].toLowerCase()}, ` +
      `distanza ${label('distanceKm', adult.distanceKm)}, ` +
      `${plural(adult.daysPerWeek, 'giorno', 'giorni')} a settimana${remote}${punctual}` +
      twoWheels
    )
  })

  const cars =
    form.cars.length === 0
      ? ['Nessuna auto']
      : form.cars.map(
          (car, index) =>
            `Auto ${index + 1}, ${nameOf(car.optionId).toLowerCase()}: ` +
            `${label('annualKm', car.annualKm)} all’anno, ` +
            `parcheggio ${label('parkingCostYear', car.parkingCostYear)}`,
        )
  if (form.simultaneousCarNeed !== null) {
    cars.push(
      `Due auto servono insieme: ${FREQUENCY_LABELS[form.simultaneousCarNeed].toLowerCase()}`,
    )
  }

  const counts = new Map<string, number>()
  for (const vehicle of form.otherVehicles) {
    if (vehicle.optionId) counts.set(vehicle.optionId, (counts.get(vehicle.optionId) ?? 0) + 1)
  }
  const otherVehicles =
    counts.size === 0
      ? 'Nessun altro mezzo'
      : [...counts].map(([id, n]) => `${nameOf(id)} × ${n}`).join(', ')

  const subscriptions = form.adults.map((adult, index) => {
    const held = [adult.ptPassOptionId, ...adult.otherSubscriptionIds]
      .filter((id): id is string => id !== null)
      .map(nameOf)
    return `Adulto ${index + 1}: ${held.length === 0 ? 'nessun abbonamento' : held.join(', ')}`
  })

  const p = form.preferences
  const preferences = [
    `Risparmiare ${p.save_money}/5, risparmiare tempo ${p.reduce_travel_time}/5, ` +
      `comfort ${p.comfort}/5, flessibilità ${p.flexibility}/5`,
  ]
  if (p.reduce_car_dependence > 0 || p.sustainability > 0) {
    preferences.push(
      `Dipendenza dall’auto ${p.reduce_car_dependence}/5, sostenibilità ${p.sustainability}/5`,
    )
  }

  return [
    {
      step: 'household',
      title: 'Famiglia',
      lines: [
        `${plural(form.adults.length, 'adulto', 'adulti')}, ` +
          (form.nChildren === 0 ? 'nessun figlio' : plural(form.nChildren, 'figlio', 'figli')),
      ],
    },
    {
      step: 'location',
      title: 'Zona',
      lines: [
        [form.areaType ? AREA_LABELS[form.areaType] : 'non scelta', form.municipality.trim()]
          .filter((part) => part !== '')
          .join(' – '),
      ],
    },
    { step: 'work', title: 'Lavoro e studio', lines: work },
    { step: 'cars', title: 'Auto', lines: cars },
    {
      step: 'mobility',
      title: 'Altri mezzi e abbonamenti',
      lines: [otherVehicles, ...subscriptions],
    },
    {
      step: 'occasional',
      title: 'Weekend, vacanze e servizi',
      lines: [
        `Gite nel weekend: ${label('weekendTrips', form.weekendTrips)}` +
          `, distanza ${label('weekendDistanceKm', form.weekendDistanceKm)}`,
        `Vacanze: ${label('holidayTrips', form.holidayTrips)}` +
          `, distanza ${label('holidayDistanceKm', form.holidayDistanceKm)}`,
        `Taxi: ${label('taxiTrips', form.taxiTrips)}`,
        `Car sharing: ${label('carSharingTrips', form.carSharingTrips)}`,
        `Noleggio auto: ${label('carRentalDays', form.carRentalDays)}`,
      ],
    },
    { step: 'preferences', title: 'Cosa conta di più', lines: preferences },
  ]
}
