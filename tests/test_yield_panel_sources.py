"""Offline checks for the extra gridded sources (src/yield_panel/gridded.py, ablation.py)."""

import unittest

import numpy as np
import pandas as pd

from src.yield_panel import ablation, gridded


class TestSampling(unittest.TestCase):
    lat = np.arange(19.0, 21.01, 0.1)
    lon = np.arange(-101.0, -98.99, 0.1)

    def test_radius_mean_and_nearest(self):
        cube = np.zeros((1, len(self.lat), len(self.lon)))
        i, j = 10, 10  # (20.0, -100.0)
        cube[0, i, j] = 9.0
        near, _ = gridded.sample(cube, self.lat, self.lon, [(20.0, -100.0)], radius_km=1)
        self.assertAlmostEqual(near[0, 0], 9.0)  # radius below one cell -> nearest cell
        wide, _ = gridded.sample(cube, self.lat, self.lon, [(20.0, -100.0)], radius_km=12)
        self.assertTrue(0 < wide[0, 0] < 9.0)  # averaged with zero neighbours

    def test_weights_and_fallback(self):
        cube = np.ones((1, len(self.lat), len(self.lon)))
        cube[0, :, :10] = 5.0  # west half different
        weights = np.zeros_like(cube[0])
        weights[:, :10] = 1.0  # only the west half is cropland
        out, used = gridded.sample(cube, self.lat, self.lon, [(20.0, -100.05)], radius_km=20, weights=weights)
        self.assertAlmostEqual(out[0, 0], 5.0)
        self.assertTrue(used[0])
        out, used = gridded.sample(cube, self.lat, self.lon, [(20.0, -99.2)], radius_km=10, weights=weights)
        self.assertAlmostEqual(out[0, 0], 1.0)  # no cropland nearby -> plain mean
        self.assertFalse(used[0])

    def test_nan_cells_ignored(self):
        cube = np.full((1, len(self.lat), len(self.lon)), 2.0)
        cube[0, 10, 10] = np.nan
        out, _ = gridded.sample(cube, self.lat, self.lon, [(20.0, -100.0)], radius_km=15)
        self.assertAlmostEqual(out[0, 0], 2.0)


class TestFeatures(unittest.TestCase):
    def test_rain_features_match_power_definitions(self):
        days = pd.date_range("2019-11-01", "2020-12-31")
        rain = pd.Series(0.0, index=days)
        rain[(days.year == 2020) & (days.month == 6) & (days.day >= 10)] = 5.0
        f = gridded.rain_features(rain, [2020], "x").iloc[0]
        self.assertAlmostEqual(f.x_rain_season_mm, 105.0)
        self.assertEqual(f.x_onset_doy, pd.Timestamp("2020-06-13").dayofyear)
        self.assertEqual(f.x_longest_dry_spell_days, 123)

    def test_ndvi_features(self):
        months = pd.date_range("2020-01-01", "2020-12-01", freq="MS")
        values = [0.2, 0.2, 0.2, 0.2, 0.25, 0.3, 0.5, 0.7, 0.6, 0.4, 0.3, 0.25]
        f = gridded.ndvi_features(months, values, [2020], "ndvi").iloc[0]
        self.assertAlmostEqual(f.ndvi_peak, 0.7)
        self.assertEqual(f.ndvi_peak_month, 8)
        self.assertAlmostEqual(f.ndvi_pre_season, 0.2)
        self.assertEqual(f.ndvi_greenup_month, 7)  # first month >= 0.45 (half-way 0.2 -> 0.7)
        self.assertAlmostEqual(f.ndvi_integral_may_oct, 0.25 + 0.3 + 0.5 + 0.7 + 0.6 + 0.4)

    def test_cmg_window(self):
        (r0, r1, c0, c1), lat, lon = gridded._cmg_window((17, 26, -106, -96))
        self.assertEqual((r0, r1, c0, c1), (1280, 1459, 1480, 1679))
        self.assertAlmostEqual(lat[0], 25.975)
        self.assertAlmostEqual(lon[0], -105.975)

    def test_smap_features(self):
        days = pd.date_range("2020-05-01", "2020-10-31")
        rz = pd.Series(0.30, index=days)
        rz[(days.month == 7) | (days.month == 8)] = 0.20
        f = gridded.smap_features(days, rz.values, rz.values, [2020]).iloc[0]
        self.assertAlmostEqual(f.smap_rootzone_jun, 0.30)
        self.assertAlmostEqual(f.smap_rootzone_jul_aug, 0.20)


class TestAblation(unittest.TestCase):
    def test_feature_sets_only_use_available_columns(self):
        cols = set(ablation.WEATHER_FEATURES) | set(ablation.prefixed("imerg"))
        sets = ablation.feature_sets(cols)
        self.assertIn("power + imerg", sets)
        self.assertTrue(all(c in cols for w, _ in sets.values() for c in w))
        self.assertEqual(sets["power + chirps"][0], ablation.WEATHER_FEATURES)  # no chirps columns -> power only

    def test_district_panel_sums_and_weights(self):
        rows = [{"crop": "maize", "state_id": 1, "mun_id": m, "ddr": 7, "year": y, "sown_ha": s, "harvested_ha": h,
                 "lost_ha": s - h, "production_t": prod, "rain_season_mm": rain}
                for y in range(2000, 2012)
                for m, s, h, prod, rain in [(1, 100, 80, 160, 500.0), (2, 300, 300, 900, 900.0)]]
        d = ablation.district_panel(pd.DataFrame(rows), ["rain_season_mm"]).iloc[0]
        self.assertEqual((d.mun_id, d.n_municipalities, d.sown_ha), (7, 2, 400))
        self.assertAlmostEqual(d.yield_t_ha, 1060 / 380)
        self.assertAlmostEqual(d.failure_rate, 20 / 400)
        self.assertAlmostEqual(d.rain_season_mm, (100 * 500 + 300 * 900) / 400)  # sown-area weighted

    def test_district_check_separates_reporting_from_weather(self):
        rng = np.random.default_rng(1)
        rows = []
        for y in range(2005, 2020):
            district_shock = {d: rng.normal(0, 1) for d in range(4)}
            for m in range(40):
                ddr, cell = m % 4, m // 10  # every cell holds municipalities of all four districts
                rows.append({"crop": "maize", "state_id": 1, "mun_id": m, "ddr": ddr, "cell_id": cell, "year": y,
                             "yield_t_ha": 3 + district_shock[ddr] + rng.normal(0, 0.3)})
        out = ablation.district_check(pd.DataFrame(rows), "maize", "yield_t_ha")
        self.assertGreater(out["r_same_cell_same_district"], 0.8)
        self.assertLess(abs(out["r_same_cell_other_district"]), 0.2)

    def test_shared_variance_detects_group_shocks(self):
        rng = np.random.default_rng(0)
        rows = []
        for m in range(40):
            for y in range(2005, 2020):
                shock = np.sin(y * (1 + m // 10))  # 4 groups with their own year shocks
                rows.append({"crop": "maize", "state_id": 1, "mun_id": m, "year": y, "cell_id": m // 10,
                             "grp": m // 10, "yield_t_ha": 2 + shock + rng.normal(0, 0.3)})
        out = ablation.shared_variance(pd.DataFrame(rows), "maize", "yield_t_ha",
                                       {"cell": ["cell_id"], "state": ["state_id"]})
        self.assertGreater(out["shared_cell"], 0.7)
        self.assertLess(out["shared_state"], out["shared_cell"])


if __name__ == "__main__":
    unittest.main()
