"""Season-level exports for the dashboard's economics, reality-check and what-if tabs.

dashboard_export.py writes the planner's files; this module reshapes the WOFOST scenario suites (one per
parameter set) and the SIAP Texcoco table into:

- scenarios.json: per parameter set ("world") and scenario, every season's crop, yield, fertilizer dose and
  frost ending, the year's May-October rain and dry/normal/wet class, and the paired-year maize risk
  comparison of rotation_risk. The browser prices seasons itself (farm_tool.rotation_economics), so prices
  stay editable.
- reality.json: SIAP's yearly Texcoco series per crop and, per world, the WOFOST-vs-SIAP gap (farm_tool.farm_gap).
- reference_economics.json (test fixture): rotation_economics at the planner's default economics, which the
  browser port must reproduce.

Nothing here runs WOFOST. The scenario CSVs come from:
    python -m src.crop_models.rotation_experiments --out-dir data/rotations           # default parameters
    python -m src.crop_models.calibration --simulate --scenarios <all ten>             # calibrated parameters
"""

import hashlib
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from .farm_setup import ROTATIONS
from .farm_tool import farm_gap, rotation_economics
from .rotation_experiments import SCENARIOS, TARGET, load_seasons
from .rotation_risk import compare_rotations

# World name -> directory of that parameter set's scenario CSVs (one file per registered scenario).
SEASON_DIRS = {"calibrated": Path("data/rotations_calibrated"), "default": Path("data/rotations")}
CALIBRATED_SUFFIX = "_calibrated"  # calibration.simulate_scenarios names its scenarios "<name>_calibrated"
SPINUP_YEARS = 1
SEASON_FIELDS = (TARGET, "n_fertilizer_kg_ha")
FAILURE_THRESHOLD = 1.0  # t/ha: a harvest below this is a failed one (farm_tool and rotation_risk default)
# rotation_risk defaults: maize in each rotation against continuous maize, 5,000 draws of ten maize harvests.
RISK = {"crop": "maize", "reference": "maize", "draws": 5000, "harvests": 10, "seed": 42}
SIAP_COLUMNS = ["sown_ha", "lost_share", "yield_sown_t_ha", "yield_harvested_t_ha", "price_mxn_t"]
FULL_SUITE = ("Run every scenario: python -m src.crop_models.rotation_experiments --out-dir data/rotations and "
              "python -m src.crop_models.calibration --simulate --scenarios " + " ".join(SCENARIOS))


def load_world(directory, world):
    """(seasons without spin-up, {file: sha256}) of one world's scenario CSVs, scenario names unsuffixed."""
    paths = sorted(Path(directory).glob("*.csv"))
    if not paths:
        raise FileNotFoundError(f"No scenario CSVs in {directory}. {FULL_SUITE}")
    seasons = load_seasons(paths, SPINUP_YEARS)
    if world == "calibrated":
        seasons["scenario"] = seasons["scenario"].str.removesuffix(CALIBRATED_SUFFIX)
    unknown = sorted(set(seasons["scenario"]) - set(SCENARIOS))
    if unknown:
        raise ValueError(f"{directory}: unregistered scenarios {unknown}")
    missing = [name for name in SCENARIOS if name not in set(seasons["scenario"])]
    if missing:
        raise ValueError(f"{directory}: missing scenarios {missing}. {FULL_SUITE}")
    hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    return seasons, hashes


def scenario_settings():
    """{scenario: settings} in registration order, rain months as a list (empty = all year)."""
    return {name: {**asdict(s), "rain_months": list(s.rain_months)} for name, s in SCENARIOS.items()}


def _per_year(frame, column, years):
    """One value per year (it must not vary across rotations and phases: it is the year's weather)."""
    values = frame.groupby("year")[column]
    if (values.nunique(dropna=False) > 1).any():
        raise ValueError(f"{column} differs between rotations within a year")
    return values.first().reindex(years).tolist()


def world_payload(seasons, rotations=ROTATIONS):
    """Seasons of one world as [year][phase] tables per scenario and rotation (fields flattened row-major)."""
    years = sorted(int(y) for y in seasons["year"].unique())
    out = {"years": years, "scenarios": {}}
    for name in SCENARIOS:
        scenario = seasons[seasons["scenario"] == name]
        if scenario.empty:
            continue
        payload = {"rain_may_oct_mm": [float(v) for v in _per_year(scenario, "rain_may_oct_mm", years)],
                   "year_class": _per_year(scenario, "year_class", years), "rotations": {}}
        for rotation in rotations:
            table = scenario[scenario["rotation"] == rotation].set_index(["year", "phase"]).sort_index()
            phases = table.index.get_level_values("phase").nunique()
            if len(table) != len(years) * phases:
                raise ValueError(f"Scenario {name!r}, rotation {rotation!r}: incomplete seasons")
            grid = lambda column: table[column].unstack("phase").reindex(years)  # noqa: E731
            payload["rotations"][rotation] = {
                "phases": int(phases),
                "crops": grid("crop").to_numpy().tolist(),
                "fields": {f: grid(f).to_numpy(float).ravel().tolist() for f in SEASON_FIELDS},
                # True when frost ended the crop before maturity (wofost_rotations writes a boolean).
                "frost_ended": grid("frost_ended").astype(str).eq("True").to_numpy().ravel().astype(int).tolist(),
            }
        out["scenarios"][name] = payload
    return out


def risk_payload(seasons):
    """Paired-year maize comparison of every rotation with continuous maize, per scenario (rotation_risk)."""
    effects, risks = compare_rotations(seasons, RISK["crop"], RISK["reference"], RISK["draws"], RISK["harvests"],
                                       FAILURE_THRESHOLD, RISK["seed"])
    keep_effects = ["mean_yield_t_ha", "mean_advantage_t_ha", "advantage_ci_low_t_ha", "advantage_ci_high_t_ha",
                    "fraction_years_better", "paired_years"]
    keep_risks = ["mean_yield_p05_t_ha", "mean_yield_p95_t_ha", "failed_harvest_fraction", "prob_any_failed_harvest",
                  "prob_mean_below_reference"]
    both = effects.merge(risks[["scenario", "rotation", *keep_risks]], on=["scenario", "rotation"], validate="1:1")
    out = {}
    for row in both.to_dict("records"):
        out.setdefault(row["scenario"], {})[row["rotation"]] = {k: _number(row[k]) for k in keep_effects + keep_risks}
    return out


def siap_payload(siap):
    """{crop: {year: [...], column: [...]}} of the SIAP Texcoco table (rainfed spring-summer)."""
    out = {}
    for crop, group in siap.sort_values("year").groupby("crop"):
        out[crop] = {"year": group["year"].astype(int).tolist(),
                     **{c: [_number(v) for v in group[c]] for c in SIAP_COLUMNS}}
    return out


def gap_payload(seasons, siap):
    """farm_gap of the baseline: per crop the mean levels, the rescaling factor, the correlation and the years."""
    gap, paired = farm_gap(seasons, siap)
    out = {}
    for crop, row in gap.iterrows():
        pairs = paired[paired["crop"] == crop].sort_values("year")
        out[crop] = {**{k: _number(v) for k, v in row.items()},
                     "year": pairs["year"].astype(int).tolist(),
                     "simulated_t_ha": pairs["simulated_t_ha"].tolist(),
                     "observed_t_ha": pairs["observed_t_ha"].tolist()}
    return out


def reference_economics(seasons_by_world, economics, gaps):
    """rotation_economics summaries at `economics`: per world as simulated, and the default world rescaled to
    SIAP's level by the farm_gap factors (the notebook's "farm-calibrated" yields)."""
    cases = {f"{world}:raw": (seasons, None) for world, seasons in seasons_by_world.items()}
    if "default" in seasons_by_world:
        factors = {crop: g["factor"] for crop, g in gaps["default"].items()}
        cases["default:siap_level"] = (seasons_by_world["default"], factors)
    out = {}
    for case, (seasons, factors) in cases.items():
        _, _, summary, crops = rotation_economics(seasons, economics["prices"], economics["other_costs"],
                                                  economics["n_price"], factors, FAILURE_THRESHOLD)
        out[case] = {"yield_factors": factors,
                     "summary": [{k: _number(v) for k, v in r.items()} for r in summary.to_dict("records")],
                     "crops": [{k: _number(v) for k, v in r.items()} for r in crops.to_dict("records")]}
    return out


def build_season_payloads(seasons_by_world, siap, economics, hashes=None):
    """(scenarios, reality, reference economics, meta additions) for the dashboard."""
    years = {world: sorted(s["year"].unique()) for world, s in seasons_by_world.items()}
    if len({tuple(y) for y in years.values()}) > 1:
        raise ValueError(f"Worlds cover different years: {years}")
    scenarios = {"worlds": {world: {**world_payload(seasons), "risk": risk_payload(seasons)}
                            for world, seasons in seasons_by_world.items()}}
    gaps = {world: gap_payload(seasons, siap) for world, seasons in seasons_by_world.items()}
    reality = {"siap": siap_payload(siap), "worlds": gaps}
    reference = reference_economics(seasons_by_world, economics, gaps)
    meta = {"farm": {"scenarios": scenario_settings(), "scenario_order": list(SCENARIOS),
                     "season_years": [int(min(next(iter(years.values())))), int(max(next(iter(years.values()))))],
                     "spinup_years": SPINUP_YEARS, "failure_threshold_t_ha": FAILURE_THRESHOLD, "risk": RISK,
                     "sources": hashes or {}}}
    return scenarios, reality, reference, meta


def _number(value):
    """JSON-safe scalar: NaN becomes null, numpy types become Python ones."""
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return None if np.isnan(value) else float(value)
    return value
