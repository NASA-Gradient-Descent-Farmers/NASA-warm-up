import type { DashboardData, FarmData, GridFile, Meta, ObjectiveKey, RealityFile, ScenariosFile, WorldKey } from './types.ts'
import { WORLDS } from './types.ts'

export function parseData(meta: Meta, file: GridFile): DashboardData {
  const grids = {} as Record<WorldKey, GridFile['worlds'][string]>
  for (const world of WORLDS) {
    if (!file.worlds[world]) throw new Error(`grid.json has no grid for ${world}`)
    grids[world] = file.worlds[world]
  }
  if (!meta.planner) throw new Error('meta.json has no planner settings: re-run python -m src.crop_models.dashboard_export')
  const maximize = Object.fromEntries(meta.objectives.map((o) => [o.key, o.maximize])) as Record<ObjectiveKey, boolean>
  return { meta, grids, maximize }
}

async function getJson<T>(name: string): Promise<T> {
  const response = await fetch(`${import.meta.env.BASE_URL}data/${name}`)
  if (!response.ok) throw new Error(`${name}: HTTP ${response.status}`)
  return (await response.json()) as T
}

export async function loadData(): Promise<DashboardData> {
  const [meta, grid] = await Promise.all([getJson<Meta>('meta.json'), getJson<GridFile>('grid.json')])
  return parseData(meta, grid)
}

const REEXPORT = 're-run python -m src.crop_models.dashboard_export'

/** Season data for the farm tabs, checked against meta.farm: every world and every scenario must be there. */
export function parseFarm(meta: Meta, scenarios: ScenariosFile, reality: RealityFile): FarmData {
  if (!meta.farm) throw new Error(`meta.json has no farm section: ${REEXPORT}`)
  const seasons = {} as FarmData['seasons']
  const gaps = {} as FarmData['reality']['gaps']
  for (const world of WORLDS) {
    const w = scenarios.worlds[world]
    if (!w) throw new Error(`scenarios.json has no ${world} seasons: ${REEXPORT}`)
    const missing = meta.farm.scenario_order.filter((name) => !w.scenarios[name])
    if (missing.length > 0) throw new Error(`scenarios.json (${world}) lacks ${missing.join(', ')}: ${REEXPORT}`)
    if (!reality.worlds[world]) throw new Error(`reality.json has no ${world} comparison: ${REEXPORT}`)
    seasons[world] = w
    gaps[world] = reality.worlds[world]
  }
  return { seasons, reality: { siap: reality.siap, gaps } }
}

let farm: Promise<FarmData> | null = null

/** The farm tabs' data, fetched the first time a tab asks for it (the planner does not need it). */
export function loadFarmData(meta: Meta): Promise<FarmData> {
  farm ??= Promise.all([getJson<ScenariosFile>('scenarios.json'), getJson<RealityFile>('reality.json')])
    .then(([scenarios, reality]) => parseFarm(meta, scenarios, reality))
    .catch((error: unknown) => {
      farm = null // a failed load is not remembered: the next visit asks again
      throw error
    })
  return farm
}
