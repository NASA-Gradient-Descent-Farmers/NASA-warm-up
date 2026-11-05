import { describe, expect, it } from 'vitest'
import { DICTIONARIES, translate } from './translate.ts'

const leaves = (node: unknown, prefix = ''): string[] =>
  typeof node === 'string'
    ? [prefix]
    : Object.entries(node as Record<string, unknown>).flatMap(([key, child]) => leaves(child, prefix ? `${prefix}.${key}` : key))

describe('dictionaries', () => {
  it('Spanish has exactly the keys English has', () => {
    expect(leaves(DICTIONARIES.es).sort()).toEqual(leaves(DICTIONARIES.en).sort())
  })

  it('keeps the same {placeholders} in both languages', () => {
    const placeholders = (text: string) => (text.match(/\{\w+\}/g) ?? []).sort()
    for (const path of leaves(DICTIONARIES.en)) {
      const english = translate(DICTIONARIES.en, path)
      expect(placeholders(translate(DICTIONARIES.es, path)), path).toEqual(placeholders(english))
    }
  })
})

describe('translate', () => {
  it('fills placeholders and falls back to the path for unknown keys', () => {
    expect(translate(DICTIONARIES.en, 'planner.plan.fertilizerValue', { kg: 96 })).toBe('96 kg N/ha')
    expect(translate(DICTIONARIES.en, 'planner.nope')).toBe('planner.nope')
    expect(translate(DICTIONARIES.en, 'planner.plan.fertilizerValue')).toBe('{kg} kg N/ha')
  })
})
