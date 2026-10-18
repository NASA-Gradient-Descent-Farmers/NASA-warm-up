"""Benchmark tree surrogates of WOFOST yield with whole-year temporal validation.

Fit one crop at a time. Select the model using expanding-window cross-validation,
then evaluate on the latest, untouched years. These emulate simulations, not field yields.
"""

import argparse
import hashlib
import json
from importlib.metadata import version
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.tree import DecisionTreeRegressor, export_text

from .rotation_experiments import KEY, TARGET, load_seasons

# Explicit allowlists keep post-harvest outputs and scenario/year IDs out of X.
CATEGORICAL = ["rotation", "previous_crop", "sowing_mode", "rain_months"]
PLANNING = [
    "n_fertilizer_kg_ha",
    "soil_water_at_start_mm",
    "mineral_n_at_start_kg_ha",
    "rain_factor",
    "n_scale",
    "frost_tmin_offset",
]
HINDCAST = ["rain_may_oct_mm", "rain_jul_aug_mm", "longest_dry_spell_days", "sowing_doy"]


def build_features(seasons, feature_set="planning"):
    """Planning uses initial state and assumed scenario forcing, hindcast adds realized weather."""
    if feature_set not in ("planning", "hindcast"):
        raise ValueError("feature_set must be planning or hindcast")
    data = seasons.copy()
    numeric = PLANNING.copy()
    if feature_set == "hindcast":
        data["sowing_doy"] = pd.to_datetime(data["sowing"], errors="raise").dt.dayofyear
        numeric += HINDCAST
    features = data[CATEGORICAL + numeric].copy()
    for column in CATEGORICAL:
        features[column] = features[column].fillna("none").astype(str)
    for column in numeric:
        features[column] = pd.to_numeric(features[column], errors="raise")
        if not np.isfinite(features[column]).all():
            raise ValueError(f"Feature {column} must contain finite values")
    return features, numeric


def temporal_splits(years, test_years=4, folds=3):
    """Split unique calendar years, then map them back to ALL scenarios and phases."""
    years = np.asarray(years)
    unique = np.unique(years)
    if test_years < 1 or folds < 2 or len(unique) - test_years <= folds:
        raise ValueError("Need test_years >= 1, folds >= 2 and at least folds+1 development years")
    development = unique[:-test_years]
    holdout = unique[-test_years:]
    splits = []
    for train, valid in TimeSeriesSplit(n_splits=folds).split(development):
        splits.append(
            (
                np.flatnonzero(np.isin(years, development[train])),
                np.flatnonzero(np.isin(years, development[valid])),
            )
        )
    return splits, np.flatnonzero(np.isin(years, development)), np.flatnonzero(np.isin(years, holdout))


def model_candidates(numeric, seed=42, include_xgboost=True):
    preprocessing = ColumnTransformer(
        [
            ("numeric", SimpleImputer(strategy="median"), numeric),
            ("categorical", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL),
        ],
        verbose_feature_names_out=False,
    )
    estimators = {
        "mean": DummyRegressor(strategy="mean"),
        "decision_tree": DecisionTreeRegressor(max_depth=4, min_samples_leaf=5, random_state=seed),
        "random_forest": RandomForestRegressor(
            n_estimators=250, max_depth=6, min_samples_leaf=3, max_features=0.8, random_state=seed, n_jobs=1
        ),
    }
    if include_xgboost:
        # Import only when requested, so other exploratory models remain usable independently.
        from xgboost import XGBRegressor

        estimators["xgboost"] = XGBRegressor(
            n_estimators=250,
            max_depth=3,
            learning_rate=0.04,
            min_child_weight=5,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_lambda=5.0,
            objective="reg:squarederror",
            tree_method="hist",
            random_state=seed,
            n_jobs=1,
        )
    return {
        name: Pipeline([("features", clone(preprocessing)), ("model", model)])
        for name, model in estimators.items()
    }


def score(y, predicted):
    return {
        "mae_t_ha": float(mean_absolute_error(y, predicted)),
        "rmse_t_ha": float(np.sqrt(mean_squared_error(y, predicted))),
        "r2": float(r2_score(y, predicted)) if len(y) > 1 and np.var(y) > 0 else None,
    }


def benchmark(
    seasons, crop="maize", feature_set="planning", test_years=4, folds=3, seed=42, include_xgboost=True
):
    """Return metrics, predictions, fold membership, fitted models and CV-selected name.

    Returned models are fit on development years only. All preprocessing is fitted
    within each fold. No tuning, early stopping or model selection uses the holdout.
    """
    data = seasons.loc[seasons["crop"] == crop].reset_index(drop=True)
    if data.empty:
        raise ValueError(f"No seasons for crop {crop!r}")
    x, numeric = build_features(data, feature_set)
    y = data[TARGET].to_numpy()
    splits, development, holdout = temporal_splits(data["year"], test_years, folds)
    metrics, predictions, memberships, fitted = [], [], [], {}
    for fold, (train, valid) in enumerate(splits, 1):
        for role, indices in (("train", train), ("validation", valid)):
            memberships.append(data.iloc[indices][KEY].assign(fold=fold, role=role))
    for role, indices in (("development", development), ("holdout", holdout)):
        memberships.append(data.iloc[indices][KEY].assign(fold=0, role=role))

    for name, template in model_candidates(numeric, seed, include_xgboost).items():
        cv_actual, cv_predicted = [], []
        for fold, (train, valid) in enumerate(splits, 1):
            model = clone(template).fit(x.iloc[train], y[train])
            predicted = np.maximum(0, model.predict(x.iloc[valid]))
            metrics.append(
                {"model": name, "split": f"cv_{fold}", "rows": len(valid), **score(y[valid], predicted)}
            )
            cv_actual.extend(y[valid])
            cv_predicted.extend(predicted)
        metrics.append(
            {"model": name, "split": "cv_pooled", "rows": len(cv_actual), **score(cv_actual, cv_predicted)}
        )
        model = clone(template).fit(x.iloc[development], y[development])
        predicted = np.maximum(0, model.predict(x.iloc[holdout]))
        metrics.append(
            {"model": name, "split": "holdout", "rows": len(holdout), **score(y[holdout], predicted)}
        )
        predictions.append(
            data.iloc[holdout][KEY + ["crop", "previous_crop", TARGET]].assign(
                model=name, predicted_yield_t_ha=predicted
            )
        )
        fitted[name] = model
    metrics = pd.DataFrame(metrics)
    selected = metrics.loc[metrics["split"] == "cv_pooled"].sort_values("rmse_t_ha").iloc[0]["model"]
    return metrics, pd.concat(predictions), pd.concat(memberships), fitted, selected


def save_diagnostics(metrics, predictions, selected, directory):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    comparison = metrics[metrics["split"].isin(["cv_pooled", "holdout"])].pivot(
        index="model", columns="split", values="rmse_t_ha"
    )
    comparison.plot.bar(ax=axes[0], rot=20)
    axes[0].set(ylabel="RMSE (t/ha)", xlabel="", title="WOFOST surrogate error")
    p = predictions[predictions["model"] == selected]
    for scenario, group in p.groupby("scenario"):
        axes[1].scatter(group[TARGET], group["predicted_yield_t_ha"], label=scenario, s=15, alpha=0.7)
    upper = max(p[TARGET].max(), p["predicted_yield_t_ha"].max(), 1)
    axes[1].plot([0, upper], [0, upper], "k--", linewidth=1)
    axes[1].set(
        xlabel="WOFOST yield (t/ha)", ylabel="Predicted yield (t/ha)", title=f"Holdout years: {selected}"
    )
    axes[1].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(directory / "diagnostics.png", dpi=160)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", nargs="+", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=Path("data/tree_surrogate"))
    parser.add_argument("--crop", default="maize")
    parser.add_argument("--feature-set", choices=["planning", "hindcast"], default="planning")
    parser.add_argument("--test-years", type=int, default=4)
    parser.add_argument("--folds", type=int, default=3)
    parser.add_argument("--spinup-years", type=int, default=1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--without-xgboost", action="store_true")
    args = parser.parse_args()
    seasons = load_seasons(args.input, args.spinup_years)
    metrics, predictions, membership, models, selected = benchmark(
        seasons, args.crop, args.feature_set, args.test_years, args.folds, args.seed, not args.without_xgboost
    )
    directory = args.out_dir
    directory.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(directory / "metrics.csv", index=False)
    predictions.to_csv(directory / "holdout_predictions.csv", index=False)
    grouped_scores = [
        {
            "model": model,
            "scenario": scenario,
            "rotation": rotation,
            "rows": len(group),
            **score(group[TARGET], group["predicted_yield_t_ha"]),
        }
        for (model, scenario, rotation), group in predictions.groupby(["model", "scenario", "rotation"])
    ]
    pd.DataFrame(grouped_scores).to_csv(directory / "holdout_groups.csv", index=False)
    membership.to_csv(directory / "fold_membership.csv", index=False)
    feature_names = models["decision_tree"]["features"].get_feature_names_out()
    (directory / "decision_tree.txt").write_text(
        export_text(models["decision_tree"]["model"], feature_names=list(feature_names))
    )
    importances = []
    for name, model in models.items():
        if hasattr(model["model"], "feature_importances_"):
            importances.extend(
                {"model": name, "feature": feature, "importance": float(value)}
                for feature, value in zip(
                    model["features"].get_feature_names_out(), model["model"].feature_importances_
                )
            )
    pd.DataFrame(importances).to_csv(directory / "feature_importance.csv", index=False)
    # Preserve the preprocessing and named DataFrame inputs along with the chosen model.
    joblib.dump(models[selected], directory / "surrogate.joblib")
    x, _ = build_features(seasons[seasons["crop"] == args.crop], args.feature_set)
    metadata = {
        "selected_by_cv": selected,
        "target": TARGET,
        "crop": args.crop,
        "feature_set": args.feature_set,
        "features": list(x.columns),
        "seed": args.seed,
        "spinup_years": args.spinup_years,
        "test_years": args.test_years,
        "folds": args.folds,
        "development_years": sorted(
            membership.loc[membership["role"] == "development", "year"].unique().tolist()
        ),
        "holdout_years": sorted(membership.loc[membership["role"] == "holdout", "year"].unique().tolist()),
        "inputs": [
            {"path": str(p.resolve()), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in args.input
        ],
        "versions": {
            name: version(name)
            for name in ["numpy", "pandas", "scikit-learn", "joblib"]
            + ([] if args.without_xgboost else ["xgboost"])
        },
        "interpretation": "Emulates WOFOST at one site; field calibration and prospective validation required.",
    }
    (directory / "run.json").write_text(json.dumps(metadata, indent=2) + "\n")
    save_diagnostics(metrics, predictions, selected, directory)
    print(metrics[metrics["split"].isin(["cv_pooled", "holdout"])].round(3).to_string(index=False))
    print(f"\nSelected by development-year CV: {selected}. Saved model and diagnostics to {directory}")


if __name__ == "__main__":
    main()
