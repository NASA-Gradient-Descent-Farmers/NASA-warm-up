// Known-answer checks of the Planner port on a small synthetic farm (the same fixture as tests/test_nsga_planner.py):
// yields, uptake and residues are linear in the fertilizer scale, so every objective is computable by hand.

import { describe, expect, it } from 'vitest'
import { lattice, Planner, tailMean } from './planner.ts'
import type { Economics, GridField, GridWorld } from './types.ts'
import { GRID_FIELDS } from './types.ts'

const YEARS = [2006, 2007, 2008, 2009, 2010]
/** The planner's bad-year share (nsga_planner.CVAR_SHARE), as in tests/test_nsga_planner.py. */
const CVAR = 0.25
const ECONOMICS: Economics = {
  prices: { maize: 5000, fababean: 12000 },
  other_costs: { maize: 10000, fababean: 8000 },
  n_price: 20,
  stover_price: 1000,
  carbon_fraction: 0.5,
}

type Crop = 'maize' | 'fababean'
/** Maize: yield 2 + 3 s (bad year 2008: 2 t/ha less), uptake 50 + 40 s, fertilizer 160 s, stover 4, roots 1.
 *  Faba bean: yield 1.5, fertilizer 40 s, uptake 80, stover 2, roots 0.5. */
function season(crop: Crop, scale: number, year: number): Record<GridField, number> {
  const bad = year === 2008 ? 2 : 0
  return crop === 'maize'
    ? { yield_water_n_t_ha: 2 + 3 * scale - bad, n_fertilizer_kg_ha: 160 * scale, n_uptake_kg_ha: 50 + 40 * scale, stover_dm_t_ha: 4, root_dm_t_ha: 1 }
    : { yield_water_n_t_ha: 1.5, n_fertilizer_kg_ha: 40 * scale, n_uptake_kg_ha: 80, stover_dm_t_ha: 2, root_dm_t_ha: 0.5 }
}

function world(scales = [0, 1, 2], tweak?: (w: GridWorld) => void): GridWorld {
  const rotations: Record<string, Crop[]> = { maize: ['maize'], 'maize-fababean': ['maize', 'fababean'] }
  const built: GridWorld = { scales, years: YEARS, order: Object.keys(rotations), rotations: {} }
  for (const [name, crops] of Object.entries(rotations)) {
    const fields = Object.fromEntries(GRID_FIELDS.map((f) => [f, [] as number[]])) as Record<GridField, number[]>
    for (const s of scales) for (const y of YEARS) for (const crop of crops) {
      const values = season(crop, s, y)
      for (const f of GRID_FIELDS) fields[f].push(values[f])
    }
    built.rotations[name] = { phases: crops.length, crops: YEARS.map(() => [...crops]), fields }
  }
  tweak?.(built)
  return built
}

const planner = () => new Planner(world(), ECONOMICS, CVAR)

describe('interpolation', () => {
  it('is exact at nodes, linear between them and clipped to the grid', () => {
    const p = planner()
    expect(p.annual('maize', 1, 0).yield_t_ha[0]).toBeCloseTo(5)
    expect(p.annual('maize', 0.5, 0).yield_t_ha[0]).toBeCloseTo(3.5)
    expect(p.annual('maize', 1.5, 0).yield_t_ha[0]).toBeCloseTo(6.5)
    expect(p.annual('maize', 5, 0).yield_t_ha[0]).toBeCloseTo(p.annual('maize', 2, 0).yield_t_ha[0])
    expect(p.annual('maize', -1, 0).yield_t_ha[0]).toBeCloseTo(p.annual('maize', 0, 0).yield_t_ha[0])
  })

  it('needs the zero-fertilizer node and complete tables', () => {
    expect(() => new Planner(world([1, 2]), ECONOMICS, CVAR)).toThrow(/zero-fertilizer/)
    expect(() => new Planner(world([0, 1, 2], (w) => w.rotations.maize.fields.n_uptake_kg_ha.pop()), ECONOMICS, CVAR)).toThrow(/Incomplete/)
  })
})

describe('objectives', () => {
  it('maize at the full dose with no stover retained, by hand', () => {
    const o = planner().objectives('maize', 1, 0)
    expect(o.yield_t_ha).toBeCloseTo(4.6) // (5 x 4 + 3) / 5
    expect(o.n_loss_kg_ha).toBeCloseTo(120) // dose 160 - extra uptake 40
    expect(o.net_mxn_ha).toBeCloseTo(13800) // 5 x 5000 - (10000 + 20 x 160) + 1000 x 4, bad year 2,000 less on grain
    expect(o.c_input_t_ha).toBeCloseTo(0.5) // 0.5 x (roots 1)
    expect(o.cvar_net_mxn_ha).toBeCloseTo(10800) // worst 2 of 5 years: 5,800 and 15,800
  })

  it('retention trades stover income for carbon', () => {
    const none = planner().objectives('maize', 1, 0)
    const all = planner().objectives('maize', 1, 1)
    expect(none.net_mxn_ha - all.net_mxn_ha).toBeCloseTo(4000) // 4 t/ha of stover x 1,000
    expect(all.c_input_t_ha - none.c_input_t_ha).toBeCloseTo(2) // 0.5 x 4 t/ha
  })

  it('no fertilizer means no N loss and no fertilizer cost', () => {
    const o = planner().objectives('maize', 0, 0)
    expect(o.n_loss_kg_ha).toBe(0)
    // 2 t/ha x 5,000 - 10,000 + 4,000 = 4,000 in four years; the bad year has no grain: -6,000
    expect(o.net_mxn_ha).toBeCloseTo((4000 * 4 - 6000) / 5)
  })

  it('a legume that takes up no extra N loses its whole dose; phases are averaged', () => {
    const p = planner()
    expect(p.objectives('maize-fababean', 1, 0).n_loss_kg_ha).toBeCloseTo((120 + 40) / 2)
    expect(p.objectives('maize-fababean', 1, 0).yield_t_ha).toBeCloseTo((3.25 * 4 + 2.25) / 5)
    expect(p.annual('maize-fababean', 1, 0).dose_kg_ha[0]).toBeCloseTo(100)
  })

  it('N loss is floored at zero when the crop takes up more than was applied', () => {
    const generous = new Planner(world([0, 1, 2], (w) => {
      const uptake = w.rotations.maize.fields.n_uptake_kg_ha
      for (let i = 0; i < uptake.length; i++) uptake[i] += (Math.floor(i / YEARS.length) % 3) * 500
    }), ECONOMICS, CVAR)
    expect(generous.objectives('maize', 1, 0).n_loss_kg_ha).toBe(0)
  })

  it('rejects retention outside 0-1, unknown rotations and missing prices', () => {
    const p = planner()
    expect(() => p.objectives('maize', 1, 1.2)).toThrow(/retention/)
    expect(() => p.objectives('maize', 1, -0.1)).toThrow(/retention/)
    expect(() => p.objectives('wheat', 1, 0)).toThrow(/Unknown rotation/)
    expect(() => new Planner(world(), { ...ECONOMICS, prices: { maize: 5000 } }, CVAR)).toThrow(/Missing price or cost for fababean/)
  })
})

describe('tailMean and lattice', () => {
  it('averages the lowest share of the values, at least one', () => {
    expect(tailMean([3, 1, 2, 5], 0.25)).toBe(1)
    expect(tailMean([3, 1, 2, 5], 0.5)).toBeCloseTo(1.5)
    expect(tailMean([4, 8], 0.01)).toBe(4)
    expect(tailMean(Array.from({ length: 16 }, (_, i) => i), 0.25)).toBeCloseTo(1.5) // exactly four of sixteen years
  })

  it('has steps + 1 points from 0 to the maximum', () => {
    expect(lattice(1.25, 50)).toHaveLength(51)
    expect(lattice(1.25, 50)[39]).toBeCloseTo(0.975)
    expect(lattice(1, 10)[10]).toBe(1)
  })
})

describe('bruteForce', () => {
  it('scores every rotation at every lattice point, in lattice order, with sequential ids', () => {
    const all = planner().bruteForce(20, 10)
    expect(all).toHaveLength(2 * 21 * 11)
    expect(all.map((s) => s.id)).toEqual(all.map((_, i) => i))
    expect(all[0]).toMatchObject({ rotation: 'maize', nScale: 0, retention: 0 })
    expect(all[all.length - 1]).toMatchObject({ rotation: 'maize-fababean', nScale: 2, retention: 1 })
  })
})
