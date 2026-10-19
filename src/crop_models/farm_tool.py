"""Helpers for the Texcoco farmer MVP notebook (Notebooks/texcoco_farmer_mvp.ipynb).

Turns WOFOST season tables into farm-level numbers: yields rescaled to what Texcoco farms
report to SIAP, income per hectare per year for whole rotations, and downside risk.
Exploratory: WOFOST is not calibrated to Texcoco farms (see farm_gap), and the costs used
by the notebook are placeholders to be replaced with real ones.
"""

from pathlib import Path

import numpy as np
import pandas as pd

from .rotation_experiments import TARGET, load_seasons

OBSERVATIONS = Path("data/observations")
SCENARIO_DIRS = [Path("data/rotations"), Path("data/exploration/scenarios"), Path("data/exploration/notebook_runs")]
# SIAP crop names for the WOFOST crops (rainfed spring-summer cycle, Texcoco municipality).
SIAP_CROPS = {"maize": "maíz grano", "barley": "cebada grano", "fababean": "haba grano"}


def scenario_files(directories=SCENARIO_DIRS):
    return [path for directory in directories for path in sorted(Path(directory).glob("*.csv"))]


def load_scenarios(paths=None, spinup_years=1):
    """All saved WOFOST scenario tables (the ten suites plus notebook runs), spin-up years removed."""
    return load_seasons(paths or scenario_files(), spinup_years)


def extract_siap(frame, year, crops=SIAP_CROPS):
    """One row per crop: Texcoco (Edo. Mex. 15, mun. 99), spring-summer (2), rainfed (2)."""
    frame = frame.rename(columns=lambda c: c.strip().lower())
    frame = frame.rename(columns={"nomcultivo sin um": "nomcultivo", "preciomediorural": "precio"})
    names = {siap: crop for crop, siap in crops.items()}
    selected = frame[(frame.idestado == 15) & (frame.idmunicipio == 99) & (frame.idciclo == 2)
                     & (frame.idmodalidad == 2) & frame.nomcultivo.str.casefold().isin(names)]
    rows = []
    for name, group in selected.groupby(selected.nomcultivo.str.casefold()):
        sown, harvested, lost, production, value = (
            pd.to_numeric(group[c], errors="raise").sum()
            for c in ("sembrada", "cosechada", "siniestrada", "volumenproduccion", "valorproduccion"))
        rows.append({
            "year": year, "crop": names[name], "sown_ha": sown, "harvested_ha": harvested, "lost_ha": lost,
            "production_t": production,
            "yield_harvested_t_ha": production / harvested if harvested else np.nan,
            # Production over sown area counts lost fields as zero, like a failed WOFOST season.
            "yield_sown_t_ha": production / sown if sown else np.nan,
            "lost_share": lost / sown if sown else np.nan,
            "price_mxn_t": value / production if production else np.nan,
        })
    return rows


def siap_texcoco(directory=OBSERVATIONS, years=range(2005, 2026)):
    """Observed Texcoco yields, losses and rural prices per crop and year from the cached SIAP files.

    The parsed table is cached as texcoco_crops.csv next to the raw files (delete it to rebuild).
    """
    directory = Path(directory)
    cache = directory / "texcoco_crops.csv"
    if cache.exists():
        return pd.read_csv(cache)
    rows = []
    for year in years:
        frame = pd.read_csv(directory / f"{year}.csv", encoding="cp1252", low_memory=False)
        rows.extend(extract_siap(frame, year))
    table = pd.DataFrame(rows).sort_values(["crop", "year"]).reset_index(drop=True)
    table.to_csv(cache, index=False)
    return table


def default_prices(siap, last_years=3):
    """Median nominal rural price (MXN/t) per crop over the latest years with a price."""
    priced = siap.dropna(subset=["price_mxn_t"])
    recent = priced[priced["year"] > priced.groupby("crop")["year"].transform("max") - last_years]
    return recent.groupby("crop")["price_mxn_t"].median().to_dict()


def farm_gap(seasons, siap, scenario="baseline"):
    """Per crop: observed SIAP yield per sown ha against WOFOST (all rotations) over shared years.

    `factor` rescales simulated yields to the municipal average level. `correlation` is the
    year-to-year agreement; a low or negative value means the year pattern is not trustworthy.
    """
    simulated = (seasons[seasons["scenario"] == scenario].groupby(["crop", "year"])[TARGET].mean()
                 .rename("simulated_t_ha"))
    observed = siap.set_index(["crop", "year"])["yield_sown_t_ha"].rename("observed_t_ha")
    both = pd.concat([simulated, observed], axis=1, join="inner").dropna().reset_index()
    rows = []
    for crop, group in both.groupby("crop"):
        rows.append({
            "crop": crop, "years": len(group),
            "simulated_mean_t_ha": group["simulated_t_ha"].mean(),
            "observed_mean_t_ha": group["observed_t_ha"].mean(),
            "factor": group["observed_t_ha"].mean() / group["simulated_t_ha"].mean(),
            "correlation": group["simulated_t_ha"].corr(group["observed_t_ha"]),
        })
    return pd.DataFrame(rows).set_index("crop"), both


def rotation_economics(seasons, prices, other_costs, n_price, yield_factors=None, failure_threshold=1.0):
    """Season, annual and summary results per hectare for every scenario and rotation.

    Every phase of a rotation is simulated each year, so the phase average is what one hectare
    split across the phases yields that year; over the years it is also a single field's average.
    prices: MXN/t per crop. other_costs: MXN/ha per crop excluding fertilizer. n_price: MXN/kg N.
    yield_factors: optional per-crop multipliers (e.g. farm_gap factors); missing crops keep 1.
    """
    factors = yield_factors or {}
    s = seasons.copy()
    s["yield_t_ha"] = s[TARGET] * s["crop"].map(lambda c: factors.get(c, 1.0))
    s["failed"] = s["yield_t_ha"] < failure_threshold
    s["revenue_mxn_ha"] = s["yield_t_ha"] * s["crop"].map(prices)
    s["cost_mxn_ha"] = s["crop"].map(other_costs) + s["n_fertilizer_kg_ha"] * n_price
    s["net_mxn_ha"] = s["revenue_mxn_ha"] - s["cost_mxn_ha"]
    if s[["revenue_mxn_ha", "cost_mxn_ha"]].isna().any().any():
        missing = sorted(set(s.loc[s["net_mxn_ha"].isna(), "crop"]))
        raise ValueError(f"Missing price or cost for {missing}")
    annual = (s.groupby(["scenario", "rotation", "year"])[["revenue_mxn_ha", "cost_mxn_ha", "net_mxn_ha"]]
              .mean().reset_index())
    summary = annual.groupby(["scenario", "rotation"]).agg(
        years=("year", "size"),
        mean_net_mxn_ha=("net_mxn_ha", "mean"),
        p10_net_mxn_ha=("net_mxn_ha", lambda x: x.quantile(0.1)),
        p90_net_mxn_ha=("net_mxn_ha", lambda x: x.quantile(0.9)),
        worst_net_mxn_ha=("net_mxn_ha", "min"),
        loss_year_share=("net_mxn_ha", lambda x: (x < 0).mean()),
    )
    crops = s.groupby(["scenario", "rotation", "crop"]).agg(
        seasons=("year", "size"), mean_yield_t_ha=("yield_t_ha", "mean"),
        p10_yield_t_ha=("yield_t_ha", lambda x: x.quantile(0.1)), failed_share=("failed", "mean"))
    return s, annual, summary.reset_index(), crops.reset_index()


def run_scenario(name, rotations=None, rain_factor=1.0, rain_months=None, frost_tmin_offset=0.0, n_scale=1.0,
                 sowing="onset", start_year=2005, end_year=2025, out_dir=SCENARIO_DIRS[-1]):
    """Run WOFOST live for a custom scenario, save it with the others, and return its loaded seasons.

    Needs internet (NASA POWER weather is cached by PCSE; soils are cached under data/). One rotation
    takes well under a minute; all four take about two minutes.
    """
    from .wofost_rotations import ROTATIONS, simulate_rotations

    chosen = {key: ROTATIONS[key] for key in (rotations or ROTATIONS)}
    seasons, _, _, _ = simulate_rotations(19.53, -98.85, start_year, end_year, chosen, sowing, rain_factor,
                                          list(rain_months) if rain_months else None, frost_tmin_offset, n_scale)
    seasons["scenario"] = name
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}.csv"
    seasons.to_csv(path, index=False)
    return load_seasons([path])
