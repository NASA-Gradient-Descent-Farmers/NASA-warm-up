import { describe, expect, it } from 'vitest'
import { distanceKm, formatCoords } from './geo.ts'

describe('distanceKm', () => {
  it('matches known distances', () => {
    expect(distanceKm({ lat: 51.5074, lon: -0.1278 }, { lat: 48.8566, lon: 2.3522 })).toBeCloseTo(343.6, 0) // London - Paris
    // Mexico City's Zocalo to El Baton: 10.8 km north and 29.7 km east, about 31.6 km
    expect(distanceKm({ lat: 19.4326, lon: -99.1332 }, { lat: 19.53, lon: -98.85 })).toBeCloseTo(31.6, 0)
  })

  it('is zero for the same point, symmetric, and half the Earth at the antipodes', () => {
    const a = { lat: 19.53, lon: -98.85 }
    const b = { lat: 25.7, lon: -100.3 }
    expect(distanceKm(a, a)).toBe(0)
    expect(distanceKm(a, b)).toBeCloseTo(distanceKm(b, a), 9)
    expect(distanceKm({ lat: 10, lon: 20 }, { lat: -10, lon: -160 })).toBeCloseTo(20015, -1)
  })
})

describe('formatCoords', () => {
  const es = { n: 'N', s: 'S', e: 'E', w: 'O' }
  it('writes hemisphere letters instead of signs', () => {
    expect(formatCoords({ lat: 19.534, lon: -98.846 }, es)).toBe('19.53° N, 98.85° O')
    expect(formatCoords({ lat: -33.4, lon: 151.2 }, es)).toBe('33.40° S, 151.20° E')
  })
})
