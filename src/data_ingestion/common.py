"""Shared helpers for the data ingestion scripts."""

from pathlib import Path

import earthaccess
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]

# Local cache for downloaded files (git-ignored).
DATA_DIR = REPO_ROOT / "data"

# Agricultural reference sites used for previews: (name, lat, lon).
SAMPLE_SITES = [
    ("Ames, IA (US Corn Belt)", 42.03, -93.47),
    ("Fresno, CA (Central Valley)", 36.74, -119.79),
    ("Celaya, GTO (Bajio, MX)", 20.52, -100.82),
    ("Pergamino (Pampas, AR)", -33.89, -60.57),
    ("Ludhiana (Punjab, IN)", 30.90, 75.85),
]


def parse_site(text):
    """argparse type for --site: 'LAT,LON' -> (name, lat, lon)."""
    lat, lon = (float(v) for v in text.split(","))
    return (f"{lat},{lon}", lat, lon)


def earthdata_login():
    """Log in to NASA Earthdata without prompting. Returns True if authenticated.

    Uses EARTHDATA_USERNAME / EARTHDATA_PASSWORD (or EARTHDATA_TOKEN) env vars,
    falling back to ~/.netrc. See src/data_ingestion/README.md for setup.
    """
    for strategy in ("environment", "netrc"):
        try:
            auth = earthaccess.login(strategy=strategy)
        except Exception:
            continue
        if auth.authenticated:
            return True
    return False


def nearest_index(coords, value):
    """Index of the grid coordinate closest to `value`."""
    return int(np.abs(np.asarray(coords) - value).argmin())
