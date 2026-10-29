import type {
  Household,
  Location,
  NumericAnswer,
  OtherMobility,
  OwnedVehicle,
  Person,
  Preferences,
  WorkPattern,
} from '../api/types.ts'
import type { AdultForm, FormState, VehicleForm } from './types.ts'

/** "I don't know": all-null, which makes the backend estimate the value statistically. */
export function unknownAnswer(): NumericAnswer {
  return { exact: null, low: null, high: null }
}

export function exactAnswer(value: number): NumericAnswer {
  return { exact: value, low: null, high: null }
}

export const DEFAULT_PREFERENCES: Preferences = {
  save_money: 3,
  reduce_travel_time: 3,
  comfort: 3,
  flexibility: 3,
  // Values-based dimensions stay off unless the user asks for them: MobiMix is neutral.
  reduce_car_dependence: 0,
  sustainability: 0,
}

export function defaultPerson(id: string): Person {
  return {
    id,
    age_range: null,
    has_license: true,
    occupation: 'WORKER',
    work_or_study: null,
    accessibility_constraints: [],
  }
}

export function defaultWorkPattern(): WorkPattern {
  return {
    one_way_distance_km: unknownAnswer(),
    days_per_week: unknownAnswer(),
    remote_days_per_week: unknownAnswer(),
    time_critical: false,
    typical_start: 'MORNING_PEAK',
  }
}

export function defaultVehicle(id: string, optionId: string): OwnedVehicle {
  return {
    id,
    option_id: optionId,
    primary_user_id: null,
    annual_km: unknownAnswer(),
    parking_cost_year: unknownAnswer(),
    current_value: unknownAnswer(),
  }
}

export function defaultLocation(): Location {
  return {
    area_type: 'URBAN',
    municipality: null,
    istat_code: null,
    car_independence_index: null,
    pt_quality: null,
    sharing_availability: null,
  }
}

export function defaultHousehold(): Omit<Household, 'adults'> {
  return {
    n_children: 0,
    location: defaultLocation(),
    income_band: null,
    family_logistics: [],
    simultaneous_car_need: null,
  }
}

export function emptyOtherMobility(): OtherMobility {
  return {
    local_non_work_trips_per_week: unknownAnswer(),
    weekend_trips_per_year: unknownAnswer(),
    weekend_trip_distance_km_one_way: unknownAnswer(),
    long_distance_weekends_per_year: unknownAnswer(),
    holiday_trips_per_year: unknownAnswer(),
    holiday_distance_km_one_way: unknownAnswer(),
    rail_trips_per_year: unknownAnswer(),
    flights_per_year: unknownAnswer(),
    taxi_trips_per_year: unknownAnswer(),
    car_sharing_trips_per_year: unknownAnswer(),
    car_rental_days_per_year: unknownAnswer(),
    bike_scooter_sharing_trips_per_year: unknownAnswer(),
  }
}

export function newAdult(index: number): AdultForm {
  return {
    id: `p${index + 1}`,
    occupation: 'WORKER',
    hasLicense: true,
    distanceKm: { kind: 'unknown' },
    daysPerWeek: 5,
    remoteDaysPerWeek: 0,
    timeCritical: false,
    ptPassOptionId: null,
    otherSubscriptionIds: [],
    base: null,
  }
}

/** Short id prefix per owned-vehicle option, used only for newly added vehicles. */
const ID_PREFIX: Record<string, string> = {
  motorcycle: 'moto',
  scooter_125: 'scooter',
  bicycle: 'bike',
  e_bike: 'ebike',
}

/** An id not used by any of the given vehicles, e.g. car2 or bike1. */
export function nextVehicleId(taken: VehicleForm[], optionId: string | null): string {
  const prefix = optionId === null ? 'car' : (ID_PREFIX[optionId] ?? 'car')
  const used = new Set(taken.map((vehicle) => vehicle.id))
  let n = 1
  while (used.has(`${prefix}${n}`)) n += 1
  return `${prefix}${n}`
}

export function newVehicle(taken: VehicleForm[], optionId: string | null): VehicleForm {
  return {
    id: nextVehicleId(taken, optionId),
    optionId,
    annualKm: { kind: 'unknown' },
    parkingCostYear: { kind: 'unknown' },
    base: null,
  }
}

export function emptyForm(): FormState {
  return {
    base: null,
    adults: [newAdult(0)],
    nChildren: 0,
    municipality: '',
    areaType: null,
    cars: [],
    simultaneousCarNeed: null,
    otherVehicles: [],
    weekendTrips: { kind: 'unknown' },
    weekendDistanceKm: { kind: 'unknown' },
    holidayTrips: { kind: 'unknown' },
    holidayDistanceKm: { kind: 'unknown' },
    taxiTrips: { kind: 'unknown' },
    carSharingTrips: { kind: 'unknown' },
    carRentalDays: { kind: 'unknown' },
    preferences: { ...DEFAULT_PREFERENCES },
  }
}
