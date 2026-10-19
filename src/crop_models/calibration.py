"""Opt-in calibration of the WOFOST rotation simulator to observed Texcoco yields (SIAP).

The default simulator (wofost_rotations.py) uses European WOFOST parameter sets and research-station
fertilizer, so it simulates attainable yields 2-5x above what Texcoco farms report. This module fits a
few interpretable knobs per crop to SIAP rainfed spring-summer yields per sown hectare (farm_tool.siap_texcoco):

- tsum_scale: multiplies TSUM1 and TSUM2 (thermal time to flowering and from flowering to maturity),
  i.e. a shorter- or longer-cycle cultivar than the European set.
- photosynthesis_scale: multiplies leaf photosynthesis (AMAX_REF, AMAX_SLP and EFFTB). A lumped
  farm-level efficiency standing in for what WOFOST does not simulate (weeds, pests, diseases, plant
  stand, landrace genetics), applied inside the model so it still interacts with water, N and frost.
- n_recovery: share of fertilizer N the crop recovers (default 0.5), i.e. effective N supply on farms.
- site mineralization_rate: share of IGBP soil N mineralized per season (default 0.005), fitted with maize.

Fit years are 2006-2021 only (2005 is spin-up); 2022-2025 is a holdout reported but never used to fit.
Everything is opt-in: default CLI runs and data/rotations/*.csv are unchanged, and calibrated runs are
written to data/rotations_calibrated/. Results and diagnosis: CALIBRATION_RESULTS.md.

Usage (from the repo root):
    python -m src.crop_models.calibration --sensitivity     # one-at-a-time diagnostics (water- and N-limited only)
    python -m src.crop_models.calibration --fit             # grid search on 2006-2021, prints before/after
    python -m src.crop_models.calibration --simulate        # calibrated baseline -> data/rotations_calibrated/
    python -m src.crop_models.calibration --simulate --scenarios baseline rain80 no_fertilizer
"""

import argparse
import itertools
import json
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from .farm_tool import siap_texcoco
from .rotation_experiments import SCENARIOS, TARGET

CALIBRATION_YEARS = range(2006, 2022)
HOLDOUT_YEARS = range(2022, 2026)
OUT_DIR = Path("data/rotations_calibrated")
CROP_KEYS = ("maize", "barley", "fababean")
SITE_KEYS = ("mineralization_rate", "frost_tmin", "rooting_depth_cm")

# Knobs per crop and for the site; the defaults reproduce the uncalibrated simulator
# (wofost_rotations.N_RECOVERY and MINERALIZATION_RATE).
DEFAULT = {"tsum_scale": 1.0, "photosynthesis_scale": 1.0, "n_recovery": 0.5}
SITE_DEFAULT = {"mineralization_rate": 0.005}

# Fitted with --fit on 2006-2021 (see CALIBRATION_RESULTS.md).
CALIBRATED = {
    "maize": {"tsum_scale": 1.0, "photosynthesis_scale": 1.0, "n_recovery": 0.2},
    "barley": {"tsum_scale": 0.8, "photosynthesis_scale": 0.5, "n_recovery": 0.5},
    "fababean": {"tsum_scale": 1.0, "photosynthesis_scale": 0.45, "n_recovery": 0.5},
    "site": {"mineralization_rate": 0.0025},
}


def scale_table(table, factor):
    """Multiply the y values of a WOFOST interpolation table [x1, y1, x2, y2, ...]."""
    return [value * factor if i % 2 else value for i, value in enumerate(table)]


def variety_overrides(params, tsum_scale=1.0, photosynthesis_scale=1.0):
    """WOFOST parameter values that apply the knobs to one variety's parameters (only those that change)."""
    out = {}
    if tsum_scale != 1.0:
        out.update(TSUM1=params["TSUM1"] * tsum_scale, TSUM2=params["TSUM2"] * tsum_scale)
    if photosynthesis_scale != 1.0:
        out.update(AMAX_REF=params["AMAX_REF"] * photosynthesis_scale,
                   AMAX_SLP=params["AMAX_SLP"] * photosynthesis_scale,
                   EFFTB=scale_table(params["EFFTB"], photosynthesis_scale))
    return out


def simulator_settings(knobs, variety_params):
    """The `calibration` dict for wofost_rotations.simulate_rotations from knobs.

    knobs: {crop key: {tsum_scale, photosynthesis_scale, n_recovery}, "site": {mineralization_rate,
    frost_tmin, rooting_depth_cm}}; missing crops, knobs or site entries keep the simulator defaults.
    variety_params: {crop key: that variety's WOFOST parameters}.
    """
    crop_params, n_recovery = {}, {}
    for crop, values in knobs.items():
        if crop == "site":
            continue
        values = {**DEFAULT, **values}
        crop_params[crop] = variety_overrides(variety_params[crop], values["tsum_scale"],
                                              values["photosynthesis_scale"])
        n_recovery[crop] = values["n_recovery"]
    return {"crop_params": crop_params, "n_recovery": n_recovery, **knobs.get("site", {})}


def split_candidate(candidate):
    """(crop knobs, site knobs) of one grid candidate."""
    site = {k: v for k, v in candidate.items() if k in SITE_KEYS}
    return {k: v for k, v in candidate.items() if k not in SITE_KEYS}, site


def distance_from_default(candidate):
    """Relative distance of a candidate's knobs from the defaults, used to break RMSE ties."""
    defaults = {**DEFAULT, **SITE_DEFAULT}
    return sum(abs(value / defaults[key] - 1) for key, value in candidate.items() if key in defaults)


def crop_year_yields(seasons):
    """Simulated yield per crop and year, averaged over rotations and phases (as in farm_tool.farm_gap)."""
    return seasons.groupby(["crop", "year"])[TARGET].mean().rename("simulated_t_ha")


def paired(simulated, siap):
    """Simulated and observed (SIAP yield per sown ha) per crop and year, where both exist."""
    observed = siap.set_index(["crop", "year"])["yield_sown_t_ha"].rename("observed_t_ha")
    return pd.concat([simulated, observed], axis=1, join="inner").dropna().reset_index()


def fit_metrics(both, years):
    """Per crop over `years`: level (means and ratio), bias, RMSE and year-to-year correlation."""
    rows = []
    for crop, group in both[both["year"].isin(years)].groupby("crop"):
        error = group["simulated_t_ha"] - group["observed_t_ha"]
        rows.append({
            "crop": crop, "years": len(group),
            "simulated_mean_t_ha": group["simulated_t_ha"].mean(),
            "observed_mean_t_ha": group["observed_t_ha"].mean(),
            "ratio": group["simulated_t_ha"].mean() / group["observed_t_ha"].mean(),
            "bias_t_ha": error.mean(),
            "rmse_t_ha": float(np.sqrt((error ** 2).mean())),
            "correlation": group["simulated_t_ha"].corr(group["observed_t_ha"]) if len(group) > 2 else np.nan,
        })
    return pd.DataFrame(rows).set_index("crop")


def grid(**values):
    """Every combination of the given knob values, as dicts."""
    return [dict(zip(values, combo)) for combo in itertools.product(*values.values())]


def best_candidate(scores, crop):
    """The candidate with the lowest calibration-year RMSE for `crop`.

    RMSE and correlation are compared at 3 decimals; remaining ties go to the candidate with the
    highest correlation, then (if scores has a "distance" column) the one closest to the defaults.
    """
    rows = scores[scores["crop"] == crop].assign(rmse=scores["rmse_t_ha"].round(3),
                                                 corr=-scores["correlation"].round(3))
    keys = ["rmse", "corr"] + (["distance"] if "distance" in rows else [])
    return rows.sort_values(keys, kind="stable").iloc[0]


# --- Simulation (needs PCSE, cached NASA POWER weather and IGBP/GLDAS soils) ---

_WORKER = {}


def _init_worker(lat, lon, soil, total_n):
    from pcse.input import NASAPowerWeatherDataProvider, YAMLCropDataProvider
    from pcse.models import Wofost81_NWLP_CWB_CNB

    _WORKER.update(weather=NASAPowerWeatherDataProvider(latitude=lat, longitude=lon),
                   crops=YAMLCropDataProvider(Wofost81_NWLP_CWB_CNB), soil=soil, total_n=total_n)


def _simulate(task):
    """Water- and N-limited seasons of the given rotations under one calibration (worker process)."""
    from .wofost_rotations import LEVELS, ROTATIONS, ROOTING_DEPTH_CM, simulate_rotation

    label, calibration, rotations, start_year, end_year = task
    calibration = dict(calibration)
    soil = dict(_WORKER["soil"])
    if "rooting_depth_cm" in calibration:  # as in simulate_rotations
        soil["RDMSOL"] = min(ROOTING_DEPTH_CM, calibration.pop("rooting_depth_cm"))
    settings = {"sowing": "onset", "frost_tmin_offset": 0.0, "n_scale": 1.0, **calibration}
    frames = [simulate_rotation(name, ROTATIONS[name], _WORKER["weather"], _WORKER["crops"], soil,
                                _WORKER["total_n"], start_year, end_year, settings,
                                {"water_n": LEVELS["water_n"]})[0]
              for name in rotations]
    return label, pd.concat(frames, ignore_index=True)


def variety_parameters():
    """{crop key: WOFOST parameters of the variety used by wofost_rotations.CROPS}."""
    from pcse.input import YAMLCropDataProvider
    from pcse.models import Wofost81_NWLP_CWB_CNB

    from .wofost_rotations import CROPS

    provider = YAMLCropDataProvider(Wofost81_NWLP_CWB_CNB)
    params = {}
    for key, crop in CROPS.items():
        provider.set_active_crop(crop["crop"], crop["variety"])
        params[key] = dict(provider)
    return params


class Runner:
    """Runs many calibrations in parallel, sharing the site's soil (read once)."""

    def __init__(self, lat=19.53, lon=-98.85, start_year=2005, end_year=2025, workers=None):
        from .wofost_rotations import site_soil

        soil, total_n = site_soil(lat, lon)
        self.years = (start_year, end_year)
        self.pool = ProcessPoolExecutor(workers, initializer=_init_worker, initargs=(lat, lon, soil, total_n))

    def run(self, calibrations, rotations):
        """{label: seasons} for {label: calibration dict}, simulating only `rotations`."""
        tasks = [(label, cal, rotations, *self.years) for label, cal in calibrations.items()]
        return dict(self.pool.map(_simulate, tasks))

    def close(self):
        self.pool.shutdown()


def rotations_with(crop):
    from .wofost_rotations import ROTATIONS

    return [name for name, sequence in ROTATIONS.items() if crop in sequence]


def score(seasons_by_label, siap, crops=CROP_KEYS):
    """Calibration- and holdout-year metrics per label and crop."""
    rows = []
    for label, seasons in seasons_by_label.items():
        both = paired(crop_year_yields(seasons[seasons["crop"].isin(crops)]), siap)
        for split, years in (("calibration", CALIBRATION_YEARS), ("holdout", HOLDOUT_YEARS)):
            metrics = fit_metrics(both, years).reset_index()
            metrics.insert(0, "split", split)
            metrics.insert(0, "label", label)
            rows.append(metrics)
    return pd.concat(rows, ignore_index=True)


def sensitivity(runner, siap, variety):
    """One-at-a-time changes from the default simulator, all crops at once, all rotations."""
    from .wofost_rotations import ROTATIONS

    all_crops = lambda **k: simulator_settings({c: k for c in CROP_KEYS}, variety)  # noqa: E731
    cases = {
        "default": {},
        "tsum x0.8": all_crops(tsum_scale=0.8),
        "tsum x0.65": all_crops(tsum_scale=0.65),
        "photosynthesis x0.5": all_crops(photosynthesis_scale=0.5),
        "n_recovery 0.25": all_crops(n_recovery=0.25),
        "mineralization x0.5": {"mineralization_rate": 0.0025},
        "frost at -2 C": {"frost_tmin": -2.0},
        "soil 50 cm": {"rooting_depth_cm": 50},
    }
    runs = runner.run(cases, list(ROTATIONS))
    return score(runs, siap), maize_diagnostics(runs)


def maize_diagnostics(runs):
    """Per label: how maize seasons end in 2006-2021 (frost vs maturity) and the 2023 maize yields."""
    rows = []
    for label, seasons in runs.items():
        maize = seasons[(seasons["crop"] == "maize") & seasons["year"].isin(CALIBRATION_YEARS)]
        rows.append({"label": label, "frost_ended_share": maize["frost_ended"].mean(),
                     "matured_share": maize["maturity"].notna().mean(),
                     "median_maturity_doy": pd.to_datetime(maize["maturity"]).dt.dayofyear.median(),
                     "y2023_continuous_t_ha": seasons.query("rotation == 'maize' and year == 2023")[TARGET].iloc[0],
                     "y2023_mean_t_ha": seasons.query("crop == 'maize' and year == 2023")[TARGET].mean()})
    return pd.DataFrame(rows).set_index("label")


# Phenology is limited to cultivars that fit Texcoco's calendar: at the default TSUM, maize flowers ~87 days
# after sowing (plausible for Valles Altos hybrids) but grain fill runs into the frosts; x0.8 matures in ~155
# days. Below x0.8 the cycle is an early-maturing material farmers do not grow, and the yield fit would only
# use it to flatten year-to-year variation.
CANDIDATES = {
    # Below x0.4 photosynthesis barley and faba bean barely establish (yields collapse).
    "barley": grid(tsum_scale=[0.8, 0.9, 1.0], photosynthesis_scale=[0.4, 0.5, 0.6, 0.8], n_recovery=[0.25, 0.5]),
    # Faba bean fixes most of its N, so fertilizer recovery barely matters.
    "fababean": grid(tsum_scale=[0.8, 0.9, 1.0], photosynthesis_scale=[0.4, 0.45, 0.5, 0.55, 0.6],
                     n_recovery=[0.5]),
    # Maize is limited through N supply: earlier grids with photosynthesis x0.5-1.0 always chose 1.0, since
    # lowering photosynthesis loses the year-to-year pattern. Fertilizer recovery and soil mineralization are
    # fitted together because SIAP cannot tell them apart on its own (see CALIBRATION_RESULTS.md).
    "maize": grid(tsum_scale=[0.8, 0.9, 1.0], photosynthesis_scale=[1.0],
                  n_recovery=[0.1, 0.2, 0.25, 0.3, 0.4, 0.5], mineralization_rate=[0.0025, 0.00375, 0.005]),
}
# Maize goes last: it inherits water and N from the calibrated barley and faba bean, which barely depend on
# maize (at the fitted photosynthesis, barley is hardly N-limited and faba bean fixes its N).
FIT_ORDER = ("barley", "fababean", "maize")


def fit(runner, siap, variety, order=FIT_ORDER, candidates=CANDIDATES, history_csv=None):
    """Coordinate grid search: each crop's knobs in turn (others fixed), lowest 2006-2021 RMSE wins.

    Appends every candidate's scores to `history_csv` after each step, so a long fit can be inspected.
    """
    knobs = {**{crop: dict(DEFAULT) for crop in CROP_KEYS}, "site": {}}
    history = []
    for step, crop in enumerate(order, 1):
        cases = {}
        for candidate in candidates[crop]:
            crop_knobs, site = split_candidate(candidate)
            cases[json.dumps(candidate, sort_keys=True)] = simulator_settings(
                {**knobs, crop: crop_knobs, "site": {**knobs["site"], **site}}, variety)
        runs = runner.run(cases, rotations_with(crop))
        matured = {label: s.loc[(s["crop"] == crop) & s["year"].isin(CALIBRATION_YEARS), "maturity"].notna().mean()
                   for label, s in runs.items()}
        scores = score(runs, siap, [crop])
        scores = scores[scores["split"] == "calibration"].assign(
            step=step, matured_share=scores["label"].map(matured),
            distance=scores["label"].map(lambda label: distance_from_default(json.loads(label))))
        history.append(scores)
        knobs[crop], site = split_candidate(json.loads(best_candidate(scores, crop)["label"]))
        knobs["site"].update(site)
        print(f"step {step} {crop}: {knobs[crop]} site {knobs['site']}", flush=True)
        if history_csv:
            pd.concat(history, ignore_index=True).to_csv(history_csv, index=False)
    return knobs, pd.concat(history, ignore_index=True)


def simulate_scenarios(knobs, scenarios=("baseline",), out_dir=OUT_DIR, lat=19.53, lon=-98.85,
                       start_year=2005, end_year=2025):
    """Calibrated runs of registered scenarios (all levels, all rotations) saved to `out_dir`."""
    from .wofost_rotations import simulate_rotations

    calibration = simulator_settings(knobs, variety_parameters())
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"latitude": lat, "longitude": lon, "start_year": start_year, "end_year": end_year,
                "calibration": knobs, "scenarios": {}}
    for name in scenarios:
        scenario = SCENARIOS[name]
        print(f"Simulating calibrated {name}: {asdict(scenario)}", flush=True)
        seasons, _, _, _ = simulate_rotations(lat, lon, start_year, end_year,
                                              **{**asdict(scenario), "rain_months": scenario.rain_months or None},
                                              calibration=calibration)
        # A distinct scenario name, so calibrated and default runs can be loaded together (load_seasons).
        seasons["scenario"] = f"{name}_calibrated"
        seasons.to_csv(out_dir / f"{name}.csv", index=False)
        manifest["scenarios"][name] = asdict(scenario)
        (out_dir / "calibration.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return out_dir


def main():
    parser = argparse.ArgumentParser(description="Calibrate WOFOST rotations to SIAP Texcoco yields (opt-in).")
    parser.add_argument("--sensitivity", action="store_true", help="One-at-a-time diagnostics")
    parser.add_argument("--fit", action="store_true", help="Grid search on 2006-2021 and report before/after")
    parser.add_argument("--simulate", action="store_true", help="Run calibrated scenarios into --out-dir")
    parser.add_argument("--scenarios", nargs="+", choices=list(SCENARIOS), default=["baseline"])
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--workers", type=int)
    args = parser.parse_args()
    if not (args.sensitivity or args.fit or args.simulate):
        parser.error("Choose --sensitivity, --fit and/or --simulate")

    siap = siap_texcoco()
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", None)
    if args.sensitivity or args.fit:
        runner = Runner(workers=args.workers)
        variety = variety_parameters()
        try:
            if args.sensitivity:
                scores, extra = sensitivity(runner, siap, variety)
                print(scores.round(3).to_string(index=False))
                print(extra.round(2).to_string())
            if args.fit:
                args.out_dir.mkdir(parents=True, exist_ok=True)
                knobs, _ = fit(runner, siap, variety, history_csv=args.out_dir / "fit_history.csv")
                calibrated = simulator_settings(knobs, variety)
                runs = runner.run({"default": {}, "calibrated": calibrated, "default, no fertilizer": {"n_scale": 0.0},
                                   "calibrated, no fertilizer": {**calibrated, "n_scale": 0.0}},
                                  list(rotations_with("maize")))
                print("Fitted knobs:", json.dumps(knobs, indent=2))
                print(score(runs, siap).round(3).to_string(index=False))
                print(maize_diagnostics(runs).round(2).to_string())
                print("Mean 2006-2021 yield (t/ha) with and without fertilizer:")
                print(pd.DataFrame({label: crop_year_yields(s[s["year"].isin(CALIBRATION_YEARS)]).groupby("crop").mean()
                                    for label, s in runs.items()}).round(2).to_string())
        finally:
            runner.close()
    if args.simulate:
        print(f"Saved to {simulate_scenarios(CALIBRATED, args.scenarios, args.out_dir)}")


if __name__ == "__main__":
    main()
