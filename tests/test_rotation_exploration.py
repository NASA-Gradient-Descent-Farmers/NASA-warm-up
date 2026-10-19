"""Regression checks for year isolation, feature leakage and paired weather sampling."""

import tempfile
import unittest
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from src.crop_models.rotation_experiments import SCENARIOS, TARGET, load_seasons
from src.crop_models.rotation_risk import compare_rotations
from src.crop_models.tree_surrogate import benchmark, build_features, temporal_splits


def season_fixture():
    rows = []
    for scenario in ("baseline", "rain80"):
        for year in range(2005, 2017):
            for rotation, advantage in (("maize", 0), ("maize-fababean", 2)):
                rows.append(
                    {
                        "scenario": scenario,
                        "rotation": rotation,
                        "phase": 0,
                        "year": year,
                        "crop": "maize",
                        "previous_crop": "maize" if rotation == "maize" else "fababean",
                        TARGET: float(year % 4 + advantage),
                        "n_fertilizer_kg_ha": 160.0,
                        "soil_water_at_start_mm": 200.0,
                        "mineral_n_at_start_kg_ha": 10.0 + advantage,
                        "sowing": f"{year}-06-01",
                        "rain_may_oct_mm": 600.0,
                        "rain_jul_aug_mm": 200.0,
                        "longest_dry_spell_days": 10,
                        **SCENARIOS[scenario].metadata(),
                    }
                )
    return pd.DataFrame(rows)


class LoadingTests(unittest.TestCase):
    def test_spinup_is_per_run_and_legacy_settings_are_restored(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = []
            data = season_fixture()
            for scenario, group in data.groupby("scenario"):
                if scenario == "rain80":
                    group = group[group["year"] >= 2008]
                path = Path(directory) / f"{scenario}.csv"
                group.drop(
                    columns=["scenario", "rain_months", "frost_tmin_offset", "n_scale", "sowing_mode"]
                ).to_csv(path, index=False)
                paths.append(path)
            loaded = load_seasons(paths)
            self.assertEqual(
                loaded.groupby("scenario")["year"].min().to_dict(), {"baseline": 2006, "rain80": 2009}
            )
            self.assertTrue((loaded["sowing_mode"] == "onset").all())

    def test_unknown_legacy_settings_and_duplicate_runs_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unknown.csv"
            data = season_fixture()
            data.to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                load_seasons([path, path])
            data.drop(columns=list(SCENARIOS["baseline"].metadata())).to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, "Missing columns"):
                load_seasons([path])

    def test_nonfinite_yields_and_inconsistent_settings_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "suite.csv"
            data = season_fixture()
            data.loc[0, TARGET] = np.inf
            data.to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, "finite"):
                load_seasons([path])
            data.loc[0, TARGET] = 1
            data.loc[0, "n_scale"] = 0.5
            data.to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, "inconsistent"):
                load_seasons([path])


class ValidationTests(unittest.TestCase):
    def test_all_scenarios_of_a_year_stay_together(self):
        original = season_fixture()
        data = pd.concat([original, original.assign(phase=1)]).sample(frac=1, random_state=8)
        splits, development, holdout = temporal_splits(data["year"], test_years=2, folds=3)
        self.assertEqual(set(data.iloc[holdout]["year"]), {2015, 2016})
        self.assertLess(data.iloc[development]["year"].max(), data.iloc[holdout]["year"].min())
        for train, valid in splits:
            self.assertLess(data.iloc[train]["year"].max(), data.iloc[valid]["year"].min())
            for indices in (train, valid):
                selected = data.iloc[indices]
                for year in selected["year"].unique():
                    self.assertEqual((selected["year"] == year).sum(), (data["year"] == year).sum())

    def test_planning_features_ignore_future_weather_and_harvest_outputs(self):
        data = season_fixture()
        before, _ = build_features(data)
        data[TARGET] = 999
        data["rain_may_oct_mm"] = 999
        data["sowing"] = "2025-12-31"
        data["grain_n_kg_ha"] = 999
        after, _ = build_features(data)
        pd.testing.assert_frame_equal(before, after)
        self.assertTrue(
            {TARGET, "year", "scenario", "phase", "sowing_doy", "grain_n_kg_ha"}.isdisjoint(after.columns)
        )
        hindcast, _ = build_features(data, "hindcast")
        self.assertIn("rain_may_oct_mm", hindcast)

    def test_holdout_targets_do_not_affect_selection_and_saved_model_replays(self):
        data = season_fixture()
        metrics, predictions, _, models, selected = benchmark(data, test_years=2, folds=2)
        changed = data.copy()
        changed.loc[changed["year"] >= 2015, TARGET] += 100
        second, _, _, _, selected_again = benchmark(changed, test_years=2, folds=2)
        self.assertEqual(selected, selected_again)
        pd.testing.assert_frame_equal(
            metrics[metrics["split"] != "holdout"], second[second["split"] != "holdout"]
        )
        self.assertEqual(set(models), {"mean", "decision_tree", "random_forest", "xgboost"})
        x, _ = build_features(data[data["year"] >= 2015])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.joblib"
            joblib.dump(models[selected], path)
            replay = np.maximum(0, joblib.load(path).predict(x))
        np.testing.assert_allclose(
            replay, predictions.loc[predictions["model"] == selected, "predicted_yield_t_ha"]
        )

    def test_too_few_years_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "development years"):
            temporal_splits([2005, 2006, 2007], test_years=2)


class PairedRiskTests(unittest.TestCase):
    def test_constant_rotation_effect_survives_shared_weather_draws(self):
        data = season_fixture()
        effects, risks = compare_rotations(data, draws=200, harvests=5)
        rotated = effects[effects["rotation"] == "maize-fababean"]
        for column in ("mean_advantage_t_ha", "advantage_ci_low_t_ha", "advantage_ci_high_t_ha"):
            np.testing.assert_allclose(rotated[column], 2.0)
        self.assertTrue((risks["prob_mean_below_reference"] == 0).all())
        again, again_risk = compare_rotations(data, draws=200, harvests=5)
        pd.testing.assert_frame_equal(effects, again)
        pd.testing.assert_frame_equal(risks, again_risk)

    def test_pairing_excludes_missing_years_and_averages_phases(self):
        data = season_fixture()
        extra = data[data["rotation"] == "maize-fababean"].copy()
        extra["phase"] = 1
        extra[TARGET] += 2
        data = pd.concat([data, extra])
        data = data[~((data["rotation"] == "maize") & (data["year"] == 2005))]
        effects, _ = compare_rotations(data, draws=100)
        self.assertTrue((effects["paired_years"] == 11).all())
        self.assertTrue((effects["excluded_years"] == 1).all())
        np.testing.assert_allclose(
            effects.loc[effects["rotation"] == "maize-fababean", "mean_advantage_t_ha"], 3
        )

    def test_missing_reference_is_not_silently_dropped(self):
        with self.assertRaisesRegex(ValueError, "Reference"):
            compare_rotations(season_fixture(), reference="barley")


if __name__ == "__main__":
    unittest.main()
