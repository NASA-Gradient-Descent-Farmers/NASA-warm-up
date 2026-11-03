import { LANGUAGES } from "../ai/explain";
import type { StaticData } from "../data";
import { ROTATION_LENGTH } from "../engine/core";
import type { Economics, Priorities, Scenario } from "../types";

interface Props {
  data: StaticData;
  scenario: Scenario;
  setScenario: (s: Scenario) => void;
  economics: Economics;
  setEconomics: (e: Economics) => void;
  priorities: Priorities;
  setPriorities: (p: Priorities) => void;
  existing: string[];
  setExisting: (ids: string[]) => void;
  language: string;
  setLanguage: (lang: string) => void;
}

const SLIDERS: { key: keyof Pick<Priorities, "income" | "badYear" | "soil" | "water" | "erosion">; label: string; hint: string }[] = [
  { key: "income", label: "Expected Income", hint: "Average net return ($/ha/yr)" },
  { key: "badYear", label: "Bad-Year Protection (CVaR)", hint: "Worst 10% of weather years" },
  { key: "soil", label: "Soil Health & N-Fixation", hint: "Residue, legume N, cover & pest break" },
  { key: "water", label: "Water Conservation", hint: "Lower seasonal crop water demand" },
  { key: "erosion", label: "Erosion Reduction", hint: "Ground cover on sloped / heavy-rain land" },
];

export function ControlsPanel({
  data, scenario, setScenario, economics, setEconomics, priorities, setPriorities, existing, setExisting, language, setLanguage,
}: Props) {
  const updateExisting = (idx: number, cropId: string) => {
    const next = [...existing];
    next[idx] = cropId;
    setExisting(next);
  };

  return (
    <div className="controls">
      <div className="control-group">
        <h3>🗣️ Explainer Language</h3>
        <select value={language} onChange={(e) => setLanguage(e.target.value)} className="full-select">
          {LANGUAGES.map((lang) => (
            <option key={lang} value={lang}>{lang}</option>
          ))}
        </select>
      </div>

      <div className="control-group">
        <h3>🌱 Your Current {ROTATION_LENGTH}-Year Rotation</h3>
        <p className="hint">Select what you currently plant in sequence so we can benchmark alternatives against it.</p>
        <div className="rotation-selects">
          {existing.map((cropId, idx) => (
            <label key={idx} className="inline-label">
              <span>Year {idx + 1}</span>
              <select value={cropId} onChange={(e) => updateExisting(idx, e.target.value)}>
                {data.crops.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
            </label>
          ))}
        </div>
      </div>

      <div className="control-group">
        <h3>⚖️ Farmer Priorities</h3>
        <p className="hint">Set how much each goal matters to you (0 = ignore, 1 = top priority).</p>
        {SLIDERS.map(({ key, label, hint }) => (
          <div key={key} className="slider-row">
            <div className="slider-header">
              <strong>{label}</strong>
              <span className="badge-num">{priorities[key].toFixed(2)}</span>
            </div>
            <small className="hint">{hint}</small>
            <input
              type="range" min={0} max={1} step={0.05} value={priorities[key]}
              onChange={(e) => setPriorities({ ...priorities, [key]: parseFloat(e.target.value) })}
            />
          </div>
        ))}
      </div>

      <div className="control-group">
        <h3>🛡️ Hard Guarantees (Constraints)</h3>
        <label className="inline-label">
          <span>Min bad-year net ($/ha)</span>
          <input
            type="number" placeholder="none" value={priorities.minBadYearUsd ?? ""}
            onChange={(e) => setPriorities({ ...priorities, minBadYearUsd: e.target.value === "" ? null : Number(e.target.value) })}
          />
        </label>
        <label className="inline-label">
          <span>Max water use (mm/season)</span>
          <input
            type="number" placeholder="none" value={priorities.maxWaterMm ?? ""}
            onChange={(e) => setPriorities({ ...priorities, maxWaterMm: e.target.value === "" ? null : Number(e.target.value) })}
          />
        </label>
        <label className="inline-label">
          <span>Max bare-fallow years</span>
          <select value={priorities.maxFallow} onChange={(e) => setPriorities({ ...priorities, maxFallow: Number(e.target.value) })}>
            <option value={0}>0 (no bare fallow)</option>
            <option value={1}>1 year max</option>
            <option value={2}>2 years max</option>
          </select>
        </label>
      </div>

      <div className="control-group">
        <h3>🌦️ Climate Shift Scenario</h3>
        <p className="hint">Test how rotations hold up under drier or warmer conditions.</p>
        <div className="slider-row">
          <div className="slider-header">
            <strong>Rainfall shift</strong>
            <span className="badge-num">{scenario.rainPct > 0 ? `+${scenario.rainPct}%` : `${scenario.rainPct}%`}</span>
          </div>
          <input
            type="range" min={-40} max={20} step={5} value={scenario.rainPct}
            onChange={(e) => setScenario({ ...scenario, rainPct: Number(e.target.value) })}
          />
        </div>
        <div className="slider-row">
          <div className="slider-header">
            <strong>Temperature shift</strong>
            <span className="badge-num">{scenario.tempC > 0 ? `+${scenario.tempC.toFixed(1)} °C` : `${scenario.tempC.toFixed(1)} °C`}</span>
          </div>
          <input
            type="range" min={-1} max={4} step={0.5} value={scenario.tempC}
            onChange={(e) => setScenario({ ...scenario, tempC: Number(e.target.value) })}
          />
        </div>
      </div>

      <div className="control-group">
        <h3>💲 Market & Cost Assumptions</h3>
        <p className="hint">Reference values are low-confidence global defaults. Adjust to test sensitivity.</p>
        <div className="slider-row">
          <div className="slider-header">
            <strong>Crop price multiplier</strong>
            <span className="badge-num">{Math.round(economics.priceScale * 100)}%</span>
          </div>
          <input
            type="range" min={0.5} max={1.5} step={0.05} value={economics.priceScale}
            onChange={(e) => setEconomics({ ...economics, priceScale: parseFloat(e.target.value) })}
          />
        </div>
        <div className="slider-row">
          <div className="slider-header">
            <strong>Input cost multiplier</strong>
            <span className="badge-num">{Math.round(economics.costScale * 100)}%</span>
          </div>
          <input
            type="range" min={0.5} max={1.5} step={0.05} value={economics.costScale}
            onChange={(e) => setEconomics({ ...economics, costScale: parseFloat(e.target.value) })}
          />
        </div>
        <label className="inline-label">
          <span>Fertilizer N price ($/kg N)</span>
          <input
            type="number" step={0.1} min={0} value={economics.nPriceUsdKg}
            onChange={(e) => setEconomics({ ...economics, nPriceUsdKg: Math.max(0, Number(e.target.value)) })}
          />
        </label>
      </div>
    </div>
  );
}

