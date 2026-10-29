// How numbers are shown. The cases mirror backend/tests/test_recommendations.py (TestWording), so a
// figure on a card and the same figure in a sentence of the explanation agree.

import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import {
  euroRange,
  euros,
  hours,
  hoursInText,
  kilometres,
  roundMoney,
  score,
  signedEuros,
  signedHours,
  signedScore,
} from './format.ts'

describe('money', () => {
  it('is rounded to what an estimate can support', () => {
    assert.equal(euros(3537), '3.550 €')
    assert.equal(euros(442), '440 €')
    assert.equal(euros(64), '65 €')
    assert.equal(euros(7), '7 €')
  })

  it('groups thousands from 1.000, as Italians write them', () => {
    assert.equal(euros(1250), '1.250 €')
    assert.equal(euros(12345), '12.350 €')
    assert.equal(euros(999), '1.000 €') // rounded to 10 first
  })

  it('has no sign unless asked for one', () => {
    assert.equal(euros(-1850), '1.850 €')
    assert.equal(signedEuros(-3537), '−3.550 €')
    assert.equal(signedEuros(610), '+610 €')
  })

  it('shows no change as no change', () => {
    assert.equal(signedEuros(0), '0 €')
    assert.equal(signedEuros(0.4), '0 €')
  })

  it('rounds by size, like the backend', () => {
    assert.equal(roundMoney(1.9), 2)
    assert.equal(roundMoney(37), 35)
    assert.equal(roundMoney(442), 440)
    assert.equal(roundMoney(3537), 3550)
  })

  it('gives a range only where it says something', () => {
    assert.equal(euroRange(2900, 4550), 'tra 2.900 e 4.550 €')
    assert.equal(euroRange(-95, 160), 'tra −95 e 160 €')
    assert.equal(euroRange(100, 105), null)
  })
})

describe('time, comfort and distance', () => {
  it('rounds hours to the unit, and to five above a hundred', () => {
    assert.equal(hours(36.4), '36 h')
    assert.equal(hours(283.4), '285 h')
    assert.equal(hours(2055), '2.055 h')
  })

  it('agrees in number inside a sentence', () => {
    assert.equal(hoursInText(1), '1 ora')
    assert.equal(hoursInText(9), '9 ore')
    assert.equal(hoursInText(-36.4), '36 ore')
  })

  it('signs a change of hours with a real minus', () => {
    assert.equal(signedHours(-59), '−59 h')
    assert.equal(signedHours(61), '+61 h')
    assert.equal(signedHours(0.2), '0 h')
  })

  it('writes scores with a decimal comma', () => {
    assert.equal(score(7.84), '7,8')
    assert.equal(score(10), '10,0')
    assert.equal(signedScore(-1.3), '−1,3')
    assert.equal(signedScore(0.04), '0,0')
  })

  it('rounds kilometres to the hundred above a thousand', () => {
    assert.equal(kilometres(10389), '10.400 km')
    assert.equal(kilometres(640), '640 km')
    assert.equal(kilometres(0), '0 km')
  })
})
