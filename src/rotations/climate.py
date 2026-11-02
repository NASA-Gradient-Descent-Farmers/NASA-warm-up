"""Monthly climate normals (2001-2025) per municipality and district from NASA POWER daily data.

Per month: rain, reference evapotranspiration ET0 (FAO-56 Penman-Monteith), mean Tmin / Tmax, the share of
years with at least one night at or below 2 °C (2 m air temperature; ground frost is often a few degrees
colder than the air at 2 m, and POWER cells of ~55 x 65 km miss cold valley bottoms), and the mean number
of days at or above 35 °C.

POWER has no wind speed in our cache, so ET0 uses the FAO-56 default of 2 m/s (Allen et al. 1998, ch. 3).

    python -m src.rotations.climate        # writes data/rotations/climate_{municipal,district}[_years].parquet

Rain is bias-corrected per municipality with CHIRPS (see rain_correction) where the yield panel has CHIRPS.
"""

from pathlib import Path

import numpy as np
import pandas as pd

from src.yield_panel import siap, weather

from . import siap_stats

OUT = siap_stats.OUT
YEARS = (2001, 2025)
FROST_C = 2.0
HEAT_C = 35.0
WIND_MS = 2.0


def et0_penman_monteith(daily, lat_deg, elevation_m, wind=WIND_MS):
    """FAO-56 eq. 6 with daily Tmax, Tmin, RH2M (%) and all-sky shortwave (MJ m-2 d-1)."""
    tmax, tmin = daily["T2M_MAX"].to_numpy(float), daily["T2M_MIN"].to_numpy(float)
    tmean = (tmax + tmin) / 2
    rs = daily["ALLSKY_SFC_SW_DWN"].to_numpy(float)
    rh = daily["RH2M"].to_numpy(float)
    doy = daily.index.dayofyear.to_numpy()

    pressure = 101.3 * ((293 - 0.0065 * elevation_m) / 293) ** 5.26
    gamma = 0.000665 * pressure
    e_sat = lambda t: 0.6108 * np.exp(17.27 * t / (t + 237.3))
    es = (e_sat(tmax) + e_sat(tmin)) / 2
    ea = np.clip(rh / 100, 0, 1) * es
    delta = 4098 * e_sat(tmean) / (tmean + 237.3) ** 2

    phi = np.radians(lat_deg)
    dr = 1 + 0.033 * np.cos(2 * np.pi * doy / 365)
    decl = 0.409 * np.sin(2 * np.pi * doy / 365 - 1.39)
    ws = np.arccos(np.clip(-np.tan(phi) * np.tan(decl), -1, 1))
    ra = 24 * 60 / np.pi * 0.0820 * dr * (ws * np.sin(phi) * np.sin(decl) + np.cos(phi) * np.cos(decl) * np.sin(ws))
    rso = (0.75 + 2e-5 * elevation_m) * ra
    rns = 0.77 * rs
    ratio = np.clip(rs / np.where(rso > 0, rso, np.nan), 0.25, 1.0)
    rnl = 4.903e-9 * ((tmax + 273.16) ** 4 + (tmin + 273.16) ** 4) / 2 * (0.34 - 0.14 * np.sqrt(ea)) * (1.35 * ratio - 0.35)
    rn = rns - rnl
    et0 = (0.408 * delta * rn + gamma * 900 / (tmean + 273) * wind * (es - ea)) / (delta + gamma * (1 + 0.34 * wind))
    return pd.Series(np.maximum(et0, 0), index=daily.index)


def monthly_normals(daily, lat, elevation_m, years=YEARS):
    d = daily.loc[f"{years[0]}-01-01":f"{years[1]}-12-31"].copy()
    d["et0"] = et0_penman_monteith(d, lat, elevation_m)
    # A few days lack radiation: fill ET0 with that calendar month's mean so monthly sums stay comparable.
    d["et0"] = d["et0"].fillna(d.groupby(d.index.month)["et0"].transform("mean"))
    d["frost"] = d["T2M_MIN"] <= FROST_C
    d["heat"] = d["T2M_MAX"] >= HEAT_C
    by = d.groupby([d.index.year.rename("year"), d.index.month.rename("month")])
    per_year = by.agg(rain=("PRECTOTCORR", "sum"), et0=("et0", "sum"), tmin=("T2M_MIN", "mean"),
                      tmax=("T2M_MAX", "mean"), frost_nights=("frost", "sum"), heat_days=("heat", "sum"))
    per_year["frost_year"] = per_year["frost_nights"] > 0
    normals = per_year.groupby("month").agg(rain=("rain", "mean"), et0=("et0", "mean"), tmin=("tmin", "mean"),
                                            tmax=("tmax", "mean"), frost_prob=("frost_year", "mean"),
                                            frost_nights=("frost_nights", "mean"), heat_days=("heat_days", "mean"),
                                            rain_p20=("rain", lambda s: s.quantile(0.2)))
    return normals.reset_index(), per_year[["rain", "et0"]].reset_index()


def _cell_file(cell_id):
    for period in ("1981_2025", "2002_2025"):
        path = weather.CACHE_DIR / f"{cell_id}_{period}.csv"
        if path.exists():
            return path
    return None


def municipal_normals(municipalities=None):
    mun = weather.assign_cells(municipalities if municipalities is not None else weather.load_municipalities())
    cache = {}
    rows, yearly = [], []
    for m in mun.itertuples(index=False):
        path = _cell_file(m.cell_id)
        if path is None:
            continue
        if m.cell_id not in cache:
            cache[m.cell_id] = pd.read_csv(path, index_col="date", parse_dates=True)
        normals, per_year = monthly_normals(cache[m.cell_id], m.lat, m.alt_m if np.isfinite(m.alt_m) else 0.0)
        for frame, out in ((normals, rows), (per_year, yearly)):
            frame.insert(0, "mun_id", m.mun_id)
            frame.insert(0, "state_id", m.state_id)
            out.append(frame)
    return pd.concat(rows, ignore_index=True), pd.concat(yearly, ignore_index=True)


def crop_area_weights(years=range(2016, 2026)):
    """Mean annual-crop sown area per municipality (both cycles), the weight for district averages."""
    parts = []
    for year in years:
        f = siap.read_year(year)
        f = f[f["idciclo"].isin([1, 2])].assign(sembrada=lambda x: pd.to_numeric(x["sembrada"], errors="coerce"))
        parts.append(f.groupby(["idestado", "idmunicipio"])["sembrada"].sum())
    w = pd.concat(parts, axis=1).fillna(0).mean(axis=1).rename("weight").reset_index()
    return w.rename(columns={"idestado": "state_id", "idmunicipio": "mun_id"})


def district_normals(municipal, districts, weights, keys=("month",)):
    m = municipal.merge(districts[["state_id", "mun_id", "ddr"]], on=["state_id", "mun_id"]).merge(
        weights, on=["state_id", "mun_id"], how="left")
    m["weight"] = m["weight"].fillna(0) + 1.0   # every municipality counts a little
    cols = [c for c in ["rain", "et0", "tmin", "tmax", "frost_prob", "frost_nights", "heat_days", "rain_p20"] if c in m]
    out = m.groupby(["state_id", "ddr", *keys]).apply(
        lambda g: pd.Series(np.average(g[cols], axis=0, weights=g["weight"]), index=cols), include_groups=False)
    return out.reset_index()


CHIRPS = Path("data/yield_panel/chirps_municipal_1999_2025.csv")
POWER_FEATURES = Path("data/yield_panel/power_municipal_1982_2025.csv")
SEASON_MONTHS = range(5, 11)      # May-October, as in the yield panel's season features


def rain_correction(chirps=CHIRPS, power=POWER_FEATURES, years=YEARS):
    """Per-municipality CHIRPS / POWER mean rain ratios, May-Oct and Nov-Apr, clipped to [0.3, 3].

    POWER rain is MERRA-2 corrected precipitation on a ~55 x 65 km grid; CHIRPS blends satellite rain with
    station gauges at ~5 km. Over 2,211 municipalities the median ratio is ~1.0, but it is 0.6-0.85 in
    places such as the Valles Centrales of Oaxaca and Texcoco, where POWER puts more rain than the gauges.
    """
    c = pd.read_csv(chirps)
    p = pd.read_csv(power, usecols=["state_id", "mun_id", "year", "rain_season_mm", "rain_pre_season_mm"])
    m = c.merge(p, on=["state_id", "mun_id", "year"])
    m = m[m["year"].between(*years)]
    g = m.groupby(["state_id", "mun_id"])[["chirps_rain_season_mm", "rain_season_mm",
                                           "chirps_rain_pre_season_mm", "rain_pre_season_mm"]].mean()
    return pd.DataFrame({
        "ratio_season": (g["chirps_rain_season_mm"] / g["rain_season_mm"]).clip(0.3, 3),
        "ratio_off": (g["chirps_rain_pre_season_mm"] / g["rain_pre_season_mm"].where(g["rain_pre_season_mm"] > 20)).clip(0.3, 3),
    }).fillna(1.0).reset_index()


def apply_correction(frame, ratios):
    out = frame.merge(ratios, on=["state_id", "mun_id"], how="left")
    out["rain_corrected"] = out["ratio_season"].notna()
    in_season = out["month"].isin(SEASON_MONTHS)
    factor = np.where(in_season, out["ratio_season"].fillna(1.0), out["ratio_off"].fillna(1.0))
    for col in ("rain", "rain_p20"):
        if col in out:
            out[col] = out[col] * factor
    return out.drop(columns=["ratio_season", "ratio_off"])


def build(out=OUT):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    path, path_years = out / "power_municipal_normals.parquet", out / "power_municipal_years.parquet"
    if path.exists() and path_years.exists():
        municipal, yearly = pd.read_parquet(path), pd.read_parquet(path_years)
    else:
        municipal, yearly = municipal_normals()
        municipal.to_parquet(path, index=False)
        yearly.to_parquet(path_years, index=False)
    if CHIRPS.exists() and POWER_FEATURES.exists():
        ratios = rain_correction()
        municipal, yearly = apply_correction(municipal, ratios), apply_correction(yearly, ratios)
    municipal.to_parquet(out / "climate_municipal.parquet", index=False)
    yearly.to_parquet(out / "climate_municipal_years.parquet", index=False)
    districts, weights = siap_stats.load_districts(out), crop_area_weights()
    district = district_normals(municipal, districts, weights)
    district.to_parquet(out / "climate_district.parquet", index=False)
    district_normals(yearly, districts, weights, keys=("year", "month")).to_parquet(
        out / "climate_district_years.parquet", index=False)
    print(f"{municipal[['state_id', 'mun_id']].drop_duplicates().shape[0]} municipalities, "
          f"{district[['state_id', 'ddr']].drop_duplicates().shape[0]} districts")
    return municipal, district


def load(level="district", out=OUT, yearly=False):
    return siap_stats.read(f"climate_{level}{'_years' if yearly else ''}", out)


if __name__ == "__main__":
    build()
