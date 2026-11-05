import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { makeFormat, type Format, type Lang } from '../lib/format.ts'
import { formatCoords, type LatLon } from '../lib/geo.ts'
import { DICTIONARIES, translate } from './translate.ts'

const STORAGE_KEY = 'campo-verde-lang'

function initialLang(): Lang {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved === 'en' || saved === 'es') return saved
  } catch {
    // storage can be blocked; fall through to the browser language
  }
  return 'es' // Campo Verde is for Texcoco: Spanish unless the visitor picked English
}

interface I18n {
  lang: Lang
  setLang: (lang: Lang) => void
  t: (path: string, vars?: Record<string, string | number>) => string
  fmt: Format
  /** A distance as it reads in a sentence: "748", or "less than 1" under a kilometre. */
  distance: (km: number) => string
  /** "19.53° N, 98.85° O" in the language's hemisphere letters. */
  coords: (point: LatLon) => string
}

const Context = createContext<I18n | null>(null)

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(initialLang)
  const setLang = useCallback((next: Lang) => {
    setLangState(next)
    document.documentElement.lang = next
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // not persisted; the choice still applies for this visit
    }
  }, [])
  const value = useMemo<I18n>(
    () => ({
      lang,
      setLang,
      t: (path, vars) => translate(DICTIONARIES[lang], path, vars),
      fmt: makeFormat(lang),
      distance: (km) => (km < 1 ? translate(DICTIONARIES[lang], 'where.lessThanOne') : makeFormat(lang).number(km)),
      coords: (point) => {
        const [n, s, e, w] = translate(DICTIONARIES[lang], 'app.hemispheres').split(',')
        return formatCoords(point, { n, s, e, w })
      },
    }),
    [lang, setLang],
  )
  return <Context.Provider value={value}>{children}</Context.Provider>
}

export function useI18n(): I18n {
  const value = useContext(Context)
  if (!value) throw new Error('useI18n needs an I18nProvider')
  return value
}
