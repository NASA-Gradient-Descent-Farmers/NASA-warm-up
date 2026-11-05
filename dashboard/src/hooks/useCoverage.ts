import { useEffect, useMemo, useState } from 'react'
import { fetchClimate, roundForNasa, type Climate } from '../lib/climate.ts'
import { compareClimate, coverage, type Comparison, type Verdict } from '../lib/coverage.ts'
import { distanceKm, type LatLon } from '../lib/geo.ts'

export type ClimateState =
  | { state: 'loading' }
  | { state: 'error'; message: string }
  | { state: 'ready'; here: Climate; reference: Climate; comparison: Comparison }

export interface CoverageInfo {
  distanceKm: number
  /** null while a mid-distance verdict waits for the climate. */
  verdict: Verdict | null
  climate: ClimateState
  retry: () => void
}

type Settled = { key: string; attempt: number; value: ClimateState }

/**
 * How far a pin is from the modeled site, that site's climate against the pin's (NASA POWER, asked once per
 * 0.1-degree cell), and the resulting verdict on whether the planner applies there.
 */
export function useCoverage(pin: LatLon | null, site: LatLon): CoverageInfo | null {
  const [attempt, setAttempt] = useState(0)
  const [settled, setSettled] = useState<Settled | null>(null)
  const key = pin ? `${roundForNasa(pin.lat)},${roundForNasa(pin.lon)}` : ''

  useEffect(() => {
    if (!key || !pin) return
    const controller = new AbortController()
    Promise.all([fetchClimate(pin, controller.signal), fetchClimate(site, controller.signal)]).then(
      ([here, reference]) =>
        setSettled({ key, attempt, value: { state: 'ready', here, reference, comparison: compareClimate(here, reference) } }),
      (error: unknown) => {
        if (error instanceof DOMException && error.name === 'AbortError') return
        setSettled({ key, attempt, value: { state: 'error', message: error instanceof Error ? error.message : String(error) } })
      },
    )
    return () => controller.abort()
    // `pin` is represented by `key`: moving it within the same 0.1-degree cell needs no new request
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, attempt, site.lat, site.lon])

  const climate: ClimateState = settled && settled.key === key && settled.attempt === attempt ? settled.value : { state: 'loading' }
  return useMemo(() => {
    if (!pin) return null
    const km = distanceKm(pin, site)
    const input = climate.state === 'ready' ? climate.comparison : climate.state === 'error' ? 'unavailable' : 'loading'
    return { distanceKm: km, verdict: coverage(km, input), climate, retry: () => setAttempt((n) => n + 1) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pin?.lat, pin?.lon, site.lat, site.lon, climate])
}
