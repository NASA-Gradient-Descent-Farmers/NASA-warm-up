"""NASA POWER ingestion: daily point data from the POWER API.

Docs: https://power.larc.nasa.gov/docs/tutorials/service-data-request/api/

Usage:
    python src/data_ingestion/power.py                      # test connection + preview 5 records
    python src/data_ingestion/power.py --lat 19.43 --lon -99.13 --start 20240101 --end 20240131
"""

import argparse
import time

import numpy as np
import pandas as pd
import requests

BASE_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"

# Agroclimatology (AG) community: units suited to crop / water-balance modelling.
COMMUNITY = "AG"

# Default agronomic variables.
DEFAULT_PARAMETERS = [
    "T2M",                # Temperature at 2 m (C)
    "T2M_MAX",            # Max temperature at 2 m (C)
    "T2M_MIN",            # Min temperature at 2 m (C)
    "PRECTOTCORR",        # Precipitation corrected (mm/day)
    "RH2M",               # Relative humidity at 2 m (%)
    "WS2M",               # Wind speed at 2 m (m/s)
    "ALLSKY_SFC_SW_DWN",  # All-sky surface shortwave downward irradiance (MJ/m^2/day)
]

# Default point: Ames, Iowa (US Corn Belt).
DEFAULT_LAT = 42.03
DEFAULT_LON = -93.47

TIMEOUT = 30


def fetch_daily_point(lat, lon, start, end, parameters=DEFAULT_PARAMETERS, community=COMMUNITY):
    """Request daily point data and return the raw JSON response.

    `start` / `end` are YYYYMMDD strings.
    """
    params = {
        "parameters": ",".join(parameters),
        "community": community,
        "latitude": lat,
        "longitude": lon,
        "start": start,
        "end": end,
        "format": "JSON",
    }
    response = requests.get(BASE_URL, params=params, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def to_dataframe(payload):
    """Convert a POWER JSON payload to a date-indexed DataFrame (fill values -> NaN)."""
    data = payload["properties"]["parameter"]
    fill_value = payload["header"]["fill_value"]

    df = pd.DataFrame(data)
    df.index = pd.to_datetime(df.index, format="%Y%m%d")
    df.index.name = "date"
    return df.replace(fill_value, np.nan)


def test_connection(lat=DEFAULT_LAT, lon=DEFAULT_LON):
    """Make a minimal one-day request to confirm the API is reachable. Returns True on success."""
    started = time.perf_counter()
    try:
        payload = fetch_daily_point(lat, lon, "20240101", "20240101", parameters=["T2M"])
    except requests.RequestException as exc:
        print(f"[FAIL] POWER API unreachable: {exc}")
        return False

    elapsed = time.perf_counter() - started
    api = payload["header"]["api"]
    print(f"[OK] {api['name']} {api['version']} responded in {elapsed:.2f}s")
    return True


def main():
    parser = argparse.ArgumentParser(description="Pull daily NASA POWER data for a point.")
    parser.add_argument("--lat", type=float, default=DEFAULT_LAT)
    parser.add_argument("--lon", type=float, default=DEFAULT_LON)
    parser.add_argument("--start", default="20240101", help="YYYYMMDD")
    parser.add_argument("--end", default="20240131", help="YYYYMMDD")
    parser.add_argument("--rows", type=int, default=5, help="Number of records to preview")
    parser.add_argument("--out", help="Optional CSV path to save the full result (e.g. data/power.csv)")
    args = parser.parse_args()

    if not test_connection(args.lat, args.lon):
        raise SystemExit(1)

    payload = fetch_daily_point(args.lat, args.lon, args.start, args.end)
    df = to_dataframe(payload)

    units = {name: meta["units"] for name, meta in payload["parameters"].items()}
    print(f"\nLocation: lat={args.lat}, lon={args.lon} | {args.start} -> {args.end} | {len(df)} records")
    print("Units: " + ", ".join(f"{k} [{v}]" for k, v in units.items()))
    print(f"\nFirst {args.rows} records:")
    with pd.option_context("display.width", 200, "display.max_columns", None):
        print(df.head(args.rows))

    if args.out:
        df.to_csv(args.out)
        print(f"\nSaved {len(df)} records to {args.out}")


if __name__ == "__main__":
    main()
