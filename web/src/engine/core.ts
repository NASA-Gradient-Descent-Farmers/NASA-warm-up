import type {
  Confidence, Crop, Economics, LensName, LensResult, Objectives, Priorities, ReferenceSite,
  Rules, Scenario, SeasonOutcome, SiteProfile,
} from "../types";

export const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export const ROTATION_LENGTH = 3;
export const DEFAULT_SCENARIO: Scenario = { rainPct: 0, tempC: 0 };
export const DEFAULT_ECONOMICS: Economics = { priceScale: 1, costScale: 1, nPriceUsdKg: 1.0, priceOverride: {} };
export const DEFAULT_PRIORITIES: Priorities = {
  income: 0.5, badYear: 0.5, soil: 0.5, water: 0.5, erosion: 0.5, minBadYearUsd: null, maxWaterMm: null, maxFallow: 1,
};

const clip = (x: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, x));
const mean = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0);
const num = (x: number | null | undefined, fallback: number) => (x === null || x === undefined || Number.isNaN(x) ? fallback : x);

export function seasonMonths(start: number, cycleMonths: number): number[] {
  const n = Math.min(12, Math.ceil(cycleMonths));
  return Array.from({ length: n }, (_, i) => (start + i) % 12);
}

// ---------------------------------------------------------------------------------------------------
// Crop-season model (Lens 3 building block): one crop, one start month, every historical weather year.
// ---------------------------------------------------------------------------------------------------

interface CropTable { start: number; byYear: SeasonOutcome[]; frostDamageRate: number; failRate: number }

function soilNSupply(profile: SiteProfile): number {
  return profile.soil.n_g_kg === null ? 60 : clip(profile.soil.n_g_kg * 58.5, 20, 160); // ~1.5%/yr of top-30 cm total N
}

function evalSeason(crop: Crop, start: number, profile: SiteProfile, scenario: Scenario, econ: Economics): SeasonOutcome[] {
  const months = crop.type === "fallow" ? [] : seasonMonths(start, crop.cycle_months);
  const awc = num(profile.soil.awc_mm, 120);
  const soilFactor = 0.85 + 0.3 * clip((awc - 80) / 120, 0, 1);
  const frostThreshold = crop.tmin_survive_c >= 0 ? 1 : crop.tmin_survive_c >= -5 ? 5 : 12;
  const price = (econ.priceOverride[crop.id] ?? crop.price_usd_t) * econ.priceScale;
  const nSoil = soilNSupply(profile);

  return profile.years_sample.map((year) => {
    if (crop.type === "fallow") {
      return { startMonth: start, yieldFactor: 0, yieldT: 0, netUsd: -crop.cost_usd_ha * econ.costScale, waterUseMm: 0, frostDamaged: false, fertKgN: 0 };
    }
    const tmean = mean(months.map((m) => year.tmean_c[m])) + scenario.tempC;
    const rain = months.reduce((s, m) => s + year.rain_mm[m], 0) * (1 + scenario.rainPct / 100);
    const demand = crop.water_need_mm * (1 + 0.03 * scenario.tempC);
    const supply = rain + 0.5 * awc;
    const stress = demand > 0 ? clip(1 - supply / demand, 0, 1) : 0;
    const waterFactor = clip(1 - crop.ky * stress, 0, 1);
    const [lo, hi] = crop.tmean_opt_c;
    const d = tmean < lo ? lo - tmean : tmean > hi ? tmean - hi : 0;
    const tempFactor = clip(1 - 0.08 * d, 0, 1);
    const heatDays = months.reduce((s, m) => s + year.heat_days[m], 0) + Math.max(0, scenario.tempC) * 3;
    const heatPenalty = Math.min(0.4, 0.015 * heatDays * (1 - 0.5 * crop.drought_tolerance));
    const frostDays = months.reduce((s, m) => s + year.frost_days[m], 0) * Math.max(0, 1 - 0.25 * Math.max(0, scenario.tempC));
    const frostDamaged = frostDays >= frostThreshold;
    const yieldFactor = tempFactor * waterFactor * (1 - heatPenalty) * (frostDamaged ? 0.15 : 1);
    const yieldT = crop.yield_t_ha * soilFactor * yieldFactor;
    const ratio = crop.yield_t_ha > 0 ? yieldT / crop.yield_t_ha : 0;
    const fertKgN = Math.max(0, crop.n_demand_kg_ha * Math.min(1, ratio) - nSoil);
    const net = yieldT * price * crop.harvest_ratio - crop.cost_usd_ha * econ.costScale - fertKgN * econ.nPriceUsdKg;
    return { startMonth: start, yieldFactor, yieldT, netUsd: net, waterUseMm: Math.min(supply, demand), frostDamaged, fertKgN };
  });
}

function buildCropTable(crop: Crop, profile: SiteProfile, scenario: Scenario, econ: Economics): CropTable {
  let best: { start: number; byYear: SeasonOutcome[]; score: number } | null = null;
  const starts = crop.type === "fallow" || crop.cycle_months >= 10 ? [0] : [...Array(12).keys()];
  for (const start of starts) {
    const byYear = evalSeason(crop, start, profile, scenario, econ);
    const score = mean(byYear.map((o) => (crop.type === "cover" ? o.yieldFactor : o.yieldFactor + 0.0001 * o.netUsd)));
    if (!best || score > best.score) best = { start, byYear, score };
  }
  const { start, byYear } = best!;
  return {
    start, byYear,
    frostDamageRate: mean(byYear.map((o) => (o.frostDamaged ? 1 : 0))),
    failRate: mean(byYear.map((o) => (o.yieldFactor < 0.3 && crop.type !== "fallow" && crop.type !== "cover" ? 1 : 0))),
  };
}

export type CropTables = Record<string, CropTable>;

export function buildTables(crops: Crop[], profile: SiteProfile, scenario: Scenario, econ: Economics): CropTables {
  return Object.fromEntries(crops.map((c) => [c.id, buildCropTable(c, profile, scenario, econ)]));
}

// ---------------------------------------------------------------------------------------------------
// Rotation aggregation
// ---------------------------------------------------------------------------------------------------

const isHarvest = (c: Crop) => c.type === "cereal" || c.type === "legume" || c.type === "forage";

export function pestBreakScore(seq: Crop[], rules: Rules): number {
  let penalty = 0;
  for (let k = 0; k < seq.length; k++) {
    const a = seq[k], b = seq[(k + 1) % seq.length];
    if (a.type === "fallow" || b.type === "fallow" || a.type === "cover" || b.type === "cover") continue;
    if (a.id === b.id) penalty += rules.same_crop_pest_penalty;
    else if (a.family === b.family) penalty += rules.same_family_pest_penalty;
  }
  return clip(1 - penalty / (seq.length * rules.same_crop_pest_penalty), 0, 1);
}

function baseErosionRisk(profile: SiteProfile): number {
  const extremeDays = (profile.climate_monthly.extreme_rain_days as (number | null)[]).reduce<number>((s, v) => s + num(v, 0), 0);
  return clip(0.25 + num(profile.location.slope_deg, 2) / 20 + extremeDays / 40, 0.05, 1);
}

export interface Aggregated {
  crops: string[]; objectives: Objectives; pestBreak: number; slots: SeasonOutcome[]; annualNet: number[];
  nCreditKg: number; erosionBase: number;
}

export function aggregate(seq: Crop[], tables: CropTables, profile: SiteProfile, rules: Rules, econ: Economics): Aggregated {
  const nYears = profile.years_sample.length;
  const annualNet = Array.from({ length: nYears }, () => 0);
  let waterSum = 0, nCreditKg = 0;
  seq.forEach((crop, k) => {
    const prev = seq[(k + seq.length - 1) % seq.length];
    const table = tables[crop.id];
    const credit = crop.type === "cereal" && prev.type === "legume" ? prev.n_fix_kg_ha * rules.legume_n_credit_fraction : 0;
    table.byYear.forEach((o, y) => {
      const saved = Math.min(o.fertKgN, credit);
      annualNet[y] += (o.netUsd + saved * econ.nPriceUsdKg) / seq.length;
      waterSum += o.waterUseMm;
      if (y === 0) nCreditKg += saved;
    });
  });
  const sorted = [...annualNet].sort((a, b) => a - b);
  const tail = sorted.slice(0, Math.max(1, Math.ceil(0.1 * nYears)));
  const residue = mean(seq.map((c) => c.residue_om));
  const nfix = clip(mean(seq.map((c) => c.n_fix_kg_ha)) / 100, 0, 1);
  const coverEff = mean(seq.map((c) => c.cover * clip((c.cycle_months + 2) / 12, 0, 1)));
  const pestBreak = pestBreakScore(seq, rules);
  const erosionBase = baseErosionRisk(profile);
  return {
    crops: seq.map((c) => c.id),
    objectives: {
      income: mean(annualNet),
      badYear: mean(tail),
      soil: 0.3 * residue + 0.25 * nfix + 0.2 * coverEff + 0.25 * pestBreak,
      water: waterSum / (nYears * seq.length),
      erosion: erosionBase * (1 - coverEff),
    },
    pestBreak,
    slots: seq.map((c) => tables[c.id].byYear[Math.floor(nYears / 2)]),
    annualNet,
    nCreditKg: nCreditKg / seq.length,
    erosionBase,
  };
}

export function allSequences(crops: Crop[], maxFallow: number, length = ROTATION_LENGTH): Crop[][] {
  const out: Crop[][] = [];
  const rec = (acc: Crop[]) => {
    if (acc.length === length) {
      if (!acc.some(isHarvest)) return;
      if (acc.filter((c) => c.type === "fallow").length > maxFallow) return;
      if (acc.filter((c) => c.type === "cover").length > 1) return;
      out.push([...acc]);
      return;
    }
    for (const c of crops) rec([...acc, c]);
  };
  rec([]);
  return out;
}

// ---------------------------------------------------------------------------------------------------
// Scoring, Pareto, constraints
// ---------------------------------------------------------------------------------------------------

export const OBJECTIVE_KEYS: (keyof Objectives)[] = ["income", "badYear", "soil", "water", "erosion"];
const sign: Record<keyof Objectives, number> = { income: 1, badYear: 1, soil: 1, water: -1, erosion: -1 };

const asVector = (o: Objectives) => OBJECTIVE_KEYS.map((k) => sign[k] * o[k]);

export function paretoFront(items: { objectives: Objectives }[]): number[] {
  const vectors = items.map((i) => asVector(i.objectives));
  const front: number[] = [];
  vectors.forEach((v, i) => {
    const dominated = vectors.some((w, j) => j !== i && w.every((x, k) => x >= v[k]) && w.some((x, k) => x > v[k]));
    if (!dominated) front.push(i);
  });
  return front;
}

function normalizers(items: Aggregated[]) {
  const ranges = OBJECTIVE_KEYS.map((k) => {
    const xs = items.map((i) => i.objectives[k]);
    return { min: Math.min(...xs), max: Math.max(...xs) };
  });
  return (o: Objectives) =>
    Object.fromEntries(OBJECTIVE_KEYS.map((k, i) => {
      const { min, max } = ranges[i];
      const unit = max === min ? 0.5 : (o[k] - min) / (max - min);
      return [k, sign[k] === 1 ? unit : 1 - unit];
    })) as Record<keyof Objectives, number>;
}

export function weightedUtility(items: Aggregated[], priorities: Priorities): number[] {
  const norm = normalizers(items);
  const w = OBJECTIVE_KEYS.map((k) => priorities[k]);
  const total = w.reduce((a, b) => a + b, 0) || 1;
  return items.map((i) => {
    const n = norm(i.objectives);
    return OBJECTIVE_KEYS.reduce<number>((s, k, idx) => s + (w[idx] / total) * n[k], 0);
  });
}

export function satisfiesGuarantees(a: Aggregated, p: Priorities): boolean {
  if (p.minBadYearUsd !== null && a.objectives.badYear < p.minBadYearUsd) return false;
  if (p.maxWaterMm !== null && a.objectives.water > p.maxWaterMm) return false;
  return true;
}

// ---------------------------------------------------------------------------------------------------
// Lens 2: observed vegetation calendar (MODIS NDVI) ; Lens 1: climate twins
// ---------------------------------------------------------------------------------------------------

export function windowsLens(seq: Crop[], tables: CropTables, profile: SiteProfile): LensResult {
  const ndvi = profile.vegetation.ndvi_monthly;
  const valid = ndvi.filter((v): v is number => v !== null);
  if (valid.length < 6) return { available: false, score: null, note: "No satellite NDVI at this location, so the observed-calendar lens is unavailable." };
  const max = Math.max(...valid);
  const bare = profile.vegetation.bare_months.map((m) => m - 1);
  const fits = seq.map((crop) => {
    if (crop.type === "fallow") return 0;
    const months = seasonMonths(tables[crop.id].start, crop.cycle_months);
    if (crop.type === "cover") {
      return bare.length ? months.filter((m) => bare.includes(m)).length / bare.length : 0.5;
    }
    const fit = mean(months.map((m) => clip(num(ndvi[m], 0) / max, 0, 1)));
    const p10 = profile.vegetation.ndvi_p10_monthly;
    const stress = mean(months.map((m) => clip(1 - num(p10[m], 0) / Math.max(0.05, num(ndvi[m], 0.05)), 0, 0.5)));
    return fit * (1 - stress);
  });
  return { available: true, score: mean(fits), note: "Fit of each crop's season to the locally observed green season (MODIS NDVI), minus stress variability." };
}

function signature(t: number[], rain: number[], dt: number, dr: number) {
  return { t: t.map((x) => x + dt), lr: rain.map((r) => Math.log(1 + Math.max(0, r) * (1 + dr / 100))) };
}

export interface Twin { site: ReferenceSite; distance: number; weight: number }

export function findTwins(profile: SiteProfile, refs: ReferenceSite[], scenario: Scenario, k = 5): Twin[] {
  const t = profile.climate_monthly.tmean_c, r = profile.climate_monthly.rain_mm;
  if (t.some((v) => v === null) || r.some((v) => v === null)) return [];
  const mine = signature(t as number[], r as number[], scenario.tempC, scenario.rainPct);
  return refs
    .map((site) => {
      const s = signature(site.tmean_c, site.rain_mm, 0, 0);
      const dT = mean(s.t.map((x, i) => ((x - mine.t[i]) / 4) ** 2));
      const dR = mean(s.lr.map((x, i) => ((x - mine.lr[i]) / 0.7) ** 2));
      return { site, distance: Math.sqrt(dT + dR) };
    })
    .sort((a, b) => a.distance - b.distance)
    .slice(0, k)
    .map((x) => ({ ...x, weight: Math.exp(-(x.distance ** 2) / (2 * 0.5 ** 2)) }));
}

export function twinSupport(twins: Twin[], cropId: string): number {
  const total = twins.reduce((s, t) => s + t.weight, 0);
  if (!total) return 0;
  if (cropId === "cover") return 0.5;
  if (cropId === "fallow") return 0.1;
  return twins.reduce((s, t) => s + (t.site.grown.includes(cropId) ? t.weight : 0), 0) / total;
}

export function twinsLens(seq: Crop[], twins: Twin[]): LensResult {
  if (!twins.length || twins[0].distance > 1.0) {
    return { available: false, score: null, note: "No sufficiently similar climate found in the reference library." };
  }
  return { available: true, score: mean(seq.map((c) => twinSupport(twins, c.id))),
    note: `Crops grown where today's climate resembles yours: ${twins.slice(0, 3).map((t) => t.site.name).join(", ")}.` };
}

// ---------------------------------------------------------------------------------------------------
// Confidence
// ---------------------------------------------------------------------------------------------------

export interface ConfidenceInput {
  percentile: Record<LensName, number | null>;
  keyLayersOk: boolean; weatherOk: boolean; robustness: number;
}

export function judgeConfidence(inp: ConfidenceInput): { label: Confidence; reasons: string[]; favored: number; available: number } {
  const lenses = (Object.keys(inp.percentile) as LensName[]).filter((l) => inp.percentile[l] !== null);
  const favored = lenses.filter((l) => (inp.percentile[l] as number) >= 0.7).length;
  const reasons: string[] = [`${favored} of ${lenses.length} available evidence lenses rank this rotation in their top 30%.`];
  reasons.push(inp.keyLayersOk ? "Key data layers (weather, soil, elevation) are available." : "Some key data layers are missing or approximated.");
  reasons.push(`Ranking stays in the top 30% in ${Math.round(inp.robustness * 100)}% of price and climate stress tests.`);
  let label: Confidence = "low";
  if (favored >= 2 && lenses.length >= 2 && inp.keyLayersOk && inp.robustness >= 0.75) label = "high";
  else if (favored >= 1 && inp.weatherOk) label = "medium";
  return { label, reasons, favored, available: lenses.length };
}

