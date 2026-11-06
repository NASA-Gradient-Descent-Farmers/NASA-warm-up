import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { parseData } from './data.ts'
import { paretoFront } from './front.ts'
import { Planner } from './planner.ts'
import { exactFront, frontOn, sameEconomics } from './scenario.ts'
import type { GridFile, Meta, ObjectiveKey } from './types.ts'
import { OBJECTIVES } from './types.ts'

const read = <T>(path: string) => JSON.parse(readFileSync(new URL(path, import.meta.url), 'utf8')) as T
const { meta, grids, maximize } = parseData(read<Meta>('../../public/data/meta.json'), read<GridFile>('../../public/data/grid.json'))

describe('exactFront', () => {
  it('is cached for the same economics and recomputed for changed ones', () => {
    const first = exactFront(grids.calibrated, meta.economics, meta, maximize)
    expect(exactFront(grids.calibrated, { ...meta.economics }, meta, maximize)).toBe(first) // equal content, same result
    const dearNitrogen = exactFront(grids.calibrated, { ...meta.economics, n_price: 60 }, meta, maximize)
    expect(dearNitrogen).not.toBe(first)
    expect(exactFront(grids.calibrated, meta.economics, meta, maximize)).toBe(first) // still cached
  })

  it('keeps lattice ids, which do not depend on prices', () => {
    const ids = (front: { id: number; rotation: string; nScale: number; retention: number }[]) =>
      new Map(front.map((s) => [s.id, `${s.rotation}|${s.nScale}|${s.retention}`]))
    const a = ids(exactFront(grids.default, meta.economics, meta, maximize))
    const b = ids(exactFront(grids.default, { ...meta.economics, stover_price: 0 }, meta, maximize))
    for (const [id, strategy] of b) if (a.has(id)) expect(a.get(id)).toBe(strategy)
  })
})

describe('frontOn', () => {
  const subsets: ObjectiveKey[][] = [
    ['net_mxn_ha', 'n_loss_kg_ha', 'c_input_t_ha'],
    ['yield_t_ha', 'net_mxn_ha', 'n_loss_kg_ha', 'c_input_t_ha'],
    ['net_mxn_ha', 'c_input_t_ha'],
    ['cvar_net_mxn_ha'],
  ]

  // The app narrows the five-objective front instead of re-scoring the lattice when a weight goes to 0.
  it.each(subsets.flatMap((keys) => (['calibrated', 'default'] as const).map((world) => [world, keys] as const)))(
    '%s on %j equals the front of the whole lattice',
    (world, keys) => {
      const all = new Planner(grids[world], meta.economics, meta.planner.cvar_share).bruteForce(meta.lattice.n_scale_steps, meta.lattice.retention_steps)
      const direct = paretoFront(all, keys, maximize, meta.planner.front_decimals)
      const narrowed = frontOn(exactFront(grids[world], meta.economics, meta, maximize), keys, maximize, meta.planner.front_decimals)
      expect(narrowed.map((s) => s.id)).toEqual(direct.map((s) => s.id))
    },
  )

  it('returns the five-objective front itself when every objective is used', () => {
    const exact = exactFront(grids.calibrated, meta.economics, meta, maximize)
    expect(frontOn(exact, [...OBJECTIVES], maximize, meta.planner.front_decimals)).toBe(exact)
  })
})

describe('sameEconomics', () => {
  it('compares by content', () => {
    expect(sameEconomics(meta.economics, JSON.parse(JSON.stringify(meta.economics)))).toBe(true)
    expect(sameEconomics(meta.economics, { ...meta.economics, n_price: 26 })).toBe(false)
  })
})
