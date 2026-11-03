import type { Card } from "../types";

export const LANGUAGES = ["English", "Español", "Français", "Português", "हिन्दी", "Kiswahili", "العربية", "中文"];

export interface Explanation {
  summary: string;
  whyThisRotation: string;
  tradeoffs: string[];
  risks: string[];
  whatToCheckLocally: string[];
  recommendation: string;
}

const round = (x: number, digits = 0) => Number(x.toFixed(digits));

/** The ONLY data the model sees. Numbers in its answer must come from here. */
export function explainerPayload(card: Card, cropNames: Record<string, string>, scenario: { rainPct: number; tempC: number }) {
  const r = card.rotation;
  return {
    strategy: card.title,
    rotation: r.crops.map((id) => cropNames[id] ?? id),
    confidence: r.confidence,
    confidenceReasons: r.confidenceReasons,
    scenario: { rainChangePct: scenario.rainPct, warmingC: scenario.tempC },
    metrics: {
      avgNetIncomeUsdPerHaYear: round(r.objectives.income),
      worstTenPercentYearsUsdPerHaYear: round(r.objectives.badYear),
      soilHealthIndex0to1: round(r.objectives.soil, 2),
      waterUseMmPerSeason: round(r.objectives.water),
      erosionRiskIndex0to1: round(r.objectives.erosion, 2),
      pestBreakScore0to1: round(r.pestBreak, 2),
    },
    why: card.why, evidence: card.evidence, benefits: card.benefits, risks: card.risks, informationGaps: card.gaps,
  };
}

export const SYSTEM_INSTRUCTION = `You explain crop-rotation options to farmers who may have limited technical or geospatial experience.
You are part of a SUPPORT tool: you never replace the farmer's judgment or local agricultural experts.

Hard rules:
1. Use ONLY the facts in the JSON the user provides. Never invent numbers, crops, places, prices or agronomic claims.
2. Any number you write must appear in the JSON. Prefer plain words over numbers.
3. Evidence tags: "observed-satellite" and "observed-practice" are observations; "model-estimate", "rule-of-thumb" and "assumption" are weaker. Say which kind of evidence supports each claim.
4. Match your tone to the confidence label:
   - high: say it is "worth seriously considering", and still name what to verify locally.
   - medium: say it is "promising" and suggest testing on a small plot or asking a local expert first.
   - low: say it is "exploratory only" and advise NOT acting without local expert review.
5. Always mention the main information gaps and risks honestly. Explain trade-offs (for example income versus water or soil).
6. Use short sentences and simple words. Explain any technical term (like nitrogen fixation or erosion) in half a sentence.
7. Write the whole answer in the requested language.
Return JSON matching the schema.`;

export function explainerPrompt(payload: unknown, language: string): string {
  return `Language: ${language}\nExplain this rotation option for a farmer.\n\nDATA:\n${JSON.stringify(payload)}`;
}

/** Numbers (two or more digits) in the explanation that do not appear in the data we supplied. */
export function ungroundedNumbers(explanation: Explanation, payload: unknown): string[] {
  const allowed = new Set<string>();
  const collect = (value: unknown) => {
    if (typeof value === "number") {
      allowed.add(String(Math.round(value)));
      allowed.add(String(Math.abs(Math.round(value))));
      allowed.add(String(value));
    } else if (typeof value === "string") {
      for (const m of value.match(/\d[\d,.]*/g) ?? []) allowed.add(m.replace(/[,.]$/, "").replace(/,/g, ""));
    } else if (Array.isArray(value)) value.forEach(collect);
    else if (value && typeof value === "object") Object.values(value).forEach(collect);
  };
  collect(payload);
  const text = [explanation.summary, explanation.whyThisRotation, explanation.recommendation, ...explanation.tradeoffs, ...explanation.risks, ...explanation.whatToCheckLocally].join(" ");
  const found = (text.match(/\d[\d,.]*\d|\d/g) ?? []).map((n) => n.replace(/,/g, ""));
  return [...new Set(found.filter((n) => n.length >= 2 && !allowed.has(n) && !allowed.has(String(Math.round(Number(n))))))];
}

/** Deterministic fallback used when Gemini is unavailable or its answer fails the grounding check. */
export function fallbackExplanation(card: Card, cropNames: Record<string, string>): Explanation {
  const r = card.rotation;
  const tone = r.confidence === "high" ? "This option is worth seriously considering, but verify the points below locally."
    : r.confidence === "medium" ? "This option looks promising. Try it on a small plot or ask a local expert first."
    : "This option is exploratory only. Do not act on it without local expert review.";
  return {
    summary: `${card.title}: ${r.crops.map((id) => cropNames[id] ?? id).join(" → ")}. Confidence: ${r.confidence}.`,
    whyThisRotation: card.why.join(" "),
    tradeoffs: card.benefits.slice(0, 3),
    risks: card.risks.slice(0, 4),
    whatToCheckLocally: card.gaps.slice(0, 4),
    recommendation: tone,
  };
}

