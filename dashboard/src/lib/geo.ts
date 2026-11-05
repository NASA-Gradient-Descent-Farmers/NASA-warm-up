export interface LatLon {
  lat: number
  lon: number
}

const EARTH_RADIUS_KM = 6371

/** Great-circle distance between two points (haversine), in km. */
export function distanceKm(a: LatLon, b: LatLon): number {
  const rad = (deg: number) => (deg * Math.PI) / 180
  const dLat = rad(b.lat - a.lat)
  const dLon = rad(b.lon - a.lon)
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLon / 2) ** 2
  return 2 * EARTH_RADIUS_KM * Math.asin(Math.min(1, Math.sqrt(h)))
}

/** "19.53° N, 98.85° W" with the hemisphere letters of the language (west is O in Spanish). */
export function formatCoords({ lat, lon }: LatLon, hemispheres: { n: string; s: string; e: string; w: string }): string {
  const ns = lat >= 0 ? hemispheres.n : hemispheres.s
  const ew = lon >= 0 ? hemispheres.e : hemispheres.w
  return `${Math.abs(lat).toFixed(2)}° ${ns}, ${Math.abs(lon).toFixed(2)}° ${ew}`
}
