import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { parseData } from './data.ts'
import { choose, goodness, paretoFront } from './front.ts'
import { Planner } from './planner.ts'
import type { Economics, GridFile, Meta, ObjectiveKey, Strategy, Values, WorldKey } from './types.ts'
import { OBJECTIVES } from './types.ts'

const read = <T>(path: string) => JSON.parse(readFileSync(new URL(path, import.meta.url), 'utf8')) as T
const data = parseData(read<Meta>('../../public/data/meta.json'), read<GridFile>('../../public/data/grid.json'))
const reference = read<{ columns: string[]; worlds: Record<string, (string | number)[][]> }>('./fixtures/reference_fronts.json')
const { maximize, meta } = data

/** The exact five-objective front of the whole lattice, scored live from grid.json like the app does. */
const fronts = new Map<string, Strategy[]>()
function liveFront(world: WorldKey, economics: Economics = meta.economics): Strategy[] {
  const key = world + JSON.stringify(economics)
  if (!fronts.has(key)) {
    const all = new Planner(data.grids[world], economics).bruteForce(meta.lattice.n_scale_steps, meta.lattice.retention_steps)
    fronts.set(key, paretoFront(all, [...OBJECTIVES], maximize))
  }
  return fronts.get(key)!
}

const strategy = (id: number, values: Partial<Values>): Strategy => ({
  id,
  rotation: 'maize',
  nScale: 0,
  retention: 0,
  values: { yield_t_ha: 0, net_mxn_ha: 0, n_loss_kg_ha: 0, c_input_t_ha: 0, cvar_net_mxn_ha: 0, ...values },
})

describe('paretoFront', () => {
  it('drops dominated strategies, keeps trade-offs and respects the objective direction', () => {
    const a = strategy(0, { net_mxn_ha: 10, n_loss_kg_ha: 5 })
    const b = strategy(1, { net_mxn_ha: 8, n_loss_kg_ha: 5 }) // less income, same N lost: dominated by a
    const c = strategy(2, { net_mxn_ha: 6, n_loss_kg_ha: 1 }) // less income but less N lost: a trade-off
    const keys: ObjectiveKey[] = ['net_mxn_ha', 'n_loss_kg_ha']
    expect(paretoFront([a, b, c], keys, maximize).map((s) => s.id)).toEqual([0, 2])
  })

  it('treats differences below the rounding as ties and keeps the first', () => {
    const a = strategy(0, { net_mxn_ha: 10 })
    const b = strategy(1, { net_mxn_ha: 10 + 1e-12 })
    expect(paretoFront([a, b], ['net_mxn_ha'], maximize).map((s) => s.id)).toEqual([0])
  })
})

// The port of the planner must reproduce what nsga_planner.py computed and saved.
describe('live front against the Python reference', () => {
  it.each(['calibrated', 'default'] as const)('%s: same strategies, same order, same objectives', (world) => {
    const rows = reference.worlds[world]
    const col = (name: string) => reference.columns.indexOf(name)
    const live = liveFront(world)
    expect(live).toHaveLength(meta.reference_front_size[world])
    expect(live).toHaveLength(rows.length)
    rows.forEach((row, i) => {
      const got = live[i]
      expect(got.rotation).toBe(row[col('rotation')])
      expect(got.nScale).toBeCloseTo(Number(row[col('n_scale')]), 6)
      expect(got.retention).toBeCloseTo(Number(row[col('retention')]), 6)
      for (const key of OBJECTIVES) {
        const expected = Number(row[col(key)])
        expect(Math.abs(got.values[key] - expected), `${world} row ${i} ${key}`).toBeLessThanOrEqual(1e-6 * Math.max(1, Math.abs(expected)))
      }
    })
  })

  it('has the front sizes reported in NSGA_RESULTS.md', () => {
    expect(liveFront('calibrated')).toHaveLength(483)
    expect(liveFront('default')).toHaveLength(1377)
  })
})

// The compromises tabulated in NSGA_RESULTS.md ("The fronts"), picked from the exact five-objective fronts.
describe('choose', () => {
  const picks = [
    ['calibrated', 'sustainability_first', 'maize-fababean', 0.0, 0.9, 11457],
    ['calibrated', 'profit_first', 'maize', 0.0, 0.0, 5895],
    ['default', 'sustainability_first', 'maize-fababean', 0.85, 1.0, 89255],
    ['default', 'profit_first', 'maize-fababean', 0.975, 0.75, 94178], // the document prints the lattice step 0.975 as 0.97
  ] as const

  it.each(picks)('%s, %s', (world, preset, rotation, nScale, retention, net) => {
    const front = liveFront(world)
    const picked = front[choose(front, meta.weights[preset], maximize)]
    expect(picked.rotation).toBe(rotation)
    expect(picked.nScale).toBeCloseTo(nScale, 6)
    expect(picked.retention).toBeCloseTo(retention, 6)
    expect(Math.round(picked.values.net_mxn_ha)).toBe(net)
  })

  it('does not depend on the scale of the weights', () => {
    const front = liveFront('default')
    const times10 = Object.fromEntries(Object.entries(meta.weights.sustainability_first).map(([k, v]) => [k, v * 10]))
    expect(choose(front, times10, maximize)).toBe(choose(front, meta.weights.sustainability_first, maximize))
  })

  it('ignores an objective with zero weight and treats all-zero as equal weights', () => {
    const front = liveFront('calibrated')
    const equal = Object.fromEntries(OBJECTIVES.map((k) => [k, 1]))
    const zero = Object.fromEntries(OBJECTIVES.map((k) => [k, 0]))
    expect(choose(front, zero, maximize)).toBe(choose(front, equal, maximize))
  })
})

// NSGA_RESULTS.md, "Robustness of the picks" 1: the calibrated picks move with the faba bean and stover prices.
// This checks the live re-pricing, not just the default prices.
describe('picks when prices change (calibrated model)', () => {
  const rows = [
    // faba price x, stover MXN/t, sustainability-first (rotation, retention), profit-first (rotation, retention)
    [1.0, 0, 'maize', 1.0, 'maize', 1.0],
    [1.0, 1000, 'maize-fababean', 0.9, 'maize', 0.0],
    [1.0, 3000, 'maize-fababean', 0.9, 'maize', 0.0],
    [0.5, 1000, 'maize-fababean', 0.95, 'maize', 0.3],
    [0.25, 1000, 'maize', 0.55, 'maize', 0.35],
  ] as const

  it.each(rows)('faba price x%s, stover %s MXN/t', (fababeanFactor, stover, sRotation, sRetention, pRotation, pRetention) => {
    const economics: Economics = {
      ...meta.economics,
      prices: { ...meta.economics.prices, fababean: meta.economics.prices.fababean * fababeanFactor },
      stover_price: stover,
    }
    const front = liveFront('calibrated', economics)
    const sustainable = front[choose(front, meta.weights.sustainability_first, maximize)]
    const profitable = front[choose(front, meta.weights.profit_first, maximize)]
    expect([sustainable.rotation, sustainable.retention, sustainable.nScale]).toEqual([sRotation, expect.closeTo(sRetention, 6), 0])
    expect([profitable.rotation, profitable.retention, profitable.nScale]).toEqual([pRotation, expect.closeTo(pRetention, 6), 0])
  })
})

describe('goodness', () => {
  it('is 1 at the best end and 0 at the worst, for either direction', () => {
    expect(goodness(10, [0, 10], true)).toBe(1)
    expect(goodness(0, [0, 10], true)).toBe(0)
    expect(goodness(0, [0, 10], false)).toBe(1)
    expect(goodness(5, [5, 5], false)).toBe(1)
  })
})
