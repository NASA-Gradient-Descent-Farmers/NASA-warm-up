"""Checks for the dashboard export: front columns, grid layout, provenance guards and deterministic JSON."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.crop_models.dashboard_export import FRONT_COLUMNS, build_payloads, crop_plan, siap_prices, write_json
from src.crop_models.farm_setup import ROTATIONS as FARM_ROTATIONS, SITE
from src.crop_models.nsga_planner import CVAR_SHARE, FIELDS, FRONT_DECIMALS
from src.crop_models.rotation_experiments import TARGET

ECONOMICS = {"prices": {"maize": 8000.0}, "other_costs": {"maize": 14000}, "n_price": 25.0,
             "stover_price": 1000.0, "carbon_fraction": 0.45}
YEARS = (2006, 2007, 2008)
SCALES = (0.0, 0.5, 1.0)
ROTATIONS = {"maize": ["maize"], "maize-fababean": ["maize", "fababean"]}


def fake_plan():
    return {"maize": 160, "fababean": 40}, {key: list(crops) for key, crops in ROTATIONS.items()}


def fake_siap():
    rows = [(2023, "maize", 8000.0), (2024, "maize", 7000.0), (2025, "maize", 9000.0),
            (2023, "fababean", 16000.0), (2024, "fababean", 16500.0), (2025, "fababean", 5000.0)]
    return pd.DataFrame(rows, columns=["year", "crop", "price_mxn_t"])


def grid_rows(models):
    """Grid table with known values: yield 2 + scale + phase + 0.1 (year - 2006), uptake 50 + 10 scale."""
    return pd.DataFrame([
        {"model": model, "rotation": rotation, "phase": phase, "year": year, "crop": crop, "n_scale": scale,
         TARGET: 2 + scale + phase + 0.1 * (year - 2006), "n_fertilizer_kg_ha": 100 * scale,
         "n_uptake_kg_ha": 50 + 10 * scale, "stover_dm_t_ha": 4.0, "root_dm_t_ha": 1.0}
        for model in models for scale in SCALES for year in YEARS
        for rotation, crops in ROTATIONS.items() for phase, crop in enumerate(crops)])


def save_world(directory, grid_hash, economics=ECONOMICS, rows=None):
    directory.mkdir(parents=True)
    rows = rows or [["maize", 0.0, 0.0, 2.3, 5895.0348963227025 + 1e-12, 0.0, 0.11, -4187.3],
                    ["maize-fababean", 0.5, 0.9, 2.1, 11457.0, 12.5, 0.59, 3000.0]]
    frame = pd.DataFrame(rows, columns=FRONT_COLUMNS)
    frame["extra_column"] = 1  # columns outside FRONT_COLUMNS are not exported
    frame.to_csv(directory / "brute_force_front.csv", index=False)
    run = {"economics": economics, "design_years": [2006, 2008], "holdout_years": [2022, 2025],
           "grid_sha256": grid_hash}
    (directory / "run.json").write_text(json.dumps(run))


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.grid_csv = self.tmp / "grid.csv"
        grid_rows(["a", "b"]).to_csv(self.grid_csv, index=False)
        self.grid_hash = hashlib.sha256(self.grid_csv.read_bytes()).hexdigest()

    def build(self, economics_b=ECONOMICS, hash_b=None):
        save_world(self.tmp / "a", self.grid_hash)
        save_world(self.tmp / "b", hash_b or self.grid_hash, economics_b)
        worlds = {"a": self.tmp / "a", "b": self.tmp / "b"}
        return build_payloads(worlds, self.grid_csv, fake_plan, fake_siap)

    def test_front_rows_follow_front_columns_and_objectives_are_rounded(self):
        meta, _, reference = self.build()
        self.assertEqual(reference["columns"], FRONT_COLUMNS)
        row = reference["worlds"]["a"][0]
        self.assertEqual(len(row), len(FRONT_COLUMNS))
        self.assertEqual(row[FRONT_COLUMNS.index("net_mxn_ha")], 5895.034896323)  # 9 decimals, the planner's tie rule
        self.assertEqual(meta["reference_front_size"], {"a": 2, "b": 2})

    def test_grid_is_flattened_scale_major_with_full_values(self):
        _, grid, _ = self.build()
        world = grid["worlds"]["a"]
        self.assertEqual(world["scales"], list(SCALES))
        self.assertEqual(world["years"], list(YEARS))
        self.assertEqual(world["order"], list(ROTATIONS))  # not the sorted order of the JSON keys
        rotation = world["rotations"]["maize-fababean"]
        phases, years, scales = rotation["phases"], len(YEARS), len(SCALES)
        self.assertEqual(phases, 2)
        self.assertEqual(rotation["crops"], [["maize", "fababean"]] * years)  # [year][phase]
        self.assertEqual(set(rotation["fields"]), set(FIELDS))
        yields = rotation["fields"][TARGET]
        self.assertEqual(len(yields), scales * years * phases)
        index = lambda s, y, p: (s * years + y) * phases + p  # noqa: E731
        self.assertAlmostEqual(yields[index(2, 1, 1)], 2 + 1.0 + 1 + 0.1)  # scale 1.0, year 2007, bean phase
        self.assertAlmostEqual(rotation["fields"]["n_uptake_kg_ha"][index(1, 0, 0)], 55.0)

    def test_doses_placeholders_and_siap_prices_are_recorded(self):
        meta, _, _ = self.build()
        self.assertEqual(meta["crops"]["maize"]["n_kg_ha_at_scale_1"], 160)
        self.assertEqual(set(meta["placeholders"]), {"other_costs", "n_price", "stover_price"})
        self.assertEqual(meta["rotations"]["maize-fababean"], ["maize", "fababean"])
        self.assertEqual(meta["rotation_order"], list(ROTATIONS))
        self.assertEqual(meta["siap_prices"]["fababean"],
                         {"latest_year": 2025, "latest_mxn_t": 5000.0, "median_3y_mxn_t": 16000.0})

    def test_siap_prices_skip_years_without_a_price(self):
        frame = pd.concat([fake_siap(), pd.DataFrame([(2026, "maize", None)], columns=fake_siap().columns)])
        self.assertEqual(siap_prices(frame)["maize"]["latest_year"], 2025)

    def test_worlds_from_different_economics_or_a_stale_grid_are_refused(self):
        with self.assertRaises(ValueError):
            self.build(economics_b={**ECONOMICS, "n_price": 50.0})
        for name in ("a", "b"):
            (self.tmp / name / "run.json").unlink()
            (self.tmp / name / "brute_force_front.csv").unlink()
            (self.tmp / name).rmdir()
        with self.assertRaises(ValueError):
            self.build(hash_b="not-the-grid")

    def test_missing_objective_column_is_reported(self):
        directory = self.tmp / "bad"
        directory.mkdir()
        pd.DataFrame({"rotation": ["maize"]}).to_csv(directory / "brute_force_front.csv", index=False)
        (directory / "run.json").write_text("{}")
        with self.assertRaises(ValueError):
            build_payloads({"bad": directory}, self.grid_csv, fake_plan, fake_siap)

    def test_json_is_compact_and_reproducible(self):
        payload = {"b": [1, 2.5], "a": {"z": 1, "y": "é"}}
        first = write_json(self.tmp / "x" / "one.json", payload).read_bytes()
        second = write_json(self.tmp / "x" / "two.json", dict(reversed(list(payload.items())))).read_bytes()
        self.assertEqual(first, second)
        self.assertNotIn(b" ", first.strip())

    def test_planner_settings_and_site_come_from_the_python_source(self):
        meta, _, _ = self.build()
        self.assertEqual(meta["planner"], {"cvar_share": CVAR_SHARE, "front_decimals": FRONT_DECIMALS})
        self.assertEqual(meta["site"], SITE)

    def test_crop_plan_needs_no_crop_model(self):
        doses, rotations = crop_plan()  # farm_setup only: works without PCSE installed
        self.assertEqual(doses, {"maize": 160, "barley": 60, "fababean": 40})
        self.assertEqual(rotations, FARM_ROTATIONS)


if __name__ == "__main__":
    unittest.main()
