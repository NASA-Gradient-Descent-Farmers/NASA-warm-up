import type { Lang } from '../lib/format.ts'
import { en, type Dict } from './en.ts'
import { es } from './es.ts'

export const DICTIONARIES: Record<Lang, Dict> = { en, es }

/** Text at a dotted path ("planner.plan.title") with {name} placeholders filled in; the path itself if missing. */
export function translate(dict: Dict, path: string, vars: Record<string, string | number> = {}): string {
  let node: unknown = dict
  for (const part of path.split('.')) {
    node = typeof node === 'object' && node !== null ? (node as Record<string, unknown>)[part] : undefined
  }
  if (typeof node !== 'string') return path
  return node.replace(/\{(\w+)\}/g, (_, name: string) => (name in vars ? String(vars[name]) : `{${name}}`))
}
