"""Export / load the processed yield-panel tables so teammates can skip every download.

    python -m src.yield_panel.share export          # writes data/shared/*.parquet + manifest.json
    python -m src.yield_panel.share check           # verifies checksums of data/shared/

data/shared/ is tracked in the repo (~70 MB), so a fresh clone already has it. To use it:

    from src.yield_panel import share
    panel = share.load("panel_national")            # same columns as the CSVs the pipeline writes

Raw caches (gridded boxes under data/imerg, data/chirps, data/smap_box, data/modis_ndvi, POWER cells under
data/power_cells, SIAP annual files under data/siap) are not included: they are large and every step
re-creates them on demand.
"""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

SHARED = Path("data/shared")
PANEL_DIR = Path("data/yield_panel")
ROTATIONS_DIR = Path("data/rotations")

TABLES = {  # name -> (source path, description)
    "panel_national": (PANEL_DIR / "panel_national_enriched.csv",
                       "Municipality x year x crop, rainfed spring-summer, 2003-2025, all states: SIAP outcomes, "
                       "POWER/IMERG/CHIRPS season features, MODIS NDVI/EVI, SMAP (2015+), GLDAS and IGBP soils"),
    "panel_central": (PANEL_DIR / "panel_central_enriched.csv", "Same as panel_national, 11 central states only"),
    "districts_1999_2025": (PANEL_DIR / "districts_1999_2025.csv",
                            "SIAP district (DDR) outcomes, 1999-2002 from the historic files + 2003-2025"),
    "states_1980_2025": (PANEL_DIR / "states_1980_2025.csv", "SIAP state outcomes, 1980-2025"),
    "power_municipal_1982_2025": (PANEL_DIR / "power_municipal_1982_2025.csv",
                                  "NASA POWER season and pre-season features per municipality-year, 1982-2025"),
    "chirps_municipal_1999_2025": (PANEL_DIR / "chirps_municipal_1999_2025.csv",
                                   "CHIRPS season rain features per municipality-year, 1999-2025"),
    "s2s_municipal_1981_2026": (PANEL_DIR / "s2s_municipal_1981_2026.csv",
                                "NASA GEOS-S2S April-issued forecast anomalies per municipality-year, 1981-2026"),
    "planning_municipal": (PANEL_DIR / "planning" / "municipal.parquet", "Planning-model panel, municipalities 2003-2025"),
    "planning_district": (PANEL_DIR / "planning" / "district.parquet", "Planning-model panel, districts 1999-2025"),
    "planning_state": (PANEL_DIR / "planning" / "state.parquet", "Planning-model panel, states 1982-2025"),
    # Tables used by the rotation tool (src/rotations); it reads them from data/shared/ when data/rotations/ is empty.
    "rotations_siap_crop_years": (ROTATIONS_DIR / "siap_crop_years.parquet",
                                  "SIAP district x crop x cycle x water regime, 2003-2025 (19 crops)"),
    "rotations_municipality_districts": (ROTATIONS_DIR / "municipality_districts.parquet",
                                         "Each municipality's SIAP district (DDR)"),
    "rotations_climate_municipal": (ROTATIONS_DIR / "climate_municipal.parquet",
                                    "Monthly climate normals 2001-2025 per municipality (NASA POWER, rain corrected with CHIRPS)"),
    "rotations_climate_municipal_years": (ROTATIONS_DIR / "climate_municipal_years.parquet",
                                          "Monthly rain and ET0 per municipality and year, 2001-2025"),
    "rotations_climate_district": (ROTATIONS_DIR / "climate_district.parquet", "Monthly climate normals per district"),
    "rotations_climate_district_years": (ROTATIONS_DIR / "climate_district_years.parquet",
                                         "Monthly rain and ET0 per district and year, 2001-2025"),
    "rotations_observed_municipal": (ROTATIONS_DIR / "observed_municipal.parquet",
                                     "MODIS NDVI (cropland) and SMAP root-zone moisture by month per municipality"),
    "rotations_observed_district": (ROTATIONS_DIR / "observed_district.parquet",
                                    "MODIS NDVI and SMAP root-zone moisture by month per district"),
}


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(2**20), b""):
            h.update(block)
    return h.hexdigest()


def export(dest=SHARED):
    from src.yield_panel import planning

    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    manifest = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "tables": {}}
    indices = planning.index_features()
    frames = {"climate_indices": (indices, "Ocean indices per year known by April 30 (NOAA CPC/PSL)")}
    for name, (src, desc) in TABLES.items():
        if src.exists():
            frames[name] = (pd.read_parquet(src) if src.suffix == ".parquet" else pd.read_csv(src, low_memory=False), desc)
    for name, (frame, desc) in frames.items():
        path = dest / f"{name}.parquet"
        frame.to_parquet(path, index=False, compression="zstd")
        manifest["tables"][name] = {"description": desc, "rows": len(frame), "columns": list(frame.columns),
                                    "bytes": path.stat().st_size, "sha256": _sha256(path)}
        print(f"{name}: {len(frame)} rows, {path.stat().st_size / 1e6:.1f} MB", flush=True)
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    return manifest


def check(dest=SHARED):
    manifest = json.loads((Path(dest) / "manifest.json").read_text())
    bad = [n for n, m in manifest["tables"].items() if _sha256(Path(dest) / f"{n}.parquet") != m["sha256"]]
    print("all tables match the manifest" if not bad else f"checksum mismatch: {bad}")
    return not bad


def load(name, dest=SHARED):
    path = Path(dest) / f"{name}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found: pull the branch (data/shared/ is in the repo) or run `python -m src.yield_panel.share export`")
    return pd.read_parquet(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("step", choices=["export", "check"])
    parser.add_argument("--dest", type=Path, default=SHARED)
    args = parser.parse_args()
    export(args.dest) if args.step == "export" else check(args.dest)


if __name__ == "__main__":
    main()
