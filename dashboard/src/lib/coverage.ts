// Does the planner apply to where the farmer is? Every crop-model number in the app is for one site, the CIMMYT
// El Batán station near Texcoco, so a pin elsewhere gets an honest verdict instead of silently reusing it.
// The thresholds are our judgment calls, not NASA's or the model's.

import type { Climate } from './climate.ts'

/** Within about the size of one NASA POWER weather cell of the modeled site (a cell is about 55 km wide). */
export const INSIDE_KM = 25
/** Beyond this the site-specific calibration says nothing about the farmer's land, whatever the climate. */
export const NEAR_KM = 100
/** A nearby site still counts as similar if rain differs by less than this share of Texcoco's... */
export const RAIN_TOLERANCE = 0.2
/** ...and its mean temperature by less than this many degrees. */
export const TEMP_TOLERANCE_C = 2

export interface Comparison {
  /** (here - reference) / reference, annual rain. */
  rainDiffShare: number
  meanTempDiffC: number
  lowestMinDiffC: number
}

export function compareClimate(here: Climate, reference: Climate): Comparison {
  return {
    rainDiffShare: (here.rainAnnualMm - reference.rainAnnualMm) / reference.rainAnnualMm,
    meanTempDiffC: here.meanTempC - reference.meanTempC,
    lowestMinDiffC: here.lowestMinC - reference.lowestMinC,
  }
}

export type CoverageStatus = 'inside' | 'near' | 'outside'
export type CoverageReason = 'distance' | 'climate' | 'unchecked'
export interface Verdict {
  status: CoverageStatus
  /** Why it is not simply "inside": too far, a different climate, or no climate to compare. */
  reason: CoverageReason | null
}

/**
 * inside: within INSIDE_KM. outside: beyond NEAR_KM, or between the two with a climate that differs from the
 * modeled site's by more than the tolerances. near: between the two with a similar climate (or, when the
 * climate could not be fetched, no way to tell). Returns null when the answer depends on a climate still loading.
 */
export function coverage(distanceKm: number, climate: Comparison | 'loading' | 'unavailable'): Verdict | null {
  if (distanceKm <= INSIDE_KM) return { status: 'inside', reason: null }
  if (distanceKm > NEAR_KM) return { status: 'outside', reason: 'distance' }
  if (climate === 'loading') return null
  if (climate === 'unavailable') return { status: 'near', reason: 'unchecked' }
  const similar = Math.abs(climate.rainDiffShare) <= RAIN_TOLERANCE && Math.abs(climate.meanTempDiffC) <= TEMP_TOLERANCE_C
  return similar ? { status: 'near', reason: null } : { status: 'outside', reason: 'climate' }
}

/** Key of the verdict's text in the dictionaries (coverage.<key>.title / .body). */
export function verdictKey({ status, reason }: Verdict): string {
  if (status === 'inside') return 'inside'
  if (status === 'near') return reason === 'unchecked' ? 'nearUnchecked' : 'near'
  return reason === 'climate' ? 'outsideClimate' : 'outsideDistance'
}
