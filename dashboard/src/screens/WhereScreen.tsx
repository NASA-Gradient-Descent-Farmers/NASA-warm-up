import { useState } from 'react'
import { ClimateCard } from '../components/ClimateCard.tsx'
import { LangToggle } from '../components/LangToggle.tsx'
import type { WipeOrigin } from '../components/LeafTransition.tsx'
import { PinMap, type MapLayer } from '../components/PinMap.tsx'
import { VerdictCard } from '../components/VerdictCard.tsx'
import { useCoverage } from '../hooks/useCoverage.ts'
import { useI18n } from '../i18n/index.tsx'
import type { LatLon } from '../lib/geo.ts'

interface Props {
  initial: LatLon | null
  /** The one site the crop model covers. */
  site: LatLon
  onConfirm: (point: LatLon, from: WipeOrigin) => void
  onBack: (from: WipeOrigin) => void
}

const centreOf = (el: HTMLElement): WipeOrigin => {
  const box = el.getBoundingClientRect()
  return { x: box.left + box.width / 2, y: box.top + box.height / 2 }
}

/** "¿Dónde está tu parcela?": a map to drop a pin on, and what NASA says about the climate there. */
export function WhereScreen({ initial, site, onConfirm, onBack }: Props) {
  const { t, distance, coords } = useI18n()
  const [pin, setPin] = useState<LatLon | null>(initial)
  const [layer, setLayer] = useState<MapLayer>('street')
  const [tilesFailed, setTilesFailed] = useState(false)
  const info = useCoverage(pin, site)

  return (
    <div className="where">
      <div className="where-top">
        <button type="button" className="where-back" onClick={(e) => onBack(centreOf(e.currentTarget))}>
          ← {t('where.back')}
        </button>
        <LangToggle />
      </div>

      <div className="where-grid">
        <section className="where-main" aria-labelledby="where-title">
          <p className="where-eyebrow">{t('where.eyebrow')}</p>
          <h1 id="where-title" className="where-title">
            {t('where.title')}
          </h1>
          <p className="where-lede">{t('where.lede')}</p>

          <div className="map-card">
            <PinMap
              value={pin}
              onChange={setPin}
              layer={layer}
              site={site}
              siteLabel={t('where.site')}
              label={t('where.mapLabel')}
              onTilesFailed={setTilesFailed}
            />
            <div className="segmented small map-layers" role="group" aria-label={t('where.layers.label')}>
              {(['street', 'satellite'] as const).map((id) => (
                <button key={id} type="button" aria-pressed={layer === id} onClick={() => setLayer(id)}>
                  {t(`where.layers.${id}`)}
                </button>
              ))}
            </div>
            <p className="map-hint">{pin ? t('where.hintMove') : t('where.hintPlace')}</p>
            {tilesFailed && (
              <p className="map-offline" role="alert">
                {t('where.offline')}
              </p>
            )}
          </div>
        </section>

        <aside className="where-side">
          <div className="pin-status">
            <h2>{t('where.pin')}</h2>
            {pin && info ? (
              <>
                <p className="pin-coords">{coords(pin)}</p>
                <p className="pin-distance">{t('where.distance', { km: distance(info.distanceKm) })}</p>
              </>
            ) : (
              <p className="pin-distance">{t('where.noPin')}</p>
            )}
            <button type="button" className="link-quiet" onClick={() => setPin(site)}>
              {t('where.inTexcoco')}
            </button>
          </div>

          {info && <VerdictCard verdict={info.verdict} distanceKm={info.distanceKm} />}

          <button
            type="button"
            className="cv-button"
            disabled={!pin}
            onClick={(e) => pin && onConfirm(pin, centreOf(e.currentTarget))}
          >
            {pin ? t('where.continue') : t('where.needPin')}
          </button>

          {info && <ClimateCard climate={info.climate} onRetry={info.retry} />}
          <p className="where-foot">{t('where.privacy')}</p>
        </aside>
      </div>
    </div>
  )
}
