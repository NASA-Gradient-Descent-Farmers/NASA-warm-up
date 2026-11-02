"""What NASA satellites observe in each municipality's farmland, by calendar month.

- MODIS NDVI (MOD13C2 v061, 0.05°, 2003-2025): greenness of cropland, weighted by the MCD12C1 cropland
  share within 15 km of the municipality point. It shows when fields are typically green or bare, which the
  tool compares with the crop calendar it assumes.
- SMAP root-zone soil moisture (SPL4SMGP v008, 0-100 cm, 9 km, 2015-2025): median by month, and the
  municipality's own dry and wet references (5th and 95th percentiles of daily values). The relative wetness
  at sowing tells how much stored water a crop sown on residual moisture can count on.

Both cubes are the caches written by src/yield_panel (gridded.fetch_ndvi, fetch_cropland, smap_years).

    python -m src.rotations.observed        # writes data/rotations/observed_{municipal,district}.parquet
"""

from pathlib import Path

import numpy as np
import pandas as pd

from src.yield_panel import gridded, weather

from . import climate, siap_stats

NDVI_FILE = Path("data/modis_ndvi/mod13c2_200301_202512_14_33_-117_-86.npz")
CROPLAND_FILE = Path("data/modis_landcover/mcd12c1_2015_14_33_-117_-86.npz")
SMAP_DIR = Path("data/smap_box")
SMAP_BOX = "14_33_-117_-86"
NDVI_RADIUS_KM, SMAP_RADIUS_KM = 15, 10


def ndvi_monthly(points):
    z = np.load(NDVI_FILE)
    crop = np.load(CROPLAND_FILE)
    months = pd.to_datetime(z["months"])
    cube, used = gridded.sample(z["ndvi"], z["lat"], z["lon"], points, NDVI_RADIUS_KM, weights=crop["cropland"])
    frame = pd.DataFrame(cube, index=months)
    by = frame.groupby(frame.index.month)
    return by.median(), by.quantile(0.2), by.quantile(0.8), used


def smap_monthly(points):
    months, daily_all = [], []
    for path in sorted(SMAP_DIR.glob(f"[12][0-9][0-9][0-9]_{SMAP_BOX}.npz")):    # skip the grid file
        z = np.load(path)
        cube, _ = gridded.sample(z["rootzone"], z["lat"], z["lon"], points, SMAP_RADIUS_KM)
        days = pd.to_datetime(z["days"])
        daily = pd.DataFrame(cube, index=days)
        daily_all.append(daily)
        months.append(daily.groupby([daily.index.year, daily.index.month]).mean())
    if not daily_all:
        return None
    daily = pd.concat(daily_all)
    monthly = pd.concat(months)
    by_month = monthly.groupby(level=1)
    return by_month.median(), daily.quantile(0.05), daily.quantile(0.95)


def municipal_table():
    mun = weather.load_municipalities()
    points = list(zip(mun["lat"], mun["lon"]))
    ndvi, ndvi_p20, ndvi_p80, used = ndvi_monthly(points)
    rows = []
    smap = smap_monthly(points)
    for k, m in enumerate(mun.itertuples(index=False)):
        for month in range(1, 13):
            row = {"state_id": m.state_id, "mun_id": m.mun_id, "month": month,
                   "ndvi": ndvi.loc[month, k], "ndvi_p20": ndvi_p20.loc[month, k], "ndvi_p80": ndvi_p80.loc[month, k],
                   "ndvi_cropland_weighted": bool(used[k])}
            if smap is not None:
                med, dry, wet = smap
                row.update({"smap_rootzone": med.loc[month, k], "smap_dry": dry[k], "smap_wet": wet[k]})
            rows.append(row)
    out = pd.DataFrame(rows)
    if "smap_rootzone" in out:
        span = (out["smap_wet"] - out["smap_dry"]).where(lambda s: s > 0.01)
        out["smap_relative"] = ((out["smap_rootzone"] - out["smap_dry"]) / span).clip(0, 1)
    return out


def district_table(municipal):
    districts, weights = siap_stats.load_districts(), climate.crop_area_weights()
    m = municipal.merge(districts[["state_id", "mun_id", "ddr"]], on=["state_id", "mun_id"]).merge(
        weights, on=["state_id", "mun_id"], how="left")
    m["weight"] = m["weight"].fillna(0) + 1.0
    cols = [c for c in ["ndvi", "ndvi_p20", "ndvi_p80", "smap_rootzone", "smap_relative"] if c in m]

    def avg(g):
        out = {}
        for c in cols:
            ok = g[c].notna()
            out[c] = np.average(g.loc[ok, c], weights=g.loc[ok, "weight"]) if ok.any() else np.nan
        return pd.Series(out)

    return m.groupby(["state_id", "ddr", "month"]).apply(avg, include_groups=False).reset_index()


def build(out=siap_stats.OUT):
    out = Path(out)
    municipal = municipal_table()
    municipal.to_parquet(out / "observed_municipal.parquet", index=False)
    district = district_table(municipal)
    district.to_parquet(out / "observed_district.parquet", index=False)
    print(f"{municipal[['state_id', 'mun_id']].drop_duplicates().shape[0]} municipalities, "
          f"{district[['state_id', 'ddr']].drop_duplicates().shape[0]} districts")
    return municipal, district


def load(level="district"):
    return siap_stats.read(f"observed_{level}")


# --- Reading the observations ------------------------------------------------------------------------

def low_green_months(observed):
    """Months whose median NDVI is in the lowest quarter of the year's range: fields typically bare or dry."""
    ndvi = observed.sort_values("month")["ndvi"].to_numpy()
    if not np.isfinite(ndvi).any():
        return [], []
    lo, hi = np.nanmin(ndvi), np.nanmax(ndvi)
    rel = (ndvi - lo) / max(hi - lo, 1e-6)
    return [m + 1 for m in range(12) if rel[m] <= 0.25], [m + 1 for m in range(12) if rel[m] >= 0.75]


def relative_moisture(observed, month):
    """SMAP relative wetness (0 = the municipality's dry reference, 1 = its wet reference) in a month."""
    if observed is None or "smap_relative" not in observed:
        return None
    row = observed[observed["month"] == month]
    value = float(row["smap_relative"].iloc[0]) if len(row) else np.nan
    return value if np.isfinite(value) else None


if __name__ == "__main__":
    build()
