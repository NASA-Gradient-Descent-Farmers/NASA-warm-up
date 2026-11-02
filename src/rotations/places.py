"""Find a farmer's district from a municipality or district name and assemble its data."""

from functools import lru_cache

import pandas as pd

from . import catalog, climate, observed, siap_stats
from .indicators import Place


@lru_cache(maxsize=1)
def _siap():
    return siap_stats.add_outcomes(siap_stats.load())


@lru_cache(maxsize=1)
def _districts():
    d = siap_stats.load_districts().copy()
    d["mun_plain"] = d["municipality"].map(catalog.plain)
    d["ddr_plain"] = d["ddr_name"].map(catalog.plain)
    d["state_plain"] = d["state"].map(catalog.plain)
    return d


@lru_cache(maxsize=1)
def _observed():
    try:
        return observed.load("district"), observed.load("municipal")
    except FileNotFoundError:
        return None, None


@lru_cache(maxsize=1)
def _climate():
    return (climate.load("district"), climate.load("municipal"),
            climate.load("district", yearly=True), climate.load("municipal", yearly=True))


def find(name, state=None):
    """Rows of the municipality -> district table matching a municipality or district name."""
    d = _districts()
    key = catalog.plain(name)
    if state:
        d = d[d["state_plain"].str.contains(catalog.plain(state), regex=False)]
    hits = d[d["mun_plain"] == key]
    if hits.empty:
        hits = d[d["ddr_plain"] == key]
    if hits.empty:
        hits = d[d["mun_plain"].str.contains(key, regex=False) | d["ddr_plain"].str.contains(key, regex=False)]
    return hits


def place(name, state=None, water="temporal", sowing_month=None):
    """Place for a municipality (its own POWER climate, its district's SIAP) or a district."""
    hits = find(name, state)
    if hits.empty:
        raise LookupError(f"No encontré '{name}'" + (f" en {state}" if state else ""))
    districts = hits[["state_id", "ddr"]].drop_duplicates()
    if len(districts) > 1:
        options = hits.drop_duplicates(["state_id", "ddr"])[["municipality", "state", "ddr_name"]]
        raise LookupError("Hay varios lugares con ese nombre: " + "; ".join(
            f"{r.municipality} ({r.state}, distrito {r.ddr_name})" for r in options.itertuples()))
    row = hits.iloc[0]
    by_district, by_municipality, years_district, years_municipality = _climate()
    municipal = catalog.plain(name) in set(hits["mun_plain"])
    notes = []
    clim = pd.DataFrame()
    if municipal:
        clim = by_municipality[(by_municipality.state_id == row.state_id) & (by_municipality.mun_id == row.mun_id)]
        yearly = years_municipality[(years_municipality.state_id == row.state_id) & (years_municipality.mun_id == row.mun_id)]
    if clim.empty:
        clim = by_district[(by_district.state_id == row.state_id) & (by_district.ddr == row.ddr)]
        yearly = years_district[(years_district.state_id == row.state_id) & (years_district.ddr == row.ddr)]
        municipal = False
    if clim.empty:
        raise LookupError(f"Sin datos de clima de NASA POWER para el distrito {row.ddr_name}")
    if not municipal:
        notes.append("Clima: promedio del distrito ponderado por superficie sembrada")
    if "rain_corrected" in clim and not bool(clim["rain_corrected"].any()):
        notes.append("Lluvia de NASA POWER sin corregir con estaciones (CHIRPS no disponible para este lugar)")
    obs_district, obs_municipal = _observed()
    obs = None
    if obs_municipal is not None:
        obs = obs_municipal[(obs_municipal.state_id == row.state_id) & (obs_municipal.mun_id == row.mun_id)] if municipal else None
        if obs is None or obs.empty or obs["ndvi"].isna().all():
            obs = obs_district[(obs_district.state_id == row.state_id) & (obs_district.ddr == row.ddr)]
        obs = obs.sort_values("month").reset_index(drop=True) if not obs.empty else None
    return Place(state_id=int(row.state_id), ddr=int(row.ddr), state=row.state, ddr_name=row.ddr_name, observed=obs,
                 water=water, climate=clim.sort_values("month").reset_index(drop=True), siap=_siap(),
                 climate_years=yearly, municipality=row.municipality if municipal else None,
                 sowing_month=sowing_month, notes=notes)
