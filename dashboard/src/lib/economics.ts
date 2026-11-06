// Port of farm_tool.rotation_economics: income per hectare of every rotation in a WOFOST scenario, from the
// seasons in scenarios.json, so prices and costs can change in the browser. economics.test.ts checks it against
// the Python results saved in fixtures/reference_economics.json.

import type { Economics, SeasonRotation, ScenarioSeasons } from './types.ts'

/** Prices and costs this needs: grain price and other costs per crop, N price. */
export type SeasonEconomics = Pick<Economics, 'prices' | 'other_costs' | 'n_price'>

/** Value at quantile q (0-1) with linear interpolation between order statistics (pandas' default). */
export function quantile(values: number[], q: number): number {
  if (values.length === 0) throw new Error('quantile of no values')
  const sorted = [...values].sort((a, b) => a - b)
  const position = (sorted.length - 1) * q
  const below = Math.floor(position)
  const above = Math.min(below + 1, sorted.length - 1)
  return sorted[below] + (position - below) * (sorted[above] - sorted[below])
}

const mean = (values: number[]) => values.reduce((sum, v) => sum + v, 0) / values.length

/** One season priced: yield (rescaled), revenue, cost and net per hectare. */
export interface PricedSeason {
  year: number
  phase: number
  crop: string
  yieldTHa: number
  failed: boolean
  frostEnded: boolean
  revenue: number
  cost: number
  net: number
}

/** Per year: the phase average, i.e. what one hectare split across the rotation's phases makes that year. */
export interface AnnualIncome {
  year: number
  revenue: number
  cost: number
  net: number
}

export interface RotationSummary {
  years: number
  meanNet: number
  p10Net: number
  p90Net: number
  worstNet: number
  /** Share of years with a negative net. */
  lossYearShare: number
}

export interface CropSummary {
  crop: string
  seasons: number
  meanYield: number
  p10Yield: number
  /** Share of seasons below the failure threshold. */
  failedShare: number
}

export interface RotationEconomics {
  seasons: PricedSeason[]
  annual: AnnualIncome[]
  summary: RotationSummary
  /** Crops in order of first appearance. */
  crops: CropSummary[]
}

/**
 * Price every season of a rotation: yield x factor (missing crops keep 1) x price - (other costs + N dose x N
 * price). Throws when a crop has no price or cost, like the Python version.
 */
export function rotationEconomics(
  rotation: SeasonRotation,
  years: number[],
  economics: SeasonEconomics,
  failureThreshold: number,
  yieldFactors: Record<string, number> = {},
): RotationEconomics {
  const { phases } = rotation
  const seasons: PricedSeason[] = []
  const annual: AnnualIncome[] = []
  years.forEach((year, y) => {
    let revenue = 0
    let cost = 0
    for (let phase = 0; phase < phases; phase++) {
      const i = y * phases + phase
      const crop = rotation.crops[y][phase]
      const price = economics.prices[crop]
      const other = economics.other_costs[crop]
      if (price === undefined || other === undefined) throw new Error(`Missing price or cost for ${crop}`)
      const yieldTHa = rotation.fields.yield_water_n_t_ha[i] * (yieldFactors[crop] ?? 1)
      const seasonRevenue = yieldTHa * price
      const seasonCost = other + rotation.fields.n_fertilizer_kg_ha[i] * economics.n_price
      seasons.push({
        year,
        phase,
        crop,
        yieldTHa,
        failed: yieldTHa < failureThreshold,
        frostEnded: rotation.frost_ended[i] === 1,
        revenue: seasonRevenue,
        cost: seasonCost,
        net: seasonRevenue - seasonCost,
      })
      revenue += seasonRevenue
      cost += seasonCost
    }
    annual.push({ year, revenue: revenue / phases, cost: cost / phases, net: (revenue - cost) / phases })
  })

  const nets = annual.map((a) => a.net)
  const summary: RotationSummary = {
    years: annual.length,
    meanNet: mean(nets),
    p10Net: quantile(nets, 0.1),
    p90Net: quantile(nets, 0.9),
    worstNet: Math.min(...nets),
    lossYearShare: nets.filter((n) => n < 0).length / nets.length,
  }
  const crops = [...new Set(seasons.map((s) => s.crop))].map((crop): CropSummary => {
    const of = seasons.filter((s) => s.crop === crop)
    const yields = of.map((s) => s.yieldTHa)
    return {
      crop,
      seasons: of.length,
      meanYield: mean(yields),
      p10Yield: quantile(yields, 0.1),
      failedShare: of.filter((s) => s.failed).length / of.length,
    }
  })
  return { seasons, annual, summary, crops }
}

/** Every rotation of a scenario priced, in `order`. */
export function scenarioEconomics(
  scenario: ScenarioSeasons,
  years: number[],
  order: string[],
  economics: SeasonEconomics,
  failureThreshold: number,
  yieldFactors?: Record<string, number>,
): Record<string, RotationEconomics> {
  return Object.fromEntries(
    order.map((name) => [name, rotationEconomics(scenario.rotations[name], years, economics, failureThreshold, yieldFactors)]),
  )
}
