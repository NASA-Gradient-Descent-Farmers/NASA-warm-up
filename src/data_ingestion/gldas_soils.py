"""GLDAS soil parameters: Noah soil texture class, sand/silt/clay fractions and porosity.

Source: https://ldas.gsfc.nasa.gov/gldas/soils (public, no login needed)

Static 0.25 deg global grids (60S-90N) in small netCDF4 files (< 2 MB each),
downloaded once and cached in data/gldas/.

Usage (from the repo root):
    python -m src.data_ingestion.gldas_soils                              # 5 sample farm sites
    python -m src.data_ingestion.gldas_soils --site 20.52,-100.82 --site 42.03,-93.47 --out data/gldas_soils.csv
"""

import argparse
import time

import h5py
import numpy as np
import pandas as pd
import requests

from src.data_ingestion.common import DATA_DIR, SAMPLE_SITES, nearest_index, parse_site

BASE_URL = "https://ldas.gsfc.nasa.gov/sites/default/files/ldas/gldas/SOILS"

FILES = {
    "texture": "GLDASp5_soiltexture_025d.nc4",
    "fraction": "GLDASp4_soilfraction_025d.nc4",
    "porosity": "GLDASp5_porosity_025d.nc4",
}

# Output column: (file key, variable name inside the netCDF file). All unitless.
VARIABLES = {
    "texture_class": ("texture", "GLDAS_soiltex"),
    "sand": ("fraction", "GLDAS_soilfraction_sand"),
    "silt": ("fraction", "GLDAS_soilfraction_silt"),
    "clay": ("fraction", "GLDAS_soilfraction_clay"),
    "porosity": ("porosity", "GLDAS_porosity"),
}

# Noah / FAO 16-category soil texture classes.
TEXTURE_CLASSES = {
    1: "Sand", 2: "Loamy Sand", 3: "Sandy Loam", 4: "Silt Loam", 5: "Silt", 6: "Loam",
    7: "Sandy Clay Loam", 8: "Silty Clay Loam", 9: "Clay Loam", 10: "Sandy Clay",
    11: "Silty Clay", 12: "Clay", 13: "Organic Materials", 14: "Water", 15: "Bedrock", 16: "Other",
}

FILL_VALUE = -9999.0
TIMEOUT = 30
CACHE_DIR = DATA_DIR / "gldas"


def test_connection():
    """HEAD each source file on the LDAS server. Returns True if all are reachable."""
    ok = True
    for name in FILES.values():
        started = time.perf_counter()
        try:
            response = requests.head(f"{BASE_URL}/{name}", timeout=TIMEOUT)
            response.raise_for_status()
        except requests.RequestException as exc:
            print(f"[FAIL] {name}: {exc}")
            ok = False
            continue
        size_kb = int(response.headers.get("Content-Length", 0)) / 1024
        print(f"[OK] {name} ({size_kb:.0f} KB) responded in {time.perf_counter() - started:.2f}s")
    return ok


def download():
    """Download the soil files into data/gldas/ (skips files already cached)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for name in FILES.values():
        path = CACHE_DIR / name
        if path.exists():
            continue
        response = requests.get(f"{BASE_URL}/{name}", timeout=TIMEOUT)
        response.raise_for_status()
        path.write_bytes(response.content)
        print(f"Downloaded {name} -> {path.relative_to(DATA_DIR.parent)}")


def extract_points(sites):
    """Read every variable at the 0.25 deg cell nearest to each (name, lat, lon) site."""
    handles = {key: h5py.File(CACHE_DIR / name, "r") for key, name in FILES.items()}
    try:
        # All files share the same 0.25 deg grid.
        lats = handles["texture"]["lat"][:]
        lons = handles["texture"]["lon"][:]

        records = []
        for name, lat, lon in sites:
            i, j = nearest_index(lats, lat), nearest_index(lons, lon)
            record = {"site": name, "lat": lat, "lon": lon,
                      "grid_lat": float(lats[i]), "grid_lon": float(lons[j])}
            for column, (key, variable) in VARIABLES.items():
                value = float(handles[key][variable][0, i, j])
                record[column] = np.nan if value == FILL_VALUE else value
            records.append(record)
    finally:
        for handle in handles.values():
            handle.close()

    df = pd.DataFrame(records).set_index("site")
    # Texture codes are stored as floats with rounding noise (e.g. 3.9999998).
    df["texture_class"] = df["texture_class"].round().astype("Int64")
    df.insert(df.columns.get_loc("texture_class") + 1, "texture", df["texture_class"].map(TEXTURE_CLASSES))
    return df


def main():
    parser = argparse.ArgumentParser(description="Extract GLDAS soil parameters at points.")
    parser.add_argument("--site", type=parse_site, action="append",
                        help="LAT,LON (repeatable). Defaults to 5 sample farm sites.")
    parser.add_argument("--rows", type=int, default=5, help="Number of records to preview")
    parser.add_argument("--out", help="Optional CSV path to save the full result (e.g. data/gldas_soils.csv)")
    args = parser.parse_args()

    if not test_connection():
        raise SystemExit(1)

    download()
    df = extract_points(args.site or SAMPLE_SITES)

    print("\nUnits: fractions and porosity are unitless (0-1)")
    print(f"\nFirst {args.rows} records:")
    with pd.option_context("display.width", 200, "display.max_columns", None):
        print(df.head(args.rows).round(3))

    if args.out:
        df.to_csv(args.out)
        print(f"\nSaved {len(df)} records to {args.out}")


if __name__ == "__main__":
    main()
