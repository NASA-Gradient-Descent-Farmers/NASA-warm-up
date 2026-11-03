"""Offline checks of the NSGA planner: interpolation, objective formulas, the front and the compromise.

The season tables below are tiny synthetic fixtures with known answers (not results): yields, uptake and
residues are linear in the fertilizer scale, so every objective can be computed by hand.
"""

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from src.crop_models.farm_tool import rotation_economics
from src.crop_models.nsga_planner import (OBJECTIVES, ROBUST_PREFIX, Economics, Grid, Planner, RobustPlanner,
                                          brute_force, choose, evaluate_years, front_quality, minimized, optimize,
                                          pareto_front, plot_front, tail_mean)
from src.crop_models.rotation_experiments import TARGET

YEARS = (2006, 2007, 2008, 2009, 2010)
PRICES = {"maize": 5000.0, "fababean": 12000.0}
COSTS = {"maize": 10000.0, "fababean": 8000.0}
ECONOMICS = Economics(prices=PRICES, other_costs=COSTS, n_price=20.0, stover_price=1000.0, carbon_fraction=0.5)


def seasons_fixture(scales=(0.0, 1.0, 2.0)):
    """maize (1 phase) and maize-fababean (2 phases). Maize: 2 + 3 s t/ha, uptake 50 + 40 s, fertilizer 160 s,
    stover 4 t/ha, roots 1 t/ha. Faba bean: 1.5 t/ha whatever the fertilizer, fertilizer 40 s, uptake 80,
    stover 2, roots 0.5. Year 2008 is a bad year: maize loses 2 t/ha."""
    rows = []
    for s in scales:
        for year in YEARS:
            bad = 2.0 if year == 2008 else 0.0
            maize = {"crop": "maize", TARGET: 2 + 3 * s - bad, "n_fertilizer_kg_ha": 160 * s,
                     "n_uptake_kg_ha": 50 + 40 * s, "stover_dm_t_ha": 4.0, "root_dm_t_ha": 1.0}
            bean = {"crop": "fababean", TARGET: 1.5, "n_fertilizer_kg_ha": 40 * s, "n_uptake_kg_ha": 80.0,
                    "stover_dm_t_ha": 2.0, "root_dm_t_ha": 0.5}
            base = {"year": year, "n_scale": s}
            rows.append({**base, "rotation": "maize", "phase": 0, **maize})
            rows.append({**base, "rotation": "maize-fababean", "phase": 0, **maize})
            rows.append({**base, "rotation": "maize-fababean", "phase": 1, **bean})
    return pd.DataFrame(rows)


def planner(scales=(0.0, 1.0, 2.0)):
    return Planner(Grid(seasons_fixture(scales), YEARS), ECONOMICS)


def flat_planner():
    """The same farm in a world where nitrogen buys nothing: maize yield and uptake do not respond to fertilizer."""
    seasons = seasons_fixture()
    maize = seasons["crop"] == "maize"
    bad = np.where(seasons["year"] == 2008, 2.0, 0.0)
    seasons.loc[maize, TARGET] = 2.0 - bad[maize]
    seasons.loc[maize, "n_uptake_kg_ha"] = 50.0
    return Planner(Grid(seasons, YEARS), ECONOMICS)


STEPS = dict(n_scale_steps=20, retention_steps=10)  # the lattice of the fixture: scales 0 to 2 in steps of 0.1


class InterpolationTests(unittest.TestCase):
    def test_exact_at_nodes_and_linear_between(self):
        grid = Grid(seasons_fixture(), YEARS)
        at_node = grid.interpolate("maize", TARGET, 1.0)
        np.testing.assert_allclose(at_node[:, 0], [5, 5, 3, 5, 5])
        between = grid.interpolate("maize", TARGET, 0.25)
        np.testing.assert_allclose(between[:, 0], [2.75, 2.75, 0.75, 2.75, 2.75])

    def test_scale_is_clipped_to_the_grid(self):
        grid = Grid(seasons_fixture(), YEARS)
        np.testing.assert_allclose(grid.interpolate("maize", TARGET, 9.0), grid.interpolate("maize", TARGET, 2.0))

    def test_needs_the_zero_fertilizer_node(self):
        with self.assertRaisesRegex(ValueError, "zero-fertilizer"):
            Grid(seasons_fixture((0.5, 1.0)), YEARS)

    def test_incomplete_grid_is_rejected(self):
        broken = seasons_fixture().iloc[1:]
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            Grid(broken, YEARS)


class ObjectiveTests(unittest.TestCase):
    def test_no_fertilizer_means_no_n_loss_and_no_fertilizer_cost(self):
        a = planner().annual("maize", 0.0, 1.0)
        np.testing.assert_allclose(a["n_loss_kg_ha"], 0.0)
        np.testing.assert_allclose(a["dose_kg_ha"], 0.0)
        # year 2006, retention 1: 2 t/ha x 5000 - 10000 = 0
        self.assertAlmostEqual(a["net_mxn_ha"][0], 0.0)

    def test_n_loss_is_dose_minus_extra_uptake(self):
        # Maize at s = 1: dose 160, uptake 90 vs 50 without fertilizer -> 160 - 40 = 120 kg N/ha lost.
        a = planner().annual("maize", 1.0, 1.0)
        np.testing.assert_allclose(a["n_loss_kg_ha"], 120.0)

    def test_legume_that_takes_up_no_extra_n_loses_its_whole_dose(self):
        # Faba bean at s = 1: dose 40, no extra uptake -> loses 40; maize loses 120; phases averaged.
        a = planner().annual("maize-fababean", 1.0, 1.0)
        np.testing.assert_allclose(a["n_loss_kg_ha"], (120.0 + 40.0) / 2)

    def test_n_loss_is_floored_at_zero(self):
        seasons = seasons_fixture()
        seasons["n_uptake_kg_ha"] = np.where(seasons["crop"] == "maize", 50 + 400 * seasons["n_scale"], 80.0)
        a = Planner(Grid(seasons, YEARS), ECONOMICS).annual("maize", 1.0, 1.0)  # extra uptake 400 > dose 160
        np.testing.assert_allclose(a["n_loss_kg_ha"], 0.0)

    def test_phases_are_averaged(self):
        a = planner().annual("maize-fababean", 1.0, 1.0)
        # maize 5 t/ha, faba bean 1.5 t/ha -> 3.25 in a normal year
        self.assertAlmostEqual(a["yield_t_ha"][0], 3.25)

    def test_carbon_input_known_answer(self):
        # Maize, retention 0.5: 0.5 x (roots 1 + 0.5 x stover 4) = 1.5 t C/ha.
        a = planner().annual("maize", 1.0, 0.5)
        np.testing.assert_allclose(a["c_input_t_ha"], 1.5)

    def test_retention_trades_carbon_for_income(self):
        p = planner()
        sold, kept = p.objectives("maize", 1.0, 0.0), p.objectives("maize", 1.0, 1.0)
        self.assertGreater(kept["c_input_t_ha"], sold["c_input_t_ha"])
        # Selling 4 t/ha of stover at 1000 MXN/t.
        self.assertAlmostEqual(sold["net_mxn_ha"] - kept["net_mxn_ha"], 4000.0)

    def test_invalid_retention_is_rejected(self):
        with self.assertRaises(ValueError):
            planner().annual("maize", 1.0, 1.5)

    def test_tail_mean(self):
        self.assertAlmostEqual(tail_mean(np.arange(1.0, 11.0), 0.2), 1.5)
        self.assertAlmostEqual(tail_mean(np.array([4.0, 2.0, 9.0]), 0.2), 2.0)  # at least one value

    def test_resilience_is_the_bad_year(self):
        # Maize at s = 1, retention 1: costs 10000 + 20 x 160 = 13200. Normal years net 5 x 5000 - 13200 = 11800;
        # in 2008 maize gives 3 t/ha and nets 1800. With 5 years the worst quarter is ceil(1.25) = 2 years:
        # 2008 and one normal year.
        o = planner().objectives("maize", 1.0, 1.0)
        self.assertAlmostEqual(o["cvar_net_mxn_ha"], (1800 + 11800) / 2)

    def test_worst_quarter_of_sixteen_years_is_exactly_four_years(self):
        self.assertAlmostEqual(tail_mean(np.arange(1.0, 17.0)), np.mean([1, 2, 3, 4]))

    def test_net_income_matches_farm_tool_at_a_node(self):
        # With all stover retained the stover price does not matter, so the economics must equal farm_tool's.
        seasons = seasons_fixture()
        node = seasons[seasons["n_scale"] == 1.0].assign(scenario="x", previous_crop="maize")
        _, annual, _, _ = rotation_economics(node, PRICES, COSTS, 20.0)
        expected = annual[annual["rotation"] == "maize-fababean"]["net_mxn_ha"].to_numpy()
        np.testing.assert_allclose(planner().annual("maize-fababean", 1.0, 1.0)["net_mxn_ha"], expected)

    def test_missing_price_is_reported(self):
        economics = Economics(prices={"maize": 1.0}, other_costs=COSTS)
        with self.assertRaisesRegex(ValueError, "fababean"):
            Planner(Grid(seasons_fixture(), YEARS), economics)


class FrontTests(unittest.TestCase):
    def test_pareto_front_drops_dominated_rows(self):
        frame = pd.DataFrame({"yield_t_ha": [3.0, 2.0, 3.0], "n_loss_kg_ha": [10.0, 10.0, 20.0]})
        front = pareto_front(frame, ["yield_t_ha", "n_loss_kg_ha"])
        self.assertEqual(front.to_dict("records"), [{"yield_t_ha": 3.0, "n_loss_kg_ha": 10.0}])

    def test_rounding_error_does_not_keep_a_strategy_on_the_front(self):
        # B beats A on yield only by 4e-16 t/ha, which is interpolation noise, and loses on income.
        frame = pd.DataFrame({"yield_t_ha": [2.0, 2.0 + 4e-16, 1.0], "net_mxn_ha": [100.0, 90.0, 80.0]})
        front = pareto_front(frame, ["yield_t_ha", "net_mxn_ha"])
        self.assertEqual(front["net_mxn_ha"].tolist(), [100.0])
        # A real difference above the tolerance still counts.
        real = pd.DataFrame({"yield_t_ha": [2.0, 2.0 + 1e-6], "net_mxn_ha": [100.0, 90.0]})
        self.assertEqual(len(pareto_front(real, ["yield_t_ha", "net_mxn_ha"])), 2)

    def test_front_rows_keep_their_unrounded_values(self):
        frame = pd.DataFrame({"yield_t_ha": [2.0000000004], "net_mxn_ha": [100.0]})
        self.assertEqual(pareto_front(frame, ["yield_t_ha", "net_mxn_ha"])["yield_t_ha"].iloc[0], 2.0000000004)

    def test_minimized_flips_maximized_objectives(self):
        frame = pd.DataFrame({"yield_t_ha": [3.0], "n_loss_kg_ha": [10.0]})
        np.testing.assert_allclose(minimized(frame, ["yield_t_ha", "n_loss_kg_ha"]), [[-3.0, 10.0]])

    def test_nsga2_recovers_the_brute_force_front(self):
        # Same lattice for both searches, so the exact front is the target. Real-coded variables converged to the
        # box bounds (where these linear trade-offs peak) too slowly: IGD+ stayed near 0.13.
        p = planner()
        objectives = ["yield_t_ha", "n_loss_kg_ha", "c_input_t_ha"]
        exact = pareto_front(brute_force(p, 20, 10), objectives)
        found = optimize(p, objectives, pop_size=40, generations=40, seed=3, n_scale_steps=20, retention_steps=10)
        quality = front_quality(found, exact, objectives)
        self.assertLess(quality["igd_plus"], 0.01)
        self.assertGreater(quality["hypervolume_ratio"], 0.99)
        # Nothing found may be beaten by an exact-front strategy.
        both = pareto_front(pd.concat([found, exact], ignore_index=True), objectives)
        self.assertEqual(len(both), len(exact))

    def test_nsga3_runs_with_five_objectives(self):
        found = optimize(planner(), generations=15, seed=2, n_scale_steps=20, retention_steps=10)
        self.assertGreater(len(found), 1)
        self.assertTrue(set(found["rotation"]) <= {"maize", "maize-fababean"})

    def test_nsga3_returns_its_whole_non_dominated_population(self):
        # On the fixture all 462 strategies are mutually non-dominated, and 5 partitions give 126 reference
        # directions, so the final population is 126 strategies. pymoo's result.X keeps one member per occupied
        # direction instead, which on the real grid was 16 of 84 and made the search look far worse than it was.
        found = optimize(planner(), generations=30, seed=1, n_scale_steps=20, retention_steps=10)
        self.assertEqual(len(found), 126)

    def test_same_seed_same_front(self):
        kwargs = dict(pop_size=20, generations=10, seed=5, n_scale_steps=20, retention_steps=10)
        a = optimize(planner(), ["yield_t_ha", "n_loss_kg_ha"], **kwargs)
        b = optimize(planner(), ["yield_t_ha", "n_loss_kg_ha"], **kwargs)
        pd.testing.assert_frame_equal(a, b)

    def test_decisions_stay_on_the_lattice(self):
        found = optimize(planner(), ["yield_t_ha", "c_input_t_ha"], pop_size=20, generations=10, seed=1,
                         n_scale_steps=20, retention_steps=10)
        np.testing.assert_allclose(found["n_scale"] / 0.1, np.round(found["n_scale"] / 0.1))  # 2.0 / 20 steps
        np.testing.assert_allclose(found["retention"] / 0.1, np.round(found["retention"] / 0.1))


class RobustTests(unittest.TestCase):
    def robust(self):
        return RobustPlanner({"responsive": planner(), "flat": flat_planner()}, **STEPS)

    def test_shortfall_is_the_worst_world_as_a_share_of_its_range(self):
        # Maize-faba bean at s = 1 loses 80 kg N/ha when maize responds (lattice range 0-240, so 1/3) and
        # 100 when it does not (range 0-320, so 0.3125): the robust shortfall is the larger, 1/3.
        values = self.robust().objectives("maize-fababean", 1.0, 1.0)
        self.assertAlmostEqual(values["shortfall_n_loss_kg_ha"], 1 / 3)
        self.assertAlmostEqual(values["responsive:n_loss_kg_ha"], 80.0)
        self.assertAlmostEqual(values["flat:n_loss_kg_ha"], 100.0)

    def test_shortfalls_lie_in_zero_one_and_hit_both_ends_in_a_single_world(self):
        table = brute_force(RobustPlanner({"only": planner()}, **STEPS), **STEPS)
        columns = [ROBUST_PREFIX + o for o in OBJECTIVES]
        self.assertTrue(((table[columns] >= -1e-12) & (table[columns] <= 1 + 1e-12)).all().all())
        np.testing.assert_allclose(table[columns].min(), 0.0, atol=1e-12)  # the best strategy of its own world
        np.testing.assert_allclose(table[columns].max(), 1.0, atol=1e-12)

    def test_two_worlds_never_do_better_than_the_worse_world(self):
        both, responsive, flat = (RobustPlanner({"responsive": planner(), "flat": flat_planner()}, **STEPS),
                                  RobustPlanner({"only": planner()}, **STEPS), RobustPlanner({"only": flat_planner()}, **STEPS))
        for rotation, s, retention in (("maize", 0.0, 1.0), ("maize", 1.3, 0.4), ("maize-fababean", 2.0, 0.0)):
            for name in OBJECTIVES:
                key = ROBUST_PREFIX + name
                worst = max(responsive.objectives(rotation, s, retention)[key], flat.objectives(rotation, s, retention)[key])
                self.assertAlmostEqual(both.objectives(rotation, s, retention)[key], worst)

    def test_worlds_must_share_rotations_and_scales(self):
        other = Planner(Grid(seasons_fixture((0.0, 1.0, 3.0)), YEARS), ECONOMICS)
        with self.assertRaisesRegex(ValueError, "same rotations"):
            RobustPlanner({"a": planner(), "b": other}, **STEPS)

    def test_nsga_recovers_the_robust_front(self):
        # Two objectives: the income / N-loss trade-off is a small front (21 strategies). With three, the
        # fixture's exact robust front has 254 strategies, more than the population can hold.
        robust = self.robust()
        names = [ROBUST_PREFIX + o for o in ("net_mxn_ha", "n_loss_kg_ha")]
        exact = pareto_front(brute_force(robust, **STEPS), names)
        found = optimize(robust, names, pop_size=40, generations=40, seed=3, **STEPS)
        quality = front_quality(found, exact, names)
        self.assertLess(quality["igd_plus"], 0.01)
        self.assertGreater(quality["hypervolume_ratio"], 0.99)

    def test_robust_front_reports_every_world_and_the_holdout(self):
        robust = self.robust()
        names = [ROBUST_PREFIX + "net_mxn_ha", ROBUST_PREFIX + "n_loss_kg_ha"]
        front = optimize(robust, names, pop_size=20, generations=10, seed=1, **STEPS)
        extra = evaluate_years(robust, front)
        self.assertIn("flat:n_loss_kg_ha", front.columns)
        self.assertIn("responsive:net_mxn_ha_holdout", extra.columns)
        self.assertEqual(len(extra), len(front))


class PlotTests(unittest.TestCase):
    def test_natural_and_robust_fronts_are_drawn(self):
        with tempfile.TemporaryDirectory() as directory:
            natural = optimize(planner(), generations=5, seed=1, **STEPS)
            plot_front(natural, {"a": 0, "b": len(natural) - 1}, Path(directory) / "natural.png", "natural")
            robust = RobustPlanner({"responsive": planner(), "flat": flat_planner()}, **STEPS)
            front = optimize(robust, [ROBUST_PREFIX + o for o in OBJECTIVES], generations=5, seed=1, **STEPS)
            plot_front(front, {"a": 0, "b": len(front) - 1}, Path(directory) / "robust.png", "robust",
                       objectives=[ROBUST_PREFIX + o for o in OBJECTIVES], x=ROBUST_PREFIX + "c_input_t_ha",
                       y=ROBUST_PREFIX + "net_mxn_ha", color=ROBUST_PREFIX + "n_loss_kg_ha")
            self.assertGreater((Path(directory) / "natural.png").stat().st_size, 1000)
            self.assertGreater((Path(directory) / "robust.png").stat().st_size, 1000)


class ChooseTests(unittest.TestCase):
    FRONT = pd.DataFrame({"yield_t_ha": [1.0, 2.0, 3.0], "n_loss_kg_ha": [0.0, 50.0, 100.0]})

    def test_weight_on_one_objective_picks_its_best(self):
        self.assertEqual(choose(self.FRONT, {"yield_t_ha": 0.99, "n_loss_kg_ha": 0.01}), 2)
        self.assertEqual(choose(self.FRONT, {"yield_t_ha": 0.01, "n_loss_kg_ha": 0.99}), 0)

    def test_equal_weights_pick_the_middle(self):
        self.assertEqual(choose(self.FRONT, {"yield_t_ha": 0.5, "n_loss_kg_ha": 0.5}), 1)


if __name__ == "__main__":
    unittest.main()
