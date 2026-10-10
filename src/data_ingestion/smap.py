"""SMAP L4 soil moisture ingestion: SPL4SMGP v008 (3-hourly, 9 km EASE-Grid 2.0).

Dataset: https://nsidc.org/data/spl4smgp/versions/8 (DOI 10.5067/T5RUATAQREF8)

Granules are ~140 MB HDF5 files. Instead of downloading them, this script streams
only the pixel it needs from each file via earthaccess.open() + h5py.

Requires a NASA Earthdata login to read values. Without one, the connection test and
granule search still run, and the preview shows granule metadata instead.

Usage (from the repo root):
    python -m src.data_ingestion.smap
    python -m src.data_ingestion.smap --lat 20.52 --lon -100.82 --start 2024-07-01 --end 2024-07-03 --out data/smap.csv
"""

import argparse
import re
import time
from datetime import datetime

import earthaccess
import h5py
import numpy as np
import pandas as pd

from src.data_ingestion.common import SAMPLE_SITES, earthdata_login, nearest_index

SHORT_NAME = "SPL4SMGP"
VERSION = "008"

# Variables read from the Geophysical_Data group.
VARIABLES = [
    "sm_surface",    # Surface soil moisture, 0-5 cm (m3/m3)
    "sm_rootzone",   # Root-zone soil moisture, 0-100 cm (m3/m3)
    "sm_profile",    # Profile soil moisture, surface to bedrock (m3/m3)
    "surface_temp",  # Mean land surface temperature (K)
]

FILL_VALUE = -9999.0

_, DEFAULT_LAT, DEFAULT_LON = SAMPLE_SITES[0]

# e.g. SMAP_L4_SM_gph_20240701T013000_Vv8010_001.h5 -> timestamp, build
GRANULE_RE = re.compile(r"_(\d{8}T\d{6})_Vv(\d+)_")


def granule_info(granule):
    """Return (timestamp UTC, processing build) parsed from the granule name."""
    match = GRANULE_RE.search(granule["umm"]["GranuleUR"])
    return datetime.strptime(match.group(1), "%Y%m%dT%H%M%S"), int(match.group(2))


def latest_builds(granules):
    """Keep one granule per 3-hourly timestamp: the most recent processing build.

    CMR returns reprocessed builds (e.g. Vv8010 and Vv8012) side by side for the same time.
    """
    best = {}
    for granule in granules:
        timestamp, build = granule_info(granule)
        if timestamp not in best or build > granule_info(best[timestamp])[1]:
            best[timestamp] = granule
    return [best[t] for t in sorted(best)]


def test_connection():
    """Look up the collection in NASA CMR (no login needed). Returns True on success."""
    started = time.perf_counter()
    try:
        collections = earthaccess.search_datasets(short_name=SHORT_NAME, version=VERSION)
    except Exception as exc:
        print(f"[FAIL] NASA CMR unreachable: {exc}")
        return False
    if not collections:
        print(f"[FAIL] Collection {SHORT_NAME} v{VERSION} not found in CMR")
        return False

    elapsed = time.perf_counter() - started
    collection = collections[0]
    print(f"[OK] CMR found {collection.concept_id}: {collection['umm']['EntryTitle']} ({elapsed:.2f}s)")
    return True


def search_granules(lat, lon, start, end):
    """Find granules covering the point and date range (YYYY-MM-DD), deduplicated by build."""
    granules = earthaccess.search_data(
        short_name=SHORT_NAME, version=VERSION, temporal=(start, end), point=(lon, lat)
    )
    # CMR also returns the window that ends exactly at `start` (centered the evening before).
    return [g for g in latest_builds(granules) if granule_info(g)[0] >= datetime.fromisoformat(start)]


def granule_table(granules):
    """Granule metadata as a DataFrame (what we can show without a login)."""
    rows = []
    for granule in granules:
        timestamp, build = granule_info(granule)
        rows.append({
            "datetime": timestamp,
            "granule": granule["umm"]["GranuleUR"],
            "build": build,
            "size_mb": round(granule.size, 1),
        })
    return pd.DataFrame(rows).set_index("datetime")


def extract_point(granules, lat, lon, variables=VARIABLES):
    """Stream each granule and read the 9 km pixel nearest to (lat, lon). Needs Earthdata login.

    Returns (DataFrame indexed by UTC datetime, units dict, (pixel_lat, pixel_lon)).
    """
    files = earthaccess.open(granules)
    records, units = [], {}
    row = col = pixel = None

    for granule, fobj in zip(granules, files):
        with h5py.File(fobj, "r") as h5:
            if row is None:
                # EASE-Grid 2.0 is cylindrical: latitude is constant along rows and
                # longitude along columns, so 1-D slices are enough to locate the pixel.
                row = nearest_index(h5["cell_lat"][:, 0], lat)
                col = nearest_index(h5["cell_lon"][0, :], lon)
                pixel = (float(h5["cell_lat"][row, col]), float(h5["cell_lon"][row, col]))

            group = h5["Geophysical_Data"]
            record = {"datetime": granule_info(granule)[0]}
            for name in variables:
                dataset = group[name]
                value = float(dataset[row, col])
                record[name] = np.nan if value == FILL_VALUE else value
                unit = dataset.attrs.get("units", "")
                units.setdefault(name, unit.decode() if isinstance(unit, bytes) else str(unit))
            records.append(record)

    return pd.DataFrame(records).set_index("datetime"), units, pixel


def main():
    parser = argparse.ArgumentParser(description="Pull SMAP L4 (SPL4SMGP) soil moisture for a point.")
    parser.add_argument("--lat", type=float, default=DEFAULT_LAT)
    parser.add_argument("--lon", type=float, default=DEFAULT_LON)
    parser.add_argument("--start", default="2024-07-01", help="YYYY-MM-DD")
    parser.add_argument("--end", default="2024-07-01", help="YYYY-MM-DD")
    parser.add_argument("--rows", type=int, default=5, help="Number of records to preview")
    parser.add_argument("--out", help="Optional CSV path to save the full result (e.g. data/smap.csv)")
    args = parser.parse_args()

    if not test_connection():
        raise SystemExit(1)

    granules = search_granules(args.lat, args.lon, args.start, args.end)
    print(f"Found {len(granules)} granules for {args.start} -> {args.end} (latest build per 3-hourly step)")
    if not granules:
        return

    with pd.option_context("display.width", 200, "display.max_columns", None):
        if not earthdata_login():
            print("\n[WARN] Not logged in to NASA Earthdata, so values can't be read. "
                  "See src/data_ingestion/README.md to set up a login.")
            print(f"\nFirst {args.rows} granules:")
            print(granule_table(granules).head(args.rows))
            return

        print("[OK] Logged in to NASA Earthdata; streaming pixel values...")
        df, units, pixel = extract_point(granules, args.lat, args.lon)
        print(f"\nRequested lat={args.lat}, lon={args.lon} | nearest 9 km pixel lat={pixel[0]:.3f}, lon={pixel[1]:.3f}")
        print("Units: " + ", ".join(f"{k} [{v}]" for k, v in units.items()) + " | times are UTC")
        print(f"\nFirst {args.rows} records:")
        print(df.head(args.rows))

    if args.out:
        df.to_csv(args.out)
        print(f"\nSaved {len(df)} records to {args.out}")


if __name__ == "__main__":
    main()
