// Pure state transitions of the form. Anything that must keep the form consistent (adding or
// removing people and vehicles, clearing answers that stop being relevant) lives here rather
// than in the components.

import { newAdult, newVehicle } from './defaults.ts'
import type { AdultForm, FormState, VehicleForm } from './types.ts'

export const MAX_ADULTS = 5
export const MAX_CHILDREN = 6
export const MAX_CARS = 4
export const MAX_PER_OTHER_VEHICLE = 4

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

export function setAdultCount(form: FormState, count: number): FormState {
  const target = clamp(count, 1, MAX_ADULTS)
  const adults = form.adults.slice(0, target)
  while (adults.length < target) adults.push(newAdult(adults.length))
  return { ...form, adults }
}

export function setChildCount(form: FormState, count: number): FormState {
  return { ...form, nChildren: clamp(count, 0, MAX_CHILDREN) }
}

export function updateAdult(form: FormState, id: string, patch: Partial<AdultForm>): FormState {
  return {
    ...form,
    adults: form.adults.map((adult) => (adult.id === id ? { ...adult, ...patch } : adult)),
  }
}

/** Adds or removes cars (last ones first). Fewer than two cars makes the simultaneity
 * question irrelevant, so its answer is cleared. */
export function setCarCount(form: FormState, count: number): FormState {
  const target = clamp(count, 0, MAX_CARS)
  const cars = form.cars.slice(0, target)
  while (cars.length < target) cars.push(newVehicle([...cars, ...form.otherVehicles], null))
  return {
    ...form,
    cars,
    simultaneousCarNeed: cars.length >= 2 ? form.simultaneousCarNeed : null,
  }
}

export function updateCar(form: FormState, id: string, patch: Partial<VehicleForm>): FormState {
  return {
    ...form,
    cars: form.cars.map((car) => (car.id === id ? { ...car, ...patch } : car)),
  }
}

export function countOtherVehicles(form: FormState, optionId: string): number {
  return form.otherVehicles.filter((vehicle) => vehicle.optionId === optionId).length
}

/** Sets how many vehicles of one kind (motorcycle, scooter, bicycle, e-bike) are owned. */
export function setOtherVehicleCount(
  form: FormState,
  optionId: string,
  count: number,
): FormState {
  const target = clamp(count, 0, MAX_PER_OTHER_VEHICLE)
  const current = countOtherVehicles(form, optionId)
  let vehicles = form.otherVehicles
  if (target < current) {
    // drop from the end
    let toRemove = current - target
    vehicles = [...vehicles].reverse().filter((vehicle) => {
      if (toRemove > 0 && vehicle.optionId === optionId) {
        toRemove -= 1
        return false
      }
      return true
    })
    vehicles.reverse()
  } else {
    vehicles = [...vehicles]
    for (let i = current; i < target; i += 1) {
      vehicles.push(newVehicle([...form.cars, ...vehicles], optionId))
    }
  }
  return { ...form, otherVehicles: vehicles }
}
