"""IGBP-DIS Global Gridded Surfaces of Selected Soil Characteristics (ORNL DAAC 569).

Dataset: https://doi.org/10.3334/ORNLDAAC/569 (CMR C2216863098-ORNL_CLOUD)

7 static global grids at 5 arc-minutes for the 0-100 cm soil layer, in ARC/INFO
ASCII grid format (~31 MB each). Downloading needs a NASA Earthdata login; files
are cached in data/igbp/. Without a login the connection test and search still run.

Usage (from the repo root):
    python -m src.data_ingestion.igbp_soils                               # 5 sample farm sites
    python -m src.data_ingestion.igbp_soils --site 20.52,-100.82 --out data/igbp_soils.csv
"""

import argparse
import time

import earthaccess
import numpy as np
import pandas as pd

from src.data_ingestion.common import DATA_DIR, SAMPLE_SITES, earthdata_login, parse_site

DOI = "10.3334/ORNLDAAC/569"

# File key (from IGBP-SurfaceProducts.<key>.dat) -> output column.
LAYERS = {
    "fieldcap": "field_capacity",
    "wiltpont": "wilting_point",
    "pawc": "profile_available_water_capacity",
    "bulkdens": "bulk_density",
    "soilcarb": "soil_carbon_density",
    "totaln": "total_nitrogen_density",
    "thermcap": "thermal_capacity",
}

CACHE_DIR = DATA_DIR / "igbp"


def layer_key(granule):
    """'IGBP-SurfaceProducts.fieldcap.dat' -> 'fieldcap'."""
    return granule["umm"]["GranuleUR"].split(".")[1]


def test_connection():
    """Look up the dataset's granules in NASA CMR (no login needed). Returns True on success."""
    started = time.perf_counter()
    try:
        granules = earthaccess.search_data(doi=DOI)
    except Exception as exc:
        print(f"[FAIL] NASA CMR unreachable: {exc}")
        return False
    if not granules:
        print(f"[FAIL] No granules found in CMR for DOI {DOI}")
        return False

    print(f"[OK] CMR found {len(granules)} files for DOI {DOI} ({time.perf_counter() - started:.2f}s)")
    return True


def search_granules():
    return earthaccess.search_data(doi=DOI)


def granule_table(granules):
    """Granule metadata as a DataFrame (what we can show without a login)."""
    rows = []
    for granule in granules:
        size = granule.size() if callable(granule.size) else granule.size
        key = layer_key(granule)
        rows.append({"layer": LAYERS.get(key, key),
                     "granule": granule["umm"]["GranuleUR"],
                     "size_mb": round(size, 1)})
    return pd.DataFrame(rows).set_index("layer")


def download(granules):
    """Download the .dat grids into data/igbp/ (skips files already cached). Needs login."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    missing = [g for g in granules if not (CACHE_DIR / f"{layer_key(g)}.dat").exists()]
    if missing:
        earthaccess.download(missing, str(CACHE_DIR))


def read_ascii_grid(path):
    """Parse an ARC/INFO ASCII grid -> (header dict, 2-D float array with NODATA as NaN)."""
    header = {}
    with open(path) as f:
        # Header lines look like "ncols 4320"; the first numeric line starts the data.
        while True:
            position = f.tell()
            parts = f.readline().split()
            if not parts or not parts[0][0].isalpha():
                f.seek(position)
                break
            header[parts[0].lower()] = float(parts[1])
        values = np.fromstring(f.read(), dtype=np.float32, sep=" ")

    grid = values.reshape(int(header["nrows"]), int(header["ncols"]))
    if "nodata_value" in header:
        grid[grid == header["nodata_value"]] = np.nan
    return header, grid


def grid_value(header, grid, lat, lon):
    """Value of the cell containing (lat, lon), or NaN if the point is off the grid."""
    size = header["cellsize"]
    # Grids reference either the lower-left cell corner or its center.
    x0 = header["xllcorner"] if "xllcorner" in header else header["xllcenter"] - size / 2
    y0 = header["yllcorner"] if "yllcorner" in header else header["yllcenter"] - size / 2
    top = y0 + grid.shape[0] * size

    row = int((top - lat) // size)
    col = int((lon - x0) // size)
    if 0 <= row < grid.shape[0] and 0 <= col < grid.shape[1]:
        return float(grid[row, col])
    return np.nan


def extract_points(sites):
    """Read every cached layer at each (name, lat, lon) site, one grid in memory at a time."""
    df = pd.DataFrame(
        [{"site": name, "lat": lat, "lon": lon} for name, lat, lon in sites]
    ).set_index("site")
    for key, column in LAYERS.items():
        header, grid = read_ascii_grid(CACHE_DIR / f"{key}.dat")
        df[column] = [grid_value(header, grid, lat, lon) for _, lat, lon in sites]
    return df


def main():
    parser = argparse.ArgumentParser(description="Extract IGBP-DIS soil characteristics at points.")
    parser.add_argument("--site", type=parse_site, action="append",
                        help="LAT,LON (repeatable). Defaults to 5 sample farm sites.")
    parser.add_argument("--rows", type=int, default=5, help="Number of records to preview")
    parser.add_argument("--out", help="Optional CSV path to save the full result (e.g. data/igbp_soils.csv)")
    args = parser.parse_args()

    if not test_connection():
        raise SystemExit(1)

    granules = search_granules()

    with pd.option_context("display.width", 200, "display.max_columns", None):
        if not earthdata_login():
            print("\n[WARN] Not logged in to NASA Earthdata, so the grids can't be downloaded. "
                  "See src/data_ingestion/README.md to set up a login.")
            print(f"\nFirst {args.rows} granules:")
            print(granule_table(granules).head(args.rows))
            return

        print("[OK] Logged in to NASA Earthdata")
        download(granules)
        df = extract_points(args.site or SAMPLE_SITES)

        print("\nValues are for the 0-100 cm soil layer (units: see src/data_ingestion/README.md)")
        print(f"\nFirst {args.rows} records:")
        print(df.head(args.rows).round(3))

    if args.out:
        df.to_csv(args.out)
        print(f"\nSaved {len(df)} records to {args.out}")


if __name__ == "__main__":
    main()
