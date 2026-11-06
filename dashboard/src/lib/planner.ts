// Port of nsga_planner.Grid / Planner / brute_force: scores a strategy (rotation, fertilizer scale, stover
// retention) from the WOFOST season outcomes in grid.json, so prices and costs can change in the browser.
// front.test.ts and planner.test.ts check it against the Python fronts and the picks in NSGA_RESULTS.md.

import type { Economics, GridField, GridWorld, Strategy, Values } from './types.ts'
import { GRID_FIELDS } from './types.ts'

/** Mean of the lowest `share` of the values (at least one): the conditional value at risk of a gain. */
export function tailMean(values: number[], share: number): number {
  const k = Math.max(1, Math.ceil(share * values.length))
  const lowest = [...values].sort((a, b) => a - b).slice(0, k)
  return lowest.reduce((sum, v) => sum + v, 0) / k
}

/** `steps + 1` equally spaced values from 0 to `maximum`. */
export function lattice(maximum: number, steps: number): number[] {
  return Array.from({ length: steps + 1 }, (_, i) => (i * maximum) / steps)
}

interface RotationData {
  phases: number
  price: Float64Array // [year * phases + phase]
  cost: Float64Array
  fields: Record<GridField, Float64Array> // [(scale * years + year) * phases + phase]
}

/** Per-year farm outcomes of one strategy (phases averaged), one entry per grid year. */
export interface AnnualOutcomes {
  yield_t_ha: number[]
  net_mxn_ha: number[]
  n_loss_kg_ha: number[]
  c_input_t_ha: number[]
  dose_kg_ha: number[]
}

const mean = (values: number[]) => values.reduce((sum, v) => sum + v, 0) / values.length

export class Planner {
  readonly years: number[]
  readonly scales: number[]
  readonly rotations: string[]
  readonly economics: Economics
  /** Share of the worst years averaged by the bad-year objective (meta.planner.cvar_share). */
  readonly cvarShare: number
  private readonly data = new Map<string, RotationData>()

  constructor(world: GridWorld, economics: Economics, cvarShare: number) {
    this.economics = economics
    this.cvarShare = cvarShare
    if (world.scales.length < 2 || world.scales[0] !== 0) {
      throw new Error('The grid needs the zero-fertilizer node and at least one more (N loss is a difference)')
    }
    this.years = world.years
    this.scales = world.scales
    this.rotations = world.order
    for (const name of world.order) {
      const rotation = world.rotations[name]
      const missing = new Set<string>()
      const price = new Float64Array(this.years.length * rotation.phases)
      const cost = new Float64Array(price.length)
      rotation.crops.forEach((row, y) =>
        row.forEach((crop, p) => {
          const crop_price = economics.prices[crop]
          const crop_cost = economics.other_costs[crop]
          if (crop_price === undefined || crop_cost === undefined) missing.add(crop)
          price[y * rotation.phases + p] = crop_price
          cost[y * rotation.phases + p] = crop_cost
        }),
      )
      if (missing.size > 0) throw new Error(`Missing price or cost for ${[...missing].sort().join(', ')}`)
      const expected = this.scales.length * price.length
      const fields = {} as Record<GridField, Float64Array>
      for (const field of GRID_FIELDS) {
        if (rotation.fields[field].length !== expected) throw new Error(`Incomplete grid for rotation '${name}'`)
        fields[field] = Float64Array.from(rotation.fields[field])
      }
      this.data.set(name, { phases: rotation.phases, price, cost, fields })
    }
  }

  get maxScale(): number {
    return this.scales[this.scales.length - 1]
  }

  /** Field values at a fertilizer scale, linear between nodes (clipped to the grid): [year * phases + phase]. */
  private interpolate(data: RotationData, field: GridField, nScale: number): Float64Array {
    const cells = this.years.length * data.phases
    const s = Math.min(Math.max(nScale, this.scales[0]), this.maxScale)
    // searchsorted(side='right') - 1: the last node at or below s, kept inside the grid.
    let k = 0
    while (k + 1 < this.scales.length && this.scales[k + 1] <= s) k++
    k = Math.min(k, this.scales.length - 2)
    const w = (s - this.scales[k]) / (this.scales[k + 1] - this.scales[k])
    const values = data.fields[field]
    const out = new Float64Array(cells)
    for (let i = 0; i < cells; i++) out[i] = (1 - w) * values[k * cells + i] + w * values[(k + 1) * cells + i]
    return out
  }

  /**
   * Farm outcomes per year (phases averaged). n_loss: fertilizer applied minus the extra N the crop took up
   * compared with no fertilizer, floored at 0. net: grain revenue - other costs - N price x dose + stover price
   * x stover removed. c_input: carbon fraction x (roots + retained stover).
   */
  annual(rotation: string, nScale: number, retention: number): AnnualOutcomes {
    if (!(retention >= 0 && retention <= 1)) throw new Error('retention must be between 0 and 1')
    const data = this.data.get(rotation)
    if (!data) throw new Error(`Unknown rotation '${rotation}'`)
    const { economics: e } = this
    const [grain, dose, uptake, stover, roots] = GRID_FIELDS.map((field) => this.interpolate(data, field, nScale))
    const uptake0 = data.fields.n_uptake_kg_ha // scale 0 is the first block
    const out: AnnualOutcomes = { yield_t_ha: [], net_mxn_ha: [], n_loss_kg_ha: [], c_input_t_ha: [], dose_kg_ha: [] }
    const { phases } = data
    for (let y = 0; y < this.years.length; y++) {
      let g = 0
      let net = 0
      let loss = 0
      let c = 0
      let d = 0
      for (let p = 0; p < phases; p++) {
        const i = y * phases + p
        g += grain[i]
        d += dose[i]
        loss += Math.max(0, dose[i] - (uptake[i] - uptake0[i]))
        net += grain[i] * data.price[i] - (data.cost[i] + e.n_price * dose[i]) + e.stover_price * (1 - retention) * stover[i]
        c += e.carbon_fraction * (roots[i] + retention * stover[i])
      }
      out.yield_t_ha.push(g / phases)
      out.net_mxn_ha.push(net / phases)
      out.n_loss_kg_ha.push(loss / phases)
      out.c_input_t_ha.push(c / phases)
      out.dose_kg_ha.push(d / phases)
    }
    return out
  }

  /** The five objectives of a strategy, averaged over years (cvar: the worst `cvarShare` of years). */
  objectives(rotation: string, nScale: number, retention: number): Values {
    const a = this.annual(rotation, nScale, retention)
    return {
      yield_t_ha: mean(a.yield_t_ha),
      net_mxn_ha: mean(a.net_mxn_ha),
      n_loss_kg_ha: mean(a.n_loss_kg_ha),
      c_input_t_ha: mean(a.c_input_t_ha),
      cvar_net_mxn_ha: tailMean(a.net_mxn_ha, this.cvarShare),
    }
  }

  /** Every rotation at every lattice point of fertilizer scale and stover retention, scored: the exact check. */
  bruteForce(nScaleSteps: number, retentionSteps: number): Strategy[] {
    const strategies: Strategy[] = []
    const retentions = lattice(1, retentionSteps)
    for (const rotation of this.rotations) {
      for (const nScale of lattice(this.maxScale, nScaleSteps)) {
        for (const retention of retentions) {
          strategies.push({
            id: strategies.length,
            rotation,
            nScale,
            retention,
            values: this.objectives(rotation, nScale, retention),
          })
        }
      }
    }
    return strategies
  }
}
