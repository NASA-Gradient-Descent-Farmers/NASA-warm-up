"""SIAP municipal agricultural statistics -> a municipality x year x crop panel.

Source: https://nube.agricultura.gob.mx/datosAbiertos/Agricola.php (one national CSV per year, 2003 on).
The URL pattern and encoding are the ones used by src/crop_models/observed_maize.py.

Two targets per row:
- yield_t_ha: production / harvested area (how much the harvested fields produced);
- failure_rate: lost area (siniestrada) / sown area (the share of the sown area that was lost).
Expected production per sown hectare is roughly (1 - failure_rate) * yield_t_ha.
"""

from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from src.data_ingestion.common import DATA_DIR

URL = "https://nube.agricultura.gob.mx/index.php?view=10AE434F-A2158368-A120BC5A-EDF4AFAA&ANIO={year}"
CACHE_DIR = DATA_DIR / "siap"

CYCLES = {"oi": 1, "pv": 2, "perennial": 3}       # otoño-invierno, primavera-verano, perennes
WATER_MODES = {"irrigated": 1, "rainfed": 2}      # riego, temporal

# Annual grain and pulse crops reported in tonnes. Names are matched case-insensitively.
DEFAULT_CROPS = {
    "maize": "maíz grano",
    "bean": "frijol",
    "sorghum": "sorgo grano",
    "wheat": "trigo grano",
    "barley": "cebada grano",
    "oats": "avena grano",
}

COLUMN_ALIASES = {"nomcultivo sin um": "nomcultivo", "preciomediorural": "precio"}
NUMERIC = ["sembrada", "cosechada", "siniestrada", "volumenproduccion"]


def normalize(frame):
    """Lower-case, strip and harmonize SIAP column names across years."""
    frame = frame.rename(columns=lambda c: c.strip().lower())
    return frame.rename(columns=COLUMN_ALIASES)


def download_year(year, directory=CACHE_DIR, timeout=120):
    """Path to the cached national SIAP file for `year`, downloading it the first time."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{year}.csv"
    if not path.exists():
        response = requests.get(URL.format(year=year), timeout=timeout)
        response.raise_for_status()
        frame = normalize(pd.read_csv(BytesIO(response.content), encoding="cp1252", low_memory=False))
        # Validate before caching so an error page never becomes a permanent input.
        missing = {"anio", "idestado", "idmunicipio", "idciclo", "idmodalidad", "nomcultivo", *NUMERIC} - set(frame)
        if missing or not (frame["anio"] == year).all():
            raise ValueError(f"Unexpected SIAP file for {year}: missing {sorted(missing)}")
        path.write_bytes(response.content)
    return path


def read_year(year, directory=CACHE_DIR):
    return normalize(pd.read_csv(download_year(year, directory), encoding="cp1252", low_memory=False))


def extract_panel(frame, crops=DEFAULT_CROPS, cycle="pv", water_mode="rainfed"):
    """Aggregate one SIAP year to one row per (state, municipality, crop) for a cycle and water mode."""
    names = {name.casefold(): key for key, name in crops.items()}
    crop = frame["nomcultivo"].astype(str).str.strip().str.casefold()
    keep = (frame["idciclo"] == CYCLES[cycle]) & (frame["idmodalidad"] == WATER_MODES[water_mode]) & crop.isin(names)
    if "nomunidad" in frame:  # all default crops are reported in tonnes; drop anything else
        keep &= frame["nomunidad"].astype(str).str.casefold().str.startswith("tonelada")
    selected = frame.loc[keep, ["anio", "idestado", "idmunicipio", *NUMERIC]].copy()
    selected["crop"] = crop[keep].map(names)
    selected[NUMERIC] = selected[NUMERIC].apply(pd.to_numeric, errors="coerce")

    panel = (selected.groupby(["anio", "idestado", "idmunicipio", "crop"], as_index=False)[NUMERIC].sum(min_count=1)
             .rename(columns={"anio": "year", "idestado": "state_id", "idmunicipio": "mun_id",
                              "sembrada": "sown_ha", "cosechada": "harvested_ha", "siniestrada": "lost_ha",
                              "volumenproduccion": "production_t"}))
    panel = panel.astype({"year": int, "state_id": int, "mun_id": int})
    panel["yield_t_ha"] = np.where(panel["harvested_ha"] > 0, panel["production_t"] / panel["harvested_ha"], np.nan)
    sown = panel["sown_ha"].where(panel["sown_ha"] > 0)
    panel["failure_rate"] = (panel["lost_ha"] / sown).clip(0, 1)
    return panel


def load_panel(years, crops=DEFAULT_CROPS, cycle="pv", water_mode="rainfed", directory=CACHE_DIR, cache=True):
    """Panel for all `years`, cached as data/siap/panel_<cycle>_<mode>.csv (delete it to rebuild)."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"panel_{cycle}_{water_mode}.csv"
    years = list(years)
    if cache and path.exists():
        panel = pd.read_csv(path)
        if set(years) <= set(panel["year"]) and set(crops) <= set(panel["crop"]):
            return panel[panel["year"].isin(years) & panel["crop"].isin(list(crops))].reset_index(drop=True)
    parts = []
    for year in years:
        parts.append(extract_panel(read_year(year, directory), crops, cycle, water_mode))
        print(f"SIAP {year}: {len(parts[-1])} rows", flush=True)
    panel = pd.concat(parts, ignore_index=True).sort_values(["crop", "state_id", "mun_id", "year"])
    if cache:
        panel.to_csv(path, index=False)
    return panel.reset_index(drop=True)


def clean_panel(panel, min_sown_ha=50.0, min_years=10, max_yield=None):
    """Drop rows too small or too short to be informative.

    - min_sown_ha: tiny plantings give noisy yields and failure rates;
    - min_years: each municipality-crop series needs enough years for its own average and trend;
    - max_yield: optional per-crop dict of implausible yields (t/ha) to drop as data errors.
    """
    out = panel[panel["sown_ha"] >= min_sown_ha].copy()
    if max_yield:
        cap = out["crop"].map(max_yield)
        out.loc[cap.notna() & (out["yield_t_ha"] > cap), "yield_t_ha"] = np.nan
    counts = out.groupby(["crop", "state_id", "mun_id"])["year"].transform("nunique")
    return out[counts >= min_years].reset_index(drop=True)
