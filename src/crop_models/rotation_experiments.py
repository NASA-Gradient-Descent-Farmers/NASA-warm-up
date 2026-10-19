"""Reproducible WOFOST scenario suites and shared season-table loading.

Run ``python -m src.crop_models.rotation_experiments --help`` from the repo root.
The analysis modules can read existing CSVs without importing PCSE or contacting NASA.
"""

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

TARGET = "yield_water_n_t_ha"
KEY = ["scenario", "rotation", "phase", "year"]


@dataclass(frozen=True)
class Scenario:
    rain_factor: float = 1.0
    rain_months: tuple[int, ...] = ()
    frost_tmin_offset: float = 0.0
    n_scale: float = 1.0
    sowing: str = "onset"

    def metadata(self):
        return {
            "rain_factor": self.rain_factor,
            "rain_months": ",".join(map(str, self.rain_months)) or "all",
            "frost_tmin_offset": self.frost_tmin_offset,
            "n_scale": self.n_scale,
            "sowing_mode": self.sowing,
        }


# The first seven names also describe the legacy data/rotations/*.csv files.
SCENARIOS = {
    "baseline": Scenario(),
    "rain80": Scenario(rain_factor=0.8),
    "rain60": Scenario(rain_factor=0.6),
    "canicula50": Scenario(rain_factor=0.5, rain_months=(7, 8)),
    "frost_minus2": Scenario(frost_tmin_offset=-2.0),
    "no_fertilizer": Scenario(n_scale=0.0),
    "fixed_sowing": Scenario(sowing="fixed"),
    "half_fertilizer": Scenario(n_scale=0.5),
    "rain80_half_fertilizer": Scenario(rain_factor=0.8, n_scale=0.5),
    "canicula50_half_fertilizer": Scenario(rain_factor=0.5, rain_months=(7, 8), n_scale=0.5),
}


def load_seasons(paths, spinup_years=1):
    """Load one or more scenario CSVs, excluding spin-up separately for each run.

    Legacy files must retain a registered scenario filename. Other inputs must carry
    explicit scenario settings. Scenario names and phase IDs never become predictors.
    This workflow describes one site; do not pool sites with unknown soil differences.
    """
    if spinup_years < 0:
        raise ValueError("spinup_years must be nonnegative")
    frames = []
    for path in map(Path, paths):
        frame = pd.read_csv(path)
        if "scenario" not in frame:
            frame["scenario"] = path.stem
        if path.stem in SCENARIOS:
            for column, value in SCENARIOS[path.stem].metadata().items():
                if column not in frame:
                    frame[column] = value
        frames.append(frame)
    if not frames:
        raise ValueError("Provide at least one season CSV")
    data = pd.concat(frames, ignore_index=True)
    required = KEY + [
        "crop",
        "previous_crop",
        TARGET,
        "n_fertilizer_kg_ha",
        "soil_water_at_start_mm",
        "mineral_n_at_start_kg_ha",
    ]
    settings = list(Scenario().metadata())
    missing = set(required + settings) - set(data.columns)
    if missing:
        raise ValueError(
            f"Missing columns: {sorted(missing)}. Legacy CSVs need a registered scenario filename."
        )
    if data.empty or data[KEY + ["crop"] + settings].isna().any().any():
        raise ValueError("Empty input or missing season identifiers / scenario settings")
    numeric = [
        "year",
        "phase",
        TARGET,
        "n_fertilizer_kg_ha",
        "soil_water_at_start_mm",
        "mineral_n_at_start_kg_ha",
        "rain_factor",
        "n_scale",
        "frost_tmin_offset",
    ]
    for column in numeric:
        data[column] = pd.to_numeric(data[column], errors="raise")
        if not np.isfinite(data[column]).all():
            raise ValueError(f"{column} must contain finite numbers")
    for column in ("year", "phase"):
        if (data[column] % 1 != 0).any():
            raise ValueError(f"{column} must contain integers")
        data[column] = data[column].astype(int)
    if (data[[c for c in numeric if c != "frost_tmin_offset"]] < 0).any().any():
        raise ValueError("Years, phases, yields, water, nitrogen and multipliers must be nonnegative")
    if not data["sowing_mode"].isin(["onset", "fixed"]).all():
        raise ValueError("sowing_mode must be onset or fixed")
    data["rain_months"] = data["rain_months"].astype(str)
    if data.duplicated(KEY).any():
        raise ValueError("Duplicate scenario/rotation/phase/year rows; do not load the same run twice")
    for name, group in data.groupby("scenario"):
        if (group[settings].nunique() > 1).any():
            raise ValueError(f"Scenario {name!r} has inconsistent settings")
    for column in ("latitude", "longitude"):
        if column in data and data[column].nunique() > 1:
            raise ValueError("Use one site per experiment")
    first_year = data.groupby(["scenario", "rotation", "phase"])["year"].transform("min")
    data = data[data["year"] >= first_year + spinup_years].copy()
    if data.empty:
        raise ValueError("No seasons remain after spin-up")
    return data.sort_values(KEY).reset_index(drop=True)


def main():
    parser = argparse.ArgumentParser(description="Run additional WOFOST crop-rotation scenarios.")
    parser.add_argument("--scenarios", nargs="+", choices=list(SCENARIOS), default=list(SCENARIOS))
    parser.add_argument("--lat", type=float, default=19.53)
    parser.add_argument("--lon", type=float, default=-98.85)
    parser.add_argument("--start-year", type=int, default=2005)
    parser.add_argument("--end-year", type=int, default=2025)
    parser.add_argument("--out-dir", type=Path, default=Path("data/rotation_experiments"))
    args = parser.parse_args()
    if args.end_year - args.start_year < 2:
        parser.error("Use at least three seasons for spin-up and drought terciles")

    # Keep offline analysis independent of PCSE and Earthdata authentication.
    from .wofost_rotations import simulate_rotations

    args.out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "latitude": args.lat,
        "longitude": args.lon,
        "start_year": args.start_year,
        "end_year": args.end_year,
        "scenarios": {},
    }
    for name in dict.fromkeys(args.scenarios):
        scenario = SCENARIOS[name]
        print(f"Simulating {name}: {asdict(scenario)}", flush=True)
        seasons, _, _, _ = simulate_rotations(
            args.lat,
            args.lon,
            args.start_year,
            args.end_year,
            **{**asdict(scenario), "rain_months": scenario.rain_months or None},
        )
        seasons["scenario"] = name
        seasons.to_csv(args.out_dir / f"{name}.csv", index=False)
        manifest["scenarios"][name] = asdict(scenario)
        (args.out_dir / "scenarios.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Saved scenarios to {args.out_dir}")


if __name__ == "__main__":
    main()
