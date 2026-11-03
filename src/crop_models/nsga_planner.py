"""Multi-objective planning of rainfed rotations at Texcoco with NSGA-II / NSGA-III (pymoo).

A strategy is three decisions: the rotation, the fertilizer scale (a multiple of the crop doses in
wofost_rotations.CROPS) and the share of the stover left in the field. Each strategy is scored by five
objectives, averaged over the simulated weather years (farm-level, per hectare, phases averaged as in
farm_tool.rotation_economics):

| Objective (column)    | Meaning                                                                | Direction |
|-----------------------|------------------------------------------------------------------------|-----------|
| yield_t_ha            | Grain dry matter                                                       | maximize  |
| net_mxn_ha            | Grain revenue + stover sold - costs - fertilizer (SIAP prices)         | maximize  |
| n_loss_kg_ha          | Fertilizer N the crop did not take up (difference method)              | minimize  |
| c_input_t_ha          | Carbon returned to the soil: roots + retained stover (soil capital)    | maximize  |
| cvar_net_mxn_ha       | Mean net income of the worst quarter of years (resilience)             | maximize  |

The last two stand for long-term sustainability: soil capital and surviving bad years. Which NASA
data each stage uses:
- POWER: the daily weather driving every WOFOST season (and its year-to-year variability, the risk term).
- IGBP-DIS: field capacity, wilting point, total soil N (mineralization) and soil carbon stock of the site.
- GLDAS: porosity (water holding of the soil).
- SMAP: not an objective; it validated the simulated root-zone water (r = 0.87, wofost_rotations --smap).

Stages (each runnable alone):
1. build_grid: WOFOST (needs PCSE, cached NASA data) -> data/nsga/grid.csv, every rotation at a grid of
   fertilizer scales, with the default and with the SIAP-calibrated parameters (calibration.py).
2. Grid / Planner: pure NumPy. Interpolate the grid along the fertilizer scale and score a strategy.
3. optimize / brute_force: NSGA-II (up to 3 objectives) or NSGA-III (more); brute_force scores a fine grid
   of strategies, giving the exact front to check NSGA against.
4. choose: pick one compromise from the front with weights you set.

--model robust (RobustPlanner) searches for strategies that hold up under both the default and the calibrated
parameters, which disagree about what nitrogen buys: each objective becomes the worst shortfall (share of that
model's attainable range) over the two models, all minimized.

Not simulated: soil carbon dynamics (c_input is the driver of the equilibrium, not a trajectory), the
effect of retained stover on N or water, prices changing over time. Costs, the N price and the stover price
are placeholders (see PLACEHOLDER_*). Read NSGA_RESULTS.md before trusting a number.

Usage (from the repo root):
    python -m src.crop_models.nsga_planner --build-grid                      # ~1-2 min on 8 cores
    python -m src.crop_models.nsga_planner --model calibrated --out-dir data/nsga/calibrated
    python -m src.crop_models.nsga_planner --model default --objectives yield_t_ha net_mxn_ha n_loss_kg_ha
    python -m src.crop_models.nsga_planner --model robust --out-dir data/nsga/robust
"""

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .calibration import CALIBRATION_YEARS, HOLDOUT_YEARS
from .farm_tool import default_prices, siap_texcoco
from .rotation_experiments import TARGET

GRID_CSV = Path("data/nsga/grid.csv")
GRID_SCALES = (0.0, 0.25, 0.5, 0.75, 1.0, 1.25)  # multiples of the crop fertilizer doses
# Strategies live on a lattice: fertilizer scale in N_SCALE_STEPS steps up to the grid maximum (1.25 -> 4 kg N/ha
# for maize), stover retention in RETENTION_STEPS steps (5%). Real-coded NSGA reaches the box bounds, where
# these linear trade-offs have their optima, only slowly; on the lattice the bounds are ordinary values.
N_SCALE_STEPS = 50
RETENTION_STEPS = 20
FRONT_DECIMALS = 9  # objectives closer than this are ties when ranking strategies (see pareto_front)

# Multiply an objective by this to turn it into something to minimize.
NATURAL_SIGN = {"yield_t_ha": -1, "net_mxn_ha": -1, "n_loss_kg_ha": 1, "c_input_t_ha": -1, "cvar_net_mxn_ha": -1}
OBJECTIVES = tuple(NATURAL_SIGN)
# Robust objectives (RobustPlanner): the worst shortfall of each objective over several models, always minimized.
ROBUST_PREFIX = "shortfall_"
ROBUST_MODELS = ("default", "calibrated")
SIGN = {**NATURAL_SIGN, **{ROBUST_PREFIX + name: 1 for name in OBJECTIVES}}
FIELDS = (TARGET, "n_fertilizer_kg_ha", "n_uptake_kg_ha", "stover_dm_t_ha", "root_dm_t_ha")

# Not sourced: placeholders from Notebooks/texcoco_farmer_mvp.ipynb (and one new one). Replace with real figures.
PLACEHOLDER_COSTS = {"maize": 14000, "barley": 9000, "fababean": 11000}  # MXN/ha excluding fertilizer
PLACEHOLDER_N_PRICE = 25.0       # MXN per kg N
PLACEHOLDER_STOVER_PRICE = 1000.0  # MXN per t of stover dry matter sold as fodder
CARBON_FRACTION = 0.45           # kg C per kg residue dry matter (crop residues: typically 0.40-0.47)
CVAR_SHARE = 0.25                # share of worst years in the resilience objective (4 of the 16 design years)

# Weights for choose(): bigger = that objective matters more. Sustainability first, as the team asked.
SUSTAINABILITY_FIRST = {"c_input_t_ha": 0.30, "cvar_net_mxn_ha": 0.20, "n_loss_kg_ha": 0.20,
                        "net_mxn_ha": 0.20, "yield_t_ha": 0.10}
PROFIT_FIRST = {"net_mxn_ha": 0.40, "yield_t_ha": 0.30, "cvar_net_mxn_ha": 0.10, "n_loss_kg_ha": 0.10,
                "c_input_t_ha": 0.10}


@dataclass(frozen=True)
class Economics:
    """Money and carbon conversion constants of the planner (MXN, t, kg)."""
    prices: dict            # MXN per t of grain, by crop
    other_costs: dict = field(default_factory=lambda: dict(PLACEHOLDER_COSTS))  # MXN/ha excluding fertilizer
    n_price: float = PLACEHOLDER_N_PRICE
    stover_price: float = PLACEHOLDER_STOVER_PRICE
    carbon_fraction: float = CARBON_FRACTION

    @classmethod
    def from_siap(cls, **overrides):
        """SIAP median rural prices of the latest three years (farm_tool.default_prices) plus the placeholders."""
        return cls(prices=default_prices(siap_texcoco()), **overrides)


class Grid:
    """WOFOST season outcomes of one model parameterization on a fertilizer-scale grid.

    `seasons` has one row per rotation, phase, year and fertilizer scale (column `n_scale`) with the columns in
    FIELDS plus `crop`. Only `years` are kept. Arrays are indexed [scale node, year, phase], so a strategy is
    scored by interpolating along the first axis: the fertilizer effect between nodes is assumed linear.
    """

    def __init__(self, seasons, years):
        seasons = seasons[seasons["year"].isin(list(years))]
        if seasons.empty:
            raise ValueError("No seasons in the requested years")
        self.years = np.array(sorted(seasons["year"].unique()))
        self.scales = np.array(sorted(seasons["n_scale"].unique()), dtype=float)
        if len(self.scales) < 2 or self.scales[0] != 0.0:
            raise ValueError("The grid needs the zero-fertilizer node and at least one more (N loss is a difference)")
        self.rotations = {}
        for rotation, group in seasons.groupby("rotation", sort=False):
            phases = sorted(group["phase"].unique())
            index = pd.MultiIndex.from_product([self.scales, self.years, phases], names=["n_scale", "year", "phase"])
            table = group.set_index(["n_scale", "year", "phase"]).reindex(index)
            if table[list(FIELDS)].isna().any().any():
                raise ValueError(f"Incomplete grid for rotation {rotation!r}")
            shape = (len(self.scales), len(self.years), len(phases))
            crops = table["crop"].to_numpy().reshape(shape)
            if not (crops == crops[0]).all():
                raise ValueError(f"The crop sequence of {rotation!r} changes with the fertilizer scale")
            self.rotations[rotation] = {"crop": crops[0],
                                        **{name: table[name].to_numpy(float).reshape(shape) for name in FIELDS}}

    def interpolate(self, rotation, name, n_scale):
        """Field `name` of a rotation at a fertilizer scale, linear between nodes: array [year, phase]."""
        values = self.rotations[rotation][name]
        s = float(np.clip(n_scale, self.scales[0], self.scales[-1]))
        k = int(np.clip(np.searchsorted(self.scales, s, side="right") - 1, 0, len(self.scales) - 2))
        w = (s - self.scales[k]) / (self.scales[k + 1] - self.scales[k])
        return (1 - w) * values[k] + w * values[k + 1]


def tail_mean(values, share=CVAR_SHARE):
    """Mean of the lowest `share` of the values (at least one): the conditional value at risk of a gain."""
    k = max(1, int(np.ceil(share * len(values))))
    return float(np.sort(values)[:k].mean())


class Planner:
    """Scores strategies (rotation, fertilizer scale, stover retention) on a Grid."""

    def __init__(self, grid, economics):
        self.grid, self.economics = grid, economics
        self.price, self.cost = {}, {}
        for rotation, data in grid.rotations.items():
            missing = {c for c in data["crop"].ravel() if c not in economics.prices or c not in economics.other_costs}
            if missing:
                raise ValueError(f"Missing price or cost for {sorted(missing)}")
            self.price[rotation] = np.array([[economics.prices[c] for c in row] for row in data["crop"]], float)
            self.cost[rotation] = np.array([[economics.other_costs[c] for c in row] for row in data["crop"]], float)

    def annual(self, rotation, n_scale, retention):
        """Farm outcomes per year (phases averaged), each an array over the grid's years.

        yield_t_ha: grain dry matter. n_loss_kg_ha: fertilizer applied minus the extra N the crop took up
        compared with no fertilizer (apparent recovery), floored at 0. net_mxn_ha: grain revenue - other costs
        - N price x dose + stover price x stover removed. c_input_t_ha: carbon fraction x (roots + retained stover).
        """
        if not 0.0 <= retention <= 1.0:
            raise ValueError("retention must be between 0 and 1")
        g, e = self.grid, self.economics
        grain, dose, uptake, stover, roots = (g.interpolate(rotation, name, n_scale) for name in FIELDS)
        n_loss = np.maximum(0.0, dose - (uptake - g.rotations[rotation]["n_uptake_kg_ha"][0]))
        net = (grain * self.price[rotation] - (self.cost[rotation] + e.n_price * dose)
               + e.stover_price * (1.0 - retention) * stover)
        c_input = e.carbon_fraction * (roots + retention * stover)
        return {"yield_t_ha": grain.mean(axis=1), "net_mxn_ha": net.mean(axis=1), "n_loss_kg_ha": n_loss.mean(axis=1),
                "c_input_t_ha": c_input.mean(axis=1), "dose_kg_ha": dose.mean(axis=1)}

    def objectives(self, rotation, n_scale, retention):
        """The five objectives of a strategy, averaged over years (cvar_net_mxn_ha: worst CVAR_SHARE of years)."""
        a = self.annual(rotation, n_scale, retention)
        return {"yield_t_ha": a["yield_t_ha"].mean(), "net_mxn_ha": a["net_mxn_ha"].mean(),
                "n_loss_kg_ha": a["n_loss_kg_ha"].mean(), "c_input_t_ha": a["c_input_t_ha"].mean(),
                "cvar_net_mxn_ha": tail_mean(a["net_mxn_ha"])}


class RobustPlanner:
    """Scores strategies in several worlds at once, e.g. the default and the calibrated WOFOST parameters.

    In each world, the shortfall of a strategy on an objective is its distance from the best strategy of that
    world's lattice, as a share of the world's range on that objective: 0 = the best attainable there,
    1 = the worst. The robust objective `shortfall_<name>` is the worst shortfall over the worlds (to minimize),
    a minimax-regret flavour whose units do not depend on a world's yield level (the default parameters give
    about 8x the money of the calibrated ones). `objectives` also returns each world's own values as
    `<world>:<name>`. Meant for strategies on the lattice; off it a shortfall can slightly leave [0, 1].
    """

    def __init__(self, planners, n_scale_steps=N_SCALE_STEPS, retention_steps=RETENTION_STEPS):
        first = next(iter(planners.values()))
        for planner in planners.values():
            if list(planner.grid.rotations) != list(first.grid.rotations) or not np.array_equal(
                    planner.grid.scales, first.grid.scales):
                raise ValueError("All worlds need the same rotations and fertilizer scales")
        self.planners, self.grid = planners, first.grid
        self.best, self.span = {}, {}
        for world, planner in planners.items():
            g = minimized(brute_force(planner, n_scale_steps, retention_steps), OBJECTIVES)
            self.best[world] = g.min(axis=0)
            self.span[world] = np.where(g.max(axis=0) > g.min(axis=0), g.max(axis=0) - g.min(axis=0), 1.0)

    def objectives(self, rotation, n_scale, retention):
        """`shortfall_<objective>` (worst over worlds) plus each world's own objectives as `<world>:<objective>`."""
        own, shortfalls = {}, []
        for world, planner in self.planners.items():
            values = planner.objectives(rotation, n_scale, retention)
            own.update({f"{world}:{name}": values[name] for name in OBJECTIVES})
            g = np.array([NATURAL_SIGN[name] * values[name] for name in OBJECTIVES])
            shortfalls.append((g - self.best[world]) / self.span[world])
        worst = np.max(shortfalls, axis=0)
        return {**{ROBUST_PREFIX + name: float(value) for name, value in zip(OBJECTIVES, worst)}, **own}


def minimized(frame, objectives):
    """The objective columns as a matrix to minimize (maximized objectives negated)."""
    return frame[list(objectives)].to_numpy(float) * np.array([SIGN[o] for o in objectives])


def pareto_front(frame, objectives):
    """Rows of `frame` not dominated by another row on the given objectives (duplicates dropped).

    Objectives are compared after rounding to FRONT_DECIMALS decimals: interpolation leaves differences of about
    1e-16 that are rounding error, and compared exactly they kept strategies on the front that nothing else
    separates. Rows keep their unrounded values.
    """
    from pymoo.util.nds.non_dominated_sorting import NonDominatedSorting

    values = np.round(minimized(frame, objectives), FRONT_DECIMALS)
    first = ~pd.DataFrame(values).duplicated().to_numpy()
    unique, values = frame[first].reset_index(drop=True), values[first]
    keep = NonDominatedSorting().do(values, only_non_dominated_front=True)
    return unique.iloc[sorted(keep)].reset_index(drop=True)


def score_strategies(planner, strategies):
    """DataFrame of strategies (columns rotation, n_scale, retention) with their objectives."""
    rows = [{**s, **planner.objectives(s["rotation"], s["n_scale"], s["retention"])} for s in strategies]
    return pd.DataFrame(rows)


def lattice(maximum, steps):
    """steps + 1 equally spaced values from 0 to `maximum`."""
    return np.arange(steps + 1) * maximum / steps


def brute_force(planner, n_scale_steps=N_SCALE_STEPS, retention_steps=RETENTION_STEPS):
    """Every rotation at every lattice point of fertilizer scale and retention, with objectives: the exact check."""
    scales = lattice(planner.grid.scales[-1], n_scale_steps)
    strategies = [{"rotation": r, "n_scale": float(s), "retention": float(k)}
                  for r in planner.grid.rotations for s in scales for k in lattice(1.0, retention_steps)]
    return score_strategies(planner, strategies)


def optimize(planner, objectives=OBJECTIVES, pop_size=None, generations=100, seed=1,
             n_scale_steps=N_SCALE_STEPS, retention_steps=RETENTION_STEPS, partitions=None):
    """NSGA-II (up to 3 objectives) or NSGA-III (4+, Das-Dennis reference directions) over the strategy lattice.

    Mixed variables: the rotation is a categorical choice, fertilizer scale and retention are integer steps
    (see N_SCALE_STEPS). `partitions` sets NSGA-III's number of reference directions (default 6 for four
    objectives, 5 for five); `pop_size` defaults to 100 (NSGA-II) or the number of directions (NSGA-III).
    Returns the non-dominated strategies with their objectives (natural units).
    """
    from pymoo.algorithms.moo.nsga2 import RankAndCrowding, binary_tournament
    from pymoo.algorithms.moo.nsga3 import NSGA3, comp_by_cv_then_random
    from pymoo.core.mixed import (MixedVariableDuplicateElimination, MixedVariableGA, MixedVariableMating,
                                  MixedVariableSampling)
    from pymoo.core.problem import ElementwiseProblem
    from pymoo.core.variable import Choice, Integer
    from pymoo.operators.selection.tournament import TournamentSelection
    from pymoo.optimize import minimize
    from pymoo.util.ref_dirs import get_reference_directions

    objectives = tuple(objectives)
    unknown = set(objectives) - set(SIGN)
    if unknown or len(objectives) < 2:
        raise ValueError(f"Choose at least two of {tuple(SIGN)}")

    scales, retentions = lattice(planner.grid.scales[-1], n_scale_steps), lattice(1.0, retention_steps)

    def decode(x):
        return {"rotation": x["rotation"], "n_scale": float(scales[int(x["n_step"])]),
                "retention": float(retentions[int(x["r_step"])])}

    class StrategyProblem(ElementwiseProblem):
        def __init__(self):
            variables = {"rotation": Choice(options=list(planner.grid.rotations)),
                         "n_step": Integer(bounds=(0, n_scale_steps)),
                         "r_step": Integer(bounds=(0, retention_steps))}
            super().__init__(vars=variables, n_obj=len(objectives))

        def _evaluate(self, x, out, *args, **kwargs):
            values = planner.objectives(**decode(x))
            out["F"] = [SIGN[o] * values[o] for o in objectives]

    dedup = MixedVariableDuplicateElimination
    if len(objectives) <= 3:
        mating = MixedVariableMating(selection=TournamentSelection(func_comp=binary_tournament),
                                     eliminate_duplicates=dedup())
        # The two settings below are what pymoo's NSGA2 sets on top of the generic genetic algorithm.
        algorithm = MixedVariableGA(pop_size=pop_size or 100, mating=mating, survival=RankAndCrowding(),
                                    advance_after_initial_infill=True)
        algorithm.tournament_type = "comp_by_dom_and_crowding"
    else:
        partitions = partitions or {4: 6, 5: 5}.get(len(objectives), 4)
        ref_dirs = get_reference_directions("das-dennis", len(objectives), n_partitions=partitions)
        mating = MixedVariableMating(selection=TournamentSelection(func_comp=comp_by_cv_then_random),
                                     eliminate_duplicates=dedup())
        algorithm = NSGA3(ref_dirs=ref_dirs, pop_size=pop_size, sampling=MixedVariableSampling(), mating=mating,
                          eliminate_duplicates=dedup())
    result = minimize(StrategyProblem(), algorithm, ("n_gen", generations), seed=seed, verbose=False)
    # Not result.X: NSGA-III keeps there only the first-front member closest to each occupied reference direction
    # (16-18 of 84 directions on this problem), while the final population holds many more non-dominated strategies.
    strategies = [decode(x) for x in result.pop.get("X")]
    return pareto_front(score_strategies(planner, strategies), objectives)


def front_quality(found, reference, objectives):
    """How well the front `found` covers `reference` (e.g. the brute-force front), in the reference's range.

    Both are rescaled so the reference spans [0, 1] on every objective. igd_plus: mean distance from each
    reference point to the found front (0 = covered). hypervolume_ratio: found / reference hypervolume with
    the reference point at 1.1 in every objective (1 = same volume; >1 means `found` beats the reference).
    """
    from pymoo.indicators.hv import HV
    from pymoo.indicators.igd_plus import IGDPlus

    ref, got = minimized(reference, objectives), minimized(found, objectives)
    ideal, nadir = ref.min(axis=0), ref.max(axis=0)
    span = np.where(nadir > ideal, nadir - ideal, 1.0)
    ref, got = (ref - ideal) / span, (got - ideal) / span
    point = np.full(ref.shape[1], 1.1)
    return {"igd_plus": float(IGDPlus(pf=ref)(got)),
            "hypervolume_ratio": float(HV(ref_point=point)(got) / HV(ref_point=point)(ref))}


def choose(front, weights):
    """The front member closest to the ideal point in weighted Chebyshev distance; returns its row index.

    Each objective is rescaled to [0, 1] over the front (0 = best on the front, 1 = worst) and multiplied by its
    weight (bigger = matters more); the member with the smallest largest weighted shortfall wins.
    """
    objectives = list(weights)
    f = minimized(front, objectives)
    span = np.where(f.max(axis=0) > f.min(axis=0), f.max(axis=0) - f.min(axis=0), 1.0)
    w = np.array([weights[o] for o in objectives], dtype=float)
    return int(np.argmin((w / w.sum() * (f - f.min(axis=0)) / span).max(axis=1)))


SURFACE, INK, INK_MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e3e2dd"
SEQUENTIAL_BLUE = ["#86b6ef", "#3987e5", "#1c5cab", "#0d366b"]  # light -> dark: more N lost
PICK_COLORS = ["#eb6834", "#1baf7a"]  # categorical slots 2 and 3, validated as a pair; direct labels carry identity
ROTATION_MARKERS = {"maize": "o", "maize-barley": "s", "maize-fababean": "^", "maize-barley-fababean": "D"}
AXIS_LABELS = {"yield_t_ha": "Yield\n(t/ha)", "net_mxn_ha": "Net income\n(MXN/ha)", "n_loss_kg_ha": "N lost\n(kg N/ha)",
               "c_input_t_ha": "Soil C input\n(t C/ha)", "cvar_net_mxn_ha": "Bad-year income\n(MXN/ha)"}
LONG_LABELS = {"yield_t_ha": "Grain yield (t/ha/yr)", "net_mxn_ha": "Mean net income (MXN/ha/yr)",
               "n_loss_kg_ha": "N lost to the environment (kg N/ha/yr)",
               "c_input_t_ha": "Carbon returned to the soil (t C/ha/yr)",
               "cvar_net_mxn_ha": "Income in the worst quarter of years (MXN/ha)"}


SHORT_NAMES = {"yield_t_ha": "yield", "net_mxn_ha": "net income", "n_loss_kg_ha": "N lost",
               "c_input_t_ha": "soil C input", "cvar_net_mxn_ha": "bad-year income"}


def axis_label(name, long=False):
    """Plot label of an objective or robust objective; long ones carry the unit, short ones fit under an axis."""
    base = name.removeprefix(ROBUST_PREFIX)
    if name == base:
        return LONG_LABELS[name] if long else AXIS_LABELS[name]
    if long:
        return f"Worst shortfall: {SHORT_NAMES[base]} (0 = best)"
    return f"Worst shortfall:\n{SHORT_NAMES[base]}"


def plot_front(front, picks, path, title, objectives=OBJECTIVES, x="c_input_t_ha", y="net_mxn_ha",
               color="n_loss_kg_ha"):
    """Save a two-panel figure of a front: `y` against `x`, and all `objectives` side by side.

    Left: one marker per strategy (shape = rotation, blue shade = `color` column). Right: parallel coordinates,
    every objective rescaled so 1 is the best value on this front; the printed numbers are the best (top) and
    worst (bottom) values. `picks` is {label: row index of `front`}, drawn in colour and labelled directly.
    The defaults draw a front of natural objectives; pass the `shortfall_*` columns for a robust front.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap

    cmap = LinearSegmentedColormap.from_list("n_loss", SEQUENTIAL_BLUE)
    fig, (left, right) = plt.subplots(1, 2, figsize=(13, 5.4), gridspec_kw={"width_ratios": [1, 1.25]},
                                      facecolor=SURFACE)
    for ax in (left, right):
        ax.set_facecolor(SURFACE)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(INK_MUTED)

    top = front[color].max() or 1.0
    for rotation, group in front.groupby("rotation"):
        points = left.scatter(group[x], group[y], c=group[color], cmap=cmap, vmin=0, vmax=top,
                              marker=ROTATION_MARKERS.get(rotation, "o"), s=46, edgecolors=SURFACE,
                              linewidths=0.8, label=rotation, zorder=2)
    x_low, x_high = left.get_xlim()
    for (label, row), pick_color in zip(picks.items(), PICK_COLORS):
        px, py = front.loc[row, x], front.loc[row, y]
        on_right = px > (x_low + x_high) / 2  # keep the label inside the axes, away from the colour bar
        left.scatter([px], [py], s=210, facecolors="none", edgecolors=pick_color, linewidths=2.2, zorder=3)
        left.annotate(label, (px, py), xytext=(-12 if on_right else 12, 16), textcoords="offset points",
                      color=INK, fontsize=9.5, ha="right" if on_right else "left",
                      arrowprops={"arrowstyle": "-", "color": pick_color, "lw": 1.2})
    left.set_xlabel(f"{axis_label(x, long=True)}  {'→' if SIGN[x] < 0 else '←'}  better", color=INK_MUTED)
    left.set_ylabel(f"{axis_label(y, long=True)}  {'↑' if SIGN[y] < 0 else '↓'}  better", color=INK_MUTED)
    left.grid(color=GRID, linewidth=0.8, zorder=0)
    left.tick_params(colors=INK_MUTED)
    colorbar = fig.colorbar(points, ax=left, pad=0.02, fraction=0.045)
    colorbar.set_label(axis_label(color, long=True), color=INK_MUTED)
    colorbar.outline.set_visible(False)
    colorbar.ax.tick_params(colors=INK_MUTED)
    left.legend(title="Rotation (shape)", loc="best", frameon=False, labelcolor=INK_MUTED, title_fontsize=9,
                handles=[plt.Line2D([], [], marker=ROTATION_MARKERS.get(r, "o"), linestyle="", color=INK_MUTED,
                                    markersize=7, label=r) for r in sorted(front["rotation"].unique())])

    values = front[list(objectives)].to_numpy(float)
    maximized = np.array([SIGN[o] for o in objectives]) < 0
    best = np.where(maximized, values.max(axis=0), values.min(axis=0))
    worst = np.where(maximized, values.min(axis=0), values.max(axis=0))
    span = np.where(best != worst, best - worst, 1.0)
    scaled = (values - worst) / span
    positions = np.arange(len(objectives))
    for row in scaled:
        right.plot(positions, row, color=INK_MUTED, alpha=0.28, linewidth=1.0, zorder=1)
    ends = [scaled[index][-1] for index in picks.values()]
    close = len(ends) == 2 and abs(ends[0] - ends[1]) < 0.08  # stagger end labels that would overprint
    for k, ((label, index), pick_color) in enumerate(zip(picks.items(), PICK_COLORS)):
        right.plot(positions, scaled[index], color=pick_color, linewidth=2.6, marker="o", markersize=6,
                   markeredgecolor=SURFACE, zorder=3)
        right.annotate(label, (positions[-1], scaled[index][-1]), xytext=(8, (7 if k == 0 else -7) if close else 0),
                       textcoords="offset points", color=INK, fontsize=9.5, va="center")
    for position, hi, lo in zip(positions, best, worst):
        right.annotate(f"{hi:,.2f}" if abs(hi) < 100 else f"{hi:,.0f}", (position, 1.0), xytext=(0, 6),
                       textcoords="offset points", ha="center", fontsize=8.5, color=INK_MUTED)
        right.annotate(f"{lo:,.2f}" if abs(lo) < 100 else f"{lo:,.0f}", (position, 0.0), xytext=(0, -14),
                       textcoords="offset points", ha="center", fontsize=8.5, color=INK_MUTED)
    right.set_xticks(positions, [axis_label(o) for o in objectives], color=INK_MUTED, fontsize=9)
    right.set_yticks([0, 1], ["worst on\nthis front", "best on\nthis front"], color=INK_MUTED, fontsize=9)
    right.set_xlim(-0.3, len(objectives) - 1 + 0.9)
    right.set_ylim(-0.12, 1.12)
    right.grid(axis="x", color=GRID, linewidth=0.8)
    right.tick_params(length=0)
    fig.suptitle(title, x=0.01, ha="left", color=INK, fontsize=12.5)
    fig.text(0.01, 0.01, "Costs, N price and stover price are placeholders; compare strategies with each other, "
                         "not as farm advice.", color=INK_MUTED, fontsize=8.5)
    fig.tight_layout(rect=(0, 0.03, 1, 0.95))
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def evaluate_years(planner_for_years, front):
    """Everything `planner_for_years` reports for the strategies in `front`, as `*_holdout` columns.

    For a RobustPlanner the shortfalls are measured against the best strategy in those years, so they are not
    comparable in size with the design-year shortfalls.
    """
    scored = score_strategies(planner_for_years, front[["rotation", "n_scale", "retention"]].to_dict("records"))
    return scored.drop(columns=["rotation", "n_scale", "retention"]).add_suffix("_holdout")


def load_planners(grid_csv, model, economics, design_years=CALIBRATION_YEARS, holdout_years=HOLDOUT_YEARS):
    """(design Planner, holdout Planner) for one model of a saved grid."""
    seasons = pd.read_csv(grid_csv)
    seasons = seasons[seasons["model"] == model]
    if seasons.empty:
        raise ValueError(f"No rows for model {model!r} in {grid_csv}")
    return Planner(Grid(seasons, design_years), economics), Planner(Grid(seasons, holdout_years), economics)


def robust_planners(grid_csv, economics, models=ROBUST_MODELS, design_years=CALIBRATION_YEARS,
                    holdout_years=HOLDOUT_YEARS):
    """(design RobustPlanner, holdout RobustPlanner) over several models of a saved grid."""
    pairs = {m: load_planners(grid_csv, m, economics, design_years, holdout_years) for m in models}
    return (RobustPlanner({m: design for m, (design, _) in pairs.items()}),
            RobustPlanner({m: holdout for m, (_, holdout) in pairs.items()}))


# --- Stage 1: WOFOST runs (needs PCSE, cached NASA POWER weather and IGBP/GLDAS soils) ---

def build_grid(scales=GRID_SCALES, out=GRID_CSV, lat=19.53, lon=-98.85, workers=None):
    """Simulate every rotation at each fertilizer scale with the default and the calibrated parameters.

    Saves the water- and N-limited seasons to `out` (columns `model`, `n_scale` added) and a grid.json next to it
    with the knobs, scales, site soil from IGBP-DIS/GLDAS, versions and the date of the cached POWER weather.
    """
    from src.data_ingestion import igbp_soils

    from . import wofost_rotations as w
    from .calibration import CALIBRATED, Runner, run_metadata, simulator_settings, variety_parameters

    calibrated = simulator_settings(CALIBRATED, variety_parameters())
    models = {"default": {}, "calibrated": calibrated}
    runner = Runner(lat, lon, workers=workers)
    try:
        runs = runner.run({(m, s): {**cal, "n_scale": s} for m, cal in models.items() for s in scales},
                          list(w.ROTATIONS))
    finally:
        runner.close()
    frames = [seasons.assign(model=m, n_scale=s) for (m, s), seasons in runs.items()]
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.concat(frames, ignore_index=True).to_csv(out, index=False)

    soil, total_n = w.site_soil(lat, lon)
    carbon = igbp_soils.extract_points([("site", lat, lon)]).iloc[0]["soil_carbon_density"]  # kg C/m2 in 0-100 cm
    meta = {"latitude": lat, "longitude": lon, "scales": list(scales), "calibrated_knobs": CALIBRATED,
            "site": {"field_capacity_m3_m3": soil["SMFCF"], "wilting_point_m3_m3": soil["SMW"],
                     "porosity_m3_m3": soil["SM0"], "total_soil_n_kg_ha": total_n,
                     "soil_carbon_stock_t_ha": 10 * float(carbon)},  # 1 kg/m2 = 10 t/ha
            **run_metadata(lat, lon)}
    out.with_suffix(".json").write_text(json.dumps(meta, indent=2, default=float) + "\n")
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--build-grid", action="store_true", help="Run WOFOST to make the grid (needs PCSE)")
    parser.add_argument("--grid", type=Path, default=GRID_CSV)
    parser.add_argument("--model", choices=["default", "calibrated", "robust"], default="calibrated",
                        help="WOFOST parameters, or robust = worst shortfall across the default and calibrated ones")
    parser.add_argument("--objectives", nargs="+", choices=OBJECTIVES, default=list(OBJECTIVES))
    parser.add_argument("--pop-size", type=int)
    parser.add_argument("--partitions", type=int, help="NSGA-III reference-direction partitions (4+ objectives)")
    parser.add_argument("--generations", type=int, default=100)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--n-price", type=float, default=PLACEHOLDER_N_PRICE, help="MXN per kg N")
    parser.add_argument("--stover-price", type=float, default=PLACEHOLDER_STOVER_PRICE, help="MXN per t dry matter")
    parser.add_argument("--workers", type=int)
    parser.add_argument("--out-dir", type=Path)
    args = parser.parse_args()

    if args.build_grid:
        print(f"Saved {build_grid(out=args.grid, workers=args.workers)}")
    if not args.grid.exists():
        parser.error(f"{args.grid} not found; run with --build-grid first")

    economics = Economics.from_siap(n_price=args.n_price, stover_price=args.stover_price)
    robust = args.model == "robust"
    if robust:
        design, holdout = robust_planners(args.grid, economics)
    else:
        design, holdout = load_planners(args.grid, args.model, economics)
    prefix = ROBUST_PREFIX if robust else ""
    names = [prefix + o for o in args.objectives]  # the columns the search works on
    exact = pareto_front(brute_force(design), names)
    front = optimize(design, names, args.pop_size, args.generations, args.seed, partitions=args.partitions)
    front = pd.concat([front, evaluate_years(holdout, front)], axis=1)
    quality = front_quality(front, exact, names)

    algorithm = "NSGA-II" if len(names) <= 3 else "NSGA-III"
    print(f"{algorithm}, model={args.model}, design years {design.grid.years[0]}-{design.grid.years[-1]}: "
          f"{len(front)} non-dominated strategies; brute-force front {len(exact)}; "
          f"IGD+ {quality['igd_plus']:.3f}, hypervolume ratio {quality['hypervolume_ratio']:.3f}")
    # A robust front also shows what each pick earns and loses in each world.
    shown = [f"{world}:{o}" for world in design.planners for o in ("net_mxn_ha", "n_loss_kg_ha")] if robust else []
    picks = {}
    with pd.option_context("display.width", 250, "display.max_columns", None):
        for name, weights in (("sustainability-first", SUSTAINABILITY_FIRST), ("profit-first", PROFIT_FIRST)):
            weights = {prefix + o: v for o, v in weights.items() if o in args.objectives}
            picks[name] = choose(front, weights)
            print(f"\nCompromise, {name}:")
            print(front.iloc[[picks[name]]][["rotation", "n_scale", "retention", *names, *shown]]
                  .round(2).to_string(index=False))

    if args.out_dir:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        front.to_csv(args.out_dir / "front.csv", index=False)
        label = "robust across the default and calibrated" if robust else f"{args.model}"
        plot_front(front, picks, args.out_dir / "front.png",
                   f"{algorithm} front, {label} WOFOST parameters: {len(front)} non-dominated strategies "
                   f"(design years {design.grid.years[0]}-{design.grid.years[-1]})",
                   objectives=[prefix + o for o in OBJECTIVES], x=prefix + "c_input_t_ha", y=prefix + "net_mxn_ha",
                   color=prefix + "n_loss_kg_ha")
        exact.to_csv(args.out_dir / "brute_force_front.csv", index=False)
        run = {"model": args.model, "objectives": names, "algorithm": algorithm,
               "generations": args.generations, "pop_size": args.pop_size, "partitions": args.partitions,
               "seed": args.seed,
               "design_years": [int(design.grid.years[0]), int(design.grid.years[-1])],
               "holdout_years": [int(holdout.grid.years[0]), int(holdout.grid.years[-1])],
               "economics": asdict(economics), "front_quality": quality,
               "grid_sha256": hashlib.sha256(args.grid.read_bytes()).hexdigest()}
        (args.out_dir / "run.json").write_text(json.dumps(run, indent=2) + "\n")
        print(f"\nSaved the front to {args.out_dir}")


if __name__ == "__main__":
    main()
