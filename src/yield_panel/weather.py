"""Municipality coordinates, NASA POWER weather per grid cell, and season-level features.

Many municipalities share one POWER grid cell (~55 x 65 km), so weather is requested once per cell,
not once per municipality. POWER meteorology comes from MERRA-2, whose native grid has cell centres
every 0.5 deg of latitude from -90 and every 0.625 deg of longitude from -180. A point request returns
the cell containing the point, so requesting the snapped centre gives the same values.
`check_snapping()` verifies this for a few municipalities against the live API.
"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from src.data_ingestion import power
from src.data_ingestion.common import DATA_DIR

MUNICIPALITIES = Path(__file__).with_name("municipalities.csv")
CACHE_DIR = DATA_DIR / "power_cells"

LAT_STEP, LON_STEP = 0.5, 0.625

PARAMETERS = ["T2M", "T2M_MAX", "T2M_MIN", "PRECTOTCORR", "RH2M", "ALLSKY_SFC_SW_DWN"]


def load_municipalities(path=MUNICIPALITIES):
    """INEGI municipalities with a representative farmland point (median of rural localities)."""
    return pd.read_csv(path)


def snap(lat, lon):
    """Centre of the MERRA-2 / POWER meteorology cell containing (lat, lon)."""
    lat_c = np.round(np.asarray(lat) / LAT_STEP) * LAT_STEP
    lon_c = np.round((np.asarray(lon) + 180) / LON_STEP) * LON_STEP - 180
    return np.round(lat_c, 3), np.round(lon_c, 3)


def assign_cells(municipalities):
    lat_c, lon_c = snap(municipalities["lat"], municipalities["lon"])
    out = municipalities.copy()
    out["cell_lat"], out["cell_lon"] = lat_c, lon_c
    out["cell_id"] = [f"{a:+08.3f}_{b:+09.3f}" for a, b in zip(lat_c, lon_c)]
    return out


def fetch_cell(cell_lat, cell_lon, start_year, end_year, directory=CACHE_DIR):
    """Daily POWER data for one cell, cached as CSV."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{cell_lat:+08.3f}_{cell_lon:+09.3f}_{start_year}_{end_year}.csv"
    if path.exists():
        return pd.read_csv(path, index_col="date", parse_dates=True)
    payload = power.fetch_daily_point(cell_lat, cell_lon, f"{start_year}0101", f"{end_year}1231",
                                      parameters=PARAMETERS)
    daily = power.to_dataframe(payload)
    daily.to_csv(path)
    return daily


def check_snapping(municipalities, n=3, year=2020, seed=0):
    """Compare POWER at the municipality point and at its snapped cell centre for a few municipalities."""
    sample = assign_cells(municipalities).sample(n, random_state=seed)
    rows = []
    for _, m in sample.iterrows():
        at_point = power.to_dataframe(power.fetch_daily_point(m.lat, m.lon, f"{year}0101", f"{year}1231",
                                                              parameters=["T2M", "PRECTOTCORR"]))
        at_cell = power.to_dataframe(power.fetch_daily_point(m.cell_lat, m.cell_lon, f"{year}0101", f"{year}1231",
                                                             parameters=["T2M", "PRECTOTCORR"]))
        rows.append({"municipality": m.municipality, "lat": m.lat, "lon": m.lon, "cell": m.cell_id,
                     "max_abs_diff": float((at_point - at_cell).abs().max().max())})
    return pd.DataFrame(rows)


# --- Season features ----------------------------------------------------------------------------

def longest_run(mask):
    best = run = 0
    for value in mask:
        run = run + 1 if value else 0
        best = max(best, run)
    return best


def rain_onset_doy(rain, start, window=5, threshold=20.0, max_delay=75):
    """Day of year of the first day from `start` with >= threshold mm over `window` days (rainfed sowing rule).

    Capped at start + max_delay days when the rains never arrive, so a missing onset reads as very late.
    """
    rolling = rain.rolling(window, min_periods=window).sum()
    window_end = start + pd.Timedelta(days=max_delay)
    hits = rolling[(rolling.index >= start) & (rolling.index <= window_end) & (rolling >= threshold)]
    return (hits.index[0] if len(hits) else window_end).dayofyear


def season_features(daily, years, season=(5, 10)):
    """One row per year of features for a spring-summer rainfed season (default May-October).

    Every feature uses only weather up to the end of that season.
    """
    rain = daily["PRECTOTCORR"]
    rows = []
    for year in years:
        s = daily[(daily.index >= pd.Timestamp(year, season[0], 1)) & (daily.index <= pd.Timestamp(year, season[1], 31))]
        if len(s) < 150:
            continue
        pre = daily[(daily.index >= pd.Timestamp(year - 1, 11, 1)) & (daily.index < pd.Timestamp(year, season[0], 1))]
        months = s.index.month
        teff = (s["T2M_MAX"].clip(upper=30) + s["T2M_MIN"].clip(lower=10)) / 2 - 10
        late = daily[(daily.index >= pd.Timestamp(year, 9, 1)) & (daily.index <= pd.Timestamp(year, 11, 30))]
        rows.append({
            "year": year,
            "rain_season_mm": s["PRECTOTCORR"].sum(),
            "rain_jun_mm": s.loc[months == 6, "PRECTOTCORR"].sum(),
            "rain_jul_aug_mm": s.loc[(months == 7) | (months == 8), "PRECTOTCORR"].sum(),
            "rain_sep_oct_mm": s.loc[(months == 9) | (months == 10), "PRECTOTCORR"].sum(),
            "rain_pre_season_mm": pre["PRECTOTCORR"].sum() if len(pre) > 150 else np.nan,
            "wet_days": int((s["PRECTOTCORR"] >= 1).sum()),
            "max_daily_rain_mm": s["PRECTOTCORR"].max(),
            "longest_dry_spell_days": longest_run(s["PRECTOTCORR"] < 1.0),
            "onset_doy": rain_onset_doy(rain, pd.Timestamp(year, season[0], 1)),
            "gdd_10_30": teff.clip(lower=0).sum(),
            "tmax_season_c": s["T2M_MAX"].mean(),
            "tmin_season_c": s["T2M_MIN"].mean(),
            "heat_days_35": int((s["T2M_MAX"] >= 35).sum()),
            "frost_nights_sep_nov": int((late["T2M_MIN"] <= 0).sum()),
            "rh_season_pct": s["RH2M"].mean(),
            "radiation_season_mj_m2": s["ALLSKY_SFC_SW_DWN"].sum(),
        })
    return pd.DataFrame(rows)


WEATHER_FEATURES = [
    "rain_season_mm", "rain_jun_mm", "rain_jul_aug_mm", "rain_sep_oct_mm", "rain_pre_season_mm", "wet_days",
    "max_daily_rain_mm", "longest_dry_spell_days", "onset_doy", "gdd_10_30", "tmax_season_c", "tmin_season_c",
    "heat_days_35", "frost_nights_sep_nov", "rh_season_pct", "radiation_season_mj_m2",
]


def build_weather(municipalities, years, workers=4, directory=CACHE_DIR):
    """Season features for every municipality and year, fetching each POWER cell once.

    Returns (features by municipality-year, the municipality table with cell ids, failed cells).
    POWER asks clients not to hammer the API, so keep `workers` small.
    """
    years = list(years)
    start, end = min(years) - 1, max(years)  # previous Nov-Apr feeds rain_pre_season_mm
    munis = assign_cells(municipalities)
    cells = munis.drop_duplicates("cell_id")[["cell_id", "cell_lat", "cell_lon"]]
    print(f"{len(munis)} municipalities -> {len(cells)} POWER cells", flush=True)

    def one(cell):
        try:
            daily = fetch_cell(cell.cell_lat, cell.cell_lon, start, end, directory)
            feats = season_features(daily, years)
            feats["cell_id"] = cell.cell_id
            return feats, None
        except Exception as exc:  # keep going; report failed cells at the end
            return None, (cell.cell_id, repr(exc))

    results, failed = [], []
    with ThreadPoolExecutor(workers) as pool:
        for i, (feats, error) in enumerate(pool.map(one, cells.itertuples()), start=1):
            (results.append(feats) if error is None else failed.append(error))
            if i % 25 == 0 or i == len(cells):
                print(f"  {i}/{len(cells)} cells", flush=True)
    by_cell = pd.concat(results, ignore_index=True) if results else pd.DataFrame(columns=["cell_id", "year"])
    weather = munis[["state_id", "mun_id", "cell_id"]].merge(by_cell, on="cell_id", how="inner")
    return weather, munis, failed


def build_soils(municipalities):
    """GLDAS texture, sand/silt/clay and porosity at each municipality point (no login needed)."""
    from src.data_ingestion import gldas_soils

    gldas_soils.download()
    sites = [(f"{r.state_id}_{r.mun_id}", r.lat, r.lon) for r in municipalities.itertuples()]
    soils = gldas_soils.extract_points(sites).reset_index()
    ids = soils["site"].str.split("_", expand=True).astype(int)
    soils["state_id"], soils["mun_id"] = ids[0], ids[1]
    return soils[["state_id", "mun_id", "texture_class", "sand", "silt", "clay", "porosity"]]
