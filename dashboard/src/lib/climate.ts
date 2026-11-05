// Long-term climate of a point from NASA POWER's climatology service (monthly means of many years).
// The browser asks NASA directly; only a coordinate rounded to 0.1 degrees (about 11 km) is sent, which is finer
// than POWER's weather cell, so nothing is lost and the farmer's exact spot never leaves the device.

import type { LatLon } from './geo.ts'

export interface Climate {
  /** Mean rain of each month (January first), mm. */
  rainMonthlyMm: number[]
  rainAnnualMm: number
  /** Mean of the twelve monthly mean temperatures, degrees C. */
  meanTempC: number
  /** The lowest temperature NASA estimates here over its whole record, degrees C: one cold night, not an average.
   *  POWER's climatology T2M_MIN is each month's extreme (at El Baton, January shows -4.5 while the daily
   *  minimums of 2015-2024 averaged +4.3 and their lowest was -3.5), so this is the minimum of those. */
  lowestMinC: number
}

export const MONTH_KEYS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'] as const
const DAYS_IN_MONTH = [31, 28.25, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
const PARAMETERS = ['PRECTOTCORR', 'T2M', 'T2M_MIN'] as const
const POWER_FILL = -999

const mean = (values: number[]) => values.reduce((sum, v) => sum + v, 0) / values.length

/** A coordinate rounded to 0.1 degrees. */
export const roundForNasa = (degrees: number) => Math.round(degrees * 10) / 10

export function powerUrl({ lat, lon }: LatLon): string {
  const query = new URLSearchParams({
    parameters: PARAMETERS.join(','),
    community: 'AG',
    longitude: String(roundForNasa(lon)),
    latitude: String(roundForNasa(lat)),
    format: 'JSON',
  })
  return `https://power.larc.nasa.gov/api/temporal/climatology/point?${query}`
}

/** Climate from a POWER climatology response; throws if a month is missing or NASA reports no data. */
export function parsePower(json: unknown): Climate {
  const parameter = (json as { properties?: { parameter?: Record<string, Record<string, unknown>> } })?.properties?.parameter
  if (!parameter) throw new Error('unexpected answer from NASA POWER')
  const monthly = (name: (typeof PARAMETERS)[number]) => {
    const table = parameter[name]
    if (!table) throw new Error(`NASA POWER sent no ${name}`)
    return MONTH_KEYS.map((month) => {
      const value = table[month]
      if (typeof value !== 'number' || !Number.isFinite(value) || value === POWER_FILL) {
        throw new Error(`NASA POWER has no ${name} for ${month} here`)
      }
      return value
    })
  }
  const rainPerDay = monthly('PRECTOTCORR')
  const rainMonthlyMm = rainPerDay.map((perDay, i) => perDay * DAYS_IN_MONTH[i])
  return {
    rainMonthlyMm,
    rainAnnualMm: rainMonthlyMm.reduce((sum, v) => sum + v, 0),
    meanTempC: mean(monthly('T2M')),
    lowestMinC: Math.min(...monthly('T2M_MIN')),
  }
}

const cache = new Map<string, Promise<Climate>>()

/** Climate at a point, asked of NASA once per 0.1-degree cell and kept for the visit. */
export function fetchClimate(point: LatLon, signal?: AbortSignal): Promise<Climate> {
  const url = powerUrl(point)
  let pending = cache.get(url)
  if (!pending) {
    pending = fetch(url)
      .then(async (response) => {
        if (!response.ok) throw new Error(`NASA POWER answered ${response.status}`)
        return parsePower(await response.json())
      })
      .catch((error: unknown) => {
        cache.delete(url) // a failure is not remembered: the next visit asks again
        throw error
      })
    cache.set(url, pending)
  }
  if (!signal) return pending
  // A caller that stops waiting (its pin moved on) does not cancel the shared request, only its own wait.
  return new Promise<Climate>((resolve, reject) => {
    signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')), { once: true })
    pending.then(resolve, reject)
  })
}
