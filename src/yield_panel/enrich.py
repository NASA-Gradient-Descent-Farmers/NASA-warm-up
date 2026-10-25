"""Add the extra gridded sources to a built panel.

Usage (from the repo root, after `python -m src.yield_panel.build`; needs EARTHDATA_TOKEN or ~/.netrc):
    python -m src.yield_panel.enrich --panel data/yield_panel/panel_central.csv

Each source is sampled around every municipality point:

| Source | Radius | Weighting | Columns |
|---|---|---|---|
| IMERG rain | 15 km | plain mean | imerg_* (same rain features as POWER) |
| CHIRPS rain | 10 km | plain mean | chirps_* |
| MODIS NDVI / EVI | 15 km | MCD12C1 cropland share | ndvi_*, evi_*, cropland_share |
| SMAP L4 (2015 on) | 10 km | plain mean | smap_* |
| IGBP-DIS soils | point | - | field_capacity, wilting_point, profile_available_water_capacity, ... |
"""

import argparse
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from src.yield_panel import gridded

UNIT = ["state_id", "mun_id"]


def rain_block(municipalities, years, source, bbox=None):
    """Season rain features per municipality-year. Gridded data are read one year at a time and reduced
    to municipality series straight away, so memory stays bounded even for a national box."""
    start, end = min(years) - 1, max(years)
    bbox = bbox or gridded.bbox_for(municipalities)
    if source == "imerg":
        chunks, radius = gridded.imerg_years(date(start, 11, 1), date(end, 12, 31), bbox), 15
    else:
        chunks, radius = gridded.chirps_years(range(start, end + 1), bbox), 10
    points = list(zip(municipalities.lat, municipalities.lon))
    days, pts = [], []
    for d, cube, lat, lon in chunks:
        p, _ = gridded.sample(cube, lat, lon, points, radius)
        days.append(d)
        pts.append(p)
        del cube
    return gridded.daily_to_features(pd.DatetimeIndex(np.concatenate(days)), np.concatenate(pts), municipalities,
                                     years, source)


def vegetation_block(municipalities, years):
    bbox = gridded.bbox_for(municipalities)
    months, ndvi, evi, lat, lon = gridded.fetch_ndvi(date(min(years), 1, 1), date(max(years), 12, 31), bbox)
    cropland, clat, clon = gridded.fetch_cropland(bbox)
    if cropland.shape != ndvi.shape[1:] or not (np.allclose(clat, lat) and np.allclose(clon, lon)):
        raise ValueError("Cropland mask and NDVI grids differ")
    points = list(zip(municipalities.lat, municipalities.lon))
    n_pts, weighted = gridded.sample(ndvi, lat, lon, points, 15, weights=cropland)
    e_pts, _ = gridded.sample(evi, lat, lon, points, 15, weights=cropland)
    share, _ = gridded.sample(cropland[None], lat, lon, points, 15)
    out = gridded.monthly_to_features(months, n_pts, municipalities, years, "ndvi").merge(
        gridded.monthly_to_features(months, e_pts, municipalities, years, "evi"), on=["year", *UNIT])
    static = municipalities[UNIT].assign(cropland_share=share[0], ndvi_cropland_weighted=weighted)
    return out, static


def smap_block(municipalities, years):
    bbox = gridded.bbox_for(municipalities)
    points = list(zip(municipalities.lat, municipalities.lon))
    days, rzs, sfs = [], [], []
    for d, rz, sf, lat, lon in gridded.smap_years(date(2015, 4, 1), date(max(years), 12, 31), bbox):
        days.append(d)
        rzs.append(gridded.sample(rz, lat, lon, points, 10)[0])
        sfs.append(gridded.sample(sf, lat, lon, points, 10)[0])
    return gridded.points_to_features(pd.DatetimeIndex(np.concatenate(days)), np.concatenate(rzs), np.concatenate(sfs),
                                      municipalities, [y for y in years if y >= 2015])


def igbp_block(municipalities):
    from src.data_ingestion import igbp_soils
    from src.data_ingestion.common import earthdata_login

    earthdata_login()
    igbp_soils.download(igbp_soils.search_granules())
    sites = [(f"{r.state_id}_{r.mun_id}", r.lat, r.lon) for r in municipalities.itertuples()]
    soils = igbp_soils.extract_points(sites).reset_index()
    ids = soils["site"].str.split("_", expand=True).astype(int)
    soils["state_id"], soils["mun_id"] = ids[0], ids[1]
    keep = [c for c in igbp_soils.LAYERS.values() if c in soils]
    soils[keep] = soils[keep].where(soils[keep] > 0)  # 0 and negative values are no-data (water, urban)
    return soils[[*UNIT, *keep]]


def enrich(panel, sources=("imerg", "chirps", "vegetation", "smap", "igbp")):
    years = sorted(panel["year"].unique())
    munis = panel.drop_duplicates(UNIT)[[*UNIT, "lat", "lon"]].reset_index(drop=True)
    out = panel.copy()
    for source in sources:
        print(f"Adding {source}...", flush=True)
        if source in ("imerg", "chirps"):
            out = out.merge(rain_block(munis, years, source), on=["year", *UNIT], how="left")
        elif source == "vegetation":
            seasonal, static = vegetation_block(munis, years)
            out = out.merge(seasonal, on=["year", *UNIT], how="left").merge(static, on=UNIT, how="left")
        elif source == "smap":
            out = out.merge(smap_block(munis, years), on=["year", *UNIT], how="left")
        elif source == "igbp":
            out = out.merge(igbp_block(munis), on=UNIT, how="left")
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--panel", type=Path, default=Path("data/yield_panel/panel_central.csv"))
    parser.add_argument("--sources", nargs="+", default=["imerg", "chirps", "vegetation", "smap", "igbp"])
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    panel = pd.read_csv(args.panel)
    out = enrich(panel, args.sources)
    path = args.out or args.panel.with_name(args.panel.stem + "_enriched.csv")
    out.to_csv(path, index=False)
    new = [c for c in out.columns if c not in panel.columns]
    print(f"Saved {len(out)} rows, {len(new)} new columns to {path}")
    print(out[new].notna().mean().round(3).to_string())


if __name__ == "__main__":
    main()
