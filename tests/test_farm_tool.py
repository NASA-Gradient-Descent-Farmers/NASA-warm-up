"""Checks for the farmer MVP helpers: SIAP parsing, farm-gap scaling and rotation economics."""

import unittest

import numpy as np
import pandas as pd

from src.crop_models.farm_tool import default_prices, extract_siap, farm_gap, rotation_economics
from src.crop_models.rotation_experiments import TARGET


def siap_frame(price_column="Precio"):
    base = {"Idestado": 15, "Idmunicipio": 99, "Idciclo": 2, "Idmodalidad": 2}
    rows = [
        {**base, "Nomcultivo": "Maíz grano", "Sembrada": 100, "Cosechada": 80, "Siniestrada": 20,
         "Volumenproduccion": 240, "Valorproduccion": 960000, price_column: 4000},
        {**base, "Nomcultivo": "Haba grano", "Sembrada": 10, "Cosechada": 10, "Siniestrada": 0,
         "Volumenproduccion": 20, "Valorproduccion": 300000, price_column: 15000},
        # Irrigated maize and another municipality must be ignored.
        {**base, "Idmodalidad": 1, "Nomcultivo": "Maíz grano", "Sembrada": 50, "Cosechada": 50,
         "Siniestrada": 0, "Volumenproduccion": 500, "Valorproduccion": 1, price_column: 1},
        {**base, "Idmunicipio": 1, "Nomcultivo": "Maíz grano", "Sembrada": 50, "Cosechada": 50,
         "Siniestrada": 0, "Volumenproduccion": 500, "Valorproduccion": 1, price_column: 1},
    ]
    return pd.DataFrame(rows)


def seasons_fixture():
    rows = []
    for year, maize, bean in ((2006, 6.0, 9.0), (2007, 2.0, 7.0)):
        rows.append({"scenario": "baseline", "rotation": "maize", "phase": 0, "year": year, "crop": "maize",
                     TARGET: maize, "n_fertilizer_kg_ha": 160})
        rows.append({"scenario": "baseline", "rotation": "maize-fababean", "phase": 0, "year": year,
                     "crop": "maize", TARGET: maize + 1, "n_fertilizer_kg_ha": 160})
        rows.append({"scenario": "baseline", "rotation": "maize-fababean", "phase": 1, "year": year,
                     "crop": "fababean", TARGET: bean, "n_fertilizer_kg_ha": 40})
    return pd.DataFrame(rows)


class SiapTests(unittest.TestCase):
    def test_filters_texcoco_rainfed_and_counts_lost_area(self):
        rows = {r["crop"]: r for r in extract_siap(siap_frame(), 2024)}
        self.assertEqual(set(rows), {"maize", "fababean"})
        maize = rows["maize"]
        self.assertAlmostEqual(maize["yield_harvested_t_ha"], 3.0)
        self.assertAlmostEqual(maize["yield_sown_t_ha"], 2.4)
        self.assertAlmostEqual(maize["lost_share"], 0.2)
        self.assertAlmostEqual(maize["price_mxn_t"], 4000)

    def test_newer_price_header_is_accepted(self):
        rows = extract_siap(siap_frame("PrecioMedioRural"), 2025)
        self.assertEqual(len(rows), 2)

    def test_default_prices_use_recent_median(self):
        siap = pd.DataFrame({"crop": ["maize"] * 4, "year": [2020, 2021, 2022, 2023],
                             "price_mxn_t": [1.0, 10.0, 30.0, 20.0]})
        self.assertEqual(default_prices(siap), {"maize": 20.0})


class EconomicsTests(unittest.TestCase):
    def test_farm_gap_compares_crop_year_means(self):
        siap = pd.DataFrame({"crop": ["maize", "maize"], "year": [2006, 2007], "yield_sown_t_ha": [3.25, 1.25]})
        gap, both = farm_gap(seasons_fixture(), siap)
        # Simulated maize averages both rotations: 6.5 and 2.5 -> mean 4.5; observed mean 2.25.
        self.assertAlmostEqual(gap.loc["maize", "factor"], 0.5)
        self.assertAlmostEqual(gap.loc["maize", "correlation"], 1.0)
        self.assertEqual(len(both), 2)

    def test_annual_rotation_value_averages_phases(self):
        prices = {"maize": 1000, "fababean": 2000}
        costs = {"maize": 500, "fababean": 100}
        seasons, annual, summary, crops = rotation_economics(
            seasons_fixture(), prices, costs, n_price=10, yield_factors={"fababean": 0.5})
        row = annual[(annual["rotation"] == "maize-fababean") & (annual["year"] == 2006)].iloc[0]
        maize_net = 7.0 * 1000 - (500 + 160 * 10)
        bean_net = 9.0 * 0.5 * 2000 - (100 + 40 * 10)
        self.assertAlmostEqual(row["net_mxn_ha"], (maize_net + bean_net) / 2)
        mono = summary.set_index("rotation").loc["maize"]
        self.assertAlmostEqual(mono["worst_net_mxn_ha"], 2.0 * 1000 - 2100)
        self.assertAlmostEqual(mono["loss_year_share"], 0.5)
        self.assertTrue(np.isclose(crops.set_index(["rotation", "crop"]).loc[("maize-fababean", "fababean"),
                                                                             "mean_yield_t_ha"], 4.0))

    def test_missing_price_is_rejected(self):
        with self.assertRaises(ValueError):
            rotation_economics(seasons_fixture(), {"maize": 1}, {"maize": 1, "fababean": 1}, n_price=1)


if __name__ == "__main__":
    unittest.main()
