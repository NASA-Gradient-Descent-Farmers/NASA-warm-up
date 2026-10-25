"""Offline checks for historic.py and planning.py."""

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from src.yield_panel import historic, planning


class TestHistoric(unittest.TestCase):
    def test_crop_names_across_eras(self):
        names = ["MAIZ GRANO SIN CLASIFICAR", "Maíz grano", "MAIZ GRANO (AMARILLO)", "MAIZ GRANO (SEMILLA)",
                 "MAIZ FORRAJERO EN VERDE", "FRIJOL SIN CLASIFICAR", "Frijol", "SORGO GRANO", "SORGO FORRAJERO EN VERDE",
                 "TRIGO GRANO SIN CLASIFICAR", "Cebada grano", "AVENA FORRAJERA EN VERDE", "Tomate rojo"]
        got = [None if pd.isna(c) else c for c in historic.crop_of(names)]
        self.assertEqual(got, ["maize", "maize", "maize", None, None, "bean", "bean", "sorghum", None, "wheat",
                               "barley", None, None])

    def test_area_weighted_features(self):
        feats = pd.DataFrame({"state_id": [1, 1], "mun_id": [1, 2], "year": [2000, 2000], "rain": [100.0, 400.0]})
        weights = pd.DataFrame({"state_id": [1, 1], "mun_id": [1, 2], "crop": ["maize", "maize"], "ddr": [5, 5],
                                "weight": [3.0, 1.0]})
        out = historic.area_weighted_features(feats, weights, ["state_id", "ddr"], ["rain"]).iloc[0]
        self.assertAlmostEqual(out.rain, (3 * 100 + 400) / 4)

    def test_finish_targets(self):
        t = historic._finish(pd.DataFrame({"sown_ha": [100.0, 0.0], "harvested_ha": [50.0, 0.0],
                                           "lost_ha": [50.0, 0.0], "production_t": [100.0, 0.0]}))
        self.assertEqual(t.yield_t_ha[0], 2.0)
        self.assertEqual(t.failure_rate[0], 0.5)
        self.assertTrue(np.isnan(t.yield_t_ha[1]) and np.isnan(t.failure_rate[1]))


class TestPlanning(unittest.TestCase):
    def test_read_psl(self):
        text = "  2000 2001\n 2000 " + " ".join(["0.5"] * 12) + "\n 2001 " + " ".join(["0.1"] * 11) + " -99.99\n  -99.99\n note\n"
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "x.data"
            path.write_text(text)
            s = planning.read_psl(path)
        self.assertEqual(len(s), 24)
        self.assertAlmostEqual(s["2000-03-01"], 0.5)
        self.assertTrue(np.isnan(s["2001-12-01"]))

    def test_index_features_use_only_data_known_by_april(self):
        oni = pd.DataFrame({"season": ["NDJ", "DJF", "FMA", "JAS"] * 2, "year": [2019] * 4 + [2020] * 4,
                            "anom": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]})
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            with open(d / "oni.ascii.txt", "w") as f:
                f.write("SEAS YR TOTAL ANOM\n")
                for r in oni.itertuples():
                    f.write(f"{r.season} {r.year} 27.0 {r.anom}\n")
            psl = "  2019 2020\n" + "".join(f" {y} " + " ".join([str(y - 2019 + 0.1 * m) for m in range(1, 13)]) + "\n" for y in (2019, 2020)) + "  -99.99\n"
            for name in ["nina34.anom.data", "tna.data", "amon.us.data", "pdo.data"]:
                (d / name).write_text(psl)
            f = planning.index_features(d).set_index("year")
        self.assertEqual(f.loc[2020, "oni_fma"], 7.0)
        self.assertEqual(f.loc[2020, "oni_jas_prev"], 4.0)        # last year's JAS
        self.assertEqual(f.loc[2020, "oni_tendency"], 7.0 - 1.0)  # FMA(2020) - NDJ(Nov 2019-Jan 2020)
        self.assertAlmostEqual(f.loc[2020, "nino34_apr"], 1.4)
        self.assertAlmostEqual(f.loc[2020, "tna_fma"], 1.3)       # mean of Feb-Apr

    def test_lags_do_not_bridge_gaps(self):
        p = pd.DataFrame({"crop": "maize", "state_id": 1, "mun_id": 1, "year": [2000, 2001, 2003], "x": [1.0, 2.0, 4.0]})
        out = planning.add_lags(p, ["x"]).set_index("year")
        self.assertTrue(np.isnan(out.loc[2000, "x_prev"]))
        self.assertEqual(out.loc[2001, "x_prev"], 1.0)
        self.assertTrue(np.isnan(out.loc[2003, "x_prev"]))  # 2002 missing: no lag

    def test_interactions(self):
        p = pd.DataFrame({"oni_fma": [1.0, 1.0, -1.0], "lat": [18.0, 20.0, 22.0]})
        out, names = planning.add_interactions(p, indices=["oni_fma"], place=["lat"])
        self.assertEqual(names, ["oni_fma_x_lat"])
        self.assertAlmostEqual(out.oni_fma_x_lat[1], 0.0)
        self.assertLess(out.oni_fma_x_lat[2], 0)

    def test_planning_sets_skip_missing_groups(self):
        cols = set(planning.OCEAN) | set(planning.PRESEASON)
        sets = planning.planning_sets(cols)
        self.assertIn("ocean", sets)
        self.assertNotIn("last season outcome", sets)
        self.assertNotIn("all + preseason ndvi", sets)

    def test_conditional_outlook(self):
        class Const:
            def predict(self, rows):
                return np.full(len(rows), 0.2)
        rows = pd.DataFrame({"a": [0]})
        out = planning.conditional_outlook(Const(), None, "failure_rate", rows, np.array([-0.3, 0.0, 0.05, 0.2]), 0.3)
        self.assertAlmostEqual(out["prediction"][0], 0.2)
        self.assertAlmostEqual(out["p_above_0.3"][0], 0.25)  # only 0.2 + 0.2 = 0.4 exceeds 0.3


if __name__ == "__main__":
    unittest.main()
