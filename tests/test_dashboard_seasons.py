"""Checks for the season exports behind the dashboard's economics, reality-check and what-if tabs."""

import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from src.crop_models import dashboard_seasons as ds
from src.crop_models.rotation_experiments import SCENARIOS, TARGET

ROTATIONS = {"maize": ["maize"], "maize-fababean": ["maize", "fababean"]}
YEARS = range(2005, 2011)  # 2005 is the spin-up year
CLASSES = {2006: "dry", 2007: "normal", 2008: "wet", 2009: "normal", 2010: "dry"}


def seasons(scenario="baseline", suffix=""):
    """Known seasons: yield 3 + phase + 0.1 (year - 2005), halved under rain60; frost ends faba bean in 2008."""
    rows = []
    settings = SCENARIOS[scenario].metadata()
    for rotation, crops in ROTATIONS.items():
        for phase in range(len(crops)):
            for year in YEARS:
                crop = crops[(phase + year) % len(crops)]
                value = 3 + phase + 0.1 * (year - 2005)
                rows.append({"scenario": scenario + suffix, "rotation": rotation, "phase": phase, "year": year,
                             "crop": crop, "previous_crop": crops[(phase + year - 1) % len(crops)],
                             TARGET: value / 2 if scenario == "rain60" else value,
                             "n_fertilizer_kg_ha": 160 if crop == "maize" else 40,
                             "soil_water_at_start_mm": 200, "mineral_n_at_start_kg_ha": 10,
                             "frost_ended": crop == "fababean" and year == 2008,
                             "rain_may_oct_mm": 500 + year, "year_class": CLASSES.get(year, "normal"), **settings})
    return pd.DataFrame(rows)


def siap():
    rows = [{"year": y, "crop": crop, "sown_ha": 100.0, "lost_share": 0.0, "yield_sown_t_ha": level + 0.2 * (y % 2),
             "yield_harvested_t_ha": level + 0.2 * (y % 2), "price_mxn_t": 8000.0}
            for y in range(2006, 2011) for crop, level in (("maize", 2.0), ("fababean", 1.0))]
    return pd.DataFrame(rows)


ECONOMICS = {"prices": {"maize": 8000.0, "fababean": 15000.0}, "other_costs": {"maize": 14000, "fababean": 11000},
             "n_price": 25.0}


class SeasonExportTests(unittest.TestCase):
    def loaded(self, scenarios=("baseline", "rain60")):
        from src.crop_models.rotation_experiments import load_seasons

        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        for name in scenarios:
            seasons(name).to_csv(tmp / f"{name}.csv", index=False)
        return load_seasons(sorted(tmp.glob("*.csv")))

    def test_world_payload_is_year_major_with_weather_per_year(self):
        payload = ds.world_payload(self.loaded(), ROTATIONS)
        self.assertEqual(payload["years"], list(range(2006, 2011)))  # spin-up removed
        base = payload["scenarios"]["baseline"]
        self.assertEqual(base["year_class"], [CLASSES[y] for y in range(2006, 2011)])
        self.assertEqual(base["rain_may_oct_mm"], [500.0 + y for y in range(2006, 2011)])
        rotation = base["rotations"]["maize-fababean"]
        self.assertEqual(rotation["phases"], 2)
        self.assertEqual(rotation["crops"][0], ["maize", "fababean"])  # 2006: phase p grows crops[(p + 2006) % 2]
        self.assertAlmostEqual(rotation["fields"][TARGET][1], 4.1)  # 2006, phase 1
        self.assertAlmostEqual(payload["scenarios"]["rain60"]["rotations"]["maize"]["fields"][TARGET][0], 1.55)
        frost = rotation["frost_ended"]
        self.assertEqual(sum(frost), 1)
        self.assertEqual(frost[2 * 2 + 1], 1)  # 2008 is the third year; faba bean is phase 1 that year

    def test_risk_compares_every_rotation_with_continuous_maize(self):
        risk = ds.risk_payload(self.loaded())
        self.assertEqual(set(risk), {"baseline", "rain60"})
        self.assertEqual(risk["baseline"]["maize"]["mean_advantage_t_ha"], 0.0)
        self.assertEqual(risk["baseline"]["maize"]["paired_years"], 5)
        self.assertIn("prob_any_failed_harvest", risk["rain60"]["maize-fababean"])

    def test_scenario_settings_list_rain_months(self):
        settings = ds.scenario_settings()
        self.assertEqual(list(settings), list(SCENARIOS))
        self.assertEqual(settings["canicula50"]["rain_months"], [7, 8])
        self.assertEqual(settings["baseline"], {**asdict(SCENARIOS["baseline"]), "rain_months": []})

    def test_payloads_meta_and_reference_economics(self):
        both = {"calibrated": self.loaded(), "default": self.loaded()}
        scenarios, reality, reference, meta = ds.build_season_payloads(both, siap(), ECONOMICS, {"default": {}})
        self.assertEqual(set(scenarios["worlds"]), {"calibrated", "default"})
        self.assertEqual(reality["siap"]["maize"]["year"], list(range(2006, 2011)))
        gap = reality["worlds"]["default"]["maize"]
        self.assertEqual(len(gap["year"]), gap["years"])
        self.assertAlmostEqual(gap["factor"], gap["observed_mean_t_ha"] / gap["simulated_mean_t_ha"])
        self.assertEqual(set(reference), {"calibrated:raw", "default:raw", "default:siap_level"})
        self.assertIsNone(reference["default:raw"]["yield_factors"])
        self.assertAlmostEqual(reference["default:siap_level"]["yield_factors"]["maize"], gap["factor"])
        self.assertEqual(meta["farm"]["season_years"], [2006, 2010])
        self.assertEqual(meta["farm"]["failure_threshold_t_ha"], ds.FAILURE_THRESHOLD)

    def test_worlds_must_cover_the_same_years(self):
        short = self.loaded()
        short = short[short["year"] < 2010]
        with self.assertRaisesRegex(ValueError, "different years"):
            ds.build_season_payloads({"calibrated": self.loaded(), "default": short}, siap(), ECONOMICS)

    def test_load_world_unsuffixes_calibrated_names_and_wants_every_scenario(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        seasons("baseline", "_calibrated").to_csv(tmp / "baseline.csv", index=False)
        with self.assertRaisesRegex(ValueError, "missing scenarios"):
            ds.load_world(tmp, "calibrated")
        for name in SCENARIOS:
            seasons(name, "_calibrated").to_csv(tmp / f"{name}.csv", index=False)
        loaded, hashes = ds.load_world(tmp, "calibrated")
        self.assertEqual(set(loaded["scenario"]), set(SCENARIOS))
        self.assertEqual(len(hashes), len(SCENARIOS))
        with self.assertRaisesRegex(FileNotFoundError, "rotation_experiments"):
            ds.load_world(tmp / "empty", "default")


if __name__ == "__main__":
    unittest.main()
