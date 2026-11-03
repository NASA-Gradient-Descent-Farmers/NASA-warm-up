import {
  Bar, CartesianGrid, ComposedChart, Legend, Line, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { MONTHS } from "../engine/core";
import type { SiteProfile } from "../types";

export function EvidencePanel({ profile }: { profile: SiteProfile }) {
  const c = profile.climate_monthly;
  const v = profile.vegetation;
  const rows = MONTHS.map((m, i) => ({
    month: m,
    rain: c.rain_mm[i] ?? 0,
    et0: c.et0_mm[i] ?? 0,
    tmean: c.tmean_c[i],
    tmin: c.tmin_c[i],
    tmax: c.tmax_c[i],
    frostProb: c.frost_prob[i] !== null ? Math.round((c.frost_prob[i] as number) * 100) : 0,
    drySpell: c.dry_spell_days[i] ?? 0,
    ndvi: v.ndvi_monthly[i],
    ndviP10: v.ndvi_p10_monthly[i],
  }));

  const bareNames = v.bare_months.map((m) => MONTHS[m - 1]);
  const tempCorr = profile.provenance["temperature_correction_c"] as number | undefined;

  return (
    <section className="card evidence-panel">
      <div className="section-header">
        <div>
          <h2>🛰️ NASA Earth Observation Evidence — {profile.cell_id}</h2>
          <p className="subtitle">
            Lat {profile.location.lat.toFixed(2)}°, Lon {profile.location.lon.toFixed(2)}° ·{" "}
            Elevation {profile.location.elevation_m !== null ? `${profile.location.elevation_m} m` : "n/a"} ·{" "}
            Slope {profile.location.slope_deg !== null ? `${profile.location.slope_deg}°` : "n/a"} ·{" "}
            Aridity index (Rain/ET₀): {profile.water.aridity_index ?? "n/a"}
            {tempCorr !== undefined && ` · SRTM lapse-rate shift: ${tempCorr > 0 ? "+" : ""}${tempCorr} °C`}
          </p>
        </div>
        <span className={`tier-badge tier-${profile.location.data_tier}`}>
          Data Tier {profile.location.data_tier}
        </span>
      </div>

      <div className="availability-strip">
        {Object.entries(profile.availability).map(([layer, info]) => (
          <span key={layer} className={`avail-pill avail-${info.status}`} title={info.reason ?? ""}>
            <strong>{layer.replace("_", " ")}:</strong> {info.status}
          </span>
        ))}
      </div>

      <div className="charts-grid">
        <div className="chart-box">
          <h4>🌧️ Water Balance & Temperature (NASA POWER + SRTM)</h4>
          <p className="hint">
            Comparing monthly rainfall against reference evapotranspiration (ET₀, water atmosphere demands). Months where ET₀ exceeds rain require stored soil moisture or drought-hardy crops.
          </p>
          <ResponsiveContainer width="100%" height={220}>
            <ComposedChart data={rows}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="month" />
              <YAxis yAxisId="mm" label={{ value: "mm", angle: -90, position: "insideLeft" }} />
              <YAxis yAxisId="c" orientation="right" label={{ value: "°C", angle: 90, position: "insideRight" }} />
              <Tooltip />
              <Legend />
              <Bar yAxisId="mm" dataKey="rain" name="Rain (mm)" fill="#1976d2" />
              <Line yAxisId="mm" type="monotone" dataKey="et0" name="Ref. ET₀ (mm)" stroke="#ef6c00" strokeWidth={2} />
              <Line yAxisId="c" type="monotone" dataKey="tmean" name="Mean Temp (°C)" stroke="#2e7d32" strokeWidth={2} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>

        <div className="chart-box">
          <h4>🌿 Satellite Greenness & Bare-Field Windows (MODIS NDVI)</h4>
          <p className="hint">
            NDVI measures live green cover (250 m resolution). Months below 0.25 indicate typically bare soil:{" "}
            <b>{bareNames.length ? bareNames.join(", ") : "none detected"}</b>. Cover crops or winter grains can protect soil during bare windows.
          </p>
          <ResponsiveContainer width="100%" height={220}>
            <ComposedChart data={rows}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="month" />
              <YAxis domain={[0, 0.9]} />
              <Tooltip />
              <Legend />
              {v.bare_months.map((m) => (
                <ReferenceArea key={m} x1={MONTHS[m - 1]} x2={MONTHS[m - 1]} fill="#ffccbc" fillOpacity={0.45} />
              ))}
              <Line type="monotone" dataKey="ndvi" name="Mean NDVI" stroke="#2e7d32" strokeWidth={2.5} />
              <Line type="monotone" dataKey="ndviP10" name="Bad-year NDVI (P10)" stroke="#c62828" strokeDasharray="4 4" />
            </ComposedChart>
          </ResponsiveContainer>
        </div>

        <div className="chart-box">
          <h4>❄️ Frost Risk & Longest Dry Spell by Month</h4>
          <p className="hint">
            Frost probability (% of days with Tmin ≤ 0 °C after SRTM elevation correction) and longest dry run (&lt;1 mm/day). Helps avoid sowing frost-sensitive crops too early or late.
          </p>
          <ResponsiveContainer width="100%" height={200}>
            <ComposedChart data={rows}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="month" />
              <YAxis yAxisId="pct" label={{ value: "Frost %", angle: -90, position: "insideLeft" }} />
              <YAxis yAxisId="days" orientation="right" label={{ value: "Dry days", angle: 90, position: "insideRight" }} />
              <Tooltip />
              <Legend />
              <Bar yAxisId="pct" dataKey="frostProb" name="Frost risk (%)" fill="#5c6bc0" />
              <Line yAxisId="days" type="monotone" dataKey="drySpell" name="Longest dry spell (days)" stroke="#d84315" strokeWidth={2} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>

        <div className="chart-box soil-summary">
          <h4>🪨 Local Soil & Multi-Decade Trends</h4>
          <ul className="metrics-list">
            <li>
              <strong>Available water capacity (AWC):</strong>{" "}
              {profile.soil.awc_mm !== null ? `${profile.soil.awc_mm} mm (0–100 cm, texture pedotransfer)` : "missing (using 120 mm regional fallback)"}
            </li>
            <li>
              <strong>Soil organic carbon (0–30 cm):</strong>{" "}
              {profile.soil.soc_g_kg !== null ? `${profile.soil.soc_g_kg} g/kg` : "missing in SoilGrids"}
            </li>
            <li>
              <strong>Texture (clay / sand) & pH:</strong>{" "}
              {profile.soil.clay_pct !== null ? `${profile.soil.clay_pct}% clay, ${profile.soil.sand_pct}% sand, pH ${profile.soil.ph}` : "missing (SoilGrids unavailable)"}
            </li>
            {profile.climate_trend?.tmean_c_per_decade !== undefined && (
              <li>
                <strong>Observed POWER trend ({profile.climate_trend.years?.[0]}–{profile.climate_trend.years?.[1]}):</strong>{" "}
                {profile.climate_trend.tmean_c_per_decade > 0 ? "+" : ""}
                {profile.climate_trend.tmean_c_per_decade} °C/decade ·{" "}
                {profile.climate_trend.rain_pct_per_decade && profile.climate_trend.rain_pct_per_decade > 0 ? "+" : ""}
                {profile.climate_trend.rain_pct_per_decade}% rain/decade
              </li>
            )}
          </ul>
          <p className="hint">
            <b>Note on satellite vs. ground data:</b> Satellite grids (9–50 km) capture regional patterns, not single fields. Combine with a local soil test and farm records before changing rotations.
          </p>
        </div>
      </div>
    </section>
  );
}

