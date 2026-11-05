import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchClimate, MONTH_KEYS, parsePower, powerUrl, roundForNasa } from './climate.ts'

const monthly = (value: (i: number) => number) => ({
  ...Object.fromEntries(MONTH_KEYS.map((m, i) => [m, value(i)])),
  ANN: 0,
})
const response = (overrides: Record<string, unknown> = {}) => ({
  properties: {
    parameter: {
      PRECTOTCORR: monthly(() => 2), // 2 mm per day all year
      T2M: monthly((i) => 10 + i), // 10 ... 21 degrees, mean 15.5
      T2M_MIN: monthly((i) => 4 - i), // 4 ... -7 degrees, the coldest month is -7
      ...overrides,
    },
  },
})

describe('parsePower', () => {
  it('turns mm per day into mm per month and sums the year', () => {
    const climate = parsePower(response())
    expect(climate.rainMonthlyMm[0]).toBe(62) // January: 31 days x 2
    expect(climate.rainMonthlyMm[1]).toBeCloseTo(56.5) // February counts 28.25 days
    expect(climate.rainAnnualMm).toBeCloseTo(2 * 365.25)
  })

  it('takes the mean temperature and the lowest of the monthly minimums', () => {
    const climate = parsePower(response())
    expect(climate.meanTempC).toBeCloseTo(15.5)
    expect(climate.lowestMinC).toBe(-7)
  })

  it('refuses answers with a fill value, a missing month or parameter, or another shape', () => {
    expect(() => parsePower(response({ T2M: monthly((i) => (i === 3 ? -999 : 10)) }))).toThrow(/APR/)
    expect(() => parsePower(response({ T2M_MIN: { JAN: 1 } }))).toThrow(/FEB/)
    expect(() => parsePower(response({ T2M: undefined }))).toThrow(/T2M/)
    expect(() => parsePower({ properties: {} })).toThrow(/unexpected/)
    expect(() => parsePower(null)).toThrow(/unexpected/)
    expect(() => parsePower(response({ PRECTOTCORR: monthly(() => Number.NaN) }))).toThrow(/PRECTOTCORR/)
  })
})

describe('powerUrl', () => {
  it('sends the coordinate rounded to 0.1 degrees, never the exact spot', () => {
    expect(roundForNasa(19.5349)).toBe(19.5)
    const url = new URL(powerUrl({ lat: 19.5349, lon: -98.8612 }))
    expect(url.searchParams.get('latitude')).toBe('19.5')
    expect(url.searchParams.get('longitude')).toBe('-98.9')
    expect(url.searchParams.get('parameters')).toBe('PRECTOTCORR,T2M,T2M_MIN')
    expect(url.origin).toBe('https://power.larc.nasa.gov')
  })
})

describe('fetchClimate', () => {
  afterEach(() => vi.unstubAllGlobals())
  const ok = () => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(response()) })

  it('asks NASA once for the same 0.1-degree cell, even for concurrent callers', async () => {
    const fetchMock = vi.fn(ok)
    vi.stubGlobal('fetch', fetchMock)
    const [a, b] = await Promise.all([fetchClimate({ lat: 30.01, lon: -105.02 }), fetchClimate({ lat: 30.03, lon: -105.04 })])
    expect(a).toBe(b)
    await fetchClimate({ lat: 30.0, lon: -105.0 })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('does not remember a failure', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: () => Promise.resolve({}) })
      .mockImplementation(ok)
    vi.stubGlobal('fetch', fetchMock)
    const point = { lat: 31.5, lon: -106.5 }
    await expect(fetchClimate(point)).rejects.toThrow(/503/)
    await expect(fetchClimate(point)).resolves.toMatchObject({ lowestMinC: -7 })
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('stops waiting when aborted, without cancelling the shared request', async () => {
    vi.stubGlobal('fetch', vi.fn(ok))
    const controller = new AbortController()
    const point = { lat: 32.5, lon: -107.5 }
    const waiting = fetchClimate(point, controller.signal)
    controller.abort()
    await expect(waiting).rejects.toMatchObject({ name: 'AbortError' })
    await expect(fetchClimate(point)).resolves.toBeDefined() // the request itself carried on
  })
})
