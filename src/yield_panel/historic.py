"""Long SIAP series: districts (DDR) 1999-2025 and states 1980-2025.

SIAP's open municipal files start in 2003. Older annual statistics ("Estadística de la Producción
Agrícola", formerly at sagarpa.gob.mx) survive on datamx.io:

| File | Years | Finest level for rainfed spring-summer grains |
|---|---|---|
| Agt_cierre_1980_1990 | 1980-1990 | state |
| Agt_cierre_1991_2000 | 1991-2000 | state (1991-1998), district (1999-2000) |
| Agt_cierre_2001_2002 | 2001-2002 | district |

District codes match the 2003+ files (188 of 190 districts). Rows split by variety are additive
(the no-variety row is not a total), so every row of a crop is summed.

Modern years are aggregated from the national SIAP files with the same rules, so both periods share
one schema: the district or state id goes in `mun_id` (with `state_id`), as in ablation.district_panel.
"""

import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from src.data_ingestion.common import DATA_DIR
from src.yield_panel import siap

CACHE = DATA_DIR / "siap_historic"
DATAMX = "https://datamx.io/datastore/dump/{rid}"
FILES = {  # datamx resource ids (dataset "estadistica-agropecuaria")
    "Agt_cierre_1980_1990.csv": "eadb54d5-66f1-4a23-93a6-1a7325c9d7f5",
    "Agt_cierre_1991_2000.csv": "102be916-d273-4f65-b8e9-462151644f6b",
    "Agt_cierre_2001_2002.csv": "8af966cf-5569-4a05-b70b-3d608edd18b4",
}

# Upper-case, accent-free crop names -> panel crop. Seed, forage and popcorn variants are excluded.
CROP_PATTERNS = {
    "maize": r"^MAIZ GRANO",
    "bean": r"^FRIJOL",
    "sorghum": r"^SORGO GRANO",
    "wheat": r"^TRIGO GRANO",
    "barley": r"^CEBADA GRANO",
    "oats": r"^AVENA GRANO",
}
EXCLUDE = r"SEMILLA|FORRAJ|PALOMERO|EJOTE"
AREAS = ["sown_ha", "harvested_ha", "lost_ha", "production_t"]


def normalize_name(name):
    text = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", text.upper()).strip()


def crop_of(names):
    norm = pd.Series(names).map(normalize_name)
    out = pd.Series(pd.NA, index=norm.index, dtype="object")
    for crop, pattern in CROP_PATTERNS.items():
        out[norm.str.contains(pattern) & ~norm.str.contains(EXCLUDE)] = crop
    return out.to_numpy()


def download(directory=CACHE):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for name, rid in FILES.items():
        path = directory / name
        if not path.exists():
            r = requests.get(DATAMX.format(rid=rid), timeout=600)
            r.raise_for_status()
            if not r.content.startswith(b"_id,"):
                raise ValueError(f"Unexpected datamx response for {name}")
            path.write_bytes(r.content)
    return [directory / n for n in FILES]


def _finish(table):
    table["yield_t_ha"] = np.where(table["harvested_ha"] > 0, table["production_t"] / table["harvested_ha"], np.nan)
    table["failure_rate"] = (table["lost_ha"] / table["sown_ha"].where(table["sown_ha"] > 0)).clip(0, 1)
    return table


def historic_levels(directory=CACHE, cycle=2, water_mode=2):
    """(districts 1999-2002, states 1980-2002) for rainfed spring-summer grains from the datamx files."""
    parts = []
    for path in download(directory):
        d = pd.read_csv(path, low_memory=False)
        d = d[(d["CveCiclo"] == cycle) & (d["CveModa"] == water_mode)]
        d = d[d["UnidadMedida"].astype(str).str.upper().str.startswith("TONELADA")]
        d = d.assign(crop=crop_of(d["Cultivo"])).dropna(subset=["crop"])
        d = d.rename(columns={"AñoAgricola": "year", "CveEstado": "state_id", "CveDDR": "ddr", "Sembrada": "sown_ha",
                              "Cosechada": "harvested_ha", "Siniestrada": "lost_ha", "Produccion": "production_t"})
        parts.append(d[["year", "state_id", "ddr", "crop", *AREAS]])
    d = pd.concat(parts, ignore_index=True)
    d[AREAS] = d[AREAS].apply(pd.to_numeric, errors="coerce")
    states = _finish(d.groupby(["crop", "state_id", "year"], as_index=False)[AREAS].sum(min_count=1))
    dist = d[d["ddr"] != 0]
    districts = _finish(dist.groupby(["crop", "state_id", "ddr", "year"], as_index=False)[AREAS].sum(min_count=1))
    return districts, states


def modern_levels(years, directory=siap.CACHE_DIR, cycle="pv", water_mode="rainfed"):
    """(districts, states) for 2003+ aggregated from the national SIAP files with the historic crop rules."""
    dparts, sparts = [], []
    for year in years:
        f = siap.read_year(year, directory)
        f = f[(f["idciclo"] == siap.CYCLES[cycle]) & (f["idmodalidad"] == siap.WATER_MODES[water_mode])]
        if "nomunidad" in f:
            f = f[f["nomunidad"].astype(str).str.casefold().str.startswith("tonelada")]
        f = f.assign(crop=crop_of(f["nomcultivo"])).dropna(subset=["crop"])
        f = f.rename(columns={"anio": "year", "idestado": "state_id", "idddr": "ddr", "sembrada": "sown_ha",
                              "cosechada": "harvested_ha", "siniestrada": "lost_ha", "volumenproduccion": "production_t"})
        f[AREAS] = f[AREAS].apply(pd.to_numeric, errors="coerce")
        dparts.append(f.groupby(["crop", "state_id", "ddr", "year"], as_index=False)[AREAS].sum(min_count=1))
        sparts.append(f.groupby(["crop", "state_id", "year"], as_index=False)[AREAS].sum(min_count=1))
    return _finish(pd.concat(dparts, ignore_index=True)), _finish(pd.concat(sparts, ignore_index=True))


def long_panels(modern_years=range(2003, 2026)):
    """District panel 1999-2025 and state panel 1980-2025 in the models' schema (unit id in `mun_id`)."""
    hd, hs = historic_levels()
    md, ms = modern_levels(modern_years)
    districts = pd.concat([hd, md], ignore_index=True).assign(mun_id=lambda t: t["ddr"])
    states = pd.concat([hs, ms], ignore_index=True).assign(mun_id=0)
    return (districts.sort_values(["crop", "state_id", "ddr", "year"]).reset_index(drop=True),
            states.sort_values(["crop", "state_id", "year"]).reset_index(drop=True))


def area_weighted_features(municipal_features, weights, unit_keys, feature_cols):
    """Average municipality-year features into district- or state-years, weighted by `weights`.

    municipal_features: state_id, mun_id, year, features. weights: state_id, mun_id, crop, weight and the
    unit keys (e.g. ddr). Weights are fixed per municipality and crop, so historic years use the same map.
    """
    m = municipal_features.merge(weights, on=["state_id", "mun_id"])
    out = []
    for keys, g in m.groupby(["crop", *unit_keys, "year"]):
        w = g["weight"].to_numpy(float)
        vals = g[feature_cols].to_numpy(float)
        ok = np.isfinite(vals)
        den = (ok * w[:, None]).sum(axis=0)
        num = np.nansum(np.where(ok, vals, 0) * w[:, None], axis=0)
        out.append([*keys, *np.where(den > 0, num / np.where(den > 0, den, 1), np.nan)])
    return pd.DataFrame(out, columns=["crop", *unit_keys, "year", *feature_cols])
