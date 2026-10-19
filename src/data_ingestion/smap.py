"""SMAP L4 soil moisture ingestion: SPL4SMGP v008 (3-hourly, 9 km EASE-Grid 2.0).

Dataset: https://nsidc.org/data/spl4smgp/versions/8 (DOI 10.5067/T5RUATAQREF8)

Granules are ~140 MB HDF5 files, and each variable is stored as one compressed block for the
whole globe, so even streaming a single pixel downloads ~4 MB per variable. Instead, this
script asks NASA's OPeNDAP server for just the pixel and reads granules in parallel: a week of
3-hourly data takes seconds. If OPeNDAP fails for a granule, it falls back to streaming that
granule's HDF5 with earthaccess.open() + h5py (same values, much slower).

Requires a NASA Earthdata login to read values. Without one, the connection test and
granule search still run, and the preview shows granule metadata instead.

Usage (from the repo root):
    python -m src.data_ingestion.smap
    python -m src.data_ingestion.smap --lat 20.52 --lon -100.82 --start 2024-07-01 --end 2024-07-07 --out data/smap.csv
    python -m src.data_ingestion.smap --variables sm_rootzone sm_rootzone_pctl precipitation_total_surface_flux
"""

import argparse
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import earthaccess
import h5py
import numpy as np
import pandas as pd
import requests

from src.data_ingestion.common import SAMPLE_SITES, earthdata_login, nearest_index

SHORT_NAME = "SPL4SMGP"
VERSION = "008"

# Default variables read from the Geophysical_Data group (all 45 are listed in the README).
VARIABLES = [
    "sm_surface",    # Surface soil moisture, 0-5 cm (m3/m3)
    "sm_rootzone",   # Root-zone soil moisture, 0-100 cm (m3/m3)
    "sm_profile",    # Profile soil moisture, surface to bedrock (m3/m3)
    "surface_temp",  # Mean land surface temperature (K)
]

FILL_VALUE = -9999.0

WORKERS = 16  # parallel OPeNDAP requests
RETRIES = 3   # OPeNDAP attempts per granule before the HDF5 fallback
TIMEOUT = 60

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


def h5_url(granule):
    """HTTPS link to the granule's HDF5 file (each granule also links a .qa and an .iso.xml file)."""
    return next(url for url in granule.data_links() if url.endswith(".h5"))


def opendap_url(granule):
    """The granule's OPeNDAP endpoint from CMR, or None if it has none."""
    for link in granule["umm"].get("RelatedUrls", []):
        if link.get("Subtype") == "OPENDAP DATA":
            return link["URL"]
    return None


def locate_pixel(granule, lat, lon, variables=VARIABLES):
    """Find the grid cell nearest to (lat, lon) and the variables' units by streaming one granule.

    The grid is identical in every granule, so this runs once per request (~6 s).
    Returns (row, col, (pixel_lat, pixel_lon), units dict). Raises ValueError for unknown variables.
    """
    with h5py.File(earthaccess.open([h5_url(granule)])[0], "r") as h5:
        # EASE-Grid 2.0 is cylindrical: latitude is constant along rows and
        # longitude along columns, so 1-D slices are enough to locate the pixel.
        lats = h5["cell_lat"][:, 0]
        lons = h5["cell_lon"][0, :]
        row, col = nearest_index(lats, lat), nearest_index(lons, lon)

        group = h5["Geophysical_Data"]
        unknown = [name for name in variables if name not in group]
        if unknown:
            raise ValueError(f"Unknown SMAP variable(s): {', '.join(unknown)}. Available: {', '.join(group)}")
        units = {}
        for name in variables:
            unit = group[name].attrs.get("units", "")
            units[name] = unit.decode() if isinstance(unit, bytes) else str(unit)

    return row, col, (float(lats[row]), float(lons[col])), units


def read_opendap(session, url, row, col, variables=VARIABLES):
    """One granule's pixel from OPeNDAP (DAP2 ASCII). Returns {variable: value}.

    Values come back rounded to 6 significant digits, far finer than the product's accuracy.
    """
    constraint = ",".join(f"/Geophysical_Data/{name}[{row}][{col}]" for name in variables)
    response = session.get(f"{url}.ascii?{constraint}", timeout=TIMEOUT)
    response.raise_for_status()

    # A "Dataset: <file>" line, then one "/Geophysical_Data/<name>[0], <value>" line per variable.
    values = {}
    for line in response.text.splitlines()[1:]:
        if "," in line:
            name, value = line.split(",", 1)
            values[name.split("[")[0].rsplit("/", 1)[-1]] = float(value)
    missing = set(variables) - set(values)
    if missing:
        raise ValueError(f"OPeNDAP response is missing {sorted(missing)}")
    return values


def read_h5(granule, row, col, variables=VARIABLES):
    """Fallback: stream the granule's HDF5 and read the pixel (downloads ~4 MB per variable)."""
    with h5py.File(earthaccess.open([h5_url(granule)])[0], "r") as h5:
        group = h5["Geophysical_Data"]
        return {name: float(group[name][row, col]) for name in variables}


def read_granule(session, granule, row, col, variables=VARIABLES):
    """Read one granule's pixel: OPeNDAP with retries, then the HDF5 fallback."""
    url = opendap_url(granule)
    if url:
        for attempt in range(RETRIES):
            try:
                return read_opendap(session, url, row, col, variables)
            except (requests.RequestException, ValueError):
                time.sleep(2 ** attempt)
    return read_h5(granule, row, col, variables)


def extract_point(granules, lat, lon, variables=VARIABLES, workers=WORKERS):
    """Read the 9 km pixel nearest to (lat, lon) from every granule. Needs Earthdata login.

    Returns (DataFrame indexed by UTC datetime, fill values as NaN; units dict; (pixel_lat, pixel_lon)).
    """
    variables = list(variables)
    row, col, pixel, units = locate_pixel(granules[0], lat, lon, variables)
    session = earthaccess.get_requests_https_session()
    with ThreadPoolExecutor(workers) as pool:
        records = list(pool.map(lambda g: read_granule(session, g, row, col, variables), granules))

    index = pd.DatetimeIndex([granule_info(g)[0] for g in granules], name="datetime")
    df = pd.DataFrame(records, index=index)[variables].replace(FILL_VALUE, np.nan)
    return df, units, pixel


def main():
    parser = argparse.ArgumentParser(description="Pull SMAP L4 (SPL4SMGP) soil moisture for a point.")
    parser.add_argument("--lat", type=float, default=DEFAULT_LAT)
    parser.add_argument("--lon", type=float, default=DEFAULT_LON)
    parser.add_argument("--start", default="2024-07-01", help="YYYY-MM-DD")
    parser.add_argument("--end", default="2024-07-01", help="YYYY-MM-DD")
    parser.add_argument("--variables", nargs="+", default=VARIABLES,
                        help="Geophysical_Data variables to read (default: %(default)s)")
    parser.add_argument("--workers", type=int, default=WORKERS, help="Parallel requests")
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

        print("[OK] Logged in to NASA Earthdata; reading pixel values...")
        started = time.perf_counter()
        try:
            df, units, pixel = extract_point(granules, args.lat, args.lon, args.variables, args.workers)
        except ValueError as exc:
            raise SystemExit(f"[FAIL] {exc}")
        print(f"Read {len(df)} granules in {time.perf_counter() - started:.0f}s")
        print(f"\nRequested lat={args.lat}, lon={args.lon} | nearest 9 km pixel lat={pixel[0]:.3f}, lon={pixel[1]:.3f}")
        print("Units: " + ", ".join(f"{k} [{v}]" for k, v in units.items()) + " | times are UTC")
        print(f"\nFirst {args.rows} records:")
        print(df.head(args.rows))

    if args.out:
        df.to_csv(args.out)
        print(f"\nSaved {len(df)} records to {args.out}")


if __name__ == "__main__":
    main()
