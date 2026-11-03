"""Network pullers for the SiteProfile pipeline. Each returns (data, status_dict) and never raises on a data outage.

status = {"status": "ok" | "fallback" | "missing", "reason": "..."}; raw responses are cached under data/advisor/cache/.
"""

import hashlib
import json
import time
from pathlib import Path

import requests

from src.data_ingestion import power

CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "advisor" / "cache"
TIMEOUT = 60
POWER_START, POWER_END = "19910101", "20241231"

SOILGRIDS_URL = "https://rest.isric.org/soilgrids/v2.0/properties/query"
OPENTOPO_URL = "https://api.opentopodata.org/v1/srtm30m"
MODIS_URL = "https://modis.ornl.gov/rst/api/v1/MOD13Q1/subset"
# SoilGrids stores some properties scaled by an integer factor; `d_factor` converts to conventional units.
SOIL_PROPERTIES = ["soc", "clay", "sand", "phh2o", "nitrogen"]


def _cached(name, producer):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(name.encode()).hexdigest()[:16]
    path = CACHE_DIR / f"{name.split('|')[0]}_{key}.json"
    if path.exists():
        return json.loads(path.read_text())
    value = producer()
    path.write_text(json.dumps(value))
    return value


def _get(url, params, retries=3, pause=2.0):
    last = None
    for attempt in range(retries):
        try:
            response = requests.get(url, params=params, timeout=TIMEOUT, headers={"User-Agent": "gradient-descent-farmers"})
            if response.status_code == 429:
                time.sleep(pause * (attempt + 2))
                continue
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            last = exc
            time.sleep(pause * (attempt + 1))
    raise RuntimeError(str(last))


def pull_power(lat, lon):
    """Daily POWER weather 1991-2024 for one point. Returns (payload, status)."""
    try:
        payload = _cached(f"power|{lat:.3f}|{lon:.3f}|{POWER_START}|{POWER_END}",
                          lambda: power.fetch_daily_point(lat, lon, POWER_START, POWER_END, time_standard="UTC"))
        return payload, {"status": "ok", "reason": "NASA POWER daily 1991-2024 (~50 km grid)"}
    except Exception as exc:  # noqa: BLE001 - report any outage as missing data
        return None, {"status": "missing", "reason": f"POWER unavailable: {exc}"}


def pull_elevation(lat, lon, step=0.003):
    """SRTM 30 m elevation at the point and slope from four neighbours. Returns ((elev, slope), status)."""
    points = [(lat, lon), (lat + step, lon), (lat - step, lon), (lat, lon + step), (lat, lon - step)]
    locations = "|".join(f"{a},{b}" for a, b in points)
    try:
        data = _cached(f"elev|{lat:.4f}|{lon:.4f}", lambda: _get(OPENTOPO_URL, {"locations": locations}))
        z = [r["elevation"] for r in data["results"]]
        if any(v is None for v in z):
            raise RuntimeError("no SRTM coverage")
        import math

        dy = 2 * step * 111_320.0
        dx = 2 * step * 111_320.0 * math.cos(math.radians(lat))
        slope = math.degrees(math.atan(math.hypot((z[1] - z[2]) / dy, (z[3] - z[4]) / dx)))
        return (round(z[0], 1), round(slope, 2)), {"status": "ok", "reason": "SRTM 30 m via OpenTopoData"}
    except Exception as exc:  # noqa: BLE001
        return (None, None), {"status": "missing", "reason": f"elevation unavailable: {exc}"}


def pull_soilgrids(lat, lon):
    """SoilGrids 0-30 cm weighted means. Returns (dict, status); units converted to schema units."""
    try:
        params = [("lat", lat), ("lon", lon), ("value", "mean"), ("depth", "0-5cm"), ("depth", "5-15cm"),
                  ("depth", "15-30cm")] + [("property", p) for p in SOIL_PROPERTIES]
        data = _cached(f"soil|{lat:.4f}|{lon:.4f}", lambda: _get(SOILGRIDS_URL, params, pause=5.0))
        weights = {"0-5cm": 5, "5-15cm": 10, "15-30cm": 15}
        out = {}
        for layer in data["properties"]["layers"]:
            factor = layer["unit_measure"].get("d_factor", 1) or 1
            total = weight = 0.0
            for depth in layer["depths"]:
                value = depth["values"].get("mean")
                if value is None:
                    continue
                w = weights.get(depth["label"].replace(" ", ""), 0)
                total += w * value / factor
                weight += w
            out[layer["name"]] = round(total / weight, 2) if weight else None
        # SoilGrids: soc dg/kg -> g/kg (d_factor 10), clay/sand g/kg -> % (d_factor 10), nitrogen cg/kg -> g/kg (d_factor 100)
        soil = {"soc_g_kg": out.get("soc"), "clay_pct": out.get("clay"), "sand_pct": out.get("sand"),
                "ph": out.get("phh2o"), "n_g_kg": out.get("nitrogen")}
        if all(v is None for v in soil.values()):
            raise RuntimeError("no SoilGrids values at this point (water, ice or urban?)")
        return soil, {"status": "ok", "reason": "SoilGrids 250 m, 0-30 cm weighted mean"}
    except Exception as exc:  # noqa: BLE001
        return None, {"status": "missing", "reason": f"SoilGrids unavailable: {exc}"}


def pull_modis_ndvi(lat, lon, first_year=2019, last_year=2023, chunk=10):
    """MOD13Q1 NDVI composites (16-day, 250 m) via ORNL DAAC subset service. Returns (samples, status)."""
    try:
        samples = _cached(f"modis|{lat:.4f}|{lon:.4f}|{first_year}|{last_year}",
                          lambda: _fetch_modis(lat, lon, first_year, last_year, chunk))
        if not samples:
            raise RuntimeError("no valid NDVI composites returned")
        return samples, {"status": "ok", "reason": f"MODIS MOD13Q1 NDVI {first_year}-{last_year} (250 m, ORNL DAAC)"}
    except Exception as exc:  # noqa: BLE001
        return None, {"status": "missing", "reason": f"MODIS NDVI unavailable: {exc}"}


def _fetch_modis(lat, lon, first_year, last_year, chunk):
    dates = _get("https://modis.ornl.gov/rst/api/v1/MOD13Q1/dates", {"latitude": lat, "longitude": lon})["dates"]
    wanted = [d for d in dates if first_year <= int(d["calendar_date"][:4]) <= last_year]
    samples = []
    for i in range(0, len(wanted), chunk):
        block = wanted[i:i + chunk]
        data = _get(MODIS_URL, {"latitude": lat, "longitude": lon, "band": "250m_16_days_NDVI",
                                "startDate": block[0]["modis_date"], "endDate": block[-1]["modis_date"],
                                "kmAboveBelow": 0, "kmLeftRight": 0})
        scale = float(data.get("scale", 0.0001))
        for row in data["subset"]:
            value = row["data"][0]
            if value is not None and value > -2000:
                samples.append((row["calendar_date"], round(value * scale, 4)))
    return samples

