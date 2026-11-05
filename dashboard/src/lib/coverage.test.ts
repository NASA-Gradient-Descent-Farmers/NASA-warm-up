import { describe, expect, it } from 'vitest'
import type { Climate } from './climate.ts'
import { compareClimate, coverage, INSIDE_KM, NEAR_KM, verdictKey, type Comparison } from './coverage.ts'

const texcoco: Climate = { rainMonthlyMm: [], rainAnnualMm: 900, meanTempC: 12, lowestMinC: -4.5 }
const comparison = (rain: number, temp: number): Comparison => ({ rainDiffShare: rain, meanTempDiffC: temp, lowestMinDiffC: 0 })

describe('compareClimate', () => {
  it('is relative for rain and absolute for temperatures', () => {
    const drier: Climate = { rainMonthlyMm: [], rainAnnualMm: 450, meanTempC: 14.5, lowestMinC: -1.5 }
    expect(compareClimate(drier, texcoco)).toEqual({ rainDiffShare: -0.5, meanTempDiffC: 2.5, lowestMinDiffC: 3 })
  })
})

describe('coverage', () => {
  it('is inside up to INSIDE_KM, whatever the climate', () => {
    expect(coverage(0, 'loading')).toEqual({ status: 'inside', reason: null })
    expect(coverage(INSIDE_KM, comparison(0.9, 9))).toEqual({ status: 'inside', reason: null })
  })

  it('is outside beyond NEAR_KM even with an identical climate', () => {
    expect(coverage(NEAR_KM + 1, comparison(0, 0))).toEqual({ status: 'outside', reason: 'distance' })
    expect(coverage(800, 'loading')).toEqual({ status: 'outside', reason: 'distance' }) // no need to wait for climate
  })

  it('in between, depends on how similar the climate is', () => {
    expect(coverage(60, comparison(0.15, 1.5))).toEqual({ status: 'near', reason: null })
    expect(coverage(60, comparison(-0.2, -2))).toEqual({ status: 'near', reason: null }) // exactly at the tolerances
    expect(coverage(60, comparison(0.25, 0))).toEqual({ status: 'outside', reason: 'climate' })
    expect(coverage(60, comparison(0, -2.1))).toEqual({ status: 'outside', reason: 'climate' })
  })

  it('waits for the climate in between, and says so when it never comes', () => {
    expect(coverage(60, 'loading')).toBeNull()
    expect(coverage(60, 'unavailable')).toEqual({ status: 'near', reason: 'unchecked' })
  })
})

describe('verdictKey', () => {
  it('names the text for every verdict', () => {
    expect(verdictKey({ status: 'inside', reason: null })).toBe('inside')
    expect(verdictKey({ status: 'near', reason: null })).toBe('near')
    expect(verdictKey({ status: 'near', reason: 'unchecked' })).toBe('nearUnchecked')
    expect(verdictKey({ status: 'outside', reason: 'distance' })).toBe('outsideDistance')
    expect(verdictKey({ status: 'outside', reason: 'climate' })).toBe('outsideClimate')
  })
})
