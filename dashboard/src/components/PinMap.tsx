import * as L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useEffect, useRef } from 'react'
import { INSIDE_KM } from '../lib/coverage.ts'
import type { LatLon } from '../lib/geo.ts'

export type MapLayer = 'street' | 'satellite'

// Street map: OpenStreetMap. Satellite: NASA GIBS "Blue Marble Next Generation" (about 500 m per pixel, so it
// is for seeing the land around, while the street map is for finding the exact spot).
const STREET = {
  url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
  options: { maxZoom: 17, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' },
}
const SATELLITE = {
  url: 'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/BlueMarble_NextGeneration/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpeg',
  options: { maxNativeZoom: 8, maxZoom: 11, attribution: 'Imagery &copy; NASA EOSDIS GIBS' },
}
const MEXICO: L.LatLngBoundsExpression = [
  [14.3, -118.6],
  [32.9, -86.5],
]
const TILE_ERRORS_BEFORE_GIVING_UP = 6

/** A teardrop pin in the Campo Verde colours with a leaf cut out of it. */
const PIN_ICON = L.divIcon({
  className: 'cv-pin-holder',
  html: `<div class="cv-pin"><svg viewBox="0 0 40 52" width="40" height="52" aria-hidden="true">
    <path d="M20 50C20 50 4 33 4 20a16 16 0 0 1 32 0c0 13-16 30-16 30z" fill="#d4532a" stroke="#12392a" stroke-width="2.5" stroke-linejoin="round"/>
    <path d="M20 31C13 29 12 21 15 14c8 1 12 6 10 13z" fill="#f5ecd6"/>
    <path d="M20 31c1-5 2-9 4-13" stroke="#d4532a" stroke-width="1.6" fill="none" stroke-linecap="round"/>
  </svg></div>`,
  iconSize: [40, 52],
  iconAnchor: [20, 50],
})

interface Props {
  value: LatLon | null
  onChange: (point: LatLon) => void
  layer: MapLayer
  /** The one site the crop model is calibrated for, drawn with the radius inside which the planner applies. */
  site: LatLon
  siteLabel: string
  label: string
  onTilesFailed: (failed: boolean) => void
}

const toLatLon = ({ lat, lng }: L.LatLng): LatLon => ({ lat, lon: lng })

export function PinMap({ value, onChange, layer, site, siteLabel, label, onTilesFailed }: Props) {
  const host = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const marker = useRef<L.Marker | null>(null)
  const tiles = useRef<L.TileLayer | null>(null)
  const latest = useRef({ onChange, onTilesFailed })
  useEffect(() => {
    latest.current = { onChange, onTilesFailed }
  })

  // The map itself, the modeled site and the ways to place the pin.
  useEffect(() => {
    const element = host.current
    if (!element) return
    const instance = L.map(element, { zoomControl: true, minZoom: 3, worldCopyJump: true })
    instance.fitBounds(MEXICO)
    L.circle([site.lat, site.lon], {
      radius: INSIDE_KM * 1000,
      color: '#1f7a45',
      weight: 2,
      dashArray: '6 6',
      fillColor: '#8fcf6a',
      fillOpacity: 0.22,
      interactive: false,
    }).addTo(instance)
    L.circleMarker([site.lat, site.lon], { radius: 6, color: '#12392a', weight: 2.5, fillColor: '#8fcf6a', fillOpacity: 1, interactive: false })
      .bindTooltip(siteLabel, { permanent: true, direction: 'right', offset: [8, 0], className: 'cv-site-tip' })
      .addTo(instance)
    instance.on('click', (e: L.LeafletMouseEvent) => latest.current.onChange(toLatLon(e.latlng)))
    // From the keyboard: arrows move the map, Enter drops the pin at its centre.
    const dropAtCentre = (e: KeyboardEvent) => {
      if (e.key === 'Enter' && e.target === instance.getContainer()) latest.current.onChange(toLatLon(instance.getCenter()))
    }
    instance.getContainer().addEventListener('keydown', dropAtCentre)
    map.current = instance
    return () => {
      instance.getContainer().removeEventListener('keydown', dropAtCentre)
      instance.remove()
      map.current = null
      marker.current = null
      tiles.current = null
    }
    // The site never changes while the map is shown.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [site.lat, site.lon, siteLabel])

  // The tile layer: swapped when the visitor changes layer.
  useEffect(() => {
    const instance = map.current
    if (!instance) return
    const source = layer === 'street' ? STREET : SATELLITE
    const tileLayer = L.tileLayer(source.url, source.options).addTo(instance)
    let errors = 0
    let loaded = 0
    latest.current.onTilesFailed(false)
    tileLayer.on('tileload', () => {
      loaded++
      if (loaded === 1) latest.current.onTilesFailed(false)
    })
    tileLayer.on('tileerror', () => {
      errors++
      if (loaded === 0 && errors >= TILE_ERRORS_BEFORE_GIVING_UP) latest.current.onTilesFailed(true)
    })
    instance.setMaxZoom(source.options.maxZoom)
    tiles.current = tileLayer
    return () => {
      tileLayer.remove()
      tiles.current = null
    }
  }, [layer, site.lat, site.lon, siteLabel])

  // The pin follows `value`; a pin set from outside the map (or off screen) brings the map to it.
  useEffect(() => {
    const instance = map.current
    if (!instance) return
    if (!value) {
      marker.current?.remove()
      marker.current = null
      return
    }
    const at: L.LatLngExpression = [value.lat, value.lon]
    if (!marker.current) {
      const pin = L.marker(at, { icon: PIN_ICON, draggable: true, title: label }).addTo(instance)
      pin.on('dragend', () => latest.current.onChange(toLatLon(pin.getLatLng())))
      marker.current = pin
    } else {
      marker.current.setLatLng(at)
    }
    if (!instance.getBounds().pad(-0.15).contains(at) || instance.getZoom() < 6) instance.flyTo(at, Math.max(instance.getZoom(), 9))
    // Restart the drop animation of the pin.
    const el = marker.current.getElement()?.querySelector('.cv-pin')
    if (el) {
      el.classList.remove('drop')
      void (el as HTMLElement).offsetWidth
      el.classList.add('drop')
    }
  }, [value, label])

  return <div className="pin-map" ref={host} role="application" aria-label={label} tabIndex={0} />
}
