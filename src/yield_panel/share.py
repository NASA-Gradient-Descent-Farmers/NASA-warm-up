"""Export / load the processed yield-panel tables so teammates can skip every download.

    python -m src.yield_panel.share export          # writes data/shared/*.parquet + manifest.json
    python -m src.yield_panel.share check           # verifies checksums of data/shared/

Then zip data/shared/ and put it in the team drive. To use it, unzip it to data/shared/ and:

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
    "planning_municipal": (PANEL_DIR / "planning" / "municipal.parquet", "Planning-model panel, municipalities 2003-2025"),
    "planning_district": (PANEL_DIR / "planning" / "district.parquet", "Planning-model panel, districts 1999-2025"),
    "planning_state": (PANEL_DIR / "planning" / "state.parquet", "Planning-model panel, states 1982-2025"),
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
        raise FileNotFoundError(f"{path} not found: unzip the shared data package into {dest}/")
    return pd.read_parquet(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("step", choices=["export", "check"])
    parser.add_argument("--dest", type=Path, default=SHARED)
    args = parser.parse_args()
    export(args.dest) if args.step == "export" else check(args.dest)


if __name__ == "__main__":
    main()
