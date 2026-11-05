import type { ObjectiveKey } from './types.ts'

export type Lang = 'en' | 'es'

const LOCALES: Record<Lang, string> = { en: 'en-US', es: 'es-MX' }
/** Decimals shown per objective. */
const DIGITS: Record<ObjectiveKey, number> = {
  yield_t_ha: 2,
  net_mxn_ha: 0,
  n_loss_kg_ha: 0,
  c_input_t_ha: 2,
  cvar_net_mxn_ha: 0,
}

export function makeFormat(lang: Lang) {
  const locale = LOCALES[lang]
  const fixed = (digits: number) => new Intl.NumberFormat(locale, { minimumFractionDigits: digits, maximumFractionDigits: digits })
  const compact = new Intl.NumberFormat(locale, { notation: 'compact', maximumFractionDigits: 1 })
  const percent = new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 0 })
  const month = new Intl.DateTimeFormat(locale, { month: 'short', timeZone: 'UTC' })
  const monthLong = new Intl.DateTimeFormat(locale, { month: 'long', timeZone: 'UTC' })
  return {
    /** Short month name, 0 = January ("ene", "Jan"). */
    monthShort: (index: number) => month.format(new Date(Date.UTC(2001, index, 1))).replace('.', ''),
    monthLong: (index: number) => monthLong.format(new Date(Date.UTC(2001, index, 1))),
    /** With an explicit sign: +12, -8 (a real minus sign) and 0 without one. */
    signed: (value: number, digits = 0) => {
      const text = fixed(digits).format(Math.abs(value))
      const rounded = Number(Math.abs(value).toFixed(digits))
      return rounded === 0 ? text : `${value < 0 ? '\u2212' : '+'}${text}`
    },
    number: (value: number, digits = 0) => fixed(digits).format(value),
    /** An objective value with its usual number of decimals. */
    objective: (key: ObjectiveKey, value: number) => fixed(DIGITS[key]).format(value),
    /** Axis tick: compact from 10,000 up (10K), plain below. */
    tick: (value: number) =>
      Math.abs(value) >= 10000 ? compact.format(value) : new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(value),
    percent: (share: number) => percent.format(share),
  }
}

export type Format = ReturnType<typeof makeFormat>
