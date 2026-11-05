import { useEffect, useState } from 'react'
import { LangToggle } from './components/LangToggle.tsx'
import { PinGlyph } from './components/icons.tsx'
import { LeafMark } from './components/Leaf.tsx'
import { LeafTransition, type WipeOrigin } from './components/LeafTransition.tsx'
import { useCoverage } from './hooks/useCoverage.ts'
import { useI18n } from './i18n/index.tsx'
import { loadData } from './lib/data.ts'
import { verdictKey } from './lib/coverage.ts'
import type { LatLon } from './lib/geo.ts'
import { loadPin, savePin } from './lib/location.ts'
import type { DashboardData } from './lib/types.ts'
import { HomeScreen, type Destination } from './screens/HomeScreen.tsx'
import { PlannerScreen } from './screens/PlannerScreen.tsx'
import { WhereScreen } from './screens/WhereScreen.tsx'

const TABS = ['planner', 'economics', 'reality', 'whatifs'] as const
type Route = 'home' | 'where' | Destination

const prefersReducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches
const NO_SITE: LatLon = { lat: 0, lon: 0 } // only used before the data (and so the modeled site) has loaded

export default function App() {
  const { t, distance, lang, coords } = useI18n()
  const [route, setRoute] = useState<Route>('home')
  const [wipe, setWipe] = useState<{ origin: WipeOrigin; to: Route } | null>(null)
  const [data, setData] = useState<DashboardData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pin, setPin] = useState<LatLon | null>(loadPin)
  // Where the map step leads once the pin is confirmed, and where its back button returns to.
  const [after, setAfter] = useState<Destination>('planner')
  const [before, setBefore] = useState<Route>('home')

  const site: LatLon = data ? { lat: data.meta.site.latitude, lon: data.meta.site.longitude } : NO_SITE
  const coverage = useCoverage(data ? pin : null, site)

  useEffect(() => {
    document.documentElement.lang = lang
    document.title = t('app.title')
  }, [lang, t])

  useEffect(() => {
    loadData().then(setData, (e: unknown) => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  /** Go to a page behind the leaf wipe (straight away if the visitor asked for less motion). */
  const go = (to: Route, from: WipeOrigin) => {
    if (wipe) return
    if (prefersReducedMotion()) {
      setRoute(to)
      window.scrollTo(0, 0)
    } else {
      setWipe({ origin: from, to })
    }
  }

  /** Open the map step; `then` is where it leads and where "back" returns. */
  const openMap = (then: Destination, from: WipeOrigin, returnTo: Route) => {
    setAfter(then)
    setBefore(returnTo)
    go('where', from)
  }

  const transition = wipe && (
    <LeafTransition
      origin={wipe.origin}
      onCovered={() => {
        setRoute(wipe.to)
        window.scrollTo(0, 0)
      }}
      onDone={() => setWipe(null)}
    />
  )

  const shellDestination = route === 'home' || route === 'where' ? 'planner' : route

  let page
  if (route === 'home') {
    page = (
      <HomeScreen
        pin={pin}
        onChoose={(to, from) => (pin ? go(to, from) : openMap(to, from, 'home'))}
        onChangePin={(from) => openMap('planner', from, 'home')}
      />
    )
  } else if (route === 'where') {
    page = data ? (
      <WhereScreen
        initial={pin}
        site={site}
        onBack={(from) => go(before, from)}
        onConfirm={(point, from) => {
          savePin(point)
          setPin(point)
          go(after, from)
        }}
      />
    ) : (
      <p className="status">{error ? t('app.loadError', { message: error }) : t('app.loading')}</p>
    )
  } else {
    const verdict = coverage?.verdict
    page = (
      <div className="shell">
        <header className="app-header">
          <button
            type="button"
            className="brand-link"
            aria-label={t('app.home')}
            onClick={(e) => {
              const box = e.currentTarget.getBoundingClientRect()
              go('home', { x: box.left + 24, y: box.top + box.height / 2 })
            }}
          >
            <LeafMark className="brand-leaf" />
            <span className="brand-name">{t('app.title')}</span>
          </button>
          <p className="brand-tagline">{t('app.tagline')}</p>
          {pin && (
            <button
              type="button"
              className="pin-chip"
              onClick={(e) => {
                const box = e.currentTarget.getBoundingClientRect()
                openMap(shellDestination, { x: box.left + 16, y: box.top + box.height / 2 }, route)
              }}
            >
              <PinGlyph /> {t('where.pinLabel')}: {coords(pin)} · <u>{t('where.change')}</u>
            </button>
          )}
          <LangToggle />
        </header>

        <nav className="tabs" aria-label={t('nav.label')}>
          {TABS.map((id) => (
            <button key={id} type="button" aria-current={route === id ? 'page' : undefined} onClick={() => setRoute(id)}>
              {t(`nav.${id}`)}
            </button>
          ))}
        </nav>

        {coverage && verdict && verdict.status !== 'inside' && (
          <div className={`coverage-note ${verdict.status}`} role="note">
            <strong>{t(`coverage.${verdictKey(verdict)}.title`)}.</strong>{' '}
            {t(`coverage.${verdictKey(verdict)}.body`, { km: distance(coverage.distanceKm) })}{' '}
            <button
              type="button"
              className="link"
              onClick={(e) => {
                const box = e.currentTarget.getBoundingClientRect()
                openMap(shellDestination, { x: box.left + box.width / 2, y: box.top + box.height / 2 }, route)
              }}
            >
              {t('coverage.seeClimate')}
            </button>
          </div>
        )}

        <div className="caveat" role="note">
          <strong>{t('caveat.title')}</strong> {t('caveat.body')}
        </div>

        <main>
          {error && <p className="status error">{t('app.loadError', { message: error })}</p>}
          {!error && !data && <p className="status">{t('app.loading')}</p>}
          {data && route === 'planner' && <PlannerScreen data={data} />}
          {data && route !== 'planner' && (
            <section className="card coming" aria-labelledby="coming-title">
              <h2 id="coming-title">{t(`nav.${route}`)}</h2>
              <p className="lede">{t(`comingNext.${route}`)}</p>
              <p className="note">{t('comingNext.title')}</p>
            </section>
          )}
        </main>
      </div>
    )
  }

  // The wipe sits at the same place in the tree whichever page is shown, so it survives the page swap.
  return (
    <>
      {page}
      {transition}
    </>
  )
}
