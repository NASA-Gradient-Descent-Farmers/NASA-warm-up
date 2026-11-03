export type Months = (number | null)[];
export type Status = "ok" | "fallback" | "missing";

export interface SiteProfile {
  schema_version: string;
  cell_id: string;
  location: { lat: number; lon: number; elevation_m: number | null; slope_deg: number | null; region_id: string; data_tier: "A" | "B" };
  climate_monthly: {
    tmean_c: Months; tmin_c: Months; tmax_c: Months; rain_mm: Months; et0_mm: Months;
    frost_prob: Months; heat_days: Months; dry_spell_days: Months; extreme_rain_days: Months;
  };
  years_sample: { year: number; rain_mm: number[]; frost_days: number[]; heat_days: number[]; tmean_c: number[] }[];
  climate_trend?: { tmean_c_per_decade?: number; rain_pct_per_decade?: number; years?: number[] };
  water: { aridity_index: number | null; soil_moisture_pctl: Months; drought_freq: number | null; water_trend: number | null };
  vegetation: { ndvi_monthly: Months; ndvi_p10_monthly: Months; bare_months: number[] };
  soil: { soc_g_kg: number | null; clay_pct: number | null; sand_pct: number | null; ph: number | null; n_g_kg: number | null; awc_mm: number | null };
  availability: Record<string, { status: Status; reason?: string }>;
  provenance: Record<string, unknown>;
}

export interface Crop {
  id: string; name: string; family: string; type: "cereal" | "legume" | "forage" | "cover" | "fallow";
  cycle_months: number; tmean_opt_c: [number, number]; tmin_survive_c: number; water_need_mm: number; ky: number;
  root_depth_m: number; n_fix_kg_ha: number; n_demand_kg_ha: number; residue_om: number; cover: number; forage: number;
  drought_tolerance: number; yield_t_ha: number; price_usd_t: number; cost_usd_ha: number; harvest_ratio: number;
}

export interface Rules {
  same_crop_pest_penalty: number; same_family_pest_penalty: number; break_bonus_per_year: number; legume_n_credit_fraction: number;
}

export interface ReferenceSite {
  id: string; name: string; lat: number; lon: number; grown: string[];
  tmean_c: number[]; rain_mm: number[]; aridity_index: number | null;
}

export interface Scenario { rainPct: number; tempC: number }
export interface Economics { priceScale: number; costScale: number; nPriceUsdKg: number; priceOverride: Record<string, number> }

/** Farmer priorities: weights (0..1) and optional hard guarantees. */
export interface Priorities {
  income: number; badYear: number; soil: number; water: number; erosion: number;
  minBadYearUsd: number | null; maxWaterMm: number | null; maxFallow: number;
}

export interface SeasonOutcome {
  startMonth: number; yieldFactor: number; yieldT: number; netUsd: number; waterUseMm: number;
  frostDamaged: boolean; fertKgN: number;
}

export interface Objectives { income: number; badYear: number; soil: number; water: number; erosion: number }

export type LensName = "budget" | "windows" | "twins";

export interface LensResult { available: boolean; score: number | null; note: string }

export type Confidence = "high" | "medium" | "low";
export type EvidenceTag = "observed-satellite" | "observed-practice" | "model-estimate" | "rule-of-thumb" | "assumption";

export interface Evidence { text: string; tag: EvidenceTag }

export interface RotationResult {
  crops: string[];
  objectives: Objectives;
  utility: number;
  pestBreak: number;
  lenses: Record<LensName, LensResult>;
  percentile: Record<LensName, number | null>;
  agreement: { favored: number; available: number };
  robustness: number;
  confidence: Confidence;
  confidenceReasons: string[];
  slots: SeasonOutcome[];
}

export interface Card {
  kind: "existing" | "priority" | "soil-water" | "income";
  title: string;
  rotation: RotationResult;
  why: string[];
  evidence: Evidence[];
  benefits: string[];
  risks: string[];
  gaps: string[];
}

