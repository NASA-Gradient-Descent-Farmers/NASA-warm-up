"""Export saved model outputs as small JSON files for the web dashboard (dashboard/).

The dashboard is a static React app: it reads these files and does the rest in the browser, so it runs
without Python, PCSE or NASA access. Nothing here re-runs a model; it reshapes files that already exist under
data/ and records where they came from.

Files written to --out-dir (default dashboard/public/data):
- meta.json: site, crops and fertilizer doses, rotations, objectives, decision weights, the planner's settings
             (lattice, bad-year share, tie decimals), its economics (which figures are placeholders) and the
             latest SIAP prices, design/holdout years, provenance.
- grid.json: the WOFOST season outcomes the NSGA planner scores strategies from (nsga_planner.Grid, design years,
             every rotation at each fertilizer scale), one table per parameter set. The browser re-prices
             and re-scores strategies from it, so prices and costs can be edited live.
- scenarios.json, reality.json: the WOFOST scenario suites and SIAP comparison for the economics, reality-check
             and what-if tabs (see dashboard_seasons.py; meta.json gains a `farm` section describing them).

Written to --fixtures-dir (default dashboard/src/lib/fixtures), for the dashboard's tests only:
- reference_fronts.json: the exact Pareto fronts saved by nsga_planner at the default economics, which the
             browser port of the planner must reproduce.
- reference_economics.json: farm_tool.rotation_economics at the same economics, for the browser's port of it.

Usage (from the repo root):
    python -m src.crop_models.dashboard_export
"""

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from . import dashboard_seasons
from .calibration import CALIBRATION_YEARS
from .farm_setup import CROPS, ROTATIONS, SITE, fertilizer_kg_ha
from .farm_tool import default_prices, siap_texcoco
from .nsga_planner import (CVAR_SHARE, FIELDS, FRONT_DECIMALS, GRID_CSV, N_SCALE_STEPS, OBJECTIVES, PROFIT_FIRST,
                           RETENTION_STEPS, SUSTAINABILITY_FIRST, Grid)

NSGA_DIR = Path("data/nsga")
OUT_DIR = Path("dashboard/public/data")
FIXTURES_DIR = Path("dashboard/src/lib/fixtures")
# World name -> directory holding the five-objective run (brute_force_front.csv, run.json). The world name is also
# the `model` column of the grid.
WORLDS = {"calibrated": NSGA_DIR / "calibrated", "default": NSGA_DIR / "default"}
FRONT_COLUMNS = ["rotation", "n_scale", "retention", *OBJECTIVES]
# Economics that are not sourced (nsga_planner.PLACEHOLDER_*): the dashboard must say so next to the numbers.
PLACEHOLDERS = ["other_costs", "n_price", "stover_price"]


def crop_plan():
    """({crop: kg N/ha at fertilizer scale 1}, {rotation: [crops]}) from farm_setup (no PCSE needed)."""
    return ({key: fertilizer_kg_ha(key) for key in CROPS}, {key: list(crops) for key, crops in ROTATIONS.items()})


def load_front(directory):
    """(front rows as lists in FRONT_COLUMNS order, run.json) of one saved NSGA run."""
    front = pd.read_csv(Path(directory) / "brute_force_front.csv")
    missing = [c for c in FRONT_COLUMNS if c not in front.columns]
    if missing:
        raise ValueError(f"{directory}/brute_force_front.csv lacks {missing}")
    front = front[FRONT_COLUMNS].copy()
    front[list(OBJECTIVES)] = front[list(OBJECTIVES)].round(FRONT_DECIMALS)  # the tie rule of pareto_front
    front[["n_scale", "retention"]] = front[["n_scale", "retention"]].round(6)
    run = json.loads((Path(directory) / "run.json").read_text())
    return front.to_numpy(object).tolist(), run


def grid_payload(grid):
    """A Grid as plain lists. Each rotation has `crops` [year][phase] and, per field of nsga_planner.FIELDS, the
    values flattened from [fertilizer scale][year][phase] (row-major; the shape is len(scales) x len(years) x phases).
    Floats keep full precision so the browser reproduces the planner's arithmetic."""
    return {
        "scales": [float(s) for s in grid.scales],
        "years": [int(y) for y in grid.years],
        # JSON keys are written sorted; the lattice (and so tie-breaking in `choose`) follows this order.
        "order": list(grid.rotations),
        "rotations": {
            name: {"phases": int(data["crop"].shape[1]), "crops": data["crop"].tolist(),
                   "fields": {field: data[field].ravel().tolist() for field in FIELDS}}
            for name, data in grid.rotations.items()},
    }


def load_grid(grid_csv, model, years=CALIBRATION_YEARS):
    seasons = pd.read_csv(grid_csv)
    seasons = seasons[seasons["model"] == model]
    if seasons.empty:
        raise ValueError(f"No rows for model {model!r} in {grid_csv}")
    return Grid(seasons, years)


def siap_prices(siap):
    """{crop: latest year, latest price and the three-year median the planner uses}, MXN per t."""
    medians = default_prices(siap)
    priced = siap.dropna(subset=["price_mxn_t"]).sort_values("year")
    out = {}
    for crop, group in priced.groupby("crop"):
        last = group.iloc[-1]
        out[crop] = {"latest_year": int(last["year"]), "latest_mxn_t": float(last["price_mxn_t"]),
                     "median_3y_mxn_t": float(medians[crop])}
    return out


def build_payloads(worlds=WORLDS, grid_csv=GRID_CSV, crop_plan_fn=crop_plan, siap_fn=siap_texcoco):
    """(meta, grid, reference fronts) dictionaries ready to be written as JSON."""
    doses, rotations = crop_plan_fn()
    fronts, runs, grids = {}, {}, {}
    for name, directory in worlds.items():
        fronts[name], runs[name] = load_front(directory)
        grids[name] = load_grid(grid_csv, name)
    first = next(iter(runs.values()))
    grid_hash = hashlib.sha256(Path(grid_csv).read_bytes()).hexdigest()
    for name, run in runs.items():
        if run["economics"] != first["economics"] or run["design_years"] != first["design_years"]:
            raise ValueError(f"World {name!r} was run with different economics or years from the others")
        if run["grid_sha256"] != grid_hash:
            raise ValueError(f"The fronts of world {name!r} were not computed from {grid_csv}; rerun nsga_planner")
        years = grids[name].years
        if [int(years[0]), int(years[-1])] != run["design_years"]:
            raise ValueError(f"World {name!r}: grid years differ from the run's design years")
    meta = {
        "site": dict(SITE),
        "crops": {key: {"n_kg_ha_at_scale_1": kg} for key, kg in doses.items()},
        "rotations": rotations,
        "rotation_order": list(rotations),
        "objectives": [{"key": o, "maximize": o != "n_loss_kg_ha"} for o in OBJECTIVES],
        "weights": {"sustainability_first": SUSTAINABILITY_FIRST, "profit_first": PROFIT_FIRST},
        "lattice": {"n_scale_max": float(next(iter(grids.values())).scales[-1]), "n_scale_steps": N_SCALE_STEPS,
                    "retention_steps": RETENTION_STEPS},
        # Read by the browser's port of the planner, so its scoring and tie rule follow nsga_planner.
        "planner": {"cvar_share": CVAR_SHARE, "front_decimals": FRONT_DECIMALS},
        "economics": first["economics"],
        "siap_prices": siap_prices(siap_fn()),
        "placeholders": PLACEHOLDERS,
        "design_years": first["design_years"],
        "holdout_years": first["holdout_years"],
        "reference_front_size": {name: len(rows) for name, rows in fronts.items()},
        "grid_sha256": grid_hash,
    }
    grid = {"worlds": {name: grid_payload(g) for name, g in grids.items()}}
    reference = {"columns": FRONT_COLUMNS, "decimals": FRONT_DECIMALS, "worlds": fronts}
    return meta, grid, reference


def write_json(path, payload):
    """Compact, key-ordered JSON so a re-export of unchanged inputs gives identical bytes."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False) + "\n")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--fixtures-dir", type=Path, default=FIXTURES_DIR)
    parser.add_argument("--grid", type=Path, default=GRID_CSV)
    args = parser.parse_args()
    meta, grid, reference = build_payloads(grid_csv=args.grid)
    loaded = {world: dashboard_seasons.load_world(directory, world)
              for world, directory in dashboard_seasons.SEASON_DIRS.items()}
    scenarios, reality, economics, farm = dashboard_seasons.build_season_payloads(
        {world: seasons for world, (seasons, _) in loaded.items()}, siap_texcoco(), meta["economics"],
        {world: hashes for world, (_, hashes) in loaded.items()})
    meta.update(farm)
    for directory, name, payload in ((args.out_dir, "meta.json", meta), (args.out_dir, "grid.json", grid),
                                     (args.out_dir, "scenarios.json", scenarios),
                                     (args.out_dir, "reality.json", reality),
                                     (args.fixtures_dir, "reference_fronts.json", reference),
                                     (args.fixtures_dir, "reference_economics.json", economics)):
        path = write_json(directory / name, payload)
        print(f"Saved {path} ({path.stat().st_size / 1024:.0f} kB)")


if __name__ == "__main__":
    main()
