import { useEffect, useMemo, useState } from "react";
import { ControlsPanel } from "./components/ControlsPanel";
import { EvidencePanel } from "./components/EvidencePanel";
import { MapView } from "./components/MapView";
import { Results } from "./components/Results";
import { DEFAULT_EXISTING, FALLBACK_EXISTING, loadProfile, loadStatic, nearestCell, type StaticData } from "./data";
import { DEFAULT_ECONOMICS, DEFAULT_PRIORITIES, DEFAULT_SCENARIO } from "./engine/core";
import { evaluate } from "./engine/evaluate";
import type { Economics, Priorities, Scenario, SiteProfile } from "./types";

export function App() {
  const [data, setData] = useState<StaticData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [profile, setProfile] = useState<SiteProfile | null>(null);
  const [message, setMessage] = useState<string>("Click a pilot area on the map to begin.");
  const [scenario, setScenario] = useState<Scenario>(DEFAULT_SCENARIO);
  const [economics, setEconomics] = useState<Economics>(DEFAULT_ECONOMICS);
  const [priorities, setPriorities] = useState<Priorities>(DEFAULT_PRIORITIES);
  const [existing, setExisting] = useState<string[]>(FALLBACK_EXISTING);
  const [language, setLanguage] = useState("English");

  useEffect(() => { loadStatic().then(setData).catch((e) => setError(String(e))); }, []);

  const select = async (lat: number, lon: number) => {
    if (!data) return;
    const hit = nearestCell(data.cells, lat, lon);
    if (!hit) { setMessage("No precomputed data within 80 km of that point yet. Pick one of the highlighted pilot areas."); return; }
    setMessage(`Loading ${hit.cell.cell_id} (${hit.km.toFixed(0)} km from your click)…`);
    const p = await loadProfile(hit.cell.cell_id);
    setProfile(p);
    setExisting(DEFAULT_EXISTING[p.location.region_id] ?? FALLBACK_EXISTING);
    setMessage(`Showing ${data.regions[p.location.region_id]?.name ?? p.location.region_id} · data cell ${p.cell_id}`);
  };

  const evaluation = useMemo(() => {
    if (!data || !profile) return null;
    return evaluate({ profile, crops: data.crops, rules: data.rules, references: data.references, scenario, economics, priorities, existing });
  }, [data, profile, scenario, economics, priorities, existing]);

  if (error) return <div className="fatal">Could not load data: {error}</div>;
  if (!data) return <div className="fatal">Loading…</div>;

  return (
    <div className="app">
      <header>
        <h1>🌾 Rotation Advisor <small>Gradient Descent Farmers · NASA Space Apps · Field Shift</small></h1>
        <p className="disclaimer">A decision-support tool: it highlights patterns and possibilities, it does <b>not</b> replace your judgment or local agricultural experts.</p>
      </header>
      <div className="layout">
        <aside>
          <ControlsPanel data={data} scenario={scenario} setScenario={setScenario} economics={economics} setEconomics={setEconomics}
            priorities={priorities} setPriorities={setPriorities} existing={existing} setExisting={setExisting} language={language} setLanguage={setLanguage} />
        </aside>
        <main>
          <section className="card">
            <MapView data={data} selected={profile} onSelect={select} />
            <p className="status">{message}</p>
          </section>
          {profile && <EvidencePanel profile={profile} />}
          {profile && evaluation && (
            <Results evaluation={evaluation} data={data} scenario={scenario} language={language} nYears={evaluation.nYears} />
          )}
        </main>
      </div>
    </div>
  );
}

