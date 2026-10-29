// Run with `npm test` (Node's built-in test runner; no extra dependencies).
// Fixtures are JSON snapshots of the backend reference data; regenerate them with
// `python -m app.data.export_demo_fixture` from backend/ (a backend test fails if stale).

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { describe, it } from 'node:test'
import type {
  BandGroup,
  MobilityOptionSummary,
  QuestionnaireConfig,
  UserProfile,
} from '../api/types.ts'
import { emptyForm, newAdult, unknownAnswer } from './defaults.ts'
import { answerToNumeric, formToProfile, numericToAnswer, profileToForm } from './mapping.ts'
import type { FormState } from './types.ts'

function fixture<T>(name: string): T {
  return JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), 'utf-8')) as T
}

const config = fixture<QuestionnaireConfig>('questionnaire.json')
const options = fixture<MobilityOptionSummary[]>('mobility_options.json')
const households = fixture<Record<string, UserProfile>>('demo_households.json')
const makeId = () => 'test-id'

function bands(name: string): BandGroup {
  const found = config.groups[name]
  assert.ok(found, `missing band group ${name}`)
  return found
}

describe('numeric answers', () => {
  const km = bands('annual_km_per_car')
  const parking = bands('parking_cost_year')

  it('turns a band into a range', () => {
    assert.deepEqual(numericToAnswer({ kind: 'band', bandId: 'lt_5k' }, km), {
      exact: null,
      low: 0,
      high: 5000,
    })
  })

  it('turns a band with low == high into an exact answer', () => {
    assert.deepEqual(numericToAnswer({ kind: 'band', bandId: 'none' }, parking), {
      exact: 0,
      low: null,
      high: null,
    })
  })

  it('turns "I do not know" and an empty exact value into an all-null answer', () => {
    assert.deepEqual(numericToAnswer({ kind: 'unknown' }, km), unknownAnswer())
    assert.deepEqual(numericToAnswer({ kind: 'exact', value: null }, km), unknownAnswer())
  })

  it('ignores a band id that no longer exists', () => {
    assert.deepEqual(numericToAnswer({ kind: 'band', bandId: 'gone' }, km), unknownAnswer())
  })

  it('finds the band again when reading an answer back', () => {
    assert.deepEqual(answerToNumeric({ exact: null, low: 5000, high: 10000 }, km), {
      kind: 'band',
      bandId: '5k_10k',
    })
    assert.deepEqual(answerToNumeric({ exact: 0, low: null, high: null }, parking), {
      kind: 'band',
      bandId: 'none',
    })
  })

  it('keeps values that match no band', () => {
    assert.deepEqual(answerToNumeric({ exact: 7300, low: null, high: null }, km), {
      kind: 'exact',
      value: 7300,
    })
    assert.deepEqual(answerToNumeric({ exact: null, low: 6000, high: 9000 }, km), {
      kind: 'range',
      low: 6000,
      high: 9000,
    })
  })

  it('reads nothing as unknown', () => {
    assert.deepEqual(answerToNumeric(null, km), { kind: 'unknown' })
    assert.deepEqual(answerToNumeric(unknownAnswer(), km), { kind: 'unknown' })
  })
})

describe('profile -> form -> profile round trip', () => {
  for (const [name, profile] of Object.entries(households)) {
    it(`loses nothing for the demo household "${name}"`, () => {
      const form = profileToForm(profile, config, options)
      assert.deepEqual(formToProfile(form, config, makeId), profile)
    })
  }

  it('separates cars from other vehicles and PT passes from other subscriptions', () => {
    const form = profileToForm(households['car_free_household']!, config, options)
    assert.equal(form.cars.length, 0)
    assert.equal(form.otherVehicles.length, 2)
    assert.deepEqual(
      form.adults.map((adult) => adult.ptPassOptionId),
      ['pt_annual_urban_milano', 'pt_annual_urban_milano'],
    )

    const family = profileToForm(households['family_two_cars']!, config, options)
    assert.equal(family.cars.length, 2)
    assert.equal(family.nChildren, 2)
    assert.equal(family.simultaneousCarNeed, 'OFTEN')
  })
})

function completeForm(): FormState {
  const form = emptyForm()
  return { ...form, areaType: 'URBAN' }
}

describe('form -> profile', () => {
  it('refuses a form without an area type', () => {
    assert.throws(() => formToProfile(emptyForm(), config, makeId), /area type/)
  })

  it('builds a valid minimal profile from a fresh form', () => {
    const profile = formToProfile(completeForm(), config, makeId)
    assert.equal(profile.id, 'test-id')
    assert.equal(profile.mode, 'QUICK')
    assert.equal(profile.household.adults.length, 1)
    assert.equal(profile.household.location.area_type, 'URBAN')
    assert.equal(profile.household.location.municipality, null)
    assert.deepEqual(profile.vehicles, [])
    assert.deepEqual(profile.subscriptions, [])
    assert.equal(profile.preferences.sustainability, 0, 'values-based preferences default to off')
  })

  it('maps commute answers to the work pattern', () => {
    const form = completeForm()
    form.adults = [
      {
        ...newAdult(0),
        distanceKm: { kind: 'band', bandId: 'from_8' },
        daysPerWeek: 4,
        remoteDaysPerWeek: 1,
        timeCritical: true,
      },
    ]
    const work = formToProfile(form, config, makeId).household.adults[0]!.work_or_study
    assert.deepEqual(work?.one_way_distance_km, { exact: null, low: 8, high: 15 })
    assert.deepEqual(work?.days_per_week, { exact: 4, low: null, high: null })
    assert.deepEqual(work?.remote_days_per_week, { exact: 1, low: null, high: null })
    assert.equal(work?.time_critical, true)
  })

  it('drops work details for retired adults', () => {
    const form = completeForm()
    form.adults = [{ ...newAdult(0), occupation: 'RETIRED' }]
    assert.equal(formToProfile(form, config, makeId).household.adults[0]!.work_or_study, null)
  })

  it('builds vehicles and sequentially numbered subscriptions', () => {
    const form = completeForm()
    form.adults = [
      { ...newAdult(0), ptPassOptionId: 'pt_annual_urban_milano', otherSubscriptionIds: ['bikemi_annual'] },
      { ...newAdult(1), ptPassOptionId: 'pt_monthly_urban_milano' },
    ]
    form.cars = [
      {
        id: 'car1',
        optionId: 'car_small_petrol',
        annualKm: { kind: 'band', bandId: 'lt_5k' },
        parkingCostYear: { kind: 'band', bandId: 'none' },
        base: null,
      },
    ]
    const profile = formToProfile(form, config, makeId)
    assert.deepEqual(
      profile.subscriptions.map((s) => [s.id, s.option_id, s.holder_id]),
      [
        ['sub1', 'pt_annual_urban_milano', 'p1'],
        ['sub2', 'bikemi_annual', 'p1'],
        ['sub3', 'pt_monthly_urban_milano', 'p2'],
      ],
    )
    assert.equal(profile.vehicles.length, 1)
    assert.deepEqual(profile.vehicles[0]!.annual_km, { exact: null, low: 0, high: 5000 })
    assert.deepEqual(profile.vehicles[0]!.parking_cost_year, { exact: 0, low: null, high: null })
  })

  it('skips a car whose type has not been chosen yet', () => {
    const form = completeForm()
    form.cars = [
      { id: 'car1', optionId: null, annualKm: { kind: 'unknown' }, parkingCostYear: { kind: 'unknown' }, base: null },
    ]
    assert.deepEqual(formToProfile(form, config, makeId).vehicles, [])
  })

  it('trims the municipality and stores blank as null', () => {
    const form = { ...completeForm(), municipality: '  Milano ' }
    assert.equal(formToProfile(form, config, makeId).household.location.municipality, 'Milano')
    assert.equal(
      formToProfile({ ...form, municipality: '   ' }, config, makeId).household.location.municipality,
      null,
    )
  })

  it('keeps fields the questionnaire does not ask when editing a loaded profile', () => {
    const profile = structuredClone(households['peripheral_family']!)
    profile.household.location.pt_quality = 'LOW'
    profile.household.adults[0]!.age_range = 'A35_44'
    const form = profileToForm(profile, config, options)
    form.nChildren = 2
    const result = formToProfile(form, config, makeId)
    assert.equal(result.household.n_children, 2)
    assert.equal(result.household.location.pt_quality, 'LOW')
    assert.equal(result.household.adults[0]!.age_range, 'A35_44')
    assert.equal(result.id, profile.id)
  })
})
