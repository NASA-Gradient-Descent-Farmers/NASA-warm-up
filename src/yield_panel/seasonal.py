"""NASA GEOS-S2S seasonal forecasts (NMME archive, IRI Data Library) as pre-season planning features.

For every year, the forecast issued in April (initialized April 1, published around April 10, so known
before the April 30 planning cutoff) predicts monthly conditions through October: lead 0.5 = April,
1.5 = May, ..., 6.5 = October. The archive splits into the HINDCAST stream (starts 1981-02 to 2017-01,
4 members) and the real-time FORECAST stream (2017-02 on, 10 members). Both are GEOS-S2S on a 1 degree grid.

Downloads are anonymous NetCDF requests (the Data Library's sign-in covers its web pages, not downloads),
cut to a box over Mexico and averaged over ensemble members server-side.

Features per municipality-year (`s2s_*`), as anomalies from the hindcast's own 1991-2016 climatology for
each grid cell and lead month, so model drift and the stream change do not leak into the signal:

| Feature | Meaning |
|---|---|
| s2s_prec_may_oct_anom_mm | forecast May-Oct rain minus the model's usual May-Oct rain |
| s2s_prec_jun_anom_mm, s2s_prec_jul_aug_anom_mm, s2s_prec_sep_oct_anom_mm | the same by period |
| s2s_tref_may_oct_anom_c, s2s_t2mmax_jul_aug_anom_c | forecast mean / daily-maximum temperature anomalies |
"""

from pathlib import Path

import numpy as np
import pandas as pd
import requests
from scipy.io import netcdf_file

from src.data_ingestion.common import DATA_DIR
from src.yield_panel import gridded

BASE = "https://iridl.ldeo.columbia.edu/SOURCES/.Models/.NMME/.NASA-GEOSS2S/.{stream}/.MONTHLY/.{var}"
BOX = "Y/13.5/33.5/RANGEEDGES/X/242.5/274.5/RANGEEDGES/L/0.5/6.5/RANGEEDGES/%5BM%5Daverage/data.nc"
CACHE = DATA_DIR / "geos_s2s"
VARIABLES = ["prec", "tref", "t2mmax"]
REQUIRED = ["prec"]  # the others are added when their download succeeds (the server builds t2mmax slowly)
CLIM_YEARS = range(1991, 2017)
DAYS = {5: 31, 6: 30, 7: 31, 8: 31, 9: 30, 10: 31}
LEAD_MONTH = {0.5: 4, 1.5: 5, 2.5: 6, 3.5: 7, 4.5: 8, 5.5: 9, 6.5: 10}  # for April starts


def download(directory=CACHE, retries=3):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for var in VARIABLES:
        for stream in ["HINDCAST", "FORECAST"]:
            path = directory / f"{var}_{stream}_mex.nc"
            if path.exists() and path.read_bytes()[:3] == b"CDF":
                continue
            for attempt in range(retries):
                try:
                    r = requests.get(f"{BASE.format(stream=stream, var=var)}/{BOX}", timeout=900)
                    r.raise_for_status()
                    if not r.content.startswith(b"CDF"):
                        raise ValueError("not a NetCDF file")
                    path.write_bytes(r.content)
                    break
                except Exception as exc:
                    if attempt == retries - 1:
                        if var in REQUIRED:
                            raise
                        print(f"[WARN] GEOS-S2S {var} {stream} not downloaded ({exc!r}); continuing without it")
    return directory


def available(directory=CACHE):
    return [v for v in VARIABLES if all((Path(directory) / f"{v}_{s}_mex.nc").exists() for s in ["HINDCAST", "FORECAST"])]


def april_forecasts(var, directory=CACHE):
    """(years, cube[year, lead, lat, lon], lat, lon, leads) of April-initialized forecasts, both streams."""
    parts = []
    for stream in ["HINDCAST", "FORECAST"]:
        n = netcdf_file(Path(directory) / f"{var}_{stream}_mex.nc", "r", mmap=False)
        s = np.round(n.variables["S"][:]).astype(int)  # months since 1960-01
        keep = s % 12 == 3
        years = 1960 + s[keep] // 12
        data = n.variables[var][:][keep].astype(float)
        if data.ndim == 5:  # temperature carries a single-level height axis
            data = data.reshape(data.shape[0], data.shape[1], data.shape[-2], data.shape[-1])
        parts.append((years, data))
        lat, lon, leads = n.variables["Y"][:].copy(), n.variables["X"][:].copy(), n.variables["L"][:].copy()
        n.close()
    years = np.concatenate([p[0] for p in parts])
    cube = np.concatenate([p[1] for p in parts])
    order = np.argsort(years)
    return years[order], cube[order], lat, np.where(lon > 180, lon - 360, lon), leads


def anomaly_grids(directory=CACHE):
    """Seasonal anomaly grids per year: {feature: (years, grid[year, lat, lon])} plus lat, lon."""
    out = {}
    for var in available(directory):
        years, cube, lat, lon, leads = april_forecasts(var, directory)
        months = np.array([LEAD_MONTH[float(l)] for l in leads])
        clim = cube[np.isin(years, list(CLIM_YEARS))].mean(axis=0)  # per lead and cell
        anom = cube - clim
        if var == "prec":  # mm/day -> mm over the period
            days = np.array([DAYS.get(m, 0) for m in months], dtype=float)[None, :, None, None]
            total = lambda ms: (anom * days * np.isin(months, ms)[None, :, None, None]).sum(axis=1)
            out["s2s_prec_may_oct_anom_mm"] = total([5, 6, 7, 8, 9, 10])
            out["s2s_prec_jun_anom_mm"] = total([6])
            out["s2s_prec_jul_aug_anom_mm"] = total([7, 8])
            out["s2s_prec_sep_oct_anom_mm"] = total([9, 10])
        elif var == "tref":
            out["s2s_tref_may_oct_anom_c"] = anom[:, np.isin(months, [5, 6, 7, 8, 9, 10])].mean(axis=1)
        else:
            out["s2s_t2mmax_jul_aug_anom_c"] = anom[:, np.isin(months, [7, 8])].mean(axis=1)
    return years, out, lat, lon


S2S = ["s2s_prec_may_oct_anom_mm", "s2s_prec_jun_anom_mm", "s2s_prec_jul_aug_anom_mm", "s2s_prec_sep_oct_anom_mm",
       "s2s_tref_may_oct_anom_c", "s2s_t2mmax_jul_aug_anom_c"]


def municipal_features(municipalities, directory=CACHE, radius_km=60, fetch=True):
    """S2S anomaly features per municipality-year (average of 1 degree cells within `radius_km`)."""
    if fetch:
        download(directory)
    years, grids, lat, lon = anomaly_grids(directory)
    points = list(zip(municipalities["lat"], municipalities["lon"]))
    frame = municipalities[["state_id", "mun_id"]].reset_index(drop=True)
    parts = []
    for name, grid in grids.items():
        vals, _ = gridded.sample(grid, lat, lon, points, radius_km)  # (years, points)
        parts.append(pd.DataFrame(vals.T, columns=years).assign(**frame).melt(
            id_vars=["state_id", "mun_id"], var_name="year", value_name=name))
    out = parts[0]
    for p in parts[1:]:
        out = out.merge(p, on=["state_id", "mun_id", "year"])
    out["year"] = out["year"].astype(int)
    return out
