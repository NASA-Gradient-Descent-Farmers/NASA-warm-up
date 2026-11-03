import {
  aggregate, allSequences, buildTables, findTwins, judgeConfidence, MONTHS, OBJECTIVE_KEYS, paretoFront, ROTATION_LENGTH,
  satisfiesGuarantees, seasonMonths, twinsLens, twinSupport, weightedUtility, windowsLens,
  type Aggregated, type CropTables, type Twin,
} from "./core";
import type {
  Card, Crop, Economics, Evidence, LensName, LensResult, Priorities, ReferenceSite, Rules, RotationResult, Scenario, SiteProfile,
} from "../types";

export interface EvaluationInput {
  profile: SiteProfile; crops: Crop[]; rules: Rules; references: ReferenceSite[];
  scenario: Scenario; economics: Economics; priorities: Priorities; existing: string[];
}

export interface Evaluation {
  results: RotationResult[]; front: number[]; cards: Card[]; twins: Twin[]; nYears: number; tables: CropTables;
}

const keyOf = (ids: string[]) => ids.join("|");

function percentilesOf(scores: (number | null)[]): (number | null)[] {
  const valid = scores.map((s, i) => ({ s, i })).filter((x): x is { s: number; i: number } => x.s !== null);
  const sorted = [...valid].sort((a, b) => a.s - b.s);
  const out: (number | null)[] = scores.map(() => null);
  sorted.forEach((x, rank) => { out[x.i] = valid.length > 1 ? rank / (valid.length - 1) : 1; });
  return out;
}

function candidateSet(input: EvaluationInput): Crop[][] {
  const byId = new Map(input.crops.map((c) => [c.id, c]));
  const seqs = allSequences(input.crops, input.priorities.maxFallow);
  const existing = input.existing.map((id) => byId.get(id)!).filter(Boolean);
  if (existing.length === ROTATION_LENGTH && !seqs.some((s) => keyOf(s.map((c) => c.id)) === keyOf(input.existing))) seqs.push(existing);
  return seqs;
}

/** Percentile of each rotation's weighted utility under one perturbed world. */
function utilityPercentiles(input: EvaluationInput, scenario: Scenario, economics: Economics, seqs: Crop[][]): Map<string, number> {
  const tables = buildTables(input.crops, input.profile, scenario, economics);
  const aggs = seqs.map((s) => aggregate(s, tables, input.profile, input.rules, economics));
  const pct = percentilesOf(weightedUtility(aggs, input.priorities));
  return new Map(aggs.map((a, i) => [keyOf(a.crops), pct[i] as number]));
}

function robustnessMap(input: EvaluationInput, seqs: Crop[][]): Map<string, number> {
  const { scenario, economics } = input;
  const worlds: { s: Scenario; e: Economics }[] = [];
  for (const dRain of [0, -20]) {
    for (const dTemp of [0, 2]) {
      for (const price of [0.7, 1, 1.3]) {
        worlds.push({
          s: { rainPct: scenario.rainPct + dRain, tempC: scenario.tempC + dTemp },
          e: { ...economics, priceScale: economics.priceScale * price },
        });
      }
    }
  }
  const hits = new Map<string, number>();
  for (const w of worlds) {
    for (const [k, p] of utilityPercentiles(input, w.s, w.e, seqs)) hits.set(k, (hits.get(k) ?? 0) + (p >= 0.7 ? 1 : 0));
  }
  return new Map([...hits].map(([k, v]) => [k, v / worlds.length]));
}

export function evaluate(input: EvaluationInput): Evaluation {
  const { profile, crops, rules, references, scenario, economics, priorities } = input;
  const byId = new Map(crops.map((c) => [c.id, c]));
  const seqs = candidateSet(input);
  const tables = buildTables(crops, profile, scenario, economics);
  const aggs: Aggregated[] = seqs.map((s) => aggregate(s, tables, profile, rules, economics));
  const utilities = weightedUtility(aggs, priorities);
  const twins = findTwins(profile, references, scenario);

  const lensList: Record<LensName, LensResult>[] = seqs.map((s, i) => ({
    budget: { available: true, score: utilities[i], note: "Quantitative water, frost and nitrogen budget over historical weather years." },
    windows: windowsLens(s, tables, profile),
    twins: twinsLens(s, twins),
  }));
  const pct: Record<LensName, (number | null)[]> = {
    budget: percentilesOf(lensList.map((l) => l.budget.score)),
    windows: percentilesOf(lensList.map((l) => l.windows.score)),
    twins: percentilesOf(lensList.map((l) => l.twins.score)),
  };
  const robust = robustnessMap(input, seqs);

  const av = profile.availability;
  const keyLayersOk = ["weather", "soil", "elevation"].every((l) => av[l]?.status === "ok");
  const weatherOk = av.weather?.status === "ok";

  const results: RotationResult[] = aggs.map((a, i) => {
    const percentile = { budget: pct.budget[i], windows: pct.windows[i], twins: pct.twins[i] };
    const robustness = robust.get(keyOf(a.crops)) ?? 0;
    const judged = judgeConfidence({ percentile, keyLayersOk, weatherOk, robustness });
    return {
      crops: a.crops, objectives: a.objectives, utility: utilities[i], pestBreak: a.pestBreak, lenses: lensList[i], percentile,
      agreement: { favored: judged.favored, available: judged.available }, robustness, confidence: judged.label,
      confidenceReasons: judged.reasons, slots: a.slots,
    };
  });

  const front = paretoFront(results);
  const ok = (_r: RotationResult, i: number) => satisfiesGuarantees(aggs[i], priorities) && seqs[i].filter((c) => c.type === "fallow").length <= priorities.maxFallow;
  const eligible = results.map((r, i) => ({ r, i })).filter((x) => ok(x.r, x.i));
  const pool = eligible.length ? eligible : results.map((r, i) => ({ r, i }));
  const existingKey = keyOf(input.existing);
  const existingIdx = results.findIndex((r) => keyOf(r.crops) === existingKey);
  const used = new Set<string>([existingKey]);
  const pick = (score: (x: { r: RotationResult; i: number }) => number) => {
    const onFront = pool.filter((x) => front.includes(x.i) && !used.has(keyOf(x.r.crops)));
    const candidates = onFront.length ? onFront : pool.filter((x) => !used.has(keyOf(x.r.crops)));
    const best = candidates.reduce((a, b) => (score(b) > score(a) ? b : a));
    used.add(keyOf(best.r.crops));
    return best.r;
  };
  const priority = pick((x) => x.r.utility);
  const soilWater = pick((x) => 0.4 * x.r.objectives.soil - 0.3 * x.r.objectives.water / 500 - 0.3 * x.r.objectives.erosion);
  const income = pick((x) => x.r.objectives.income + 0.001 * x.r.objectives.badYear);

  const make = (kind: Card["kind"], title: string, r: RotationResult): Card =>
    buildCard(kind, title, r, input, tables, twins, seqs[results.indexOf(r)] ?? r.crops.map((id) => byId.get(id)!));
  const cards = [
    make("existing", "Your current rotation", results[existingIdx]),
    make("priority", "Best for your priorities", priority),
    make("soil-water", "Best for soil & water", soilWater),
    make("income", "Highest expected income", income),
  ];
  return { results, front, cards, twins, nYears: profile.years_sample.length, tables };
}

// ---------------------------------------------------------------------------------------------------
// Card text: deterministic, every claim carries an evidence tag
// ---------------------------------------------------------------------------------------------------

const usd = (x: number) => `${x < 0 ? "-" : ""}$${Math.abs(Math.round(x)).toLocaleString("en-US")}`;
const monthRange = (months: number[]) => (months.length ? `${MONTHS[months[0]]}–${MONTHS[months[months.length - 1]]}` : "n/a");

function buildCard(kind: Card["kind"], title: string, r: RotationResult, input: EvaluationInput, tables: CropTables, twins: Twin[], seq: Crop[]): Card {
  const { profile, scenario } = input;
  const names = seq.map((c) => c.name);
  const o = r.objectives;
  const evidence: Evidence[] = [];
  const why: string[] = [];
  const benefits: string[] = [];
  const risks: string[] = [];
  const gaps: string[] = [];

  evidence.push({ tag: "model-estimate", text: `Modelled over ${input.profile.years_sample.length} historical weather years (NASA POWER): average net income ${usd(o.income)}/ha/yr, and ${usd(o.badYear)}/ha/yr in the worst 10% of years.` });
  evidence.push({ tag: "model-estimate", text: `Average crop water use ${Math.round(o.water)} mm per season; erosion risk index ${o.erosion.toFixed(2)} (0 = low, 1 = high).` });

  if (r.lenses.windows.available) {
    const green = seq.filter((c) => c.type !== "fallow").map((c) => `${c.name}: ${monthRange(seasonMonths(tables[c.id].start, c.cycle_months))}`);
    evidence.push({ tag: "observed-satellite", text: `MODIS NDVI shows the typical local green season; planned seasons: ${green.join("; ")}. Typically bare months: ${profile.vegetation.bare_months.length ? profile.vegetation.bare_months.map((m) => MONTHS[m - 1]).join(", ") : "none detected"}.` });
  } else {
    gaps.push("No satellite vegetation (NDVI) record at this location, so we could not check the rotation against the observed growing calendar.");
  }
  if (r.lenses.twins.available) {
    const support = seq.filter((c) => c.type !== "fallow" && c.type !== "cover").map((c) => `${c.name} ${Math.round(twinSupport(twins, c.id) * 100)}%`).join(", ");
    evidence.push({ tag: "observed-practice", text: `Places whose current climate resembles your ${scenario.rainPct || scenario.tempC ? "scenario" : "present"} climate (${twins.slice(0, 3).map((t) => t.site.name).join(", ")}) grow these crops. Share of twins growing each: ${support}. (Team-curated reference list, unverified.)` });
  } else {
    gaps.push("No close climate match in the reference library, so the 'climate twins' evidence is unavailable.");
  }
  if (r.pestBreak >= 0.75) {
    benefits.push("Good crop diversity: rotating crop families helps interrupt pest and disease cycles.");
    evidence.push({ tag: "rule-of-thumb", text: "Pest-cycle break score from crop family rules (repeating a family raises pressure)." });
  } else if (r.pestBreak < 0.45) {
    risks.push("Repeating the same crop or family in successive years can build up pests and diseases.");
  }
  const legumes = seq.filter((c) => c.type === "legume" || c.id === "alfalfa" || c.id === "cover");
  if (legumes.length) {
    benefits.push(`Nitrogen-fixing crops (${legumes.map((c) => c.name).join(", ")}) can supply nitrogen to following crops and reduce fertilizer needs.`);
    evidence.push({ tag: "rule-of-thumb", text: "Nitrogen fixation values per crop are general agronomic rules of thumb, not site measurements." });
  }
  if (seq.some((c) => c.cover >= 0.8)) benefits.push("Dense ground cover helps protect soil from erosion and adds organic matter.");
  if (o.water < 300) benefits.push("Relatively low water demand compared with the alternatives.");
  if (seq.some((c) => c.drought_tolerance >= 0.8 && c.type !== "fallow")) benefits.push("Includes a drought-tolerant crop, which buffers dry years.");
  if (o.income > 0) benefits.push(`Positive average net income under the price and cost assumptions (${usd(o.income)}/ha/yr).`);

  for (const c of seq) {
    if (c.type === "fallow" || c.type === "cover") continue;
    const t = tables[c.id];
    if (t.frostDamageRate > 0.15) risks.push(`${c.name}: frost damaged the crop in about ${Math.round(t.frostDamageRate * 100)}% of historical years.`);
    if (t.failRate > 0.2) risks.push(`${c.name}: very poor yield (water or heat stress) in about ${Math.round(t.failRate * 100)}% of historical years.`);
  }
  if (o.erosion > 0.55) risks.push("High erosion risk (slope, heavy-rain days or little ground cover).");
  if (o.badYear < 0) risks.push(`In bad years this rotation loses money (${usd(o.badYear)}/ha/yr on average in the worst 10%).`);
  if (seq.some((c) => c.type === "fallow")) risks.push("Bare fallow leaves soil exposed and earns no income that year.");

  gaps.push("Crop parameters, prices and costs are general reference values, not local data. Edit prices and costs in the sidebar.");
  if (profile.soil.awc_mm !== null) gaps.push("Soil water capacity is estimated from soil texture, not measured. A local soil test would improve it.");
  for (const [layer, info] of Object.entries(profile.availability)) {
    if (info.status !== "ok" && layer !== "weather") gaps.push(`${layer.replace("_", " ")}: ${info.status}${info.reason ? ` (${info.reason})` : ""}.`);
  }
  gaps.push("Pests, diseases, local cultivars and market access are not modelled. Check with a local agronomist.");

  why.push(kind === "existing" ? "Baseline: what you grow now, scored with the same method as the alternatives."
    : kind === "priority" ? "Highest combined score for the priorities and guarantees you set."
    : kind === "soil-water" ? "Best balance of soil building, low water use and low erosion among the efficient options."
    : "Highest average net income among the efficient options.");
  why.push(`Sequence: ${names.join(" → ")} (then repeats).`);
  if (r.agreement.available) why.push(`${r.agreement.favored} of ${r.agreement.available} independent evidence lenses favor it.`);

  void OBJECTIVE_KEYS;
  return { kind, title, rotation: r, why, evidence, benefits, risks, gaps };
}

