"""Derive agronomic evidence features from raw daily weather (pure functions, no network)."""

import math

import numpy as np
import pandas as pd

LAPSE_RATE_C_PER_M = 0.0065  # standard atmosphere
FROST_C = 0.0
HEAT_TMAX_C = 35.0
WET_DAY_MM = 1.0


def extraterrestrial_radiation_mm(lat_deg, day_of_year):
    """FAO-56 extraterrestrial radiation Ra, expressed as mm/day of evaporation equivalent."""
    phi = math.radians(lat_deg)
    dr = 1 + 0.033 * np.cos(2 * math.pi * day_of_year / 365)
    delta = 0.409 * np.sin(2 * math.pi * day_of_year / 365 - 1.39)
    x = np.clip(-np.tan(phi) * np.tan(delta), -1, 1)
    ws = np.arccos(x)
    ra_mj = (24 * 60 / math.pi) * 0.0820 * dr * (
        ws * math.sin(phi) * np.sin(delta) + math.cos(phi) * np.cos(delta) * np.sin(ws))
    return 0.408 * ra_mj


def hargreaves_et0(tmean, tmin, tmax, lat_deg, day_of_year):
    """Reference evapotranspiration (mm/day), Hargreaves-Samani; needs only temperature + latitude."""
    ra = extraterrestrial_radiation_mm(lat_deg, np.asarray(day_of_year))
    return np.maximum(0.0, 0.0023 * ra * (tmean + 17.8) * np.sqrt(np.maximum(tmax - tmin, 0)))


def correct_temperature(daily, grid_elevation_m, site_elevation_m):
    """Shift POWER temperatures from the grid-cell elevation to the site elevation with the lapse rate."""
    if grid_elevation_m is None or site_elevation_m is None:
        return daily.copy(), 0.0
    shift = (grid_elevation_m - site_elevation_m) * LAPSE_RATE_C_PER_M
    out = daily.copy()
    for column in ("T2M", "T2M_MAX", "T2M_MIN"):
        out[column] = out[column] + shift
    return out, shift


def _longest_dry_run(is_dry):
    best = run = 0
    for dry in is_dry:
        run = run + 1 if dry else 0
        best = max(best, run)
    return best


def monthly_features(daily, lat_deg):
    """Monthly climatology and per-year samples from a daily frame (index=date; T2M, T2M_MAX, T2M_MIN, PRECTOTCORR)."""
    daily = daily.dropna(subset=["T2M", "T2M_MAX", "T2M_MIN", "PRECTOTCORR"]).copy()
    daily["year"] = daily.index.year
    daily["month"] = daily.index.month
    doy = daily.index.day_of_year.values
    daily["et0"] = hargreaves_et0(daily["T2M"].values, daily["T2M_MIN"].values, daily["T2M_MAX"].values, lat_deg, doy)
    daily["frost"] = daily["T2M_MIN"] <= FROST_C
    daily["heat"] = daily["T2M_MAX"] > HEAT_TMAX_C
    wet = daily.loc[daily["PRECTOTCORR"] >= WET_DAY_MM, "PRECTOTCORR"]
    extreme_threshold = float(wet.quantile(0.95)) if len(wet) else float("nan")
    daily["extreme"] = daily["PRECTOTCORR"] >= extreme_threshold

    grouped = daily.groupby(["year", "month"])
    per_ym = pd.DataFrame({
        "tmean": grouped["T2M"].mean(),
        "tmin": grouped["T2M_MIN"].mean(),
        "tmax": grouped["T2M_MAX"].mean(),
        "rain": grouped["PRECTOTCORR"].sum(),
        "et0": grouped["et0"].sum(),
        "frost_days": grouped["frost"].sum(),
        "heat_days": grouped["heat"].sum(),
        "extreme_days": grouped["extreme"].sum(),
        "dry_spell": grouped["PRECTOTCORR"].apply(lambda s: _longest_dry_run((s < WET_DAY_MM).values)),
        "n_days": grouped["PRECTOTCORR"].size(),
    })
    days_in_month = pd.Series(per_ym.index.get_level_values("month")).map(
        lambda m: [31, 28.25, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]).values
    per_ym = per_ym[per_ym["n_days"] >= 0.9 * days_in_month]  # drop partial months

    def by_month(column, how="mean"):
        values = getattr(per_ym[column].groupby("month"), how)()
        return [None if m not in values.index or pd.isna(values[m]) else round(float(values[m]), 3)
                for m in range(1, 13)]

    frost_prob = [None if v is None else round(v / d, 4) for v, d in
                  zip(by_month("frost_days"), [31, 28.25, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])]
    climate = {
        "tmean_c": by_month("tmean"), "tmin_c": by_month("tmin"), "tmax_c": by_month("tmax"),
        "rain_mm": by_month("rain"), "et0_mm": by_month("et0"), "frost_prob": frost_prob,
        "heat_days": by_month("heat_days"), "dry_spell_days": by_month("dry_spell"),
        "extreme_rain_days": by_month("extreme_days"),
    }

    years = []
    for year, block in per_ym.groupby(level="year"):
        if len(block) < 12:
            continue
        block = block.droplevel("year").sort_index()
        years.append({
            "year": int(year),
            "rain_mm": [round(float(v), 1) for v in block["rain"]],
            "frost_days": [int(v) for v in block["frost_days"]],
            "heat_days": [int(v) for v in block["heat_days"]],
            "tmean_c": [round(float(v), 2) for v in block["tmean"]],
        })

    annual = per_ym.groupby("year").agg(rain=("rain", "sum"), et0=("et0", "sum"), tmean=("tmean", "mean"))
    annual = annual[per_ym.groupby("year").size() == 12]
    trend = {}
    if len(annual) >= 10:
        x = annual.index.values.astype(float)
        trend = {
            "tmean_c_per_decade": round(float(np.polyfit(x, annual["tmean"].values, 1)[0] * 10), 3),
            "rain_pct_per_decade": round(float(np.polyfit(x, annual["rain"].values, 1)[0] * 10
                                               / annual["rain"].mean() * 100), 2),
            "years": [int(x.min()), int(x.max())],
        }
    aridity = None
    if len(annual) and annual["et0"].mean() > 0:
        aridity = round(float(annual["rain"].mean() / annual["et0"].mean()), 3)
    return climate, years, trend, aridity, extreme_threshold


def awc_from_texture(clay_pct, sand_pct):
    """Rough available water capacity (mm per 100 cm) from texture. A rule-of-thumb pedotransfer, NOT a measurement."""
    if clay_pct is None or sand_pct is None:
        return None
    return round(float(np.clip(190 - 1.1 * (sand_pct - 30) + 0.3 * (clay_pct - 25), 70, 230)), 1)


def ndvi_monthly(samples, bare_threshold=0.25):
    """Monthly NDVI mean and 10th percentile from (date, value) samples, plus the typically bare months."""
    frame = pd.DataFrame(samples, columns=["date", "ndvi"]).dropna()
    frame["month"] = pd.to_datetime(frame["date"]).dt.month
    mean, p10 = [], []
    for month in range(1, 13):
        values = frame.loc[frame["month"] == month, "ndvi"]
        mean.append(round(float(values.mean()), 3) if len(values) else None)
        p10.append(round(float(values.quantile(0.1)), 3) if len(values) else None)
    bare = [m for m, v in enumerate(mean, start=1) if v is not None and v < bare_threshold]
    return mean, p10, bare

