// API types. Hand-written for now and kept in sync with backend/app/models by hand; once the
// domain models settle they will be generated from the OpenAPI schema
// (http://127.0.0.1:8000/openapi.json) to avoid drift.

export interface HealthStatus {
  status: string
  parameters_version: string
  n_options: number
}

// --- enums (string unions: `erasableSyntaxOnly` forbids TS enums) -------------------------

export type AreaType = 'CITY_CENTER' | 'URBAN' | 'SUBURBAN' | 'PERIPHERAL'
export type Occupation = 'WORKER' | 'STUDENT' | 'RETIRED' | 'OTHER'
export type Frequency = 'NEVER' | 'RARELY' | 'SOMETIMES' | 'OFTEN' | 'ALMOST_DAILY'
export type Level = 'LOW' | 'MEDIUM' | 'HIGH'
export type ProfileMode = 'QUICK' | 'DETAILED' | 'RETROSPECTIVE'

// --- profile (mirrors backend/app/models/profile.py) -------------------------------------

/** Exact value, approximate range, or all-null for "I don't know". */
export interface NumericAnswer {
  exact: number | null
  low: number | null
  high: number | null
}

export interface WorkPattern {
  one_way_distance_km: NumericAnswer
  days_per_week: NumericAnswer
  remote_days_per_week: NumericAnswer
  time_critical: boolean
  typical_start: string
}

export interface Person {
  id: string
  age_range: string | null
  has_license: boolean
  occupation: Occupation
  work_or_study: WorkPattern | null
  accessibility_constraints: string[]
}

export interface Location {
  area_type: AreaType
  municipality: string | null
  istat_code: string | null
  car_independence_index: number | null
  pt_quality: Level | null
  sharing_availability: Level | null
}

export interface Household {
  adults: Person[]
  n_children: number
  location: Location
  income_band: string | null
  family_logistics: string[]
  simultaneous_car_need: Frequency | null
}

export interface OwnedVehicle {
  id: string
  option_id: string
  primary_user_id: string | null
  annual_km: NumericAnswer
  parking_cost_year: NumericAnswer
  current_value: NumericAnswer
}

export interface HeldSubscription {
  id: string
  option_id: string
  holder_id: string | null
  annual_cost: NumericAnswer
}

export interface OtherMobility {
  local_non_work_trips_per_week: NumericAnswer
  weekend_trips_per_year: NumericAnswer
  weekend_trip_distance_km_one_way: NumericAnswer
  long_distance_weekends_per_year: NumericAnswer
  holiday_trips_per_year: NumericAnswer
  holiday_distance_km_one_way: NumericAnswer
  rail_trips_per_year: NumericAnswer
  flights_per_year: NumericAnswer
  taxi_trips_per_year: NumericAnswer
  car_sharing_trips_per_year: NumericAnswer
  car_rental_days_per_year: NumericAnswer
  bike_scooter_sharing_trips_per_year: NumericAnswer
}

export interface Preferences {
  save_money: number
  reduce_travel_time: number
  comfort: number
  flexibility: number
  reduce_car_dependence: number
  sustainability: number
}

export interface UserProfile {
  schema_version: string
  id: string
  mode: ProfileMode
  household: Household
  vehicles: OwnedVehicle[]
  subscriptions: HeldSubscription[]
  other_mobility: OtherMobility
  preferences: Preferences
  declared_missions: unknown[]
}

// --- reference data ----------------------------------------------------------------------

/** The part of a mobility option the questionnaire needs. */
export interface MobilityOptionSummary {
  id: string
  name: string
  type: string
  mode: string
  ownership: 'OWNED' | 'SUBSCRIPTION' | 'PAY_PER_USE' | 'FREE'
  min_age: number | null
  max_age: number | null
}

export interface Band {
  id: string
  label: string
  low: number
  high: number
}

export interface BandGroup {
  description: string | null
  unit: string | null
  placeholder: boolean
  notes: string | null
  bands: Band[]
}

export interface QuestionnaireConfig {
  groups: Record<string, BandGroup>
}
