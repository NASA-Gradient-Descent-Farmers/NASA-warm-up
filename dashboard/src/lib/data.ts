import type { DashboardData, GridFile, Meta, ObjectiveKey, WorldKey } from './types.ts'
import { WORLDS } from './types.ts'

export function parseData(meta: Meta, file: GridFile): DashboardData {
  const grids = {} as Record<WorldKey, GridFile['worlds'][string]>
  for (const world of WORLDS) {
    if (!file.worlds[world]) throw new Error(`grid.json has no grid for ${world}`)
    grids[world] = file.worlds[world]
  }
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
