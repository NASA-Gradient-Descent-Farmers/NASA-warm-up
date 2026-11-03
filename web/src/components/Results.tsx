import { useState } from "react";
import {
  CartesianGrid, Legend, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis,
} from "recharts";
import { explainCard, geminiConfigured, type ExplainResult } from "../ai/gemini";
import type { StaticData } from "../data";
import type { Evaluation } from "../engine/evaluate";
import type { Card, Scenario } from "../types";

interface Props {
  evaluation: Evaluation;
  data: StaticData;
  scenario: Scenario;
  language: string;
  nYears: number;
}

const fmtUsd = (n: number) => `${n < 0 ? "-" : ""}$${Math.abs(Math.round(n)).toLocaleString("en-US")}`;

export function Results({ evaluation, data, scenario, language, nYears }: Props) {
  const cropNames = Object.fromEntries(data.crops.map((c) => [c.id, c.name]));
  const [explanations, setExplanations] = useState<Record<string, ExplainResult>>({});
  const [loadingKey, setLoadingKey] = useState<string | null>(null);

  const frontSet = new Set(evaluation.front);
  const paretoPts = evaluation.results
    .filter((_, i) => frontSet.has(i))
    .map((r) => ({
      income: Math.round(r.objectives.income),
      soil: Number(r.objectives.soil.toFixed(2)),
      water: Math.round(r.objectives.water),
      label: r.crops.map((id) => cropNames[id] ?? id).join(" → "),
    }));
  const otherPts = evaluation.results
    .filter((_, i) => !frontSet.has(i))
    .slice(0, 200)
    .map((r) => ({
      income: Math.round(r.objectives.income),
      soil: Number(r.objectives.soil.toFixed(2)),
      water: Math.round(r.objectives.water),
      label: r.crops.map((id) => cropNames[id] ?? id).join(" → "),
    }));

  const handleExplain = async (card: Card) => {
    const key = `${card.kind}:${card.rotation.crops.join("-")}:${language}:${scenario.rainPct}:${scenario.tempC}`;
    setLoadingKey(card.kind);
    const res = await explainCard(card, cropNames, scenario, language);
    setExplanations((prev) => ({ ...prev, [key]: res }));
    setLoadingKey(null);
  };

  return (
    <section className="card results-panel">
      <div className="section-header">
        <div>
          <h2>🎯 Triangulated Rotation Strategies & Pareto Frontier</h2>
          <p className="subtitle">
            Evaluated {evaluation.results.length} candidate 3-year rotations across {nYears} historical weather years{" "}
            ({evaluation.front.length} Pareto-optimal plans).
          </p>
        </div>
        <span className={`gemini-badge ${geminiConfigured ? "gemini-ready" : "gemini-fallback"}`}>
          {geminiConfigured ? "✨ Gemini 3.8 Flash Ready" : "🔒 Gemini Offline (Deterministic Explainer Active)"}
        </span>
      </div>

      <div className="pareto-box">
        <h4>📊 Multi-Objective Trade-off: Expected Net Income vs. Soil Health Index</h4>
        <p className="hint">
          Green points sit on the exact <b>Pareto frontier</b>: you cannot improve one objective without trading off another. Grey points are dominated options.
        </p>
        <ResponsiveContainer width="100%" height={240}>
          <ScatterChart margin={{ top: 10, right: 20, bottom: 15, left: 10 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis type="number" dataKey="soil" name="Soil Health Index" domain={[0, 1]} label={{ value: "Soil Health Index (0–1)", position: "insideBottom", offset: -8 }} />
            <YAxis type="number" dataKey="income" name="Net Income ($/ha/yr)" label={{ value: "$/ha/yr", angle: -90, position: "insideLeft" }} />
            <Tooltip cursor={{ strokeDasharray: "3 3" }} />
            <Legend />
            <Scatter name="Dominated candidates" data={otherPts} fill="#b0bec5" />
            <Scatter name="Pareto-optimal frontier" data={paretoPts} fill="#2e7d32" />
          </ScatterChart>
        </ResponsiveContainer>
      </div>

      <div className="cards-grid">
        {evaluation.cards.map((card) => {
          const r = card.rotation;
          const expKey = `${card.kind}:${r.crops.join("-")}:${language}:${scenario.rainPct}:${scenario.tempC}`;
          const exp = explanations[expKey];
          return (
            <article key={card.kind} className={`strategy-card kind-${card.kind}`}>
              <div className="card-top">
                <div>
                  <span className="card-kicker">{card.title}</span>
                  <h3>{r.crops.map((id) => cropNames[id] ?? id).join(" → ")}</h3>
                </div>
                <span className={`conf-badge conf-${r.confidence}`}>
                  {r.confidence.toUpperCase()} CONFIDENCE
                </span>
              </div>

              <div className="kpi-row">
                <div className="kpi">
                  <span>Avg Net</span>
                  <strong>{fmtUsd(r.objectives.income)}/ha</strong>
                </div>
                <div className="kpi">
                  <span>Bad-Year (P10)</span>
                  <strong>{fmtUsd(r.objectives.badYear)}/ha</strong>
                </div>
                <div className="kpi">
                  <span>Soil Health</span>
                  <strong>{r.objectives.soil.toFixed(2)} / 1.0</strong>
                </div>
                <div className="kpi">
                  <span>Water Use</span>
                  <strong>{Math.round(r.objectives.water)} mm</strong>
                </div>
                <div className="kpi">
                  <span>Erosion Risk</span>
                  <strong>{r.objectives.erosion.toFixed(2)}</strong>
                </div>
              </div>

              <div className="lens-strip">
                {(["budget", "windows", "twins"] as const).map((lens) => {
                  const pct = r.percentile[lens];
                  const favored = pct !== null && pct >= 0.7;
                  return (
                    <span key={lens} className={`lens-pill ${pct === null ? "lens-na" : favored ? "lens-fav" : "lens-mid"}`} title={r.lenses[lens].note}>
                      {lens === "budget" ? "Lens 3 · Budget" : lens === "windows" ? "Lens 2 · NDVI Windows" : "Lens 1 · Climate Twins"}:{" "}
                      {pct === null ? "n/a" : `P${Math.round(pct * 100)}`}
                    </span>
                  );
                })}
                <span className="lens-pill lens-rob" title="Share of ±30% price and climate stress worlds where this plan stays in the top 30%">
                  Stress robustness: {Math.round(r.robustness * 100)}%
                </span>
              </div>

              <div className="card-section">
                <h5>Why suggested</h5>
                <ul>
                  {card.why.map((w, i) => <li key={i}>{w}</li>)}
                </ul>
              </div>

              <div className="card-section">
                <h5>Evidence Ledger</h5>
                <ul className="evidence-list">
                  {card.evidence.map((ev, i) => (
                    <li key={i}>
                      <span className={`ev-tag ev-${ev.tag}`}>{ev.tag}</span> {ev.text}
                    </li>
                  ))}
                </ul>
              </div>

              {card.benefits.length > 0 && (
                <div className="card-section">
                  <h5>Expected Benefits</h5>
                  <ul>{card.benefits.map((b, i) => <li key={i}>{b}</li>)}</ul>
                </div>
              )}

              {card.risks.length > 0 && (
                <div className="card-section warn-section">
                  <h5>⚠️ Risks to Review Locally</h5>
                  <ul>{card.risks.map((rk, i) => <li key={i}>{rk}</li>)}</ul>
                </div>
              )}

              <div className="card-section gap-section">
                <h5>🔍 Information Gaps</h5>
                <ul>{card.gaps.map((g, i) => <li key={i}>{g}</li>)}</ul>
              </div>

              <div className="ai-box">
                <button className="explain-btn" onClick={() => handleExplain(card)} disabled={loadingKey === card.kind}>
                  {loadingKey === card.kind ? "Generating farmer explanation…" : `🗣️ Explain to Farmer (${language})`}
                </button>
                {exp && (
                  <div className="ai-output">
                    {exp.warning && <p className="ai-warning">{exp.warning}</p>}
                    <p><strong>{exp.explanation.summary}</strong></p>
                    <p>{exp.explanation.whyThisRotation}</p>
                    <p className="ai-rec"><strong>Recommendation ({r.confidence} confidence):</strong> {exp.explanation.recommendation}</p>
                  </div>
                )}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

