import { afterEach, describe, expect, it, vi } from 'vitest'
import { loadPin, parsePin, savePin } from './location.ts'

describe('parsePin', () => {
  it('reads a stored pin', () => {
    expect(parsePin('{"lat":19.53,"lon":-98.85}')).toEqual({ lat: 19.53, lon: -98.85 })
  })

  it('refuses anything that is not a place on Earth', () => {
    for (const text of [null, '', 'nope', '{}', '{"lat":"19","lon":-98}', '{"lat":91,"lon":0}', '{"lat":0,"lon":-181}', '{"lat":null,"lon":1}', '[]']) {
      expect(parsePin(text), String(text)).toBeNull()
    }
  })
})

describe('storage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('keeps the pin with about one metre of precision and loads it back', () => {
    const store = new Map<string, string>()
    vi.stubGlobal('localStorage', { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v) })
    expect(loadPin()).toBeNull()
    savePin({ lat: 19.5312345678, lon: -98.8512345678 })
    expect(loadPin()).toEqual({ lat: 19.53123, lon: -98.85123 })
  })

  it('works without storage: nothing is saved and nothing throws', () => {
    const blocked = () => {
      throw new Error('blocked')
    }
    vi.stubGlobal('localStorage', { getItem: blocked, setItem: blocked })
    expect(() => savePin({ lat: 1, lon: 2 })).not.toThrow()
    expect(loadPin()).toBeNull()
  })
})
