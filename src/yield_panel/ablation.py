"""Which data sources help? Rolling evaluation of feature sets against the average + trend bar.

Usage (from the repo root, after build + enrich):
    python -m src.yield_panel.ablation --panel data/yield_panel/panel_central_enriched.csv

Every feature set is scored on the same rows (municipality-years where all non-SMAP features exist),
with the same expanding one-year-ahead evaluation and year-level bootstrap as models.py. SMAP starts
in 2015, so it gets its own comparison on 2015 onwards.

Also reports how much of the bar's residual is shared within SIAP districts (DDR) versus POWER cells,
tests district reporting directly (municipality pairs in the same weather cell, same vs different
district), and reruns the ablation with districts as the unit.

Outputs in --out-dir: feature_sets.csv, smap.csv, shared_variance.csv, district_check.csv,
district_panel.csv, district_level.csv.
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from src.yield_panel import models as pm
from src.yield_panel.weather import WEATHER_FEATURES

RAIN = ["rain_season_mm", "rain_jun_mm", "rain_jul_aug_mm", "rain_sep_oct_mm", "rain_pre_season_mm", "wet_days",
        "max_daily_rain_mm", "longest_dry_spell_days", "onset_doy"]
POWER_NON_RAIN = [f for f in WEATHER_FEATURES if f not in RAIN]
VEG = ["peak", "peak_month", "integral_may_oct", "jul_aug", "pre_season", "amplitude", "greenup_month"]
IGBP = ["field_capacity", "wilting_point", "profile_available_water_capacity", "bulk_density",
        "soil_carbon_density", "total_nitrogen_density"]
SMAP = ["smap_rootzone_may", "smap_rootzone_jun", "smap_rootzone_jul_aug", "smap_rootzone_jul_aug_min",
        "smap_rootzone_sep_oct", "smap_surface_jul_aug"]
STATIC = ["lat", "lon", "alt_m", "sand", "clay", "porosity"]
DISTRICT_SETS = ["power", "power + imerg", "power + chirps", "power + ndvi",
                 "all_weather (power + imerg + chirps + igbp)", "all + ndvi"]


def prefixed(prefix, names=RAIN):
    return [f"{prefix}_{n}" for n in names]


def feature_sets(columns):
    """name -> (weather features, extra static features for the boosted model)."""
    have = lambda cols: [c for c in cols if c in columns]
    imerg, chirps = have(prefixed("imerg")), have(prefixed("chirps"))
    ndvi = have(prefixed("ndvi", VEG) + prefixed("evi", VEG))
    igbp = have(IGBP)
    sets = {
        "power": (WEATHER_FEATURES, []),
        "power_temp + imerg_rain": (POWER_NON_RAIN + imerg, []),
        "power_temp + chirps_rain": (POWER_NON_RAIN + chirps, []),
        "power + imerg": (WEATHER_FEATURES + imerg, []),
        "power + chirps": (WEATHER_FEATURES + chirps, []),
        "power + igbp_soils": (WEATHER_FEATURES, igbp),
        "power + ndvi": (WEATHER_FEATURES + ndvi, []),
        "all_weather (power + imerg + chirps + igbp)": (WEATHER_FEATURES + imerg + chirps, igbp),
        "all + ndvi": (WEATHER_FEATURES + imerg + chirps + ndvi, igbp + have(["cropland_share"])),
    }
    return {k: v for k, v in sets.items() if v[0]}


def evaluate_sets(data, crop, target, sets, test_years, min_train_years=8, draws=500, static=None):
    """Score each feature set's fe and gbm models against the bar. `static` defaults to STATIC (columns that exist)."""
    rows, preds_all = [], {}
    base_static = [c for c in (STATIC if static is None else static) if c in data.columns]
    for name, (weather, extra_static) in sets.items():
        d, feats = pm.add_terms(data, weather)
        gbm_static = base_static + [c for c in extra_static if c in data.columns]
        models = {
            "mean_trend": lambda: pm.FixedEffects(["year"], alpha=0.0),
            "fe": lambda: pm.FixedEffects(["year", *feats], alpha=float(len(feats))),
            "gbm": lambda: pm.BoostedResidual(feats, gbm_static),
        }
        preds = pm.rolling_evaluation(d, target, models, test_years, min_train_years=min_train_years)
        table = pm.score(preds, models)
        for model in ["fe", "gbm"]:
            ci = pm.bootstrap_skill(preds, model, draws=draws)
            rows.append({"crop": crop, "target": target, "features": name, "model": model, "n_features": len(feats),
                         "skill": table.loc[model, "skill_vs_bar"], "rmse": table.loc[model, "rmse"],
                         "rmse_bar": table.loc["mean_trend", "rmse"], "gain_ci_low": ci["ci_low"],
                         "gain_ci_high": ci["ci_high"], "rows": len(preds), "years": preds["year"].nunique()})
        preds_all[name] = preds
    return pd.DataFrame(rows), preds_all


def district_map(siap_dir=Path("data/siap"), years=range(2016, 2026)):
    """Each municipality's SIAP district (DDR): the most frequent idddr across recent years."""
    parts = []
    for year in years:
        path = siap_dir / f"{year}.csv"
        if path.exists():
            f = pd.read_csv(path, encoding="cp1252", usecols=lambda c: c.strip().lower() in {"idestado", "idmunicipio", "idddr"})
            f.columns = [c.strip().lower() for c in f.columns]
            parts.append(f)
    f = pd.concat(parts)
    return (f.groupby(["idestado", "idmunicipio"])["idddr"].agg(lambda s: s.mode().iloc[0]).reset_index()
            .rename(columns={"idestado": "state_id", "idmunicipio": "mun_id", "idddr": "ddr"}))


def district_panel(panel, feature_cols, min_years=10):
    """Aggregate municipalities to SIAP districts (DDR): summed areas and production, sown-area-weighted features.

    The district id is stored in `mun_id` (with `state_id`) so the models' unit keys work unchanged.
    """
    rows = []
    for (crop, state, ddr, year), g in panel.groupby(["crop", "state_id", "ddr", "year"]):
        w = g["sown_ha"].to_numpy(float)
        vals = g[feature_cols].to_numpy(float)
        ok = np.isfinite(vals)
        weight = (ok * w[:, None]).sum(axis=0)
        means = np.where(weight > 0, np.nansum(np.where(ok, vals, 0) * w[:, None], axis=0) / np.where(weight > 0, weight, 1), np.nan)
        row = {"crop": crop, "state_id": state, "mun_id": ddr, "year": year, "n_municipalities": len(g),
               "sown_ha": w.sum(), "harvested_ha": g["harvested_ha"].sum(), "lost_ha": g["lost_ha"].sum(),
               "production_t": g["production_t"].sum()}
        row.update(dict(zip(feature_cols, means)))
        rows.append(row)
    d = pd.DataFrame(rows)
    d["yield_t_ha"] = np.where(d["harvested_ha"] > 0, d["production_t"] / d["harvested_ha"], np.nan)
    d["failure_rate"] = (d["lost_ha"] / d["sown_ha"].where(d["sown_ha"] > 0)).clip(0, 1)
    counts = d.groupby(["crop", "state_id", "mun_id"])["year"].transform("nunique")
    return d[counts >= min_years].reset_index(drop=True)


def district_check(panel, crop, target):
    """Within the same POWER cell and year: residual correlation of municipality pairs in the same vs a
    different SIAP district, and the share of values identical to another municipality's in the district-year."""
    d = panel[panel["crop"] == crop].dropna(subset=[target, "ddr"]).copy()
    d["r"] = d[target] - pm.FixedEffects(["year"], alpha=0).fit(d, target).predict(d)
    same, diff = [], []
    for _, g in d.groupby(["cell_id", "year"]):
        if len(g) < 2:
            continue
        r, ddr = g["r"].to_numpy(), g["ddr"].to_numpy()
        i, j = np.triu_indices(len(g), 1)
        match = ddr[i] == ddr[j]
        same.append(np.c_[r[i][match], r[j][match]])
        diff.append(np.c_[r[i][~match], r[j][~match]])
    same, diff = np.vstack(same), np.vstack(diff)
    nonzero = d[d[target] > 0]
    dup = nonzero.groupby(["state_id", "ddr", "year"])[target].transform(lambda s: s.round(4).duplicated(keep=False))
    return {"crop": crop, "target": target,
            "r_same_cell_same_district": float(np.corrcoef(same.T)[0, 1]), "pairs_same": len(same),
            "r_same_cell_other_district": float(np.corrcoef(diff.T)[0, 1]) if len(diff) > 30 else np.nan,
            "pairs_other": len(diff), "share_identical_nonzero": float(dup.mean())}


def shared_variance(panel, crop, target, groups):
    """Leave-one-out share of the bar's residual variance shared with other municipalities in the same group-year."""
    d = panel[panel["crop"] == crop].dropna(subset=[target]).copy()
    d["r"] = d[target] - pm.FixedEffects(["year"], alpha=0).fit(d, target).predict(d)
    out = {"crop": crop, "target": target}
    for name, keys in groups.items():
        g = d.groupby([*keys, "year"])["r"]
        n, s = g.transform("size"), g.transform("sum")
        loo = ((s - d["r"]) / (n - 1)).where(n > 1)
        m = loo.notna()
        out[f"shared_{name}"] = float(np.cov(d["r"][m], loo[m])[0, 1] / d["r"][m].var())
        out[f"size_{name}"] = float(d.groupby([*keys, "year"]).size().mean())
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--panel", type=Path, default=Path("data/yield_panel/panel_central_enriched.csv"))
    parser.add_argument("--crops", nargs="+", default=["maize", "bean", "sorghum"])
    parser.add_argument("--out-dir", type=Path, default=Path("data/yield_panel/ablation"))
    parser.add_argument("--draws", type=int, default=500)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    panel = pd.read_csv(args.panel)

    sets = feature_sets(panel.columns)
    needed = sorted(set().union(*(w + s for w, s in sets.values())))
    complete = panel.dropna(subset=needed)
    print(f"{len(complete)} of {len(panel)} rows have every non-SMAP feature", flush=True)

    results = []
    for crop in args.crops:
        for target in ["yield_t_ha", "failure_rate"]:
            table, _ = evaluate_sets(complete[complete["crop"] == crop], crop, target, sets, range(2014, 2026),
                                     draws=args.draws)
            results.append(table)
            print(table[["features", "model", "skill", "gain_ci_low", "gain_ci_high"]].round(3).to_string(index=False), flush=True)
    results = pd.concat(results, ignore_index=True)
    results.to_csv(args.out_dir / "feature_sets.csv", index=False)

    # SMAP: 2015 onwards only (training from 2015, test 2020-2025).
    smap_cols = [c for c in SMAP if c in panel.columns]
    if smap_cols:
        recent = panel[panel["year"] >= 2015].dropna(subset=WEATHER_FEATURES + smap_cols)
        smap_sets = {"power (2015+)": (WEATHER_FEATURES, []), "power + smap (2015+)": (WEATHER_FEATURES + smap_cols, [])}
        smap_rows = []
        for crop in args.crops:
            for target in ["yield_t_ha", "failure_rate"]:
                table, _ = evaluate_sets(recent[recent["crop"] == crop], crop, target, smap_sets, range(2020, 2026),
                                         min_train_years=5, draws=args.draws)
                smap_rows.append(table)
        smap_rows = pd.concat(smap_rows, ignore_index=True)
        smap_rows.to_csv(args.out_dir / "smap.csv", index=False)
        print(smap_rows[["crop", "target", "features", "model", "skill", "gain_ci_low", "gain_ci_high"]].round(3).to_string(index=False))

    # Is the shared shock administrative (SIAP district) or spatial (POWER cell)?
    try:
        ddr = district_map()
        p = panel.merge(ddr, on=["state_id", "mun_id"], how="left")
        shares = pd.DataFrame([shared_variance(p.dropna(subset=["ddr"]), c, t,
                                               {"state": ["state_id"], "ddr": ["state_id", "ddr"], "cell": ["cell_id"]})
                               for c in args.crops for t in ["yield_t_ha", "failure_rate"]])
        shares.to_csv(args.out_dir / "shared_variance.csv", index=False)
        print(shares.round(3).to_string(index=False))
        checks = pd.DataFrame([district_check(p, c, t) for c in args.crops for t in ["yield_t_ha", "failure_rate"]])
        checks.to_csv(args.out_dir / "district_check.csv", index=False)
        print(checks.round(3).to_string(index=False))
    except (FileNotFoundError, ValueError) as exc:
        print("Skipping district check:", exc)
        return

    # The same ablation at SIAP's own unit: districts.
    feature_cols = sorted(set(needed) | set(STATIC))
    districts = district_panel(p.dropna(subset=["ddr"]), feature_cols)
    districts.to_csv(args.out_dir / "district_panel.csv", index=False)
    keep = {k: v for k, v in sets.items() if k in DISTRICT_SETS}
    complete_d = districts.dropna(subset=sorted(set().union(*(w + s for w, s in keep.values()))))
    district_rows = []
    for crop in args.crops:
        for target in ["yield_t_ha", "failure_rate"]:
            table, _ = evaluate_sets(complete_d[complete_d["crop"] == crop], crop, target, keep, range(2014, 2026),
                                     draws=max(args.draws, 1000))
            district_rows.append(table)
    district_rows = pd.concat(district_rows, ignore_index=True)
    district_rows.to_csv(args.out_dir / "district_level.csv", index=False)
    print(district_rows[["crop", "target", "features", "model", "skill", "gain_ci_low", "gain_ci_high"]].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
