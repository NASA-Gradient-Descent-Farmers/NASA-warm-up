"""Build SiteProfile JSON files (one schema for every location) and the availability report.

Usage (from the repo root, needs network):
    .venv/bin/python -m src.advisor.build_profile --lat 19.53 --lon -98.85 --region texcoco     # one point
    .venv/bin/python -m src.advisor.build_profile --pilots                                       # all pilot grids
Outputs: web/public/data/profiles/<cell_id>.json, web/public/data/index.json, data/advisor/availability.csv
"""

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from src.data_ingestion import power

from . import features, pull
from .schema import LAYERS, SCHEMA_VERSION, empty_months, validate

REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE_DIR = REPO_ROOT / "web" / "public" / "data" / "profiles"
INDEX_PATH = REPO_ROOT / "web" / "public" / "data" / "index.json"
AVAILABILITY_CSV = REPO_ROOT / "data" / "advisor" / "availability.csv"

# Pilot regions: centre point and grid spacing in degrees (POWER's native grid is ~0.5 degrees).
PILOTS = {
    "texcoco_mx": {"name": "Texcoco, Mexico (temperate highland, rainfed)", "lat": 19.53, "lon": -98.85},
    "iowa_us": {"name": "Iowa, USA (humid temperate)", "lat": 42.03, "lon": -93.47},
    "punjab_in": {"name": "Punjab, India (hot semi-arid, irrigated)", "lat": 30.90, "lon": 75.85},
}
GRID_STEP = 0.5


def cell_id(region, lat, lon):
    return f"{region}_{lat:.2f}_{lon:.2f}"


def build_profile(lat, lon, region="adhoc", tier="B", with_vegetation=True):
    """Pull everything for one point and return a validated SiteProfile dict."""
    availability = {layer: {"status": "missing", "reason": "not pulled"} for layer in LAYERS}
    provenance = {"retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "sources": {}}

    (elevation, slope), availability["elevation"] = pull.pull_elevation(lat, lon)
    provenance["sources"]["elevation"] = "SRTM 30 m via OpenTopoData"

    payload, availability["weather"] = pull.pull_power(lat, lon)
    climate = {k: empty_months() for k in ["tmean_c", "tmin_c", "tmax_c", "rain_mm", "et0_mm", "frost_prob",
                                           "heat_days", "dry_spell_days", "extreme_rain_days"]}
    years, trend, aridity, temp_shift = [], {}, None, 0.0
    if payload is not None:
        daily = power.to_dataframe(payload)
        grid_elevation = payload.get("geometry", {}).get("coordinates", [None, None, None])[2]
        daily, temp_shift = features.correct_temperature(daily, grid_elevation, elevation)
        climate, years, trend, aridity, extreme_mm = features.monthly_features(daily, lat)
        provenance["sources"]["weather"] = "NASA POWER daily (AG), 1991-2024, UTC"
        provenance["temperature_correction_c"] = round(temp_shift, 2)
        provenance["extreme_rain_threshold_mm"] = round(extreme_mm, 1)
        if elevation is None:  # no elevation correction possible: mark weather as usable but uncorrected
            availability["weather"]["reason"] += "; no elevation correction (SRTM missing)"
        availability["extreme_rain"] = {"status": "fallback",
                                        "reason": "extreme days from POWER rain (95th pct of wet days); GPM IMERG not yet used"}

    soil, availability["soil"] = pull.pull_soilgrids(lat, lon)
    if soil is None:
        soil = {k: None for k in ["soc_g_kg", "clay_pct", "sand_pct", "ph", "n_g_kg"]}
    soil["awc_mm"] = features.awc_from_texture(soil["clay_pct"], soil["sand_pct"])
    provenance["sources"]["soil"] = "SoilGrids 250 m (ISRIC); AWC = texture rule of thumb"

    vegetation = {"ndvi_monthly": empty_months(), "ndvi_p10_monthly": empty_months(), "bare_months": []}
    if with_vegetation:
        samples, availability["vegetation"] = pull.pull_modis_ndvi(lat, lon)
        if samples:
            mean, p10, bare = features.ndvi_monthly(samples)
            vegetation = {"ndvi_monthly": mean, "ndvi_p10_monthly": p10, "bare_months": bare}
    else:
        availability["vegetation"] = {"status": "missing", "reason": "skipped (--no-vegetation)"}

    availability["soil_moisture"] = {"status": "missing", "reason": "SMAP L4 climatology not pulled yet"}
    availability["water_trend"] = {"status": "missing", "reason": "GRACE-FO not integrated yet"}

    profile = {
        "schema_version": SCHEMA_VERSION,
        "cell_id": cell_id(region, lat, lon),
        "location": {"lat": lat, "lon": lon, "elevation_m": elevation, "slope_deg": slope,
                     "region_id": region, "data_tier": tier},
        "climate_monthly": climate,
        "years_sample": years,
        "climate_trend": trend,
        "water": {"aridity_index": aridity, "soil_moisture_pctl": empty_months(), "drought_freq": None,
                  "water_trend": None},
        "vegetation": vegetation,
        "soil": soil,
        "availability": availability,
        "provenance": provenance,
    }
    validate(profile)
    return profile


def grid_points(center_lat, center_lon, n=3, step=GRID_STEP):
    half = (n - 1) / 2
    return [(round(center_lat + (i - half) * step, 2), round(center_lon + (j - half) * step, 2))
            for i in range(n) for j in range(n)]


def write_outputs(profiles):
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    AVAILABILITY_CSV.parent.mkdir(parents=True, exist_ok=True)
    index = []
    if INDEX_PATH.exists():
        index = [c for c in json.loads(INDEX_PATH.read_text())["cells"]
                 if c["cell_id"] not in {p["cell_id"] for p in profiles}]
    for p in profiles:
        (PROFILE_DIR / f"{p['cell_id']}.json").write_text(json.dumps(p, separators=(",", ":")))
        index.append({"cell_id": p["cell_id"], "lat": p["location"]["lat"], "lon": p["location"]["lon"],
                      "region_id": p["location"]["region_id"],
                      "availability": {k: v["status"] for k, v in p["availability"].items()}})
    INDEX_PATH.write_text(json.dumps({"schema_version": SCHEMA_VERSION, "regions": PILOTS, "cells": index}, indent=1))
    with AVAILABILITY_CSV.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["cell_id", "region", "layer", "status", "reason"])
        for cell in index:
            profile = json.loads((PROFILE_DIR / f"{cell['cell_id']}.json").read_text())
            for layer, info in profile["availability"].items():
                writer.writerow([cell["cell_id"], cell["region_id"], layer, info["status"], info.get("reason", "")])


def main():
    parser = argparse.ArgumentParser(description="Build SiteProfile files.")
    parser.add_argument("--lat", type=float)
    parser.add_argument("--lon", type=float)
    parser.add_argument("--region", default="adhoc")
    parser.add_argument("--pilots", action="store_true", help="build the 3x3 grid for every pilot region")
    parser.add_argument("--only", nargs="*", help="restrict --pilots to these region ids")
    parser.add_argument("--grid", type=int, default=3, help="points per side of each pilot grid")
    parser.add_argument("--no-vegetation", action="store_true")
    args = parser.parse_args()

    targets = []
    if args.pilots:
        for region, info in PILOTS.items():
            if args.only and region not in args.only:
                continue
            targets += [(region, la, lo, "A") for la, lo in grid_points(info["lat"], info["lon"], args.grid)]
    elif args.lat is not None and args.lon is not None:
        targets.append((args.region, args.lat, args.lon, "B"))
    else:
        parser.error("give --lat/--lon or --pilots")

    profiles = []
    for i, (region, lat, lon, tier) in enumerate(targets, start=1):
        print(f"[{i}/{len(targets)}] {region} ({lat}, {lon})", flush=True)
        profile = build_profile(lat, lon, region, tier, with_vegetation=not args.no_vegetation)
        status = {k: v["status"] for k, v in profile["availability"].items()}
        print("    ", status, flush=True)
        profiles.append(profile)
        write_outputs(profiles)  # incremental so a crash keeps earlier cells
    print(f"Wrote {len(profiles)} profiles to {PROFILE_DIR}")


if __name__ == "__main__":
    main()

