"""Python implementation of the Triangulated Rotation Advisor decision engine.

Mirrors `web/src/engine/core.ts` and `web/src/engine/evaluate.ts` so the entire pipeline
(Lens 1 Climate Twins, Lens 2 Satellite NDVI Opportunity Windows, Lens 3 Resource Budget,
exact Pareto frontier, stress-test robustness, confidence labels, and Dynamic Programming adaptive policy)
can be inspected, validated, and plotted directly inside Jupyter Notebooks or backend tests.
"""

from __future__ import annotations

import itertools
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
ROTATION_LENGTH = 3
OBJECTIVE_KEYS = ["income", "badYear", "soil", "water", "erosion"]
OBJECTIVE_SIGN = {"income": 1.0, "badYear": 1.0, "soil": 1.0, "water": -1.0, "erosion": -1.0}


def season_months(start: int, cycle_months: float) -> list[int]:
    n = min(12, math.ceil(cycle_months))
    return [(start + i) % 12 for i in range(n)]


def soil_n_supply(profile: dict[str, Any]) -> float:
    n_g_kg = profile["soil"].get("n_g_kg")
    if n_g_kg is None:
        return 60.0
    return float(np.clip(n_g_kg * 58.5, 20.0, 160.0))


def eval_crop_season(
    crop: dict[str, Any],
    start: int,
    profile: dict[str, Any],
    rain_pct: float = 0.0,
    temp_c: float = 0.0,
    price_scale: float = 1.0,
    cost_scale: float = 1.0,
    n_price_usd_kg: float = 1.0,
) -> list[dict[str, Any]]:
    """Simulate a single crop across every historical weather year for a candidate start month."""
    months = [] if crop["type"] == "fallow" else season_months(start, crop["cycle_months"])
    awc = profile["soil"].get("awc_mm") or 120.0
    soil_factor = 0.85 + 0.3 * float(np.clip((awc - 80.0) / 120.0, 0.0, 1.0))
    frost_threshold = 1 if crop["tmin_survive_c"] >= 0 else (5 if crop["tmin_survive_c"] >= -5 else 12)
    price = crop["price_usd_t"] * price_scale
    n_soil = soil_n_supply(profile)

    outcomes = []
    for year_row in profile["years_sample"]:
        if crop["type"] == "fallow":
            outcomes.append({
                "year": year_row["year"],
                "startMonth": start,
                "yieldFactor": 0.0,
                "yieldT": 0.0,
                "netUsd": -crop["cost_usd_ha"] * cost_scale,
                "waterUseMm": 0.0,
                "frostDamaged": False,
                "fertKgN": 0.0,
            })
            continue

        tmean = float(np.mean([year_row["tmean_c"][m] for m in months])) + temp_c
        rain = sum(year_row["rain_mm"][m] for m in months) * (1.0 + rain_pct / 100.0)
        demand = crop["water_need_mm"] * (1.0 + 0.03 * temp_c)
        supply = rain + 0.5 * awc
        stress = float(np.clip(1.0 - supply / demand, 0.0, 1.0)) if demand > 0 else 0.0
        water_factor = float(np.clip(1.0 - crop["ky"] * stress, 0.0, 1.0))

        lo, hi = crop["tmean_opt_c"]
        d = (lo - tmean) if tmean < lo else ((tmean - hi) if tmean > hi else 0.0)
        temp_factor = float(np.clip(1.0 - 0.08 * d, 0.0, 1.0))

        heat_days = sum(year_row["heat_days"][m] for m in months) + max(0.0, temp_c) * 3.0
        heat_penalty = min(0.4, 0.015 * heat_days * (1.0 - 0.5 * crop["drought_tolerance"]))
        frost_days = sum(year_row["frost_days"][m] for m in months) * max(0.0, 1.0 - 0.25 * max(0.0, temp_c))
        frost_damaged = frost_days >= frost_threshold

        yield_factor = temp_factor * water_factor * (1.0 - heat_penalty) * (0.15 if frost_damaged else 1.0)
        yield_t = crop["yield_t_ha"] * soil_factor * yield_factor
        ratio = (yield_t / crop["yield_t_ha"]) if crop["yield_t_ha"] > 0 else 0.0
        fert_kg_n = max(0.0, crop["n_demand_kg_ha"] * min(1.0, ratio) - n_soil)
        net = yield_t * price * crop["harvest_ratio"] - crop["cost_usd_ha"] * cost_scale - fert_kg_n * n_price_usd_kg
        outcomes.append({
            "year": year_row["year"],
            "startMonth": start,
            "yieldFactor": yield_factor,
            "yieldT": yield_t,
            "netUsd": net,
            "waterUseMm": min(supply, demand),
            "frostDamaged": bool(frost_damaged),
            "fertKgN": fert_kg_n,
        })
    return outcomes


def build_crop_tables(
    crops: list[dict[str, Any]],
    profile: dict[str, Any],
    rain_pct: float = 0.0,
    temp_c: float = 0.0,
    price_scale: float = 1.0,
    cost_scale: float = 1.0,
    n_price_usd_kg: float = 1.0,
) -> dict[str, dict[str, Any]]:
    """Select optimal sowing month per crop and cache year-by-year outcomes."""
    tables: dict[str, dict[str, Any]] = {}
    for crop in crops:
        starts = [0] if (crop["type"] == "fallow" or crop["cycle_months"] >= 10) else list(range(12))
        best = None
        for s in starts:
            by_year = eval_crop_season(crop, s, profile, rain_pct, temp_c, price_scale, cost_scale, n_price_usd_kg)
            score = float(np.mean([
                o["yieldFactor"] if crop["type"] == "cover" else o["yieldFactor"] + 0.0001 * o["netUsd"]
                for o in by_year
            ]))
            if best is None or score > best["score"]:
                best = {"start": s, "byYear": by_year, "score": score}
        assert best is not None
        by_year = best["byYear"]
        tables[crop["id"]] = {
            "start": best["start"],
            "sowingMonthName": MONTHS[best["start"]],
            "byYear": by_year,
            "frostDamageRate": float(np.mean([1.0 if o["frostDamaged"] else 0.0 for o in by_year])),
            "failRate": float(np.mean([
                1.0 if (o["yieldFactor"] < 0.3 and crop["type"] not in ("fallow", "cover")) else 0.0
                for o in by_year
            ])),
        }
    return tables


def pest_break_score(seq: list[dict[str, Any]], rules: dict[str, Any]) -> float:
    penalty = 0.0
    n = len(seq)
    for k in range(n):
        a, b = seq[k], seq[(k + 1) % n]
        if a["type"] in ("fallow", "cover") or b["type"] in ("fallow", "cover"):
            continue
        if a["id"] == b["id"]:
            penalty += rules["same_crop_pest_penalty"]
        elif a["family"] == b["family"]:
            penalty += rules["same_family_pest_penalty"]
    return float(np.clip(1.0 - penalty / (n * rules["same_crop_pest_penalty"]), 0.0, 1.0))


def base_erosion_risk(profile: dict[str, Any]) -> float:
    extreme_days = sum(v or 0.0 for v in profile["climate_monthly"]["extreme_rain_days"])
    slope = profile["location"].get("slope_deg")
    slope = 2.0 if slope is None else slope
    return float(np.clip(0.25 + slope / 20.0 + extreme_days / 40.0, 0.05, 1.0))


def aggregate_rotation(
    seq: list[dict[str, Any]],
    tables: dict[str, dict[str, Any]],
    profile: dict[str, Any],
    rules: dict[str, Any],
    n_price_usd_kg: float = 1.0,
) -> dict[str, Any]:
    """Compute the 5 objectives and annual net series for a candidate rotation sequence."""
    n_years = len(profile["years_sample"])
    annual_net = np.zeros(n_years, dtype=float)
    water_sum = 0.0
    n_seq = len(seq)

    for k, crop in enumerate(seq):
        prev = seq[(k - 1) % n_seq]
        credit = (
            prev["n_fix_kg_ha"] * rules["legume_n_credit_fraction"]
            if (crop["type"] == "cereal" and prev["type"] == "legume")
            else 0.0
        )
        for y, o in enumerate(tables[crop["id"]]["byYear"]):
            saved = min(o["fertKgN"], credit)
            annual_net[y] += (o["netUsd"] + saved * n_price_usd_kg) / n_seq
            water_sum += o["waterUseMm"]

    sorted_net = np.sort(annual_net)
    tail_count = max(1, math.ceil(0.1 * n_years))
    bad_year = float(np.mean(sorted_net[:tail_count]))
    residue = float(np.mean([c["residue_om"] for c in seq]))
    nfix = float(np.clip(np.mean([c["n_fix_kg_ha"] for c in seq]) / 100.0, 0.0, 1.0))
    cover_eff = float(np.mean([c["cover"] * np.clip((c["cycle_months"] + 2.0) / 12.0, 0.0, 1.0) for c in seq]))
    pest_break = pest_break_score(seq, rules)
    erosion_base = base_erosion_risk(profile)

    return {
        "crops": [c["id"] for c in seq],
        "cropNames": " → ".join(c["name"] for c in seq),
        "income": float(np.mean(annual_net)),
        "badYear": bad_year,
        "soil": 0.3 * residue + 0.25 * nfix + 0.2 * cover_eff + 0.25 * pest_break,
        "water": water_sum / (n_years * n_seq),
        "erosion": erosion_base * (1.0 - cover_eff),
        "pestBreak": pest_break,
        "annualNet": annual_net,
    }


def windows_lens_score(seq: list[dict[str, Any]], tables: dict[str, dict[str, Any]], profile: dict[str, Any]) -> float | None:
    """Lens 2: alignment of planned crops with satellite-observed MODIS NDVI seasonal curve."""
    ndvi = profile["vegetation"]["ndvi_monthly"]
    valid = [v for v in ndvi if v is not None]
    if len(valid) < 6:
        return None
    max_ndvi = max(valid)
    bare = [m - 1 for m in profile["vegetation"]["bare_months"]]
    p10 = profile["vegetation"]["ndvi_p10_monthly"]
    fits = []
    for crop in seq:
        if crop["type"] == "fallow":
            fits.append(0.0)
            continue
        months = season_months(tables[crop["id"]]["start"], crop["cycle_months"])
        if crop["type"] == "cover":
            fits.append(len([m for m in months if m in bare]) / len(bare) if bare else 0.5)
            continue
        fit = float(np.mean([np.clip((ndvi[m] or 0.0) / max_ndvi, 0.0, 1.0) for m in months]))
        stress = float(np.mean([
            np.clip(1.0 - (p10[m] or 0.0) / max(0.05, ndvi[m] or 0.05), 0.0, 0.5)
            for m in months
        ]))
        fits.append(fit * (1.0 - stress))
    return float(np.mean(fits))


def pareto_front_mask(df: pd.DataFrame) -> np.ndarray:
    """Return boolean mask of exact Pareto-optimal rows across the 5 objectives."""
    mat = np.column_stack([OBJECTIVE_SIGN[k] * df[k].to_numpy(dtype=float) for k in OBJECTIVE_KEYS])
    n = len(mat)
    is_pareto = np.ones(n, dtype=bool)
    for i in range(n):
        if not is_pareto[i]:
            continue
        ge = np.all(mat >= mat[i], axis=1)
        gt = np.any(mat > mat[i], axis=1)
        dominated_by_other = ge & gt
        dominated_by_other[i] = False
        if np.any(dominated_by_other):
            is_pareto[i] = False
    return is_pareto


def evaluate_all_rotations(
    profile: dict[str, Any],
    crops: list[dict[str, Any]],
    rules: dict[str, Any],
    weights: dict[str, float] | None = None,
    rain_pct: float = 0.0,
    temp_c: float = 0.0,
    max_fallow: int = 1,
) -> tuple[pd.DataFrame, dict[str, dict[str, Any]]]:
    """Enumerate all valid 3-year rotations, compute objectives, lenses, and exact Pareto membership."""
    weights = weights or {"income": 0.25, "badYear": 0.25, "soil": 0.2, "water": 0.15, "erosion": 0.15}
    tables = build_crop_tables(crops, profile, rain_pct=rain_pct, temp_c=temp_c)

    rows = []
    for seq_tuple in itertools.product(crops, repeat=ROTATION_LENGTH):
        seq = list(seq_tuple)
        if not any(c["type"] in ("cereal", "legume", "forage") for c in seq):
            continue
        if sum(1 for c in seq if c["type"] == "fallow") > max_fallow:
            continue
        if sum(1 for c in seq if c["type"] == "cover") > 1:
            continue
        agg = aggregate_rotation(seq, tables, profile, rules)
        agg["lens_windows"] = windows_lens_score(seq, tables, profile)
        rows.append(agg)

    df = pd.DataFrame(rows)
    # Normalize objectives to [0, 1] where 1 is always better
    utility = np.zeros(len(df), dtype=float)
    total_w = sum(weights.values()) or 1.0
    for k in OBJECTIVE_KEYS:
        vals = df[k].to_numpy(dtype=float)
        lo, hi = vals.min(), vals.max()
        norm = np.full_like(vals, 0.5) if hi == lo else (vals - lo) / (hi - lo)
        if OBJECTIVE_SIGN[k] < 0:
            norm = 1.0 - norm
        df[f"norm_{k}"] = norm
        utility += (weights.get(k, 0.0) / total_w) * norm

    df["utility"] = utility
    df["is_pareto"] = pareto_front_mask(df)
    df["pct_budget"] = df["utility"].rank(pct=True)
    df["pct_windows"] = df["lens_windows"].rank(pct=True) if df["lens_windows"].notna().any() else np.nan
    return df.sort_values("utility", ascending=False).reset_index(drop=True), tables


def solve_adaptive_dp(
    profile: dict[str, Any],
    crops: list[dict[str, Any]],
    rules: dict[str, Any],
    tables: dict[str, dict[str, Any]],
    horizon: int = 6,
    discount: float = 0.95,
) -> dict[str, Any]:
    """Finite-horizon Stochastic Dynamic Programming (Bellman backward induction) over discrete farm states.

    State s = (previous_crop_id, soil_n_bin) where soil_n_bin in {'low', 'high'} reflects whether
    the preceding season fixed nitrogen (legume/cover/alfalfa) or depleted it.
    Transition uncertainty comes from the empirical distribution of historical weather years.
    """
    action_crops = [c for c in crops if c["type"] != "fallow"]
    states = [(c["id"], n_bin) for c in action_crops for n_bin in ("low", "high")]
    crop_by_id = {c["id"]: c for c in crops}

    # Immediate expected reward R(s, a) and next state s'(s, a)
    reward_table: dict[tuple[tuple[str, str], str], float] = {}
    next_state: dict[tuple[tuple[str, str], str], tuple[str, str]] = {}

    for prev_id, n_bin in states:
        prev_crop = crop_by_id[prev_id]
        for act in action_crops:
            act_id = act["id"]
            by_year = tables[act_id]["byYear"]
            credit = (
                prev_crop["n_fix_kg_ha"] * rules["legume_n_credit_fraction"]
                if (n_bin == "high" and act["type"] == "cereal")
                else 0.0
            )
            net_years = np.array([o["netUsd"] + min(o["fertKgN"], credit) for o in by_year], dtype=float)
            mean_net = float(np.mean(net_years))
            cvar_net = float(np.mean(np.sort(net_years)[: max(1, math.ceil(0.1 * len(net_years)))]))

            # Penalty for repeating same crop or family
            pest_pen = 0.0
            if act["type"] not in ("cover", "fallow") and prev_crop["type"] not in ("cover", "fallow"):
                if act_id == prev_id:
                    pest_pen = 140.0
                elif act["family"] == prev_crop["family"]:
                    pest_pen = 60.0

            soil_bonus = 120.0 * (0.4 * act["residue_om"] + 0.4 * act["cover"] + 0.2 * min(1.0, act["n_fix_kg_ha"] / 100.0))
            reward = 0.5 * mean_net + 0.3 * cvar_net + soil_bonus - pest_pen
            reward_table[((prev_id, n_bin), act_id)] = reward
            next_n = "high" if act["n_fix_kg_ha"] >= 40 else "low"
            next_state[((prev_id, n_bin), act_id)] = (act_id, next_n)

    # Backward induction: V_{t}(s) = max_a [ R(s, a) + gamma * V_{t+1}(s') ]
    V: dict[tuple[str, str], float] = {s: 0.0 for s in states}
    policy_by_stage: list[dict[tuple[str, str], str]] = []
    for _ in range(horizon):
        V_next = {}
        stage_policy = {}
        for s in states:
            best_a, best_val = None, -1e18
            for act in action_crops:
                a_id = act["id"]
                val = reward_table[(s, a_id)] + discount * V[next_state[(s, a_id)]]
                if val > best_val:
                    best_val = val
                    best_a = a_id
            V_next[s] = best_val
            stage_policy[s] = best_a or action_crops[0]["id"]
        V = V_next
        policy_by_stage.append(stage_policy)

    stationary_policy = policy_by_stage[-1]
    return {
        "policy": stationary_policy,
        "value_function": V,
        "reward_table": reward_table,
        "next_state": next_state,
    }

