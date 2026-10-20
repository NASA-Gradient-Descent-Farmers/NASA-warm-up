"""Checks for the opt-in WOFOST calibration helpers: parameter overrides, pairing with SIAP, fit metrics,
naive baselines and the fertilizer-trial constraint."""

import unittest

import numpy as np
import pandas as pd

from src.crop_models.calibration import (CALIBRATION_YEARS, DEFAULT, HOLDOUT_YEARS, TRIAL_NO_N_RATIO, baselines,
                                         best_candidate, distance_from_default, edge_knobs, fertilizer_ratio,
                                         fit_metrics, grid, paired, scale_table, simulator_settings,
                                         split_candidate, variety_overrides, with_baselines, within_trial)
from src.crop_models.farm_tool import simulated_like_siap
from src.crop_models.rotation_experiments import TARGET

VARIETY = {"TSUM1": 700.0, "TSUM2": 800.0, "AMAX_REF": 80.0, "AMAX_SLP": 8.0, "EFFTB": [0.0, 0.45, 40.0, 0.45]}


class OverrideTests(unittest.TestCase):
    def test_scale_table_scales_only_y_values(self):
        self.assertEqual(scale_table([0.0, 0.4, 40.0, 0.5], 0.5), [0.0, 0.2, 40.0, 0.25])

    def test_default_knobs_change_nothing(self):
        self.assertEqual(variety_overrides(VARIETY), {})
        settings = simulator_settings({"maize": DEFAULT}, {"maize": VARIETY})
        self.assertEqual(settings, {"crop_params": {"maize": {}}, "n_recovery": {"maize": DEFAULT["n_recovery"]}})

    def test_knobs_scale_phenology_and_photosynthesis(self):
        out = variety_overrides(VARIETY, tsum_scale=0.8, photosynthesis_scale=0.5)
        self.assertAlmostEqual(out["TSUM1"], 560.0)
        self.assertAlmostEqual(out["TSUM2"], 640.0)
        self.assertAlmostEqual(out["AMAX_REF"], 40.0)
        self.assertAlmostEqual(out["AMAX_SLP"], 4.0)
        self.assertEqual(out["EFFTB"], [0.0, 0.225, 40.0, 0.225])
        self.assertEqual(VARIETY["TSUM1"], 700.0)  # the variety itself is not modified

    def test_settings_fill_missing_knobs_and_keep_site_overrides(self):
        settings = simulator_settings({"barley": {"n_recovery": 0.3}, "site": {"mineralization_rate": 0.0025}},
                                      {"barley": VARIETY})
        self.assertEqual(settings["crop_params"], {"barley": {}})
        self.assertEqual(settings["n_recovery"], {"barley": 0.3})
        self.assertEqual(settings["mineralization_rate"], 0.0025)

    def test_candidates_split_into_crop_and_site_knobs(self):
        crop, site = split_candidate({"n_recovery": 0.2, "tsum_scale": 1.0, "mineralization_rate": 0.0025})
        self.assertEqual(crop, {"n_recovery": 0.2, "tsum_scale": 1.0})
        self.assertEqual(site, {"mineralization_rate": 0.0025})

    def test_distance_is_relative_to_defaults(self):
        self.assertEqual(distance_from_default(DEFAULT), 0)
        self.assertAlmostEqual(distance_from_default({"n_recovery": 0.25, "mineralization_rate": 0.0025}), 1.0)

    def test_grid_lists_every_combination(self):
        combos = grid(tsum_scale=[0.8, 1.0], n_recovery=[0.25, 0.5, 0.75])
        self.assertEqual(len(combos), 6)
        self.assertIn({"tsum_scale": 0.8, "n_recovery": 0.75}, combos)


def seasons_fixture():
    rows = []
    for year in range(2005, 2026):
        rows.append({"rotation": "maize", "phase": 0, "year": year, "crop": "maize", "previous_crop": "maize",
                     TARGET: 4.0})
        rows.append({"rotation": "maize-barley", "phase": 0, "year": year, "crop": "maize",
                     "previous_crop": "barley", TARGET: 2.0})
        rows.append({"rotation": "maize-barley", "phase": 1, "year": year, "crop": "barley",
                     "previous_crop": "maize", TARGET: 1.0})
    return pd.DataFrame(rows)


def siap_fixture():
    # 100 ha of maize every year; barley (from 2008, as in SIAP) on 25 ha.
    rows = [{"crop": "maize", "year": y, "sown_ha": 100.0, "yield_sown_t_ha": 2.0 + (y % 2)}
            for y in range(2005, 2026)]
    rows += [{"crop": "barley", "year": y, "sown_ha": 25.0, "yield_sown_t_ha": 2.0} for y in range(2008, 2026)]
    return pd.DataFrame(rows)


class MetricTests(unittest.TestCase):
    def test_years_split_without_overlap(self):
        self.assertEqual(set(CALIBRATION_YEARS) & set(HOLDOUT_YEARS), set())
        self.assertEqual((min(CALIBRATION_YEARS), max(HOLDOUT_YEARS)), (2006, 2025))

    def test_simulated_maize_is_weighted_by_last_years_barley_area(self):
        simulated = simulated_like_siap(seasons_fixture(), siap_fixture())
        # 25 ha of barley in 2009 precede 100 ha of maize in 2010: 25% maize after barley, 75% after maize.
        self.assertAlmostEqual(simulated[("maize", 2010)], 0.75 * 4.0 + 0.25 * 2.0)
        # No barley in 2007, so all 2008 maize follows maize.
        self.assertAlmostEqual(simulated[("maize", 2008)], 4.0)
        self.assertAlmostEqual(simulated[("barley", 2010)], 1.0)

    def test_pairing_drops_years_without_observations(self):
        both = paired(simulated_like_siap(seasons_fixture(), siap_fixture()), siap_fixture())
        self.assertEqual(both[both["crop"] == "barley"]["year"].min(), 2008)
        self.assertEqual(len(both[both["crop"] == "maize"]), 21)

    def test_baselines_use_fit_year_mean_and_last_year(self):
        siap = pd.DataFrame({"crop": "maize", "year": [2020, 2021, 2022, 2024],
                             "yield_sown_t_ha": [2.0, 4.0, 10.0, 1.0]})
        naive = baselines(siap)
        climatology = naive["climatology"].set_index("year")["simulated_t_ha"]
        self.assertTrue((climatology == 3.0).all())  # 2022 and 2024 do not enter the fit-year mean
        persistence = naive["persistence"].set_index("year")["simulated_t_ha"]
        self.assertEqual(persistence.to_dict(), {2021: 2.0, 2022: 4.0})  # 2024 has no 2023 to persist

    def test_skill_is_relative_to_climatology(self):
        siap = pd.DataFrame({"crop": "maize", "year": range(2006, 2026), "yield_sown_t_ha": [2.0, 4.0] * 10})
        model = pd.DataFrame({"label": "model", "split": "calibration", "crop": "maize", "rmse_t_ha": [0.5]})
        table = with_baselines(model, siap).set_index(["label", "split"])
        self.assertAlmostEqual(table.loc[("climatology", "calibration"), "rmse_t_ha"], 1.0)
        self.assertAlmostEqual(table.loc[("model", "calibration"), "skill"], 0.5)
        self.assertAlmostEqual(table.loc[("climatology", "calibration"), "skill"], 0.0)

    def test_fit_metrics_level_rmse_and_correlation(self):
        both = pd.DataFrame({"crop": "maize", "year": [2006, 2007, 2008, 2022],
                             "simulated_t_ha": [3.0, 5.0, 4.0, 100.0], "observed_t_ha": [2.0, 4.0, 2.0, 1.0]})
        metrics = fit_metrics(both, CALIBRATION_YEARS).loc["maize"]
        self.assertEqual(metrics["years"], 3)  # the 2022 holdout year is excluded
        self.assertAlmostEqual(metrics["simulated_mean_t_ha"], 4.0)
        self.assertAlmostEqual(metrics["observed_mean_t_ha"], 8 / 3)
        self.assertAlmostEqual(metrics["ratio"], 1.5)
        self.assertAlmostEqual(metrics["bias_t_ha"], 4 / 3)
        self.assertAlmostEqual(metrics["rmse_t_ha"], np.sqrt((1 + 1 + 4) / 3))
        self.assertAlmostEqual(metrics["correlation"], both["simulated_t_ha"][:3].corr(both["observed_t_ha"][:3]))

    def test_best_candidate_minimizes_rmse_then_maximizes_correlation(self):
        scores = pd.DataFrame({"label": ["a", "b", "c", "d"], "crop": ["maize", "maize", "maize", "barley"],
                               "rmse_t_ha": [0.5, 0.4, 0.4, 0.1], "correlation": [0.9, 0.1, 0.3, 0.0]})
        self.assertEqual(best_candidate(scores, "maize")["label"], "c")

    def test_best_candidate_breaks_full_ties_by_distance_from_defaults(self):
        scores = pd.DataFrame({"label": ["far", "near"], "crop": "barley", "rmse_t_ha": [0.2841, 0.2844],
                               "correlation": [-0.1081, -0.1083], "distance": [1.2, 0.0]})
        self.assertEqual(best_candidate(scores, "barley")["label"], "near")

    def test_best_candidate_ranks_missing_correlation_last(self):
        scores = pd.DataFrame({"label": ["flat", "varies"], "crop": "maize", "rmse_t_ha": [0.3, 0.3],
                               "correlation": [np.nan, 0.2]})
        self.assertEqual(best_candidate(scores, "maize")["label"], "varies")


class TrialConstraintTests(unittest.TestCase):
    def test_fertilizer_ratio_uses_continuous_maize_in_fit_years(self):
        def runs(maize, partner):
            return pd.DataFrame({"rotation": ["maize", "maize", "maize-barley"], "year": [2010, 2023, 2010],
                                 TARGET: [maize, 99.0, partner]})
        self.assertAlmostEqual(fertilizer_ratio(runs(4.0, 8.0), runs(3.0, 0.0)), 0.75)

    def test_within_trial_keeps_close_candidates_or_the_closest(self):
        scores = pd.DataFrame({"label": ["a", "b", "c"], "fertilizer_ratio": [0.3, 0.88, 0.99]})
        self.assertEqual(list(within_trial(scores)["label"]), ["b", "c"])
        self.assertAlmostEqual(TRIAL_NO_N_RATIO, 5.2 / 5.6)
        far = pd.DataFrame({"label": ["a", "b"], "fertilizer_ratio": [0.3, 0.5]})
        self.assertEqual(list(within_trial(far)["label"]), ["b"])

    def test_edge_knobs_flags_extremes_of_varied_knobs(self):
        candidates = grid(tsum_scale=[0.8, 1.0], photosynthesis_scale=[0.4, 0.5, 0.6], n_recovery=[0.5])
        choice = {"tsum_scale": 1.0, "photosynthesis_scale": 0.5, "n_recovery": 0.5}
        self.assertEqual(edge_knobs(choice, candidates), ["tsum_scale"])


if __name__ == "__main__":
    unittest.main()
