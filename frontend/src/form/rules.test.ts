import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import {
  MAX_ADULTS,
  MAX_CARS,
  countOtherVehicles,
  setAdultCount,
  setCarCount,
  setChildCount,
  setOtherVehicleCount,
  updateAdult,
} from './actions.ts'
import { emptyForm } from './defaults.ts'
import {
  STEP_ORDER,
  firstIncompleteStep,
  isStepComplete,
  showCarDetails,
  showSimultaneity,
  stepProblems,
} from './rules.ts'

describe('adaptive visibility', () => {
  it('asks nothing about cars when the household has none', () => {
    const form = emptyForm()
    assert.equal(showCarDetails(form), false)
    assert.equal(showSimultaneity(form), false)
  })

  it('asks about car use for one car but about simultaneity only from two cars', () => {
    const one = setCarCount(emptyForm(), 1)
    assert.equal(showCarDetails(one), true)
    assert.equal(showSimultaneity(one), false)
    assert.equal(showSimultaneity(setCarCount(one, 2)), true)
  })

  it('clears the simultaneity answer when cars drop below two', () => {
    const two = { ...setCarCount(emptyForm(), 2), simultaneousCarNeed: 'OFTEN' as const }
    assert.equal(setCarCount(two, 2).simultaneousCarNeed, 'OFTEN')
    assert.equal(setCarCount(two, 1).simultaneousCarNeed, null)
  })
})

describe('counts', () => {
  it('keeps at least one adult and caps the maximum', () => {
    assert.equal(setAdultCount(emptyForm(), 0).adults.length, 1)
    assert.equal(setAdultCount(emptyForm(), 99).adults.length, MAX_ADULTS)
  })

  it('gives new adults sequential ids and keeps existing ones when growing and shrinking', () => {
    const grown = setAdultCount(emptyForm(), 3)
    assert.deepEqual(grown.adults.map((a) => a.id), ['p1', 'p2', 'p3'])
    const edited = updateAdult(grown, 'p2', { occupation: 'RETIRED' })
    const shrunk = setAdultCount(edited, 2)
    assert.deepEqual(shrunk.adults.map((a) => a.occupation), ['WORKER', 'RETIRED'])
  })

  it('clamps children and cars', () => {
    assert.equal(setChildCount(emptyForm(), -3).nChildren, 0)
    assert.equal(setCarCount(emptyForm(), 99).cars.length, MAX_CARS)
  })

  it('numbers cars uniquely', () => {
    const form = setCarCount(emptyForm(), 3)
    assert.deepEqual(form.cars.map((c) => c.id), ['car1', 'car2', 'car3'])
  })

  it('adds and removes other vehicles of one kind without touching the others', () => {
    let form = setOtherVehicleCount(emptyForm(), 'bicycle', 2)
    form = setOtherVehicleCount(form, 'e_bike', 1)
    assert.equal(countOtherVehicles(form, 'bicycle'), 2)
    assert.deepEqual(form.otherVehicles.map((v) => v.id), ['bike1', 'bike2', 'ebike1'])

    form = setOtherVehicleCount(form, 'bicycle', 1)
    assert.deepEqual(form.otherVehicles.map((v) => v.id), ['bike1', 'ebike1'])
    form = setOtherVehicleCount(form, 'bicycle', 0)
    assert.deepEqual(form.otherVehicles.map((v) => v.id), ['ebike1'])
  })
})

describe('step validation', () => {
  it('requires the area type', () => {
    const form = emptyForm()
    assert.equal(isStepComplete('location', form), false)
    assert.match(stepProblems('location', form)[0]!, /zona/)
    assert.equal(isStepComplete('location', { ...form, areaType: 'URBAN' }), true)
  })

  it('rejects more remote days than work days, but only for people who work', () => {
    const base = updateAdult(emptyForm(), 'p1', { daysPerWeek: 2, remoteDaysPerWeek: 3 })
    assert.equal(isStepComplete('work', base), false)
    assert.equal(isStepComplete('work', updateAdult(base, 'p1', { occupation: 'RETIRED' })), true)
  })

  it('requires a type for every car', () => {
    const form = setCarCount(emptyForm(), 2)
    assert.equal(stepProblems('cars', form).length, 2)
  })

  it('points to the first incomplete step', () => {
    assert.equal(firstIncompleteStep(emptyForm()), 'location')
    assert.equal(firstIncompleteStep({ ...emptyForm(), areaType: 'URBAN' }), null)
  })

  it('has the summary as the last step', () => {
    assert.equal(STEP_ORDER.at(-1), 'summary')
  })
})
