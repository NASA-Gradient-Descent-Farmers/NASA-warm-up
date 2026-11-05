// Shapes of the JSON written by src/crop_models/dashboard_export.py.

export const OBJECTIVES = ['yield_t_ha', 'net_mxn_ha', 'n_loss_kg_ha', 'c_input_t_ha', 'cvar_net_mxn_ha'] as const
export type ObjectiveKey = (typeof OBJECTIVES)[number]
export type Values = Record<ObjectiveKey, number>

/** The WOFOST parameter sets the planner was run with. */
export const WORLDS = ['calibrated', 'default'] as const
export type WorldKey = (typeof WORLDS)[number]

/** One way to farm a hectare: a rotation, a fertilizer scale and the share of stover left in the field. */
export interface Strategy {
  id: number
  rotation: string
  /** Multiple of the crop fertilizer doses (1 = maize 160 kg N/ha). */
  nScale: number
  /** Share of the stover left in the field (0-1). */
  retention: number
  values: Values
}

export interface Economics {
  prices: Record<string, number>
  other_costs: Record<string, number>
  n_price: number
  stover_price: number
  carbon_fraction: number
}

export interface SiapPrice {
  latest_year: number
  latest_mxn_t: number
  median_3y_mxn_t: number
}

export interface Meta {
  site: { name: string; latitude: number; longitude: number; elevation_m: number }
  crops: Record<string, { n_kg_ha_at_scale_1: number }>
  rotations: Record<string, string[]>
  /** Rotations in the planner's lattice order (JSON keys are sorted, so this is not the key order). */
  rotation_order: string[]
  objectives: { key: ObjectiveKey; maximize: boolean }[]
  weights: { sustainability_first: Values; profit_first: Values }
  lattice: { n_scale_max: number; n_scale_steps: number; retention_steps: number }
  /** The planner's economics: SIAP grain prices (3-year median) and the placeholder costs. */
  economics: Economics
  siap_prices: Record<string, SiapPrice>
  placeholders: string[]
  design_years: [number, number]
  holdout_years: [number, number]
  reference_front_size: Record<string, number>
  grid_sha256: string
}

/** Season outcomes the planner scores strategies from (src/crop_models/nsga_planner.py FIELDS). */
export const GRID_FIELDS = [
  'yield_water_n_t_ha',
  'n_fertilizer_kg_ha',
  'n_uptake_kg_ha',
  'stover_dm_t_ha',
  'root_dm_t_ha',
] as const
export type GridField = (typeof GRID_FIELDS)[number]

export interface GridRotation {
  phases: number
  /** Crop of each phase in each year: [year][phase]. */
  crops: string[][]
  /** Each field flattened from [fertilizer scale][year][phase], row-major. */
  fields: Record<GridField, number[]>
}

export interface GridWorld {
  scales: number[]
  years: number[]
  /** Rotations in lattice order. */
  order: string[]
  rotations: Record<string, GridRotation>
}

export interface GridFile {
  worlds: Record<string, GridWorld>
}

export interface DashboardData {
  meta: Meta
  grids: Record<WorldKey, GridWorld>
  maximize: Record<ObjectiveKey, boolean>
}
