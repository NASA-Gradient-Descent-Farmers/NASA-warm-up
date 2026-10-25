"""Assemble the planning panels (municipality 2003-2025, district 1999-2025, state 1982-2025) and run the planning ablation.

Usage (from the repo root, after build.py, enrich.py and the long POWER pull; see README):
    python -m src.yield_panel.plan_build build      # writes data/yield_panel/planning/*.parquet
    python -m src.yield_panel.plan_build evaluate   # writes data/yield_panel/planning/results_*.csv

District and state features are sown-area-weighted averages of municipality features. The weights are each
municipality's mean rainfed sown area for that crop over 2003-2025, fixed across years, so the historic
years (before municipal data exists) use the same map.
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from src.yield_panel import ablation, historic, planning, weather
from src.yield_panel import models as pm
from src.yield_panel.weather import WEATHER_FEATURES

OUT = Path("data/yield_panel/planning")
POWER_LONG = Path("data/yield_panel/power_municipal_1982_2025.csv")
NATIONAL = Path("data/yield_panel/panel_national_enriched.csv")
UNIT = ["state_id", "mun_id"]
SEASON_RAIN_SOURCES = {"chirps": [f"chirps_{c}" for c in ablation.RAIN]}


CHIRPS_LONG = Path("data/yield_panel/chirps_municipal_1999_2025.csv")


def municipal_inputs():
    """Long municipal weather: POWER 1982-2025, CHIRPS 1999-2025, NDVI pre-season 2003-2025."""
    power = pd.read_csv(POWER_LONG).drop(columns="cell_id")
    national = pd.read_csv(NATIONAL)
    if not CHIRPS_LONG.exists():
        from src.yield_panel import enrich, gridded

        pts = national.drop_duplicates(UNIT)[[*UNIT, "lat", "lon"]].reset_index(drop=True)
        enrich.rain_block(pts, range(1999, 2026), "chirps", bbox=gridded.bbox_for(pts)).to_csv(CHIRPS_LONG, index=False)
    chirps = pd.read_csv(CHIRPS_LONG)
    veg = [c for c in national.columns if c.startswith(("ndvi_pre", "evi_pre"))]
    veg_by_year = national.drop_duplicates([*UNIT, "year"])[[*UNIT, "year", *veg]]
    feats = power.merge(chirps, on=[*UNIT, "year"], how="left").merge(veg_by_year, on=[*UNIT, "year"], how="left")
    clim = power.groupby(UNIT)["rain_season_mm"].mean().rename("clim_rain_season_mm").reset_index()
    munis = weather.load_municipalities()[[*UNIT, "lat", "lon", "alt_m"]].merge(clim, on=UNIT)
    return national, feats, munis


def finish(panel, indices, lag_outcomes=True):
    """Lags, ocean indices, interactions."""
    panel = planning.add_lags(panel, planning.LAST_SEASON_SOURCE)
    if lag_outcomes:
        panel = planning.add_lags(panel, ["yield_t_ha", "failure_rate"])
    panel = panel.merge(indices, on="year", how="left")
    panel, _ = planning.add_interactions(panel)
    return panel


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    indices = planning.index_features()
    national, feats, munis = municipal_inputs()
    feature_cols = [c for c in feats.columns if c not in [*UNIT, "year"]]

    # Municipal: the national panel's outcomes with the long features (2002 lags available from the long POWER).
    outcomes = national[["crop", *UNIT, "year", "sown_ha", "yield_t_ha", "failure_rate"]]
    lagged = planning.add_lags(feats.assign(crop="_"), planning.LAST_SEASON_SOURCE, keys=UNIT).drop(columns="crop")
    m = outcomes.merge(lagged, on=[*UNIT, "year"], how="left").merge(munis, on=UNIT, how="left")
    m = planning.add_lags(m, ["yield_t_ha", "failure_rate"])
    m = m.merge(indices, on="year", how="left")
    m, _ = planning.add_interactions(m)
    m.to_parquet(OUT / "municipal.parquet", index=False)

    # Weights: municipality mean sown area per crop, with its district.
    ddr = ablation.district_map(years=range(2003, 2026))
    weights = (national.groupby(["crop", *UNIT])["sown_ha"].mean().rename("weight").reset_index()
               .merge(ddr, on=UNIT))
    static = munis.merge(weights, on=UNIT)

    districts, states = historic.long_panels()
    for level, table, keys in [("district", districts, ["state_id", "ddr"]), ("state", states, ["state_id"])]:
        f = historic.area_weighted_features(feats, weights, keys, feature_cols)
        s = static.groupby(["crop", *keys]).apply(
            lambda g: pd.Series({c: np.average(g[c], weights=g["weight"]) for c in ["lat", "lon", "alt_m", "clim_rain_season_mm"]}),
            include_groups=False).reset_index()
        p = table.merge(f, on=["crop", *keys, "year"], how="inner").merge(s, on=["crop", *keys], how="left")
        p = p[p["sown_ha"] >= 200]
        p = finish(p, indices)
        counts = p.groupby(["crop", *UNIT])["year"].transform("nunique")
        p = p[counts >= 12].reset_index(drop=True)
        p.to_parquet(OUT / f"{level}.parquet", index=False)
        print(level, p.shape, p.groupby("crop").size().to_dict(), f"{p.year.min()}-{p.year.max()}", flush=True)
    print("municipal", m.shape, flush=True)


DESIGNS = {  # level -> (test years, min training years); longest histories first
    "state": (range(1995, 2026), 12),
    "district": (range(2010, 2026), 10),
    "municipal": (range(2014, 2026), 8),
}
STATIC = ["lat", "lon", "alt_m", "clim_rain_season_mm"]


def evaluate(crops=("maize", "bean", "sorghum"), draws=1000):
    results, inseason, predictions = [], [], []
    for level, (test_years, min_train) in DESIGNS.items():
        data = pd.read_parquet(OUT / f"{level}.parquet")
        sets = planning.planning_sets(data.columns, with_ndvi=False)
        needed = sorted(set().union(*(w for w, _ in sets.values())))
        complete = data.dropna(subset=needed)
        print(f"{level}: {len(complete)} of {len(data)} rows complete", flush=True)
        for crop in crops:
            for target in ["yield_t_ha", "failure_rate"]:
                d = complete[complete["crop"] == crop]
                t, preds = ablation.evaluate_sets(d, crop, target, sets, test_years, min_train, draws, static=STATIC)
                results.append(t.assign(level=level))
                predictions += [p.assign(level=level, crop=crop, target=target, features=name) for name, p in preds.items()]
                print(t[["crop", "target", "features", "model", "skill", "gain_ci_low", "gain_ci_high"]].round(3).to_string(index=False), flush=True)
        # In-season check on the long panels: realized-season weather (POWER, plus CHIRPS from 1998).
        if level != "municipal":
            season_sets = {"power (season)": (WEATHER_FEATURES, []),
                           "power + chirps (season)": (WEATHER_FEATURES + SEASON_RAIN_SOURCES["chirps"], [])}
            have = data.dropna(subset=WEATHER_FEATURES + SEASON_RAIN_SOURCES["chirps"])
            for crop in crops:
                for target in ["yield_t_ha", "failure_rate"]:
                    t, _ = ablation.evaluate_sets(have[have["crop"] == crop], crop, target, season_sets,
                                                  range(max(2010, test_years.start), 2026), min_train, draws, static=STATIC)
                    inseason.append(t.assign(level=level))
    pd.concat(results).to_csv(OUT / "results_planning.csv", index=False)
    pd.concat(predictions).to_parquet(OUT / "predictions_planning.parquet", index=False)
    pd.concat(inseason).to_csv(OUT / "results_inseason_long.csv", index=False)

    # Pre-season NDVI (2003 on), municipal level, against the same design without it.
    data = pd.read_parquet(OUT / "municipal.parquet")
    sets = planning.planning_sets(data.columns, with_ndvi=True)
    keep = {k: sets[k] for k in ["all (incl. last outcome)", "all + preseason ndvi"] if k in sets}
    needed = sorted(set().union(*(w for w, _ in keep.values())))
    complete = data.dropna(subset=needed)
    rows = []
    for crop in crops:
        for target in ["yield_t_ha", "failure_rate"]:
            t, _ = ablation.evaluate_sets(complete[complete["crop"] == crop], crop, target, keep, range(2014, 2026), 8,
                                          draws, static=STATIC)
            rows.append(t.assign(level="municipal"))
    pd.concat(rows).to_csv(OUT / "results_planning_ndvi.csv", index=False)
    print("EVALUATION DONE", flush=True)


def preseason_now(year, munis, workers=4):
    """Pre-season features for `year` (Nov of year-1 to Apr of year) per municipality, from POWER."""
    from concurrent.futures import ThreadPoolExecutor

    from src.data_ingestion import power

    cells = weather.assign_cells(munis)
    path = OUT / f"power_preseason_{year}.csv"
    if path.exists():
        by_cell = pd.read_csv(path)
    else:
        def one(c):
            daily = power.to_dataframe(power.fetch_daily_point(c.cell_lat, c.cell_lon, f"{year - 1}1101", f"{year}0430",
                                                               parameters=weather.PARAMETERS))
            row = planning.preseason_from_daily(daily, [year]).iloc[0].to_dict()
            row["rain_pre_season_mm"] = daily["PRECTOTCORR"].sum()
            row["cell_id"] = c.cell_id
            return row
        with ThreadPoolExecutor(workers) as pool:
            by_cell = pd.DataFrame(list(pool.map(one, cells.drop_duplicates("cell_id").itertuples())))
        by_cell.to_csv(path, index=False)
    return cells[[*UNIT, "cell_id"]].merge(by_cell, on="cell_id").drop(columns="cell_id")


def best_set(results, level, crop, target):
    """The pre-registered choice: highest skill among sets whose gain interval is above zero. When no set
    beats the bar in testing, the outlook is the bar itself (the unit's average + trend)."""
    r = results[(results.level == level) & (results.crop == crop) & (results.target == target)]
    sig = r[r.gain_ci_low > 0]
    if sig.empty:
        return "bar", "mean_trend", False
    pick = sig.sort_values("skill").iloc[-1]
    return pick["features"], pick["model"], True


def outlook(year=2026, crops=("maize", "bean", "sorghum"), level="district", threshold=0.3):
    """Pre-season outlook for `year` from what was known by April 30: per unit, expected failure rate and yield
    with 10-90% ranges from the model's own out-of-sample errors, next to the average + trend bar."""
    history = pd.read_parquet(OUT / f"{level}.parquet")
    results = pd.read_csv(OUT / "results_planning.csv")
    preds = pd.read_parquet(OUT / "predictions_planning.parquet")
    national, feats, munis = municipal_inputs()
    pre = preseason_now(year, munis[[*UNIT, "lat", "lon"]])
    ddr = ablation.district_map(years=range(2003, 2026))
    weights = national.groupby(["crop", *UNIT])["sown_ha"].mean().rename("weight").reset_index().merge(ddr, on=UNIT)
    keys = ["state_id", "ddr"] if level == "district" else ["state_id"]
    pre_cols = [c for c in pre.columns if c not in [*UNIT, "year"]]
    agg = historic.area_weighted_features(pre.assign(year=year), weights, keys, pre_cols)

    last = history[history.year == year - 1]
    new = last[["crop", "state_id", "mun_id", *[k for k in keys if k not in ("state_id",)], "lat", "lon", "alt_m",
                "clim_rain_season_mm", "sown_ha", *planning.LAST_SEASON_SOURCE, "yield_t_ha", "failure_rate"]].copy()
    new = new.rename(columns={c: f"{c}_prev" for c in [*planning.LAST_SEASON_SOURCE, "yield_t_ha", "failure_rate"]})
    new["year"] = year
    new = new.merge(agg, on=["crop", *keys, "year"], how="left").merge(planning.index_features(), on="year", how="left")
    base = [c for c in history.columns if "_x_" not in c]
    both = pd.concat([history[base], new.reindex(columns=base)], ignore_index=True)
    both, _ = planning.add_interactions(both)
    hist, upcoming = both[both.year < year], both[both.year == year]

    rows = []
    for crop in crops:
        for target in ["failure_rate", "yield_t_ha"]:
            name, model_name, significant = best_set(results, level, crop, target)
            feats_set = [] if name == "bar" else planning.planning_sets(both.columns, with_ndvi=False)[name][0]
            d, feats_used = pm.add_terms(hist[hist.crop == crop].dropna(subset=[target, *feats_set]), feats_set)
            u, _ = pm.add_terms(upcoming[upcoming.crop == crop].dropna(subset=feats_set), feats_set)
            u = u[u.set_index(UNIT).index.isin(d.set_index(UNIT).index)]
            if u.empty:
                continue
            bar = pm.FixedEffects(["year"], alpha=0.0).fit(d, target)
            if name == "bar":
                model = bar
            elif model_name == "fe":
                model = pm.FixedEffects(["year", *feats_used], alpha=float(len(feats_used))).fit(d, target)
            else:
                model = pm.BoostedResidual(feats_used, [c for c in STATIC if c in d]).fit(d, target)
            p = preds[(preds.level == level) & (preds.crop == crop) & (preds.target == target)]
            p = p[p.features == (p.features.iloc[0] if name == "bar" else name)]
            thr = threshold if target == "failure_rate" else None
            out = planning.conditional_outlook(model, d, target, u, (p.observed - p[model_name]).to_numpy(), thr)
            ref = planning.conditional_outlook(bar, d, target, u, (p.observed - p.mean_trend).to_numpy(), thr)
            out = out.add_prefix("model_").join(ref.add_prefix("bar_"))
            out[[*UNIT, "sown_ha_last"]] = u[[*UNIT, "sown_ha"]].to_numpy()
            rows.append(out.assign(crop=crop, target=target, features=name, model=model_name, significant=significant))
    table = pd.concat(rows, ignore_index=True)
    table.to_csv(OUT / f"outlook_{year}_{level}.csv", index=False)
    return table


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("step", choices=["build", "evaluate", "outlook"])
    parser.add_argument("--draws", type=int, default=1000)
    parser.add_argument("--year", type=int, default=2026)
    args = parser.parse_args()
    if args.step == "build":
        build()
    elif args.step == "evaluate":
        evaluate(draws=args.draws)
    else:
        print(outlook(args.year).groupby(["crop", "target"]).size())


if __name__ == "__main__":
    main()
