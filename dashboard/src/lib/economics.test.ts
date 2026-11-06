import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { parseFarm } from './data.ts'
import { quantile, rotationEconomics, scenarioEconomics } from './economics.ts'
import type { Meta, RealityFile, ScenariosFile, WorldKey } from './types.ts'

const read = <T>(path: string) => JSON.parse(readFileSync(new URL(path, import.meta.url), 'utf8')) as T
const meta = read<Meta>('../../public/data/meta.json')
const scenarios = read<ScenariosFile>('../../public/data/scenarios.json')
const reality = read<RealityFile>('../../public/data/reality.json')
const farm = parseFarm(meta, scenarios, reality)

interface SummaryRow {
  scenario: string
  rotation: string
  years: number
  mean_net_mxn_ha: number
  p10_net_mxn_ha: number
  p90_net_mxn_ha: number
  worst_net_mxn_ha: number
  loss_year_share: number
}
interface CropRow {
  scenario: string
  rotation: string
  crop: string
  seasons: number
  mean_yield_t_ha: number
  p10_yield_t_ha: number
  failed_share: number
}
type Case = { yield_factors: Record<string, number> | null; summary: SummaryRow[]; crops: CropRow[] }
const reference = read<Record<string, Case>>('./fixtures/reference_economics.json')

describe('quantile', () => {
  it('interpolates linearly between order statistics, like pandas', () => {
    expect(quantile([4, 1, 3, 2], 0.1)).toBeCloseTo(1.3)
    expect(quantile([4, 1, 3, 2], 0.9)).toBeCloseTo(3.7)
    expect(quantile([5], 0.1)).toBe(5)
    expect(quantile([1, 2, 3], 0.5)).toBe(2)
  })
})

// The port must reproduce farm_tool.rotation_economics, saved by the exporter at the planner's economics.
describe('rotation economics against the Python reference', () => {
  it.each(Object.keys(reference))('%s', (name) => {
    const [world, kind] = name.split(':') as [WorldKey, string]
    const { yield_factors, summary, crops } = reference[name]
    expect(yield_factors === null).toBe(kind === 'raw') // only the SIAP-level case rescales yields
    const data = farm.seasons[world]
    for (const row of summary) {
      const got = rotationEconomics(
        data.scenarios[row.scenario].rotations[row.rotation],
        data.years,
        meta.economics,
        meta.farm.failure_threshold_t_ha,
        yield_factors ?? undefined,
      )
      expect(got.summary.years).toBe(row.years)
      expect(got.summary.meanNet).toBeCloseTo(row.mean_net_mxn_ha, 6)
      expect(got.summary.p10Net).toBeCloseTo(row.p10_net_mxn_ha, 6)
      expect(got.summary.p90Net).toBeCloseTo(row.p90_net_mxn_ha, 6)
      expect(got.summary.worstNet).toBeCloseTo(row.worst_net_mxn_ha, 6)
      expect(got.summary.lossYearShare).toBeCloseTo(row.loss_year_share, 12)
      for (const c of crops.filter((r) => r.scenario === row.scenario && r.rotation === row.rotation)) {
        const crop = got.crops.find((x) => x.crop === c.crop)!
        expect(crop.seasons).toBe(c.seasons)
        expect(crop.meanYield).toBeCloseTo(c.mean_yield_t_ha, 9)
        expect(crop.p10Yield).toBeCloseTo(c.p10_yield_t_ha, 9)
        expect(crop.failedShare).toBeCloseTo(c.failed_share, 12)
      }
    }
    // Every scenario and rotation was checked.
    expect(summary).toHaveLength(meta.farm.scenario_order.length * meta.rotation_order.length)
  })
})

describe('scenarioEconomics', () => {
  it('prices every rotation in order and refuses a crop without a price', () => {
    const data = farm.seasons.calibrated
    const all = scenarioEconomics(data.scenarios.baseline, data.years, meta.rotation_order, meta.economics, 1)
    expect(Object.keys(all)).toEqual(meta.rotation_order)
    const noFaba = { ...meta.economics, prices: { ...meta.economics.prices, fababean: undefined as unknown as number } }
    expect(() => scenarioEconomics(data.scenarios.baseline, data.years, meta.rotation_order, noFaba, 1)).toThrow(/fababean/)
  })

  it('net rises with the grain price and falls with the N price', () => {
    const data = farm.seasons.default
    const rotation = data.scenarios.baseline.rotations.maize
    const net = (e: typeof meta.economics) => rotationEconomics(rotation, data.years, e, 1).summary.meanNet
    const base = net(meta.economics)
    expect(net({ ...meta.economics, prices: { ...meta.economics.prices, maize: meta.economics.prices.maize + 1000 } })).toBeGreaterThan(base)
    expect(net({ ...meta.economics, n_price: meta.economics.n_price + 10 })).toBeLessThan(base)
  })
})

describe('parseFarm', () => {
  it('refuses data missing a world or a scenario', () => {
    const { calibrated: _calibrated, ...onlyDefault } = scenarios.worlds
    expect(() => parseFarm(meta, { worlds: onlyDefault }, reality)).toThrow(/calibrated/)
    const { rain60: _rain60, ...fewer } = scenarios.worlds.default.scenarios
    const trimmed = { worlds: { ...scenarios.worlds, default: { ...scenarios.worlds.default, scenarios: fewer } } }
    expect(() => parseFarm(meta, trimmed, reality)).toThrow(/rain60/)
  })

  it('has SIAP series of equal length per crop and a gap for each world', () => {
    for (const series of Object.values(farm.reality.siap)) {
      for (const values of Object.values(series)) expect(values).toHaveLength(series.year.length)
    }
    expect(Object.keys(farm.reality.gaps.calibrated).sort()).toEqual(['barley', 'fababean', 'maize'])
  })
})
