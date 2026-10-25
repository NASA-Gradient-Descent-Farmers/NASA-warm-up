"""Pre-season planning model: what can be said about the coming rainfed season by the end of April?

Every feature is known by April 30 of the season's year, before rainfed sowing (May-July):

| Group | Features | Source |
|---|---|---|
| `ocean` | ONI (Dec-Feb, Feb-Apr), ONI tendency, previous Jul-Sep ONI, Nino 3.4 (April), tropical North Atlantic and PDO (Feb-Apr means) | NOAA CPC / PSL |
| `ocean_x_place` | the ocean indices times standardized latitude, longitude, altitude and typical season rain, so teleconnections can differ by region | derived |
| `preseason` | Nov-Apr rain, Mar-Apr rain, Mar-Apr Tmax / Tmin / humidity | NASA POWER |
| `last_season` | the previous season's weather (rain totals, canicula rain, dry spell, onset, late rain) | NASA POWER |
| `last_outcome` | the previous season's yield and failure rate (part persistence, part SIAP reporting habits) | SIAP |
| `preseason_ndvi` | Mar-Apr NDVI and EVI (2003 on) | MODIS |

The target is still the season's yield or failure rate, scored against the same average + trend bar.
"""

from pathlib import Path

import numpy as np
import pandas as pd

from src.data_ingestion.common import DATA_DIR
from src.yield_panel import models as pm

INDEX_DIR = DATA_DIR / "climate_indices"
INDEX_URLS = {
    "oni.ascii.txt": "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt",
    "nina34.anom.data": "https://psl.noaa.gov/data/correlation/nina34.anom.data",
    "tna.data": "https://psl.noaa.gov/data/correlation/tna.data",
    "amon.us.data": "https://psl.noaa.gov/data/correlation/amon.us.data",
    "pdo.data": "https://psl.noaa.gov/data/correlation/pdo.data",
}
UNIT = pm.UNIT


# --- Ocean indices ---------------------------------------------------------------------------------

def download_indices(directory=INDEX_DIR):
    import requests

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for name, url in INDEX_URLS.items():
        path = directory / name
        if not path.exists():
            r = requests.get(url, timeout=60)
            r.raise_for_status()
            path.write_bytes(r.content)
    return directory


def read_psl(path):
    """PSL monthly table (first line 'start end', then 'year m1..m12', then a missing value line) -> Series."""
    lines = Path(path).read_text().splitlines()
    first, last = (int(v) for v in lines[0].split()[:2])
    rows = {}
    for line in lines[1:]:
        parts = line.split()
        if len(parts) == 13 and parts[0].isdigit() and first <= int(parts[0]) <= last:
            rows[int(parts[0])] = [float(v) for v in parts[1:]]
    missing = float(lines[len(rows) + 1].split()[0])
    s = pd.DataFrame.from_dict(rows, orient="index", columns=range(1, 13)).stack()
    s.index = pd.to_datetime([f"{y}-{m:02d}-01" for y, m in s.index])
    return s.where(s > missing + 1e-6).sort_index()


def read_oni(path):
    """CPC ONI table -> DataFrame (season, year, anom)."""
    t = pd.read_csv(path, sep=r"\s+")
    return t.rename(columns={"SEAS": "season", "YR": "year", "ANOM": "anom"})[["season", "year", "anom"]]


def index_features(directory=INDEX_DIR):
    """One row per year with ocean indices known by the end of April."""
    directory = download_indices(directory)
    oni = read_oni(directory / "oni.ascii.txt")
    get = lambda season, shift=0: oni[oni.season == season].set_index("year")["anom"].rename(lambda y: y + shift)
    out = pd.DataFrame({
        "oni_djf": get("DJF"),
        "oni_fma": get("FMA"),
        "oni_ndj": get("NDJ", shift=1),          # Nov(t-1)-Jan(t), labelled with year t
        "oni_jas_prev": get("JAS", shift=1),     # last season's ENSO
    })
    out["oni_tendency"] = out["oni_fma"] - out["oni_ndj"]
    months = lambda s, ms: s[s.index.month.isin(ms)].groupby(s[s.index.month.isin(ms)].index.year).mean()
    nino = read_psl(directory / "nina34.anom.data")
    out["nino34_apr"] = nino[nino.index.month == 4].groupby(nino[nino.index.month == 4].index.year).mean()
    for name, file in [("tna", "tna.data"), ("amo", "amon.us.data"), ("pdo", "pdo.data")]:
        out[f"{name}_fma"] = months(read_psl(directory / file), [2, 3, 4])
    out.index.name = "year"
    return out.drop(columns="oni_ndj").reset_index()


# AMO is left out: the PSL series lags by years (missing from 2022 in October 2026).
OCEAN = ["oni_djf", "oni_fma", "oni_tendency", "oni_jas_prev", "nino34_apr", "tna_fma", "pdo_fma"]


# --- Local pre-season and last-season features ---------------------------------------------------

def preseason_from_daily(daily, years):
    """Mar-Apr weather from a daily POWER frame (Nov-Apr rain comes from weather.season_features)."""
    rows = []
    for year in years:
        w = daily[(daily.index >= pd.Timestamp(year, 3, 1)) & (daily.index <= pd.Timestamp(year, 4, 30))]
        if len(w) < 55:
            continue
        rows.append({"year": year, "rain_mar_apr_mm": w["PRECTOTCORR"].sum(), "tmax_mar_apr_c": w["T2M_MAX"].mean(),
                     "tmin_mar_apr_c": w["T2M_MIN"].mean(), "rh_mar_apr_pct": w["RH2M"].mean()})
    return pd.DataFrame(rows)


PRESEASON = ["rain_pre_season_mm", "rain_mar_apr_mm", "tmax_mar_apr_c", "tmin_mar_apr_c", "rh_mar_apr_pct"]
LAST_SEASON_SOURCE = ["rain_season_mm", "rain_jul_aug_mm", "rain_sep_oct_mm", "longest_dry_spell_days", "onset_doy"]
LAST_SEASON = [f"{c}_prev" for c in LAST_SEASON_SOURCE]
LAST_OUTCOME = ["yield_t_ha_prev", "failure_rate_prev"]
PRESEASON_NDVI = ["ndvi_pre_season", "evi_pre_season"]
PLACE = ["lat", "lon", "alt_m", "clim_rain_season_mm"]


def add_lags(panel, columns, keys=("crop", *UNIT)):
    """Previous calendar year's values, only when that year exists for the same unit (no gap bridging)."""
    keys = list(keys)
    prev = panel[[*keys, "year", *columns]].copy()
    prev["year"] = prev["year"] + 1
    return panel.merge(prev.rename(columns={c: f"{c}_prev" for c in columns}), on=[*keys, "year"], how="left")


def add_interactions(panel, indices=OCEAN, place=PLACE):
    """Ocean index x standardized place columns (teleconnections differ across Mexico)."""
    out = panel.copy()
    names = []
    for p in place:
        z = (out[p] - out[p].mean()) / out[p].std()
        for i in indices:
            out[f"{i}_x_{p}"] = out[i] * z
            names.append(f"{i}_x_{p}")
    return out, names


def feature_groups(columns):
    have = lambda cols: [c for c in cols if c in columns]
    inter = [c for c in columns if "_x_" in c]
    return {
        "ocean": have(OCEAN),
        "ocean_x_place": have(OCEAN) + inter,
        "preseason": have(PRESEASON),
        "last_season": have(LAST_SEASON),
        "last_outcome": have(LAST_OUTCOME),
        "preseason_ndvi": have(PRESEASON_NDVI),
    }


def planning_sets(columns, with_ndvi=True):
    """Feature sets for the ablation: each group alone, the weather-only combination, everything."""
    g = feature_groups(columns)
    sets = {
        "ocean": g["ocean"],
        "ocean x place": g["ocean_x_place"],
        "preseason (local)": g["preseason"],
        "last season weather": g["last_season"],
        "last season outcome": g["last_outcome"],
        "ocean x place + preseason + last season weather": g["ocean_x_place"] + g["preseason"] + g["last_season"],
        "all (incl. last outcome)": g["ocean_x_place"] + g["preseason"] + g["last_season"] + g["last_outcome"],
    }
    if with_ndvi and g["preseason_ndvi"]:
        sets["all + preseason ndvi"] = sets["all (incl. last outcome)"] + g["preseason_ndvi"]
    return {k: (v, []) for k, v in sets.items() if v}


def conditional_outlook(model, history, target, unit_rows, residuals, threshold=None):
    """Predicted value for upcoming unit rows plus an empirical distribution: prediction + past residuals.

    `residuals` are out-of-sample errors of the same model (e.g. from the rolling evaluation), so the spread
    reflects how wrong the model has actually been. Returns median, 10th/90th percentiles and, if a
    threshold is given, the share of outcomes above it (e.g. failure > 0.3).
    """
    pred = model.predict(unit_rows)
    rows = []
    for p in pred:
        sims = pm.clip_target(target, p + residuals)
        row = {"prediction": float(pm.clip_target(target, np.array([p]))[0]), "p10": float(np.percentile(sims, 10)),
               "median": float(np.median(sims)), "p90": float(np.percentile(sims, 90))}
        if threshold is not None:
            row[f"p_above_{threshold}"] = float((sims > threshold).mean())
        rows.append(row)
    return pd.DataFrame(rows, index=unit_rows.index)
