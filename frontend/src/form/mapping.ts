// Conversion between the questionnaire form and the domain profile (backend UserProfile).
// Pure functions, no DOM: covered by node tests (mapping.test.ts).

import type {
  BandGroup,
  HeldSubscription,
  MobilityOptionSummary,
  NumericAnswer,
  OwnedVehicle,
  Person,
  QuestionnaireConfig,
  UserProfile,
} from '../api/types.ts'
import {
  DEFAULT_PREFERENCES,
  defaultHousehold,
  defaultPerson,
  defaultVehicle,
  defaultWorkPattern,
  emptyOtherMobility,
  exactAnswer,
  unknownAnswer,
} from './defaults.ts'
import { worksOrStudies } from './rules.ts'
import type { AdultForm, FormState, NumericForm, TwoWheelsUse, VehicleForm } from './types.ts'
import { BAND_GROUPS } from './types.ts'

// --- numeric answers ---------------------------------------------------------------------

function rangeAnswer(low: number, high: number): NumericAnswer {
  // A band with low == high is an exact answer ("I pay nothing", "one holiday").
  return low === high ? exactAnswer(low) : { exact: null, low, high }
}

export function numericToAnswer(value: NumericForm, group: BandGroup): NumericAnswer {
  switch (value.kind) {
    case 'unknown':
      return unknownAnswer()
    case 'band': {
      const band = group.bands.find((candidate) => candidate.id === value.bandId)
      return band ? rangeAnswer(band.low, band.high) : unknownAnswer()
    }
    case 'exact':
      return value.value === null ? unknownAnswer() : exactAnswer(value.value)
    case 'range':
      return rangeAnswer(value.low, value.high)
  }
}

export function answerToNumeric(
  answer: NumericAnswer | null | undefined,
  group: BandGroup,
): NumericForm {
  if (!answer) return { kind: 'unknown' }
  if (answer.exact !== null) {
    const exactBand = group.bands.find((b) => b.low === answer.exact && b.high === answer.exact)
    return exactBand
      ? { kind: 'band', bandId: exactBand.id }
      : { kind: 'exact', value: answer.exact }
  }
  if (answer.low !== null && answer.high !== null) {
    const band = group.bands.find((b) => b.low === answer.low && b.high === answer.high)
    return band
      ? { kind: 'band', bandId: band.id }
      : { kind: 'range', low: answer.low, high: answer.high }
  }
  return { kind: 'unknown' }
}

/** A small whole number (days per week...) from an answer; midpoint of a range, else fallback. */
function answerToCount(answer: NumericAnswer | null | undefined, fallback: number): number {
  if (!answer) return fallback
  if (answer.exact !== null) return answer.exact
  if (answer.low !== null && answer.high !== null) return Math.round((answer.low + answer.high) / 2)
  return fallback
}

function group(config: QuestionnaireConfig, name: string): BandGroup {
  const found = config.groups[name]
  if (!found) throw new Error(`questionnaire band group missing: ${name}`)
  return found
}

// --- bicycles, e-bikes and scooters ------------------------------------------------------

const NO_TWO_WHEELS = 'NO_TWO_WHEELS'

/**
 * The two-wheeler answer as the profile keeps it: the constraint NO_TWO_WHEELS, or a weather
 * tolerance. Other constraints of a loaded profile (wheelchair...) are left alone.
 */
function twoWheelsToPerson(
  use: TwoWheelsUse,
  person: Person,
): Pick<Person, 'accessibility_constraints' | 'weather_tolerance'> {
  const others = person.accessibility_constraints.filter((c) => c !== NO_TWO_WHEELS)
  return {
    accessibility_constraints: use === 'NONE' ? [...others, NO_TWO_WHEELS] : others,
    weather_tolerance: use === 'ANY_WEATHER' || use === 'FAIR_WEATHER_ONLY' ? use : null,
  }
}

function personTwoWheels(person: Person): TwoWheelsUse {
  if (person.accessibility_constraints.includes(NO_TWO_WHEELS)) return 'NONE'
  if (person.weather_tolerance === 'ANY_WEATHER') return 'ANY_WEATHER'
  if (person.weather_tolerance === 'FAIR_WEATHER_ONLY') return 'FAIR_WEATHER_ONLY'
  return 'UNSURE'
}

// --- form -> profile ---------------------------------------------------------------------

function randomId(): string {
  return crypto.randomUUID().replaceAll('-', '')
}

/**
 * Builds the domain profile from the form. Fields the questionnaire does not ask are taken
 * from `form.base` / each item's `base`, so loading and re-saving a profile loses nothing.
 * Throws if the form is not complete enough to be a valid profile (no area type chosen).
 */
export function formToProfile(
  form: FormState,
  config: QuestionnaireConfig,
  makeId: () => string = randomId,
): UserProfile {
  if (form.areaType === null) throw new Error('area type missing')
  const base = form.base
  const answer = (field: keyof typeof BAND_GROUPS, value: NumericForm) =>
    numericToAnswer(value, group(config, BAND_GROUPS[field]))

  const adults: Person[] = form.adults.map((adult) => {
    const person = adult.base ?? defaultPerson(adult.id)
    const work = person.work_or_study ?? defaultWorkPattern()
    return {
      ...person,
      id: adult.id,
      has_license: adult.hasLicense,
      ...twoWheelsToPerson(adult.twoWheels, person),
      occupation: adult.occupation,
      work_or_study: worksOrStudies(adult)
        ? {
            ...work,
            one_way_distance_km: answer('distanceKm', adult.distanceKm),
            days_per_week: exactAnswer(adult.daysPerWeek),
            remote_days_per_week: exactAnswer(adult.remoteDaysPerWeek),
            time_critical: adult.timeCritical,
          }
        : null,
    }
  })

  const toVehicle = (vehicle: VehicleForm): OwnedVehicle | null => {
    if (vehicle.optionId === null) return null
    return {
      ...(vehicle.base ?? defaultVehicle(vehicle.id, vehicle.optionId)),
      id: vehicle.id,
      option_id: vehicle.optionId,
      annual_km: answer('annualKm', vehicle.annualKm),
      parking_cost_year: answer('parkingCostYear', vehicle.parkingCostYear),
    }
  }
  const vehicles = [...form.cars, ...form.otherVehicles]
    .map(toVehicle)
    .filter((vehicle): vehicle is OwnedVehicle => vehicle !== null)

  // Subscriptions are rebuilt from each adult's choices; ids are sequential.
  const subscriptions: HeldSubscription[] = []
  for (const adult of form.adults) {
    const held = [adult.ptPassOptionId, ...adult.otherSubscriptionIds].filter(
      (optionId): optionId is string => optionId !== null,
    )
    for (const optionId of held) {
      subscriptions.push({
        id: `sub${subscriptions.length + 1}`,
        option_id: optionId,
        holder_id: adult.id,
        annual_cost: unknownAnswer(),
      })
    }
  }

  const household = base?.household ?? { ...defaultHousehold(), adults: [] }
  const other = base?.other_mobility ?? emptyOtherMobility()

  return {
    schema_version: base?.schema_version ?? '1',
    id: base?.id ?? makeId(),
    mode: base?.mode ?? 'QUICK',
    household: {
      ...household,
      adults,
      n_children: form.nChildren,
      location: {
        ...household.location,
        area_type: form.areaType,
        municipality: form.municipality.trim() === '' ? null : form.municipality.trim(),
      },
      simultaneous_car_need: form.simultaneousCarNeed,
    },
    vehicles,
    subscriptions,
    other_mobility: {
      ...other,
      weekend_trips_per_year: answer('weekendTrips', form.weekendTrips),
      weekend_trip_distance_km_one_way: answer('weekendDistanceKm', form.weekendDistanceKm),
      holiday_trips_per_year: answer('holidayTrips', form.holidayTrips),
      holiday_distance_km_one_way: answer('holidayDistanceKm', form.holidayDistanceKm),
      taxi_trips_per_year: answer('taxiTrips', form.taxiTrips),
      car_sharing_trips_per_year: answer('carSharingTrips', form.carSharingTrips),
      car_rental_days_per_year: answer('carRentalDays', form.carRentalDays),
    },
    preferences: { ...form.preferences },
    declared_missions: base?.declared_missions ?? [],
  }
}

// --- profile -> form ---------------------------------------------------------------------

const PT_PASS_TYPES = new Set(['PT_ANNUAL', 'PT_MONTHLY'])

/**
 * Loads an existing profile (a demo household, a saved draft) into the form. `options` is the
 * catalogue, used to tell cars from other vehicles and PT passes from other subscriptions.
 */
export function profileToForm(
  profile: UserProfile,
  config: QuestionnaireConfig,
  options: MobilityOptionSummary[],
): FormState {
  const optionById = new Map(options.map((option) => [option.id, option]))
  const bands = (field: keyof typeof BAND_GROUPS) => group(config, BAND_GROUPS[field])
  const numeric = (field: keyof typeof BAND_GROUPS, answer: NumericAnswer | null | undefined) =>
    answerToNumeric(answer, bands(field))

  const firstAdultId = profile.household.adults[0]?.id ?? null
  const adults: AdultForm[] = profile.household.adults.map((person) => {
    const held = profile.subscriptions.filter(
      (subscription) => (subscription.holder_id ?? firstAdultId) === person.id,
    )
    const ptPass = held.find((s) => PT_PASS_TYPES.has(optionById.get(s.option_id)?.type ?? ''))
    const work = person.work_or_study
    return {
      id: person.id,
      occupation: person.occupation,
      hasLicense: person.has_license,
      twoWheels: personTwoWheels(person),
      distanceKm: numeric('distanceKm', work?.one_way_distance_km),
      daysPerWeek: answerToCount(work?.days_per_week, 5),
      remoteDaysPerWeek: answerToCount(work?.remote_days_per_week, 0),
      timeCritical: work?.time_critical ?? false,
      ptPassOptionId: ptPass?.option_id ?? null,
      otherSubscriptionIds: held.filter((s) => s !== ptPass).map((s) => s.option_id),
      base: person,
    }
  })

  const toVehicleForm = (vehicle: OwnedVehicle): VehicleForm => ({
    id: vehicle.id,
    optionId: vehicle.option_id,
    annualKm: numeric('annualKm', vehicle.annual_km),
    parkingCostYear: numeric('parkingCostYear', vehicle.parking_cost_year),
    base: vehicle,
  })
  const isCar = (vehicle: OwnedVehicle) => optionById.get(vehicle.option_id)?.mode === 'CAR'
  const other = profile.other_mobility

  return {
    base: profile,
    adults,
    nChildren: profile.household.n_children,
    municipality: profile.household.location.municipality ?? '',
    areaType: profile.household.location.area_type,
    cars: profile.vehicles.filter(isCar).map(toVehicleForm),
    simultaneousCarNeed: profile.household.simultaneous_car_need,
    otherVehicles: profile.vehicles.filter((v) => !isCar(v)).map(toVehicleForm),
    weekendTrips: numeric('weekendTrips', other.weekend_trips_per_year),
    weekendDistanceKm: numeric('weekendDistanceKm', other.weekend_trip_distance_km_one_way),
    holidayTrips: numeric('holidayTrips', other.holiday_trips_per_year),
    holidayDistanceKm: numeric('holidayDistanceKm', other.holiday_distance_km_one_way),
    taxiTrips: numeric('taxiTrips', other.taxi_trips_per_year),
    carSharingTrips: numeric('carSharingTrips', other.car_sharing_trips_per_year),
    carRentalDays: numeric('carRentalDays', other.car_rental_days_per_year),
    preferences: { ...DEFAULT_PREFERENCES, ...profile.preferences },
  }
}
