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
  /** nsga_planner settings the browser port follows: share of worst years in the bad-year objective
   *  (CVAR_SHARE) and the decimals below which objectives tie (FRONT_DECIMALS). */
  planner: { cvar_share: number; front_decimals: number }
  /** The scenario suites behind the economics, reality-check and what-if tabs. */
  farm: FarmMeta
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

// --- Season-level data for the economics, reality-check and what-if tabs (src/crop_models/dashboard_seasons.py).

export interface ScenarioSettings {
  rain_factor: number
  /** Months the rain factor applies to (1-12); empty = all year. */
  rain_months: number[]
  frost_tmin_offset: number
  n_scale: number
  sowing: 'onset' | 'fixed'
}

export interface FarmMeta {
  scenarios: Record<string, ScenarioSettings>
  scenario_order: string[]
  /** First and last season after the spin-up year. */
  season_years: [number, number]
  spinup_years: number
  /** A harvest below this many t/ha counts as failed. */
  failure_threshold_t_ha: number
  risk: { crop: string; reference: string; draws: number; harvests: number; seed: number }
  /** sha256 of each scenario CSV, per world. */
  sources: Record<string, Record<string, string>>
}

export const SEASON_FIELDS = ['yield_water_n_t_ha', 'n_fertilizer_kg_ha'] as const
export type SeasonField = (typeof SEASON_FIELDS)[number]

export interface SeasonRotation {
  phases: number
  /** Crop of each phase in each year: [year][phase]. */
  crops: string[][]
  /** Each field flattened from [year][phase], row-major. */
  fields: Record<SeasonField, number[]>
  /** 1 when frost ended the crop before maturity, [year][phase] flattened. */
  frost_ended: number[]
}

/** Paired-year comparison of maize in a rotation with continuous maize (rotation_risk.compare_rotations). */
export interface RiskRow {
  mean_yield_t_ha: number
  mean_advantage_t_ha: number
  advantage_ci_low_t_ha: number
  advantage_ci_high_t_ha: number
  fraction_years_better: number
  paired_years: number
  mean_yield_p05_t_ha: number
  mean_yield_p95_t_ha: number
  failed_harvest_fraction: number
  prob_any_failed_harvest: number
  prob_mean_below_reference: number
}

export interface ScenarioSeasons {
  rain_may_oct_mm: number[]
  year_class: ('dry' | 'normal' | 'wet')[]
  rotations: Record<string, SeasonRotation>
}

export interface SeasonWorld {
  years: number[]
  scenarios: Record<string, ScenarioSeasons>
  /** scenario -> rotation -> maize risk against continuous maize. */
  risk: Record<string, Record<string, RiskRow>>
}

export interface ScenariosFile {
  worlds: Record<string, SeasonWorld>
}

/** SIAP Texcoco, rainfed spring-summer, one entry per year with data. */
export interface SiapSeries {
  year: number[]
  sown_ha: number[]
  lost_share: number[]
  /** Production over sown area: lost fields count as zero, like a failed simulated season. */
  yield_sown_t_ha: number[]
  yield_harvested_t_ha: number[]
  price_mxn_t: number[]
}

/** farm_tool.farm_gap for one crop: simulated (as SIAP would see it) against observed, over shared years. */
export interface CropGap {
  years: number
  simulated_mean_t_ha: number
  observed_mean_t_ha: number
  /** observed mean / simulated mean. */
  factor: number
  /** Year-to-year agreement (null when undefined). */
  correlation: number | null
  year: number[]
  simulated_t_ha: number[]
  observed_t_ha: number[]
}

export interface RealityFile {
  siap: Record<string, SiapSeries>
  worlds: Record<string, Record<string, CropGap>>
}

export interface FarmData {
  seasons: Record<WorldKey, SeasonWorld>
  reality: { siap: Record<string, SiapSeries>; gaps: Record<WorldKey, Record<string, CropGap>> }
}
