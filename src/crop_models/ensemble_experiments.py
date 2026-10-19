"""Nested temporal evaluation of averaging, convex blending and ridge stacking.

Use --observations for a prepared table with year, observed_yield_t_ha and explicit
numeric predictors. Otherwise --input reads WOFOST simulations. Never mix targets.
"""

import argparse
import hashlib
import json
from importlib.metadata import version
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.base import BaseEstimator, RegressorMixin, clone
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.linear_model import Ridge
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .rotation_experiments import TARGET, load_seasons
from .tree_surrogate import build_features, model_candidates, score, temporal_splits


class TemporalEnsemble(RegressorMixin, BaseEstimator):
    """Fit meta-models only on predictions of strictly earlier-year training sets."""

    def __init__(self, estimators, method="equal"):
        self.estimators = estimators
        self.method = method

    def fit(self, x, y):
        y = np.asarray(y)
        count = len(self.estimators)
        self.weights_ = np.full(count, 1 / count)
        self.meta_membership_ = []
        if self.method != "equal":
            years = np.sort(x.year.unique())
            if len(years) < 3:
                raise ValueError("Stacking needs at least three training years")
            predictions, actual = [], []
            for train, valid in TimeSeriesSplit(n_splits=min(3, len(years) - 1)).split(years):
                ti = np.flatnonzero(x.year.isin(years[train]))
                vi = np.flatnonzero(x.year.isin(years[valid]))
                self.meta_membership_.append(
                    {"train_years": years[train].tolist(), "validation_years": years[valid].tolist()}
                )
                predictions.append(
                    np.column_stack(
                        [
                            clone(model).fit(x.iloc[ti], y[ti]).predict(x.iloc[vi])
                            for model in self.estimators.values()
                        ]
                    )
                )
                actual.extend(y[vi])
            p, actual = np.vstack(predictions), np.asarray(actual)
            if self.method == "convex":
                result = minimize(
                    lambda w: np.mean((p @ w - actual) ** 2) + 0.1 * np.sum((w - 1 / count) ** 2),
                    self.weights_,
                    bounds=[(0, 1)] * count,
                    constraints={"type": "eq", "fun": lambda w: w.sum() - 1},
                    method="SLSQP",
                )
                if not result.success:
                    raise ValueError(f"Blend optimization failed: {result.message}")
                self.weights_ = result.x
            elif self.method == "ridge":
                self.meta_ = Pipeline([("scale", StandardScaler()), ("ridge", Ridge(alpha=10))]).fit(
                    p, actual
                )
            else:
                raise ValueError("Unknown ensemble method")
        self.models_ = {name: clone(model).fit(x, y) for name, model in self.estimators.items()}
        return self

    def predict(self, x):
        p = np.column_stack([model.predict(x) for model in self.models_.values()])
        return np.maximum(0, self.meta_.predict(p) if self.method == "ridge" else p @ self.weights_)


class LagBaseline(RegressorMixin, BaseEstimator):
    def fit(self, x, y):
        return self

    def predict(self, x):
        return x["previous_yield_t_ha"].to_numpy()


def paired_uncertainty(predictions, selected, seed=42, draws=5000):
    """Resample whole holdout years jointly; positive advantage favors selected."""
    data = predictions.copy()
    data["squared_error"] = (data.actual_t_ha - data.predicted_t_ha) ** 2
    annual = data.pivot_table(index="year", columns="model", values="squared_error", aggfunc="mean")
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(annual), size=(draws, len(annual)))
    selected_errors = annual[selected].to_numpy()
    rows = []
    for name in annual.columns:
        advantage = np.sqrt(annual[name].to_numpy()[indices].mean(axis=1)) - np.sqrt(
            selected_errors[indices].mean(axis=1)
        )
        rows.append(
            {
                "selected": selected,
                "comparison": name,
                "holdout_years": len(annual),
                "rmse_advantage_t_ha": np.sqrt(annual[name].mean()) - np.sqrt(annual[selected].mean()),
                "ci_low_t_ha": np.quantile(advantage, 0.025),
                "ci_high_t_ha": np.quantile(advantage, 0.975),
            }
        )
    return pd.DataFrame(rows)


def plot_observed(data, predictions, selected, directory):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    axes[0].plot(data.year, data.observed_yield_t_ha, "o-", color="black", label="SIAP observed")
    axes[0].axvspan(
        predictions.year.min() - 0.5,
        predictions.year.max() + 0.5,
        alpha=0.12,
        color="orange",
        label="Holdout",
    )
    axes[0].set(title="Texcoco rainfed maize", xlabel="Year", ylabel="Reported yield (t/ha)")
    axes[0].legend(fontsize=8)
    truth = predictions[predictions.model == selected].sort_values("year")
    axes[1].plot(truth.year, truth.actual_t_ha, "ko-", label="SIAP observed")
    for name in dict.fromkeys([selected, "ensemble_equal", "mean"]):
        p = predictions[predictions.model == name].sort_values("year")
        axes[1].plot(p.year, p.predicted_t_ha, "o--", label=name)
    axes[1].set(
        title="Annual holdout predictions", xlabel="Year", ylabel="Reported yield (t/ha)", xticks=truth.year
    )
    axes[1].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(directory / "observed_predictions.png", dpi=160)
    plt.close(fig)


def candidates(numeric, observed=False, seed=42):
    if observed:
        # Reuse estimator settings, with preprocessing restricted to observed predictors.
        source = model_candidates(numeric, seed)
        models = {
            name: Pipeline(
                [
                    ("features", ColumnTransformer([("numeric", "passthrough", numeric)])),
                    ("model", clone(source[name]["model"])),
                ]
            )
            for name in ("random_forest", "xgboost")
        }
    else:
        source = model_candidates(numeric, seed)
        models = {name: source[name] for name in ("random_forest", "xgboost")}
    models["extra_trees"] = clone(models["random_forest"])
    models["extra_trees"].set_params(
        model=ExtraTreesRegressor(
            n_estimators=250, max_depth=6, min_samples_leaf=3, random_state=seed, n_jobs=1
        )
    )
    result = {"mean": DummyRegressor(), **models}
    if observed and "previous_yield_t_ha" in numeric:
        result["previous_yield"] = LagBaseline()
    result.update(
        {f"ensemble_{method}": TemporalEnsemble(models, method) for method in ("equal", "convex", "ridge")}
    )
    return result


def evaluate(x, y, years, models, test_years=4, folds=3):
    splits, development, holdout = temporal_splits(years, test_years, folds)
    y = np.asarray(y)
    metrics, predictions, fitted, audit = [], [], {}, []
    for name, template in models.items():
        truth, cv_predictions = [], []
        for fold, (train, valid) in enumerate(splits, 1):
            model = clone(template).fit(x.iloc[train], y[train])
            p = np.maximum(0, model.predict(x.iloc[valid]))
            truth.extend(y[valid])
            cv_predictions.extend(p)
            metrics.append({"model": name, "split": f"cv_{fold}", **score(y[valid], p)})
            audit.append(
                {
                    "model": name,
                    "fold": fold,
                    "train_years": sorted(set(years[train].tolist())),
                    "validation_years": sorted(set(years[valid].tolist())),
                    "inner": getattr(model, "meta_membership_", []),
                }
            )
        metrics.append({"model": name, "split": "cv_pooled", **score(truth, cv_predictions)})
        model = clone(template).fit(x.iloc[development], y[development])
        p = np.maximum(0, model.predict(x.iloc[holdout]))
        metrics.append({"model": name, "split": "holdout", **score(y[holdout], p)})
        predictions.append(
            pd.DataFrame(
                {
                    "row": holdout,
                    "year": years[holdout],
                    "model": name,
                    "actual_t_ha": y[holdout],
                    "predicted_t_ha": p,
                }
            )
        )
        fitted[name] = model
        audit.append(
            {
                "model": name,
                "fold": "final",
                "train_years": sorted(set(years[development].tolist())),
                "validation_years": sorted(set(years[holdout].tolist())),
                "inner": getattr(model, "meta_membership_", []),
            }
        )
    metrics = pd.DataFrame(metrics)
    selected = metrics[metrics.split == "cv_pooled"].sort_values("rmse_t_ha").iloc[0].model
    return metrics, pd.concat(predictions), fitted, selected, audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--input", nargs="+", type=Path)
    group.add_argument("--observations", type=Path)
    parser.add_argument("--features", nargs="+")
    parser.add_argument("--feature-set", choices=["planning", "hindcast"], default="planning")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--test-years", type=int, default=4)
    args = parser.parse_args()
    if args.observations:
        data = pd.read_csv(args.observations).sort_values("year").reset_index(drop=True)
        numeric = args.features or ["previous_yield_t_ha"]
        if set(numeric) & {"year", "observed_yield_t_ha", "production_t", "harvested_ha", "sown_ha"}:
            parser.error("Predictors must exclude target, IDs, production and harvested area")
        if data.year.duplicated().any():
            parser.error("Observed experiment requires one municipality/crop/mode row per year")
        x = data[numeric].copy()
        target, paths = "observed_yield_t_ha", [args.observations]
    else:
        data = load_seasons(args.input)
        data = data[data.crop == "maize"].reset_index(drop=True)
        x, numeric = build_features(data, args.feature_set)
        target, paths = TARGET, args.input
    if not np.isfinite(data[target]).all() or not np.isfinite(x[numeric]).all().all():
        parser.error("Targets and numeric predictors must be finite")
    x["year"] = data.year.to_numpy()  # used for splitting only; excluded by every transformer
    metrics, predictions, models, selected, audit = evaluate(
        x, data[target], data.year.to_numpy(), candidates(numeric, bool(args.observations)), args.test_years
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(args.out_dir / "metrics.csv", index=False)
    predictions.to_csv(args.out_dir / "holdout_predictions.csv", index=False)
    paired_uncertainty(predictions, selected).to_csv(args.out_dir / "paired_uncertainty.csv", index=False)
    # Store importable classes, including when invoked with python -m.
    from .ensemble_experiments import candidates as importable_candidates

    dev = data.year < predictions.year.min()
    selected_model = importable_candidates(numeric, bool(args.observations))[selected].fit(
        x[dev], data.loc[dev, target]
    )
    joblib.dump(selected_model, args.out_dir / "ensemble.joblib")
    metadata = {
        "target_type": "observed municipal yield" if args.observations else "WOFOST simulation",
        "selected_by_cv": selected,
        "features": numeric if args.observations else list(x.drop(columns="year").columns),
        "seed": 42,
        "versions": {
            name: version(name) for name in ("numpy", "pandas", "scikit-learn", "scipy", "xgboost", "joblib")
        },
        "holdout_years": sorted(predictions.year.unique().tolist()),
        "inputs": [
            {"path": str(p.resolve()), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths
        ],
        "blend_weights": {
            name: model.weights_.tolist()
            for name, model in models.items()
            if hasattr(model, "weights_") and model.method != "ridge"
        },
        "audit": audit,
    }
    (args.out_dir / "run.json").write_text(json.dumps(metadata, indent=2) + "\n")
    if args.observations:
        plot_observed(data, predictions, selected, args.out_dir)
    print(metrics[metrics.split.isin(["cv_pooled", "holdout"])].round(3).to_string(index=False))
    print(f"CV selected: {selected}; target: {metadata['target_type']}")


if __name__ == "__main__":
    main()
