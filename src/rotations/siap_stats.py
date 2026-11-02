"""SIAP history per district (DDR) x crop x cycle x water regime, 2003-2025.

SIAP's municipal numbers are largely district estimates (see src/yield_panel/README.md), so the rotation
tool works at district level and uses the state as a fallback when the district has no record of a crop.

    python -m src.rotations.siap_stats      # writes data/rotations/siap_crop_years.parquet
"""

from pathlib import Path

import numpy as np
import pandas as pd

from src.yield_panel import siap

from . import catalog

OUT = Path("data/rotations")
YEARS = range(2003, 2026)
CYCLES = {1: "oi", 2: "pv"}
WATER = {1: "riego", 2: "temporal"}
NUMERIC = ["sembrada", "cosechada", "siniestrada", "volumenproduccion", "valorproduccion"]


def extract_year(frame):
    """One SIAP year -> district x crop x cycle x water rows for the crops in the catalog."""
    names = catalog.siap_names()
    crop = frame["nomcultivo"].map(catalog.plain).map(names)
    keep = crop.notna() & frame["idciclo"].isin(CYCLES) & frame["idmodalidad"].isin(WATER)
    keep &= frame["nomunidad"].astype(str).map(catalog.plain).str.startswith("tonelada")
    f = frame.loc[keep, ["anio", "idestado", "nomestado", "idddr", "nomddr", "idciclo", "idmodalidad", *NUMERIC]].copy()
    f["crop"] = crop[keep]
    f[NUMERIC] = f[NUMERIC].apply(pd.to_numeric, errors="coerce")
    f["cycle"] = f.pop("idciclo").map(CYCLES)
    f["water"] = f.pop("idmodalidad").map(WATER)
    out = (f.groupby(["anio", "idestado", "idddr", "crop", "cycle", "water"], as_index=False)
           .agg(state=("nomestado", "first"), ddr_name=("nomddr", "first"),
                **{c: (c, lambda s: s.sum(min_count=1)) for c in NUMERIC}))
    return out.rename(columns={"anio": "year", "idestado": "state_id", "idddr": "ddr", "sembrada": "sown_ha",
                               "cosechada": "harvested_ha", "siniestrada": "lost_ha",
                               "volumenproduccion": "production_t", "valorproduccion": "value_mxn"})


def municipality_districts(years=range(2016, 2026)):
    """Each municipality's district: the most frequent idddr in recent years, with names."""
    parts = []
    for year in years:
        f = siap.read_year(year)
        parts.append(f[["idestado", "nomestado", "idmunicipio", "nommunicipio", "idddr", "nomddr"]].drop_duplicates())
    f = pd.concat(parts)
    best = (f.groupby(["idestado", "idmunicipio", "idddr"]).size().rename("n").reset_index()
            .sort_values("n").drop_duplicates(["idestado", "idmunicipio"], keep="last"))
    labels = f.drop_duplicates(["idestado", "idmunicipio"], keep="last")[["idestado", "idmunicipio", "nomestado", "nommunicipio"]]
    ddr_names = f.drop_duplicates(["idestado", "idddr"], keep="last")[["idestado", "idddr", "nomddr"]]
    out = best.merge(labels, on=["idestado", "idmunicipio"]).merge(ddr_names, on=["idestado", "idddr"])
    return out.drop(columns="n").rename(columns={"idestado": "state_id", "idmunicipio": "mun_id", "idddr": "ddr",
                                                 "nomestado": "state", "nommunicipio": "municipality",
                                                 "nomddr": "ddr_name"})


def build(years=YEARS, out=OUT):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    parts = []
    for year in years:
        parts.append(extract_year(siap.read_year(year)))
        print(f"SIAP {year}: {len(parts[-1])} district-crop rows", flush=True)
    table = pd.concat(parts, ignore_index=True)
    table.to_parquet(out / "siap_crop_years.parquet", index=False)
    municipality_districts().to_parquet(out / "municipality_districts.parquet", index=False)
    return table


SHARED = Path("data/shared")


def read(name, out=OUT):
    """A built table from data/rotations/, or from the shared data package (data/shared/rotations_<name>)."""
    for path in (Path(out) / f"{name}.parquet", SHARED / f"rotations_{name}.parquet"):
        if path.exists():
            return pd.read_parquet(path)
    raise FileNotFoundError(f"{name}: run `python -m src.rotations.build` or pull data/shared/ from the repo")


def load(out=OUT):
    return read("siap_crop_years", out)


def load_districts(out=OUT):
    return read("municipality_districts", out)


def add_outcomes(table):
    """Per-row production per sown hectare, failure share and price (MXN per tonne)."""
    t = table.copy()
    sown = t["sown_ha"].where(t["sown_ha"] > 0)
    t["prod_per_sown"] = t["production_t"] / sown           # counts lost area as zero production
    t["yield_t_ha"] = t["production_t"] / t["harvested_ha"].where(t["harvested_ha"] > 0)
    t["failure"] = (t["lost_ha"] / sown).clip(0, 1)
    t["price"] = t["value_mxn"] / t["production_t"].where(t["production_t"] > 0)
    return t


if __name__ == "__main__":
    build()
