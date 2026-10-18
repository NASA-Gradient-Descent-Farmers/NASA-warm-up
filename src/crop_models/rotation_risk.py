"""Paired-year bootstrap and Monte Carlo comparisons of WOFOST rotations.

These resample simulated crop harvests; they do not evolve soil or create new weather.
Use WOFOST to simulate new management interventions and their carryover effects.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .rotation_experiments import TARGET, load_seasons


def compare_rotations(
    seasons, crop="maize", reference="maize", draws=5000, harvests=10, failure_threshold=1.0, seed=42
):
    """Return paired bootstrap effects and sampled multi-harvest yield/risk.

    Each scenario uses the intersection of years present in ALL its rotations.
    The same year draws are used for every rotation, preserving shared weather.
    Multiple phases of the same crop are averaged before resampling years.
    """
    if draws < 1 or harvests < 1 or not np.isfinite(failure_threshold) or failure_threshold < 0:
        raise ValueError(
            "draws and harvests must be positive; failure_threshold must be finite and nonnegative"
        )
    rng = np.random.default_rng(seed)
    effects, risks = [], []
    selected = seasons[seasons["crop"] == crop]
    if selected.empty:
        raise ValueError(f"No seasons for crop {crop!r}")
    for scenario, group in selected.groupby("scenario", sort=True):
        annual = group.pivot_table(index="year", columns="rotation", values=TARGET, aggfunc="mean")
        if reference not in annual:
            raise ValueError(f"Reference rotation {reference!r} has no {crop} in scenario {scenario!r}")
        available_years = len(annual)
        annual = annual.dropna()
        if len(annual) < 2:
            raise ValueError(f"Scenario {scenario!r} needs at least two common years")
        values = annual.to_numpy()
        reference_index = annual.columns.get_loc(reference)
        bootstrap = rng.integers(0, len(annual), size=(draws, len(annual)))
        sampled = rng.integers(0, len(annual), size=(draws, harvests))
        baseline = values[:, reference_index]
        for index, rotation in enumerate(annual.columns):
            yields = values[:, index]
            difference = yields - baseline
            means = difference[bootstrap].mean(axis=1)
            future = yields[sampled]
            future_mean = future.mean(axis=1)
            future_difference = difference[sampled].mean(axis=1)
            metadata = {
                "scenario": scenario,
                "crop": crop,
                "rotation": rotation,
                "reference": reference,
                "paired_years": len(annual),
                "excluded_years": available_years - len(annual),
            }
            effects.append(
                {
                    **metadata,
                    "mean_yield_t_ha": yields.mean(),
                    "mean_advantage_t_ha": difference.mean(),
                    "advantage_ci_low_t_ha": np.quantile(means, 0.025),
                    "advantage_ci_high_t_ha": np.quantile(means, 0.975),
                    "fraction_years_better": (difference > 1e-6).mean(),
                }
            )
            risks.append(
                {
                    **metadata,
                    "harvests": harvests,
                    "draws": draws,
                    "mean_yield_t_ha": future_mean.mean(),
                    "mean_yield_p05_t_ha": np.quantile(future_mean, 0.05),
                    "mean_yield_p95_t_ha": np.quantile(future_mean, 0.95),
                    "failure_threshold_t_ha": failure_threshold,
                    "failed_harvest_fraction": (future < failure_threshold).mean(),
                    "prob_any_failed_harvest": (future < failure_threshold).any(axis=1).mean(),
                    "prob_mean_below_reference": (future_difference < -1e-6).mean(),
                }
            )
    return pd.DataFrame(effects), pd.DataFrame(risks)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, nargs="+", required=True)
    parser.add_argument("--out-dir", type=Path, default=Path("data/rotation_risk"))
    parser.add_argument("--crop", default="maize")
    parser.add_argument("--reference", default="maize")
    parser.add_argument("--draws", type=int, default=5000)
    parser.add_argument("--harvests", type=int, default=10)
    parser.add_argument("--failure-threshold", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--spinup-years", type=int, default=1)
    args = parser.parse_args()
    seasons = load_seasons(args.input, args.spinup_years)
    effects, risks = compare_rotations(
        seasons, args.crop, args.reference, args.draws, args.harvests, args.failure_threshold, args.seed
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    effects.to_csv(args.out_dir / "rotation_effects.csv", index=False)
    risks.to_csv(args.out_dir / "harvest_risk.csv", index=False)
    metadata = {
        "crop": args.crop,
        "reference": args.reference,
        "seed": args.seed,
        "draws": args.draws,
        "harvests": args.harvests,
        "spinup_years": args.spinup_years,
        "failure_threshold_t_ha": args.failure_threshold,
        "advantage_tolerance_t_ha": 1e-6,
        "inputs": [
            {"path": str(p.resolve()), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in args.input
        ],
        "method": "Paired iid year bootstrap; fixed WOFOST assumptions; conditional crop harvests, not annual field returns.",
    }
    (args.out_dir / "run.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(effects.round(3).to_string(index=False))
    print(f"\nSaved paired bootstrap and Monte Carlo harvest risk to {args.out_dir}")


if __name__ == "__main__":
    main()
