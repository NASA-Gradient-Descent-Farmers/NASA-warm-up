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

Simulated maize is weighted by SIAP crop areas (farm_tool.simulated_like_siap): most Texcoco maize follows
maize. Maize candidates must also keep the fertilizer response of the Texcoco trial (TRIAL_NO_N_RATIO), since
SIAP alone cannot tell fertilizer N from soil N. Every result is compared with naive baselines (the fit-year
SIAP mean and last year's SIAP yield).

Fit years are 2006-2021 only (2005 is spin-up); 2022-2025 is a holdout reported but never used to fit.
Everything is opt-in: default CLI runs and data/rotations/*.csv are unchanged, and calibrated runs are
written to data/rotations_calibrated/. Results and diagnosis: CALIBRATION_RESULTS.md.

Usage (from the repo root):
    python -m src.crop_models.calibration --sensitivity     # one-at-a-time diagnostics (water- and N-limited only)
    python -m src.crop_models.calibration --station-check   # can the model reproduce the fertilizer trial's yields?
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

from .farm_tool import siap_texcoco, simulated_like_siap
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

# Alonso-Sanchez et al. 2023 (doi:10.28940/terra.v41i0.1577), INIFAP Texcoco: rainfed maize hybrids gave
# 5.2 t/ha without fertilizer and 5.6 t/ha with 160 kg N/ha. Maize candidates must keep their continuous-maize
# no-fertilizer / fertilized yield ratio within TRIAL_TOLERANCE of this.
TRIAL_NO_N_RATIO = 5.2 / 5.6
TRIAL_TOLERANCE = 0.1

# Fitted with --fit on 2006-2021 (see CALIBRATION_RESULTS.md). Maize keeps the default N supply: with the
# trial's small fertilizer response, its farm level comes from lower photosynthesis instead.
CALIBRATED = {
    "maize": {"tsum_scale": 0.8, "photosynthesis_scale": 0.47, "n_recovery": 0.5},
    "barley": {"tsum_scale": 0.9, "photosynthesis_scale": 0.475, "n_recovery": 0.5},
    "fababean": {"tsum_scale": 0.9, "photosynthesis_scale": 0.475, "n_recovery": 0.5},
    "site": {"mineralization_rate": 0.005},
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
            # Constant series (e.g. climatology) have no correlation; allow for floating-point noise.
            "correlation": (group["simulated_t_ha"].corr(group["observed_t_ha"])
                            if len(group) > 2 and group[["simulated_t_ha", "observed_t_ha"]].std().min() > 1e-9
                            else np.nan),
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


def continuous_maize_mean(seasons, years=CALIBRATION_YEARS):
    """Mean yield (t/ha) of maize grown after maize every year, over `years`."""
    return seasons.loc[(seasons["rotation"] == "maize") & seasons["year"].isin(years), TARGET].mean()


def fertilizer_ratio(fertilized, unfertilized, years=CALIBRATION_YEARS):
    """Mean continuous-maize yield without fertilizer divided by the same with fertilizer, over `years`."""
    return continuous_maize_mean(unfertilized, years) / continuous_maize_mean(fertilized, years)


def within_trial(scores, target=TRIAL_NO_N_RATIO, tolerance=TRIAL_TOLERANCE):
    """Rows whose fertilizer_ratio is within `tolerance` of the trial; if none is, the closest ones."""
    gap = (scores["fertilizer_ratio"] - target).abs()
    inside = scores[gap <= tolerance]
    return inside if len(inside) else scores[gap == gap.min()]


def edge_knobs(choice, candidates):
    """Knobs whose chosen value is the lowest or highest tried (the best value may lie outside the grid)."""
    return sorted(key for key, value in choice.items()
                  if len({c[key] for c in candidates}) > 1 and value in (min(c[key] for c in candidates),
                                                                         max(c[key] for c in candidates)))


def baselines(siap, fit_years=CALIBRATION_YEARS):
    """Naive predictions in the `paired` format: the fit-year SIAP mean (climatology) and last year's SIAP
    yield (persistence; years whose previous year has no observation are left out)."""
    observed = (siap.dropna(subset=["yield_sown_t_ha"])[["crop", "year", "yield_sown_t_ha"]]
                .rename(columns={"yield_sown_t_ha": "observed_t_ha"}))
    fit_mean = observed[observed["year"].isin(fit_years)].groupby("crop")["observed_t_ha"].mean()
    climatology = observed.assign(simulated_t_ha=observed["crop"].map(fit_mean))
    last_year = (observed.assign(year=observed["year"] + 1)
                 .rename(columns={"observed_t_ha": "simulated_t_ha"}))
    persistence = observed.merge(last_year, on=["crop", "year"])
    return {"climatology": climatology, "persistence": persistence}


def with_baselines(scores, siap):
    """`scores` plus climatology and persistence rows, and a skill column 1 - RMSE / RMSE(climatology)."""
    rows = [scores]
    for name, both in baselines(siap).items():
        for split, years in (("calibration", CALIBRATION_YEARS), ("holdout", HOLDOUT_YEARS)):
            metrics = fit_metrics(both, years).reset_index()
            rows.append(metrics.assign(label=name, split=split))
    table = pd.concat(rows, ignore_index=True)
    climatology = table[table["label"] == "climatology"].set_index(["crop", "split"])["rmse_t_ha"]
    reference = pd.MultiIndex.from_frame(table[["crop", "split"]]).map(climatology.get)
    return table.assign(skill=1 - table["rmse_t_ha"] / np.asarray(reference, dtype=float))


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


def score(seasons_by_label, siap, crops=CROP_KEYS, splits=("calibration", "holdout")):
    """Metrics per label, crop and split (simulated yields combined as in farm_tool.simulated_like_siap)."""
    rows = []
    years_of = {"calibration": CALIBRATION_YEARS, "holdout": HOLDOUT_YEARS}
    for label, seasons in seasons_by_label.items():
        both = paired(simulated_like_siap(seasons, siap), siap)
        both = both[both["crop"].isin(crops)]
        for split, years in ((split, years_of[split]) for split in splits):
            metrics = fit_metrics(both, years).reset_index()
            metrics.insert(0, "split", split)
            metrics.insert(0, "label", label)
            rows.append(metrics)
    return pd.concat(rows, ignore_index=True)


def sensitivity(runner, siap, variety):
    """One-at-a-time changes from the default simulator, all crops at once, all rotations.

    Only fit years are scored, so design choices made from these diagnostics never see the holdout.
    """
    from .wofost_rotations import ROTATIONS

    all_crops = lambda **k: simulator_settings({c: k for c in CROP_KEYS}, variety)  # noqa: E731
    cases = {
        "default": {},
        "tsum x0.8": all_crops(tsum_scale=0.8),
        "tsum x0.65": all_crops(tsum_scale=0.65),
        "photosynthesis x0.5": all_crops(photosynthesis_scale=0.5),
        "n_recovery 0.25": all_crops(n_recovery=0.25),
        "mineralization x0.5": {"mineralization_rate": 0.0025},
        "frost kills at -2 C, not 0 C (fewer frosts)": {"frost_tmin": -2.0},
        "soil 50 cm": {"rooting_depth_cm": 50},
    }
    runs = runner.run(cases, list(ROTATIONS))
    return score(runs, siap, splits=("calibration",)), maize_diagnostics(runs)


def maize_diagnostics(runs):
    """Per label: how maize seasons end in the fit years (frost vs maturity)."""
    rows = []
    for label, seasons in runs.items():
        maize = seasons[(seasons["crop"] == "maize") & seasons["year"].isin(CALIBRATION_YEARS)]
        rows.append({"label": label, "frost_ended_share": maize["frost_ended"].mean(),
                     "matured_share": maize["maturity"].notna().mean(),
                     "median_maturity_doy": pd.to_datetime(maize["maturity"]).dt.dayofyear.median()})
    return pd.DataFrame(rows).set_index("label")


# Phenology is limited to cultivars that fit Texcoco's calendar: at the default TSUM, maize flowers ~87 days
# after sowing (plausible for Valles Altos hybrids) but grain fill runs into the frosts; x0.8 matures in ~155
# days. Below x0.8 the cycle is an early-maturing material farmers do not grow, and the yield fit would only
# use it to flatten year-to-year variation. Below x0.35 photosynthesis the crops barely establish.
# Soil N release is capped at 100 kg/season (wofost_rotations.run_season, PCSE's valid NSOILBASE range): with
# 12,709 kg/ha of soil N, shares above 0.79% all give 100 kg, so 1% below means 100 kg, not 127.
N_SUPPLY = [  # (fertilizer N recovery, share of soil N mineralized per season), from low to high supply
    (0.2, 0.0025),  # the first calibration's choice, kept to show what the trial constraint rules out
    (0.5, 0.005),   # simulator defaults
    (0.5, 0.0075),
    (0.5, 0.01),
]
CANDIDATES = {
    # Fine photosynthesis steps: both crops' level changes quickly between x0.4 and x0.5.
    "barley": grid(tsum_scale=[0.8, 0.9, 1.0], photosynthesis_scale=[0.4, 0.425, 0.45, 0.475, 0.5],
                   n_recovery=[0.5]),
    # Faba bean fixes most of its N, so fertilizer recovery barely matters.
    "fababean": grid(tsum_scale=[0.8, 0.9, 1.0], photosynthesis_scale=[0.4, 0.425, 0.45, 0.475, 0.5],
                     n_recovery=[0.5]),
    # Maize: photosynthesis and N supply compete; the trial constraint decides how much N limits it. Yield
    # climbs steeply between x0.45 and x0.5 (about 2 to 3 t/ha), hence the fine steps there.
    "maize": [{"tsum_scale": tsum, "photosynthesis_scale": photosynthesis, "n_recovery": recovery,
               "mineralization_rate": mineralization}
              for tsum in (0.8, 1.0)
              for photosynthesis in (0.35, 0.4, 0.45, 0.46, 0.47, 0.48, 0.49, 0.5, 0.6, 0.75, 1.0)
              for recovery, mineralization in N_SUPPLY],
}
# Maize goes last: it inherits water and N from the calibrated barley and faba bean, which barely depend on
# maize (at the fitted photosynthesis, barley is hardly N-limited and faba bean fixes its N).
FIT_ORDER = ("barley", "fababean", "maize")
TRIAL_CROPS = ("maize",)


def fit(runner, siap, variety, order=FIT_ORDER, candidates=CANDIDATES, history_csv=None, knobs=None):
    """Coordinate grid search: each crop's knobs in turn (others fixed), lowest 2006-2021 RMSE wins.

    Maize candidates are also run without fertilizer (continuous maize only), and only those that keep
    the trial's fertilizer response are eligible (`within_trial`). Every candidate's scores are written
    to `history_csv` after each step, so a long fit can be inspected. `knobs` sets starting values
    (default: the uncalibrated simulator).
    """
    knobs = {**{crop: dict(DEFAULT) for crop in CROP_KEYS}, "site": {}, **(knobs or {})}
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
        scores = score(runs, siap, [crop], splits=("calibration",))
        scores = scores.assign(step=step, matured_share=scores["label"].map(matured),
                               distance=scores["label"].map(lambda label: distance_from_default(json.loads(label))))
        eligible = scores
        if crop in TRIAL_CROPS:
            unfertilized = runner.run({label: {**cal, "n_scale": 0.0} for label, cal in cases.items()}, ["maize"])
            scores["fertilizer_ratio"] = scores["label"].map(
                {label: fertilizer_ratio(runs[label], unfertilized[label]) for label in runs})
            eligible = within_trial(scores)
        history.append(scores)
        choice = json.loads(best_candidate(eligible, crop)["label"])
        knobs[crop], site = split_candidate(choice)
        knobs["site"].update(site)
        edges = edge_knobs(choice, candidates[crop])
        print(f"step {step} {crop}: {knobs[crop]} site {knobs['site']}, {len(eligible)}/{len(scores)} eligible"
              + (f"; at the grid edge: {', '.join(edges)}" if edges else ""), flush=True)
        if history_csv:
            pd.concat(history, ignore_index=True).to_csv(history_csv, index=False)
    return knobs, pd.concat(history, ignore_index=True)


def station_check(runner, variety, tsum_scales=(1.0, 0.8), photosynthesis_scales=(1.0, 0.7, 0.65, 0.6, 0.55),
                  mineralization_rates=(0.005, 0.0075, 0.0079)):
    """Continuous-maize yields with and without fertilizer at station-like settings, to compare with the trial's
    absolute 5.2 and 5.6 t/ha (not just their ratio). Fertilizer recovery stays at the default 0.5; 0.79% of
    soil N is the simulator's 100 kg/season cap. Returns one row per setting (fit-year means, t/ha)."""
    cases = {}
    for tsum, photosynthesis, mineralization in itertools.product(tsum_scales, photosynthesis_scales,
                                                                  mineralization_rates):
        settings = simulator_settings({"maize": {"tsum_scale": tsum, "photosynthesis_scale": photosynthesis},
                                       "site": {"mineralization_rate": mineralization}}, variety)
        for n_scale in (1.0, 0.0):
            cases[(tsum, photosynthesis, mineralization, n_scale)] = {**settings, "n_scale": n_scale}
    runs = runner.run(cases, ["maize"])
    rows = []
    for tsum, photosynthesis, mineralization in itertools.product(tsum_scales, photosynthesis_scales,
                                                                  mineralization_rates):
        fertilized, unfertilized = (runs[(tsum, photosynthesis, mineralization, n)] for n in (1.0, 0.0))
        rows.append({"tsum_scale": tsum, "photosynthesis_scale": photosynthesis,
                     "soil_n_kg_season": min(100.0, mineralization * 12709),
                     "unfertilized_t_ha": continuous_maize_mean(unfertilized),
                     "fertilized_t_ha": continuous_maize_mean(fertilized),
                     "ratio": fertilizer_ratio(fertilized, unfertilized)})
    return pd.DataFrame(rows)


def run_metadata(lat=19.53, lon=-98.85):
    """Versions, git commit and the date of the NASA POWER weather used, so saved runs can be traced.

    PCSE refreshes its POWER cache after 90 days, so runs made after that use re-downloaded weather.
    """
    import subprocess
    import sys
    from datetime import datetime
    from importlib.metadata import version

    from pcse import settings

    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    cache = Path(settings.METEO_CACHE_DIR) / f"NASAPowerWeatherDataProvider_LAT{int(lat * 10):05d}_LON{int(lon * 10):05d}.cache"
    return {"python": sys.version.split()[0], "pcse": version("pcse"), "git_commit": commit,
            "power_weather_cached": (datetime.fromtimestamp(cache.stat().st_mtime).isoformat(timespec="seconds")
                                     if cache.exists() else None)}


def simulate_scenarios(knobs, scenarios=("baseline",), out_dir=OUT_DIR, lat=19.53, lon=-98.85,
                       start_year=2005, end_year=2025):
    """Calibrated runs of registered scenarios (all levels, all rotations) saved to `out_dir`.

    calibration.json records the knobs, fit and holdout years, versions, the weather date and, for the
    baseline, the scores against SIAP and the naive baselines.
    """
    from .wofost_rotations import simulate_rotations

    calibration = simulator_settings(knobs, variety_parameters())
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"latitude": lat, "longitude": lon, "start_year": start_year, "end_year": end_year,
                "fit_years": [min(CALIBRATION_YEARS), max(CALIBRATION_YEARS)],
                "holdout_years": [min(HOLDOUT_YEARS), max(HOLDOUT_YEARS)],
                "trial_no_n_ratio": [TRIAL_NO_N_RATIO, TRIAL_TOLERANCE],
                "calibration": knobs, **run_metadata(lat, lon), "scenarios": {}}
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
        if name == "baseline":
            metrics = with_baselines(score({"calibrated": seasons}, siap_texcoco()), siap_texcoco())
            manifest["metrics"] = json.loads(metrics.round(4).to_json(orient="records"))
        (out_dir / "calibration.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return out_dir


def main():
    parser = argparse.ArgumentParser(description="Calibrate WOFOST rotations to SIAP Texcoco yields (opt-in).")
    parser.add_argument("--sensitivity", action="store_true", help="One-at-a-time diagnostics (fit years only)")
    parser.add_argument("--station-check", action="store_true",
                        help="Continuous maize with and without fertilizer at station-like settings vs the trial")
    parser.add_argument("--fit", action="store_true", help="Grid search on 2006-2021 and report before/after")
    parser.add_argument("--simulate", action="store_true", help="Run calibrated scenarios into --out-dir")
    parser.add_argument("--scenarios", nargs="+", choices=list(SCENARIOS), default=["baseline"])
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--workers", type=int)
    args = parser.parse_args()
    if not (args.sensitivity or args.station_check or args.fit or args.simulate):
        parser.error("Choose --sensitivity, --station-check, --fit and/or --simulate")

    siap = siap_texcoco()
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", None)
    if args.sensitivity or args.station_check or args.fit:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        runner = Runner(workers=args.workers)
        variety = variety_parameters()
        try:
            if args.sensitivity:
                scores, extra = sensitivity(runner, siap, variety)
                print(scores.round(3).to_string(index=False))
                print(extra.round(2).to_string())
                scores.merge(extra.reset_index(), on="label").to_csv(args.out_dir / "sensitivity.csv", index=False)
            if args.station_check:
                table = station_check(runner, variety)
                print(f"Trial: {5.2} t/ha without fertilizer, {5.6} with 160 kg N/ha (ratio {TRIAL_NO_N_RATIO:.2f})")
                print(table.round(2).to_string(index=False))
                table.to_csv(args.out_dir / "station_check.csv", index=False)
            if args.fit:
                knobs, _ = fit(runner, siap, variety, history_csv=args.out_dir / "fit_history.csv")
                (args.out_dir / "fitted_knobs.json").write_text(json.dumps(knobs, indent=2) + "\n")
                calibrated = simulator_settings(knobs, variety)
                runs = runner.run({"default": {}, "calibrated": calibrated, "default, no fertilizer": {"n_scale": 0.0},
                                   "calibrated, no fertilizer": {**calibrated, "n_scale": 0.0}},
                                  list(rotations_with("maize")))
                print("Fitted knobs (copy into CALIBRATED):", json.dumps(knobs, indent=2))
                print(with_baselines(score(runs, siap), siap).round(3).to_string(index=False))
                print(maize_diagnostics(runs).round(2).to_string())
                print("Mean 2006-2021 yield (t/ha) with and without fertilizer:")
                print(pd.DataFrame({label: simulated_like_siap(s[s["year"].isin(CALIBRATION_YEARS)], siap)
                                    .groupby("crop").mean() for label, s in runs.items()}).round(2).to_string())
        finally:
            runner.close()
    if args.simulate:
        print(f"Saved to {simulate_scenarios(CALIBRATED, args.scenarios, args.out_dir)}")


if __name__ == "__main__":
    main()
