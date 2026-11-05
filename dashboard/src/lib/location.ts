import type { LatLon } from './geo.ts'

const STORAGE_KEY = 'campo-verde-pin'

/** A pin from stored text, or null if it is missing, malformed or not a place on Earth. */
export function parsePin(text: string | null): LatLon | null {
  if (!text) return null
  try {
    const { lat, lon } = JSON.parse(text) as Partial<LatLon>
    if (typeof lat !== 'number' || typeof lon !== 'number') return null
    if (!Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) return null
    return { lat, lon }
  } catch {
    return null
  }
}

/** The farmer's pin, kept only in this browser (about 1 m precision). */
export function loadPin(): LatLon | null {
  try {
    return parsePin(localStorage.getItem(STORAGE_KEY))
  } catch {
    return null
  }
}

export function savePin({ lat, lon }: LatLon): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ lat: Number(lat.toFixed(5)), lon: Number(lon.toFixed(5)) }))
  } catch {
    // storage blocked: the pin lasts for this visit only
  }
}
