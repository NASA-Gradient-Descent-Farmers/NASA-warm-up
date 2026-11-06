"""The dashboard's committed JSON must agree with the Python that produced it.

The first class needs nothing but the repo, so CI runs it: it fails when someone changes a crop, a rotation, the
site, a scenario or a planner constant in Python without re-exporting (python -m src.crop_models.dashboard_export).
The second class compares the JSON with the model outputs under data/ and is skipped where data/ is absent.
"""

import hashlib
import json
import unittest
from pathlib import Path

from src.crop_models import dashboard_seasons as ds
from src.crop_models.dashboard_export import PLACEHOLDERS
from src.crop_models.farm_setup import CROPS, ROTATIONS, SITE, fertilizer_kg_ha
from src.crop_models.nsga_planner import (CARBON_FRACTION, CVAR_SHARE, FRONT_DECIMALS, GRID_CSV, N_SCALE_STEPS,
                                          OBJECTIVES, PLACEHOLDER_COSTS, PLACEHOLDER_N_PRICE,
                                          PLACEHOLDER_STOVER_PRICE, PROFIT_FIRST, RETENTION_STEPS,
                                          SUSTAINABILITY_FIRST)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "dashboard" / "public" / "data"
FIXTURES = ROOT / "dashboard" / "src" / "lib" / "fixtures"
WORLDS = ("calibrated", "default")
REEXPORT = "out of date: run python -m src.crop_models.dashboard_export"


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class CommittedJsonMatchesCode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.meta = load(DATA / "meta.json")
        cls.grid = load(DATA / "grid.json")
        cls.scenarios = load(DATA / "scenarios.json")
        cls.reality = load(DATA / "reality.json")

    def test_site_crops_and_rotations(self):
        self.assertEqual(self.meta["site"], SITE, REEXPORT)
        self.assertEqual(self.meta["rotations"], ROTATIONS, REEXPORT)
        self.assertEqual(self.meta["rotation_order"], list(ROTATIONS), REEXPORT)
        self.assertEqual(self.meta["crops"], {c: {"n_kg_ha_at_scale_1": fertilizer_kg_ha(c)} for c in CROPS}, REEXPORT)

    def test_planner_settings(self):
        meta = self.meta
        self.assertEqual(meta["planner"], {"cvar_share": CVAR_SHARE, "front_decimals": FRONT_DECIMALS}, REEXPORT)
        self.assertEqual([o["key"] for o in meta["objectives"]], list(OBJECTIVES), REEXPORT)
        self.assertEqual((meta["lattice"]["n_scale_steps"], meta["lattice"]["retention_steps"]),
                         (N_SCALE_STEPS, RETENTION_STEPS), REEXPORT)
        self.assertEqual(meta["weights"], {"sustainability_first": SUSTAINABILITY_FIRST, "profit_first": PROFIT_FIRST},
                         REEXPORT)
        economics = meta["economics"]
        self.assertEqual((economics["other_costs"], economics["n_price"], economics["stover_price"],
                          economics["carbon_fraction"]),
                         (PLACEHOLDER_COSTS, PLACEHOLDER_N_PRICE, PLACEHOLDER_STOVER_PRICE, CARBON_FRACTION), REEXPORT)
        self.assertEqual(meta["placeholders"], PLACEHOLDERS, REEXPORT)

    def test_farm_settings(self):
        farm = self.meta["farm"]
        self.assertEqual(farm["scenarios"], ds.scenario_settings(), REEXPORT)
        self.assertEqual(farm["scenario_order"], list(ds.SCENARIOS), REEXPORT)
        self.assertEqual(farm["failure_threshold_t_ha"], ds.FAILURE_THRESHOLD, REEXPORT)
        self.assertEqual(farm["risk"], ds.RISK, REEXPORT)
        self.assertEqual(farm["spinup_years"], ds.SPINUP_YEARS, REEXPORT)

    def test_grid_covers_every_rotation_in_order(self):
        for world in WORLDS:
            g = self.grid["worlds"][world]
            self.assertEqual(g["order"], list(ROTATIONS), REEXPORT)
            for name, crops in ROTATIONS.items():
                self.assertEqual(g["rotations"][name]["phases"], len(crops), REEXPORT)

    def test_scenarios_cover_every_world_scenario_and_rotation(self):
        first, last = self.meta["farm"]["season_years"]
        for world in WORLDS:
            w = self.scenarios["worlds"][world]
            self.assertEqual(w["years"], list(range(first, last + 1)))
            # JSON keys are sorted on export; the display order is meta.farm.scenario_order (checked above).
            self.assertEqual(set(w["scenarios"]), set(ds.SCENARIOS), REEXPORT)
            for name, scenario in w["scenarios"].items():
                self.assertEqual(set(scenario["rotations"]), set(ROTATIONS), f"{world}/{name}: {REEXPORT}")
                self.assertEqual(set(w["risk"][name]), set(ROTATIONS), f"{world}/{name} risk: {REEXPORT}")
                for rotation, crops in ROTATIONS.items():
                    r = scenario["rotations"][rotation]
                    self.assertEqual(r["phases"], len(crops))
                    cells = len(w["years"]) * r["phases"]
                    for field in ds.SEASON_FIELDS:
                        self.assertEqual(len(r["fields"][field]), cells, f"{world}/{name}/{rotation}/{field}")
                    self.assertEqual(len(r["frost_ended"]), cells)

    def test_reality_covers_every_crop(self):
        self.assertEqual(set(self.reality["siap"]), set(CROPS), REEXPORT)
        for world in WORLDS:
            self.assertEqual(set(self.reality["worlds"][world]), set(CROPS), REEXPORT)

    def test_fixtures_exist_for_the_dashboard_tests(self):
        self.assertTrue((FIXTURES / "reference_fronts.json").exists(), REEXPORT)
        self.assertTrue((FIXTURES / "reference_economics.json").exists(), REEXPORT)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@unittest.skipUnless((ROOT / GRID_CSV).exists() and all((ROOT / d).is_dir() for d in ds.SEASON_DIRS.values()),
                     "no local model outputs under data/ (run python -m src.crop_models.dashboard_pipeline)")
class CommittedJsonMatchesLocalData(unittest.TestCase):
    """Cheap provenance check against data/; `dashboard_export --check` compares every byte."""

    def setUp(self):
        self.meta = load(DATA / "meta.json")

    def test_grid_hash(self):
        self.assertEqual(self.meta["grid_sha256"], sha256(ROOT / GRID_CSV), f"data/nsga/grid.csv changed; {REEXPORT}")

    def test_scenario_csv_hashes(self):
        for world, directory in ds.SEASON_DIRS.items():
            current = {p.name: sha256(p) for p in sorted((ROOT / directory).glob("*.csv"))}
            self.assertEqual(self.meta["farm"]["sources"][world], current, f"{directory} changed; {REEXPORT}")


if __name__ == "__main__":
    unittest.main()
