// Form state of the questionnaire. Deliberately separate from the domain model
// (api/types.ts): the form has "unanswered" states, band choices and fields that exist only
// for the UI. `mapping.ts` converts between the two.
//
// Items that come from an existing profile (adults, vehicles) keep that original in `base`, so
// fields the questionnaire does not ask (age band, accessibility, current value...) survive a
// profile -> form -> profile round trip instead of being silently dropped.

import type {
  AreaType,
  Frequency,
  Occupation,
  OwnedVehicle,
  Person,
  Preferences,
  UserProfile,
} from '../api/types.ts'

/**
 * A numeric answer as the user gives it: nothing / "I don't know", a band, an exact value, or
 * a custom range (only produced when loading a profile whose range matches no band).
 */
export type NumericForm =
  | { kind: 'unknown' }
  | { kind: 'band'; bandId: string }
  | { kind: 'exact'; value: number | null }
  | { kind: 'range'; low: number; high: number }

/**
 * Whether an adult rides a bicycle, an e-bike or a scooter. 'NONE' is the constraint
 * NO_TWO_WHEELS of the profile; the two weather answers are its `weather_tolerance`;
 * 'UNSURE' (the default) leaves both empty, so the model uses its average.
 */
export type TwoWheelsUse = 'ANY_WEATHER' | 'FAIR_WEATHER_ONLY' | 'NONE' | 'UNSURE'

export interface AdultForm {
  id: string
  occupation: Occupation
  hasLicense: boolean
  twoWheels: TwoWheelsUse
  distanceKm: NumericForm
  daysPerWeek: number
  remoteDaysPerWeek: number
  timeCritical: boolean
  /** Public-transport pass held (a subscription option id), if any. */
  ptPassOptionId: string | null
  /** Other subscriptions held (rail, bike sharing, car sharing): option ids. */
  otherSubscriptionIds: string[]
  base: Person | null
}

export interface VehicleForm {
  id: string
  optionId: string | null
  annualKm: NumericForm
  parkingCostYear: NumericForm
  base: OwnedVehicle | null
}

export interface FormState {
  /** The profile this form was loaded from, if any. */
  base: UserProfile | null
  adults: AdultForm[]
  nChildren: number
  municipality: string
  areaType: AreaType | null
  cars: VehicleForm[]
  simultaneousCarNeed: Frequency | null
  /** Motorcycles, scooters, bicycles, e-bikes: one entry per vehicle. */
  otherVehicles: VehicleForm[]
  weekendTrips: NumericForm
  weekendDistanceKm: NumericForm
  holidayTrips: NumericForm
  holidayDistanceKm: NumericForm
  taxiTrips: NumericForm
  carSharingTrips: NumericForm
  carRentalDays: NumericForm
  preferences: Preferences
}

export type StepId =
  | 'household'
  | 'location'
  | 'work'
  | 'cars'
  | 'mobility'
  | 'occasional'
  | 'preferences'
  | 'summary'

/** Which questionnaire band group (data/questionnaire.yaml) each numeric field uses. */
export const BAND_GROUPS = {
  distanceKm: 'commute_distance_km',
  annualKm: 'annual_km_per_car',
  parkingCostYear: 'parking_cost_year',
  weekendTrips: 'weekend_trips_per_year',
  weekendDistanceKm: 'weekend_trip_distance_km',
  holidayTrips: 'holiday_trips_per_year',
  holidayDistanceKm: 'holiday_distance_km',
  taxiTrips: 'taxi_trips_per_year',
  carSharingTrips: 'car_sharing_trips_per_year',
  carRentalDays: 'car_rental_days_per_year',
} as const

/** Catalogue option ids of the owned vehicles the questionnaire offers. */
export const CAR_OPTION_IDS = [
  'car_small_petrol',
  'car_medium_petrol',
  'car_diesel',
  'car_electric',
] as const

export const OTHER_VEHICLE_OPTION_IDS = ['motorcycle', 'scooter_125', 'bicycle', 'e_bike'] as const
