"""Simulate seasonal crop rotations in central Mexico with WOFOST 8.1 (PCSE): water, nitrogen, frost, drought.

Inputs:
- Weather: NASA POWER daily data, downloaded by PCSE's NASAPowerWeatherDataProvider (1984 onward).
- Soil: field capacity and wilting point from IGBP-DIS, porosity from GLDAS, and soil N mineralization from
  IGBP total nitrogen (src/data_ingestion), for a 100 cm rooting zone. Conductivity and percolation use
  PCSE defaults (not in our data).
- Crops: WOFOST parameter sets from https://github.com/ajwdewit/WOFOST_crop_parameters
  (mostly calibrated in Europe, so treat yields as relative, not as farm forecasts).

A rotation is a sequence of crops, one per rainy season, repeated every year. Each season runs from
March 1 to the end of February and is simulated on its own; the soil water and mineral nitrogen left at
the end of a season start the next one (with part of the nitrogen lost in between), so rotations interact
through water and nitrogen. Every phase is simulated (maize-barley starting with maize, and with barley),
so each crop appears every year, as in a field trial.

Three production levels per season (yield gap analysis):
- potential: no water or nitrogen limitation (WOFOST 8.1 PP)
- water-limited: rainfed, unlimited nitrogen (WOFOST 8.1 WLP)
- water- and N-limited: rainfed, with fertilizer as practiced in central Mexico (WOFOST 8.1 NWLP)

Mexican context added on top of WOFOST:
- Sowing when the rains start (rainfed "temporal" agriculture), or on a fixed date.
- Fertilizer plans per crop (maize from a Texcoco field trial; see CROPS).
- Legume N fixation (faba bean, from its crop parameters) and residue N carried to the next crop.
- A grain-N constraint: grain can't form below a minimum N concentration (WOFOST 8.1 has none).
- Frost: the crop ends on the first night at or below FROST_TMIN after establishment.
- Drought: per-season indicators (rain, canicula rain in July-August, longest dry spell, water-stress
  days), dry/normal/wet year classes, and scenarios with less rain (--rain-factor, --rain-months).

Not modeled: pests, diseases, weeds, phosphorus, intercropping (milpa), hail, irrigation.

Needs a NASA Earthdata login the first time (to download the IGBP soil grids).

Usage (from the repo root):
    python -m src.crop_models.wofost_rotations
    python -m src.crop_models.wofost_rotations --lat 19.53 --lon -98.85 --start-year 2005 --end-year 2025 --out data/rotations_texcoco.csv
    python -m src.crop_models.wofost_rotations --rain-factor 0.7                  # 30% less rain all year
    python -m src.crop_models.wofost_rotations --rain-factor 0.5 --rain-months 7 8   # stronger canicula
    python -m src.crop_models.wofost_rotations --frost-tmin-offset -2 --n-scale 0.5
    python -m src.crop_models.wofost_rotations --smap data/smap_texcoco_2023_2024.csv
"""

import argparse
import copy
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from pcse.base import ParameterProvider
from pcse.crop.nutrients import n_stress
from pcse.decorators import prepare_rates
from pcse.input import (DummySoilDataProvider, NASAPowerWeatherDataProvider, WOFOST81SiteDataProvider_Classic,
                        YAMLCropDataProvider)
from pcse.models import Wofost81_NWLP_CWB_CNB, Wofost81_PP, Wofost81_WLP_CWB

from src.data_ingestion import gldas_soils, igbp_soils
from src.data_ingestion.common import earthdata_login


@prepare_rates
def _n_stress_call(self, day, drv):
    """PCSE 6.0.13's N_Stress.__call__ with one guard: a crop with no above-ground N left (killed by drought)
    gets the maximum N-stress index instead of dividing by zero. Otherwise identical."""
    p, r, k = self.params, self.rates, self.kiosk
    NMAXLV = p.NMAXLV_TB(k.DVS)
    NMAXST = p.NMAXST_FR * NMAXLV
    NamountABG = k.NamountLV + k.NamountST + k.NamountSO
    NamountABGMX = k.WLV * NMAXLV + k.WST * NMAXST + k.WSO * p.NMAXSO
    ratio = NamountABGMX / NamountABG if NamountABG > 0 else 2.0
    r.NSLLV = p.NSLLV_TB(min(2.0, max(1.0, ratio)))
    NconcentrationLV = k.NamountLV / k.WLV if k.WLV > 0 else 0.0
    index = max(0, min(1, (NconcentrationLV - 0.9 * NMAXLV) / (NMAXLV - 0.9 * NMAXLV)))
    r.RFRGRL = 1 - (1.0 - index) * (p.RGRLAI - p.RGRLAI_MIN) / p.RGRLAI


n_stress.N_Stress.__call__ = _n_stress_call

# CIMMYT El Batan research station, Texcoco (Valley of Mexico, ~2,250 m).
DEFAULT_LAT = 19.53
DEFAULT_LON = -98.85

# One crop per rainy season (May-October in central Mexico).
# - variety: WOFOST parameter set. Grain_maize_202 sown mid-May matures in Nov-Dec at Texcoco.
# - earliest: earliest sowing date (MM-DD).
# - fertilizer: (days after sowing, kg N/ha) applications. Maize: 160 kg N/ha, the highest dose tested on rainfed
#   hybrids at INIFAP's Texcoco station (Alonso-Sanchez et al. 2023, doi:10.28940/terra.v41i0.1577), split half at
#   sowing and half ~40 days later (assumed split). Faba bean: 40 kg N/ha and barley: 60 kg N/ha (assumed).
# - min_grain_n: minimum N concentration in grain/seed (kg N/kg dry matter), used for the grain-N constraint.
CROPS = {
    "maize": {"crop": "maize", "variety": "Grain_maize_202", "earliest": "05-15",
              "fertilizer": [(0, 80), (40, 80)], "min_grain_n": 0.010},
    "barley": {"crop": "barley", "variety": "Spring_barley_301", "earliest": "07-01",
               "fertilizer": [(0, 60)], "min_grain_n": 0.012},
    "fababean": {"crop": "fababean", "variety": "Faba_bean_801", "earliest": "06-15",
                 "fertilizer": [(0, 40)], "min_grain_n": 0.035},
}

ROTATIONS = {
    "maize": ["maize"],
    "maize-barley": ["maize", "barley"],
    "maize-fababean": ["maize", "fababean"],
    "maize-barley-fababean": ["maize", "barley", "fababean"],
}

ROOTING_DEPTH_CM = 100  # matches the 0-100 cm IGBP layers and SMAP's root zone
INITIAL_WATER_CM = 5    # available water in the profile on Mar 1 of the first year (dry season)
INITIAL_N_KG = 10       # mineral N in the soil on Mar 1 of the first year

# "onset" sowing: first day from the earliest sowing date with this much rain over the previous 5 days,
# like farmers waiting for the rains; sown anyway after ONSET_WINDOW_DAYS.
ONSET_RAIN_MM = 20
ONSET_WINDOW_DAYS = 45

# Nitrogen assumptions (kept simple and explicit; all uncertain).
N_RECOVERY = 0.5              # share of fertilizer N the crop can access (the rest is lost)
MINERALIZATION_RATE = 0.005   # share of IGBP total soil N (0-100 cm) mineralized per year
MINERALIZATION_DAYS = 150     # released evenly over the first 150 days of the season (Mar-Jul)
N_CARRYOVER_LOSS = 0.5        # share of leftover mineral N (incl. residue N) lost before the next crop
RESIDUE_N_RELEASE = 0.5       # share of N in roots and dead leaves released the next season
                              # (stover/rastrojo is assumed removed for fodder, as is common in Mexico)

# Frost: the crop ends on the first night with POWER TMIN (+ offset) at or below this, from 30 days after sowing.
FROST_TMIN = 0.0
FROST_FROM_DAYS = 30

STRESS_RFTRA = 0.5  # a day counts as water-stressed when the water-stress factor is below this
DRY_DAY_MM = 1.0    # a day counts as dry below this much rain

LEVELS = {"potential": Wofost81_PP, "water": Wofost81_WLP_CWB, "water_n": Wofost81_NWLP_CWB_CNB}


def co2_ppm(year):
    """Atmospheric CO2, approximated linearly from Mauna Loa (~380 ppm in 2005, ~425 in 2025)."""
    return 380 + 2.2 * (year - 2005)


def site_soil(lat, lon):
    """WOFOST soil parameters for the site, plus IGBP total N (kg N/ha in 0-100 cm) for mineralization."""
    gldas_soils.download()
    igbp_soils.download(igbp_soils.search_granules())
    site = [("site", lat, lon)]
    gldas = gldas_soils.extract_points(site).iloc[0]
    igbp = igbp_soils.extract_points(site).iloc[0]

    soil = dict(DummySoilDataProvider())
    soil.update(
        SMFCF=igbp["field_capacity"] / 10 / ROOTING_DEPTH_CM,  # mm in 0-100 cm -> m3/m3
        SMW=igbp["wilting_point"] / 10 / ROOTING_DEPTH_CM,
        SM0=gldas["porosity"],
        RDMSOL=ROOTING_DEPTH_CM,
    )
    if soil["SM0"] <= soil["SMFCF"] + soil["CRAIRC"]:
        # The two products disagree; keep the water balance physical (saturation above field capacity).
        soil["SM0"] = soil["SMFCF"] + soil["CRAIRC"] + 0.01
    total_n_kg_ha = igbp["total_nitrogen_density"] * 10  # g/m2 -> kg/ha
    return soil, total_n_kg_ha


def scaled_weather(weather, rain_factor=1.0, months=None):
    """A copy of the weather with rain multiplied by `rain_factor` (only in `months`, if given)."""
    if rain_factor == 1.0:
        return weather
    scaled = copy.deepcopy(weather)
    for (day, _), record in scaled.store.items():
        if months is None or day.month in months:
            record.RAIN *= rain_factor
    return scaled


def sowing_date(weather, year, earliest, rule="onset"):
    """The crop's earliest sowing date ("fixed"), or the first day from it after the rains start ("onset")."""
    start = date.fromisoformat(f"{year}-{earliest}")
    if rule == "fixed":
        return start
    for offset in range(ONSET_WINDOW_DAYS):
        day = start + timedelta(days=offset)
        rain_mm = 10 * sum(weather(day - timedelta(days=k)).RAIN for k in range(5))  # PCSE rain is cm/day
        if rain_mm >= ONSET_RAIN_MM:
            return day
    return start + timedelta(days=ONSET_WINDOW_DAYS)


def frost_date(weather, sow, season_end, tmin_offset=0.0, threshold=FROST_TMIN):
    """First day from FROST_FROM_DAYS after sowing with TMIN + offset <= threshold, or None."""
    day = sow + timedelta(days=FROST_FROM_DAYS)
    while day < season_end:
        if weather(day).TMIN + tmin_offset <= threshold:
            return day
        day += timedelta(days=1)
    return None


def season_agromanagement(crop_key, sow, frost, year, n_scale=1.0, n_recovery=N_RECOVERY):
    """PCSE agromanagement for one season (Mar 1 to end of Feb) with one crop and its fertilizer plan."""
    crop = CROPS[crop_key]
    season_end = date(year + 1, 3, 1)
    calendar = {
        "crop_name": crop["crop"], "variety_name": crop["variety"],
        "crop_start_date": sow, "crop_start_type": "sowing",
        # Harvest at maturity, at the first killing frost, or at the end of February.
        "crop_end_date": frost, "crop_end_type": "earliest" if frost else "maturity",
        "max_duration": (season_end - sow).days - 1,
    }
    applications = [{sow + timedelta(days=d): {"N_amount": kg * n_scale, "N_recovery": n_recovery}}
                    for d, kg in crop["fertilizer"] if kg * n_scale > 0]
    events = [{"event_signal": "apply_n", "name": "fertilizer", "comment": "", "events_table": applications}]
    return [{date(year, 3, 1): {"CropCalendar": calendar, "TimedEvents": events if applications else None,
                                "StateEvents": None}},
            {season_end: None}]


def run_season(model, weather, crops, soil, agro, year, carry, mineralization, crop_overrides=None):
    """Simulate one season. Returns (summary row, daily DataFrame, state carried to the next season).

    crop_overrides: optional {WOFOST crop parameter: value} replacing the active variety's values.
    """
    site = WOFOST81SiteDataProvider_Classic(
        WAV=carry["wav"], SMLIM=carry["smlim"], NAVAILI=min(carry["navail"], 250), CO2=co2_ppm(year),
        NSOILBASE=min(mineralization, 100), NSOILBASE_FR=1 / MINERALIZATION_DAYS)
    params = ParameterProvider(cropdata=crops, soildata=soil, sitedata=site)
    # PCSE re-activates the variety when the crop starts, so changes must be overrides, not edits to `crops`.
    for name, value in (crop_overrides or {}).items():
        params.set_override(name, value)
    engine = model(params, weather, agro)
    engine.mconf.OUTPUT_VARS = list(engine.mconf.OUTPUT_VARS) + ["WWLOW"]
    engine.run_till_terminate()

    summary = engine.get_summary_output()[0]
    daily = pd.DataFrame(engine.get_output())
    daily.index = pd.DatetimeIndex(daily.pop("day"))

    # State for the next season: water above wilting point in the profile, topsoil moisture, mineral N.
    wwlow = engine.get_variable("WWLOW")
    # The profile is RDMSOL deep (ROOTING_DEPTH_CM unless a calibration sets a shallower soil).
    wav = max(0.0, wwlow - soil["RDMSOL"] * soil["SMW"]) if wwlow is not None else carry["wav"]
    smlim = min(soil["SM0"], max(soil["SMW"], daily["SM"].iloc[-1]))
    navail = engine.get_variable("NAVAIL") or 0.0
    crop_rows = daily.dropna(subset=["WRT"])
    residue_n = 0.0
    if len(crop_rows) and summary.get("TWRT") is not None:
        last = crop_rows.iloc[-1]
        residue_n = ((last.get("NamountRT") or 0.0)
                     + max(0.0, summary["TWRT"] - last["WRT"]) * crops["NRESIDRT"]
                     + max(0.0, summary["TWLV"] - last["WLV"]) * crops["NRESIDLV"])
    next_carry = {"wav": wav, "smlim": smlim,
                  "navail": (navail + RESIDUE_N_RELEASE * residue_n) * (1 - N_CARRYOVER_LOSS)}
    return summary, daily, next_carry


def drought_indicators(weather, start, end):
    """Rain, canicula (July-August) rain and longest dry spell between two dates (inclusive)."""
    days = pd.date_range(start, end).date
    rain = pd.Series([10 * weather(d).RAIN for d in days], index=pd.DatetimeIndex(days))
    dry = rain < DRY_DAY_MM
    longest = int((dry.groupby((~dry).cumsum()).cumsum()).max()) if len(dry) else 0
    return {"rain_season_mm": rain.sum(),
            "rain_jul_aug_mm": rain[rain.index.month.isin([7, 8])].sum(),
            "longest_dry_spell_days": longest}


def drought_classes(weather, start_year, end_year):
    """Classify each year's May-October rain into dry / normal / wet terciles over the simulated years."""
    totals = pd.Series({y: drought_indicators(weather, date(y, 5, 1), date(y, 10, 31))["rain_season_mm"]
                        for y in range(start_year, end_year + 1)})
    return pd.qcut(totals, 3, labels=["dry", "normal", "wet"]), totals


def simulate_rotation(name, sequence, weather, crops, soil, total_n, start_year, end_year, settings,
                      levels=LEVELS):
    """Simulate every phase of one rotation at the given production levels, chaining seasons.

    `settings` may carry calibration entries (see src/crop_models/calibration.py): "crop_params"
    ({crop key: {WOFOST parameter: value}}), "n_recovery" ({crop key: share}), "mineralization_rate"
    and "frost_tmin". Missing entries keep the module defaults. `levels` must include "water_n".
    Returns (seasons DataFrame, daily water- and N-limited output of phase 0).
    """
    mineralization = settings.get("mineralization_rate", MINERALIZATION_RATE) * total_n
    crop_params = settings.get("crop_params", {})
    n_recovery = settings.get("n_recovery", {})
    records, daily_phase0 = [], []
    for phase in range(len(sequence)):
        order = sequence[phase:] + sequence[:phase]
        carry = {level: {"wav": INITIAL_WATER_CM, "smlim": 0.4, "navail": INITIAL_N_KG} for level in levels}
        for i, year in enumerate(range(start_year, end_year + 1)):
            crop_key = order[i % len(order)]
            crop = CROPS[crop_key]
            crops.set_active_crop(crop["crop"], crop["variety"])
            sow = sowing_date(weather, year, crop["earliest"], settings["sowing"])
            frost = frost_date(weather, sow, date(year + 1, 3, 1), settings["frost_tmin_offset"],
                               settings.get("frost_tmin", FROST_TMIN))
            agro = season_agromanagement(crop_key, sow, frost, year, settings["n_scale"],
                                         n_recovery.get(crop_key, N_RECOVERY))

            row = {"rotation": name, "phase": phase, "year": year, "crop": crop_key,
                   "previous_crop": order[(i - 1) % len(order)] if i > 0 else None, "sowing": sow,
                   "n_fertilizer_kg_ha": sum(kg for _, kg in crop["fertilizer"]) * settings["n_scale"],
                   "soil_water_at_start_mm": 10 * (carry["water_n"]["wav"] + soil["RDMSOL"] * soil["SMW"]),
                   "mineral_n_at_start_kg_ha": carry["water_n"]["navail"]}
            for level, model in levels.items():
                summary, daily, carry[level] = run_season(model, weather, crops, soil, agro, year, carry[level],
                                                          mineralization, crop_params.get(crop_key))
                row[f"yield_{level}_t_ha"] = (summary["TWSO"] or 0.0) / 1000
                if level == "water_n":
                    end = summary["DOM"] or summary["DOH"] or date(year + 1, 2, 28)
                    grain_n = summary.get("NamountSO") or 0.0
                    row.update({
                        "maturity": summary["DOM"], "harvest": end,
                        "frost_ended": bool(frost and not summary["DOM"] and summary["DOH"] == frost),
                        "yield_water_n_wofost_t_ha": row["yield_water_n_t_ha"],
                        # Grain-N constraint: grain can't hold less N than the crop's minimum concentration.
                        "yield_water_n_t_ha": min(row["yield_water_n_t_ha"], grain_n / crop["min_grain_n"] / 1000),
                        "n_uptake_kg_ha": summary.get("NuptakeTotal") or 0.0,
                        "grain_n_kg_ha": grain_n,
                        "water_stress_days": int((daily.loc[pd.Timestamp(sow):pd.Timestamp(end), "RFTRA"].dropna() < STRESS_RFTRA).sum()),
                        **drought_indicators(weather, sow, end),
                    })
                    if phase == 0:
                        daily_phase0.append(daily)
            records.append(row)
    seasons = pd.DataFrame(records)
    for level in ("water", "water_n") if set(LEVELS) <= set(levels) else ():
        # Rainfed can exceed potential by a few % from numerical differences between models; cap at 100.
        upper = seasons["yield_potential_t_ha"] if level == "water" else seasons["yield_water_t_ha"]
        seasons[f"{level}_pct_of_{'potential' if level == 'water' else 'water'}"] = (
            100 * seasons[f"yield_{level}_t_ha"] / upper).clip(upper=100)
    return seasons, pd.concat(daily_phase0)


def simulate_rotations(lat, lon, start_year, end_year, rotations=ROTATIONS, sowing="onset", rain_factor=1.0,
                       rain_months=None, frost_tmin_offset=0.0, n_scale=1.0, calibration=None, levels=LEVELS):
    """Simulate each rotation at the site.

    `calibration` is an optional dict of overrides (opt-in; see src/crop_models/calibration.py):
    the simulate_rotation settings plus "rooting_depth_cm" (soil depth, at most ROOTING_DEPTH_CM).
    Returns (seasons DataFrame, {rotation: daily output of phase 0}, soil parameters, weather provider).
    """
    weather = scaled_weather(NASAPowerWeatherDataProvider(latitude=lat, longitude=lon), rain_factor, rain_months)
    crops = YAMLCropDataProvider(Wofost81_NWLP_CWB_CNB)
    soil, total_n = site_soil(lat, lon)
    calibration = dict(calibration or {})
    if "rooting_depth_cm" in calibration:
        soil["RDMSOL"] = min(ROOTING_DEPTH_CM, calibration.pop("rooting_depth_cm"))
    settings = {"sowing": sowing, "frost_tmin_offset": frost_tmin_offset, "n_scale": n_scale, **calibration}
    classes, may_oct_rain = drought_classes(weather, start_year, end_year)
    results, daily = [], {}
    for name, sequence in rotations.items():
        seasons, daily[name] = simulate_rotation(name, sequence, weather, crops, soil, total_n,
                                                 start_year, end_year, settings, levels)
        results.append(seasons)
    seasons = pd.concat(results, ignore_index=True)
    seasons["year_class"] = seasons["year"].map(classes).astype(str)
    seasons["rain_may_oct_mm"] = seasons["year"].map(may_oct_rain)
    seasons["rain_factor"] = rain_factor
    # Keep forcing and management explicit for offline surrogate and risk experiments.
    seasons["rain_months"] = ",".join(map(str, sorted(rain_months))) if rain_months else "all"
    seasons["frost_tmin_offset"] = frost_tmin_offset
    seasons["n_scale"] = n_scale
    seasons["sowing_mode"] = sowing
    seasons["latitude"] = lat
    seasons["longitude"] = lon
    soil["total_n_kg_ha"] = total_n
    return seasons, daily, soil, weather


def summarize(seasons):
    """Per rotation and crop: yields at each production level, losses to water and N, variability, frost.

    Skips the first simulated year, which starts from assumed soil water and nitrogen.
    """
    s = seasons[seasons["year"] > seasons["year"].min()]
    out = s.groupby(["rotation", "crop"], sort=False).agg(
        seasons=("year", "size"),
        yield_t_ha=("yield_water_n_t_ha", "mean"),
        cv_pct=("yield_water_n_t_ha", lambda x: 100 * x.std() / x.mean() if x.mean() else float("nan")),
        failed=("yield_water_n_t_ha", lambda x: int((x < 1).sum())),
        water_limited_t_ha=("yield_water_t_ha", "mean"),
        potential_t_ha=("yield_potential_t_ha", "mean"),
        frost_ended=("frost_ended", "sum"),
        n_uptake_kg_ha=("n_uptake_kg_ha", "mean"),
    )
    out["lost_to_water_pct"] = 100 * (1 - out["water_limited_t_ha"] / out["potential_t_ha"])
    out["lost_to_n_pct"] = 100 * (1 - out["yield_t_ha"] / out["water_limited_t_ha"])
    return out


def compare_with_smap(daily, smap_csv):
    """Correlate WOFOST's 0-100 cm soil moisture with SMAP sm_rootzone (daily means, overlapping days).

    WOFOST's own SM is only the rooted zone (the top 10 cm when no crop is growing), so the 0-100 cm
    average is total profile water (WWLOW, cm) / 100 cm, the same layer as SMAP's root zone.
    WOFOST describes one field; SMAP a 9 km cell with its own soil scale, so compare dynamics first.
    """
    smap = pd.read_csv(smap_csv, index_col=0, parse_dates=True)["sm_rootzone"].resample("D").mean()
    wofost = daily["WWLOW"] / ROOTING_DEPTH_CM
    both = pd.concat({"wofost_sm_0_100cm": wofost, "smap_sm_rootzone": smap}, axis=1).dropna()
    return both, both["wofost_sm_0_100cm"].corr(both["smap_sm_rootzone"])


def main():
    parser = argparse.ArgumentParser(description="Simulate crop rotations with WOFOST 8.1 at a point.")
    parser.add_argument("--lat", type=float, default=DEFAULT_LAT)
    parser.add_argument("--lon", type=float, default=DEFAULT_LON)
    parser.add_argument("--start-year", type=int, default=2005)
    parser.add_argument("--end-year", type=int, default=2025)
    parser.add_argument("--rotations", nargs="+", choices=list(ROTATIONS), default=list(ROTATIONS))
    parser.add_argument("--sowing", choices=["onset", "fixed"], default="onset",
                        help="Sow when the rains start (default) or on each crop's fixed earliest date")
    parser.add_argument("--rain-factor", type=float, default=1.0,
                        help="Multiply rain by this (e.g. 0.7 = 30%% less rain) to test drier conditions")
    parser.add_argument("--rain-months", type=int, nargs="+",
                        help="Only scale rain in these months (e.g. 7 8 for a stronger canicula)")
    parser.add_argument("--frost-tmin-offset", type=float, default=0.0,
                        help="Add to POWER TMIN when checking frost (e.g. -2: valley nights colder than the grid)")
    parser.add_argument("--n-scale", type=float, default=1.0,
                        help="Multiply every fertilizer dose (0 = no fertilizer)")
    parser.add_argument("--smap", help="Optional SMAP CSV from smap.py (needs sm_rootzone) to compare soil moisture")
    parser.add_argument("--out", help="Optional CSV path for every simulated season (e.g. data/rotations.csv)")
    args = parser.parse_args()

    if not earthdata_login():
        print("[WARN] Not logged in to NASA Earthdata; the IGBP soil download will fail if not cached. "
              "See src/data_ingestion/README.md.")

    started = time.perf_counter()
    seasons, daily, soil, weather = simulate_rotations(
        args.lat, args.lon, args.start_year, args.end_year, {k: ROTATIONS[k] for k in args.rotations},
        args.sowing, args.rain_factor, args.rain_months, args.frost_tmin_offset, args.n_scale)
    print(f"Simulated {len(seasons)} seasons x 3 production levels in {time.perf_counter() - started:.0f}s "
          f"| lat={args.lat}, lon={args.lon}, {args.start_year}-{args.end_year}, {args.sowing} sowing, "
          f"rain x{args.rain_factor}{' in months ' + str(args.rain_months) if args.rain_months else ''}, "
          f"frost offset {args.frost_tmin_offset:+.1f} C, fertilizer x{args.n_scale} "
          f"| POWER grid elevation {weather.elevation:.0f} m")
    print(f"Soil: field capacity {soil['SMFCF']:.3f}, wilting point {soil['SMW']:.3f}, saturation {soil['SM0']:.3f} m3/m3, "
          f"rooting depth {soil['RDMSOL']} cm, total N {soil['total_n_kg_ha']:.0f} kg/ha "
          f"-> mineralization {MINERALIZATION_RATE * soil['total_n_kg_ha']:.0f} kg N/ha/season")

    with pd.option_context("display.width", 250, "display.max_columns", None):
        print("\nYields are grain/seed dry matter, t/ha (water- and N-limited, with the grain-N constraint). "
              "First year skipped as spin-up.\n")
        print(summarize(seasons).round(1))

        s = seasons[(seasons["crop"] == "maize") & seasons["previous_crop"].notna()]
        print("\nMaize yield (t/ha) by the crop grown the year before:\n")
        print(s.groupby("previous_crop")["yield_water_n_t_ha"].describe()[["count", "mean", "min", "max"]].round(1))
        print("\nMaize yield (t/ha) by year class (May-Oct rain terciles) and rotation:\n")
        print(s.pivot_table(index="rotation", columns="year_class", values="yield_water_n_t_ha", aggfunc="mean")
              .reindex(columns=["dry", "normal", "wet"]).round(1))

    if args.smap:
        first = next(iter(daily))
        both, r = compare_with_smap(daily[first], args.smap)
        print(f"\nSoil moisture check ({first}, {len(both)} days): correlation WOFOST vs SMAP root zone r={r:.2f}")
        print(both.resample("MS").mean().round(3).to_string())

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        seasons.to_csv(args.out, index=False)
        print(f"\nSaved {len(seasons)} seasons to {args.out}")


if __name__ == "__main__":
    main()
