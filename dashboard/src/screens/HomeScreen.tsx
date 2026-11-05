import type { CSSProperties, ReactNode } from 'react'
import { LangToggle } from '../components/LangToggle.tsx'
import { LeafHero, LeafMark } from '../components/Leaf.tsx'
import { CoinIcon, MagnifierIcon, RainIcon, SeedlingIcon } from '../components/icons.tsx'
import type { WipeOrigin } from '../components/LeafTransition.tsx'
import { useI18n } from '../i18n/index.tsx'
import type { LatLon } from '../lib/geo.ts'

export type Destination = 'planner' | 'economics' | 'reality' | 'whatifs'

const OPTIONS: { id: Destination; icon: ReactNode; built: boolean }[] = [
  { id: 'planner', icon: <SeedlingIcon />, built: true },
  { id: 'economics', icon: <CoinIcon />, built: false },
  { id: 'reality', icon: <MagnifierIcon />, built: false },
  { id: 'whatifs', icon: <RainIcon />, built: false },
]

/** Leaves drifting down behind everything: [left %, size px, seconds, delay s, turn deg]. */
const DRIFTERS: [number, number, number, number, number][] = [
  [6, 26, 19, 3.2, 40],
  [21, 16, 24, 7, -60],
  [44, 22, 21, 11, 25],
  [63, 14, 26, 5, -30],
  [78, 24, 20, 14, 70],
  [92, 18, 23, 9, -45],
]

interface HomeProps {
  onChoose: (to: Destination, from: WipeOrigin) => void
  /** The farmer's saved pin, if any, and how to move it. */
  pin: LatLon | null
  onChangePin: (from: WipeOrigin) => void
}

export function HomeScreen({ onChoose, pin, onChangePin }: HomeProps) {
  const { t, coords } = useI18n()
  const title = t('home.title')
  // Words with the index of their first letter, so the letters rise one after the other across the words.
  const words = title.split(' ').map((word, i, all) => ({ word, start: all.slice(0, i).join(' ').length + (i > 0 ? 1 : 0) }))

  return (
    <div className="home">
      <div className="home-sky" aria-hidden="true">
        <div className="home-sun" />
        <svg className="furrows" viewBox="0 0 1000 300" preserveAspectRatio="none" focusable="false">
          {Array.from({ length: 17 }, (_, i) => (
            <path key={i} d={`M500 0L${500 + (i - 8) * 150} 300`} />
          ))}
        </svg>
        {DRIFTERS.map(([left, size, seconds, delay, turn], i) => (
          <LeafMark
            key={i}
            className="drifter"
            style={{ left: `${left}%`, width: size, '--dur': `${seconds}s`, '--delay': `${delay}s`, '--turn': `${turn}deg` } as CSSProperties}
          />
        ))}
      </div>

      <LangToggle className="home-lang" />

      <main className="home-copy">
        <p className="home-eyebrow">{t('home.eyebrow')}</p>
        <h1 className="home-title" aria-label={title}>
          {words.map(({ word, start }) => (
            <span key={start} className="word" aria-hidden="true">
              {[...word].map((letter, i) => (
                <span key={i} className="letter" style={{ '--i': start + i } as CSSProperties}>
                  {letter}
                </span>
              ))}
            </span>
          ))}
        </h1>
        <p className="home-tagline">{t('home.tagline')}</p>

        <p className="home-hello">{t('home.hello')}</p>
        <h2 className="home-ask">{t('home.ask')}</h2>

        <div className="loteria-grid">
          {OPTIONS.map(({ id, icon, built }, index) => (
            <button
              key={id}
              type="button"
              className="loteria"
              style={{ '--n': index } as CSSProperties}
              onClick={(e) => {
                const box = e.currentTarget.getBoundingClientRect()
                onChoose(id, e.detail === 0 ? { x: box.left + box.width / 2, y: box.top + box.height / 2 } : { x: e.clientX, y: e.clientY })
              }}
            >
              <span className="loteria-side">
                <span className="loteria-art">{icon}</span>
                <span className="loteria-number">{t('home.number', { n: index + 1 })}</span>
              </span>
              <span className="loteria-title">
                {t(`home.options.${id}.title`)}
                {!built && <span className="loteria-soon">{t('home.soon')}</span>}
              </span>
              <span className="loteria-body">{t(`home.options.${id}.body`)}</span>
            </button>
          ))}
        </div>
        {pin && (
          <p className="home-pin">
            {t('home.yourPin', { coords: coords(pin) })} ·{' '}
            <button
              type="button"
              className="link-quiet"
              onClick={(e) => {
                const box = e.currentTarget.getBoundingClientRect()
                onChangePin({ x: box.left + box.width / 2, y: box.top + box.height / 2 })
              }}
            >
              {t('where.change')}
            </button>
          </p>
        )}
        <p className="home-foot">{t('home.foot')}</p>
      </main>

      <div className="home-stage" aria-hidden="true">
        <LeafHero />
      </div>
    </div>
  )
}
