"""Extra gridded NASA (and NASA-adjacent) sources, sampled at municipality points.

Every source is pulled as a box over the panel's municipalities (server-side subsetting where the
archive offers it), cached under data/<source>/, and then sampled at each municipality:

| Source | Product | Grid | Period | Access |
|---|---|---|---|---|
| IMERG | GPM_3IMERGDF v07, daily precipitation | 0.1 deg | 2000- | Earthdata, GES DISC OPeNDAP (one box per day) |
| CHIRPS | CHIRPS v2.0 daily precipitation | 0.05 deg | 1981- | UCSB, no login |
| MODIS NDVI | MOD13C2 v061 monthly NDVI/EVI | 0.05 deg | 2000- | Earthdata, LP DAAC OPeNDAP |
| Cropland mask | MCD12C1 v061 land cover percent (IGBP classes 12 + 14) | 0.05 deg | 2001- | Earthdata, LP DAAC (one file) |
| SMAP | SPL4SMGP v008 root-zone and surface soil moisture | 9 km | 2015-04- | Earthdata, NSIDC OPeNDAP (one granule per day) |

Rain from IMERG and CHIRPS goes through the same season features as POWER rain, so the three can be
compared like for like.
"""

import io
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import h5py
import numpy as np
import pandas as pd

from src.data_ingestion.common import DATA_DIR, earthdata_login
from src.yield_panel.weather import longest_run, rain_onset_doy

UNIT = ["state_id", "mun_id"]


# --- Boxes and point sampling -------------------------------------------------------------------

def bbox_for(municipalities, margin=0.5):
    """(lat_min, lat_max, lon_min, lon_max) around all municipality points, rounded outwards."""
    return (np.floor(municipalities["lat"].min() - margin), np.ceil(municipalities["lat"].max() + margin),
            np.floor(municipalities["lon"].min() - margin), np.ceil(municipalities["lon"].max() + margin))


def sample(cube, lat, lon, points, radius_km, weights=None):
    """Average a (time, lat, lon) cube over the cells within `radius_km` of each point.

    `weights` (lat, lon), e.g. cropland share, weight the cells; cells with weight 0 are ignored unless
    a point has no weighted cell, in which case the plain average is used. Returns (time, n_points).
    """
    lat, lon = np.asarray(lat), np.asarray(lon)
    out = np.full((cube.shape[0], len(points)), np.nan, dtype=float)
    used_weights = np.zeros(len(points), bool)
    for k, (plat, plon) in enumerate(points):
        dy = (lat - plat) * 111.0
        dx = (lon - plon) * 111.0 * np.cos(np.radians(plat))
        iy, ix = np.where(np.abs(dy) <= radius_km)[0], np.where(np.abs(dx) <= radius_km)[0]
        if len(iy) == 0 or len(ix) == 0:  # radius smaller than a cell: nearest cell
            iy, ix = [int(np.abs(dy).argmin())], [int(np.abs(dx).argmin())]
        mask = (dy[iy][:, None] ** 2 + dx[ix][None, :] ** 2) <= max(radius_km, 1e-9) ** 2
        if not mask.any():
            mask[:] = True
        block = cube[:, iy][:, :, ix]
        w = mask.astype(float)
        if weights is not None:
            ww = weights[np.ix_(iy, ix)] * mask
            if np.nansum(ww) > 0:
                w, used_weights[k] = ww, True
        valid = np.isfinite(block)
        num = np.nansum(np.where(valid, block, 0) * w, axis=(1, 2))
        den = np.sum(valid * w, axis=(1, 2))
        out[:, k] = np.where(den > 0, num / np.where(den > 0, den, 1), np.nan)
    return out, used_weights


def rain_features(rain, years, prefix, season=(5, 10)):
    """Season rain features from a daily rain Series (mm/day): the rain block of weather.season_features."""
    rows = []
    for year in years:
        s = rain[(rain.index >= pd.Timestamp(year, season[0], 1)) & (rain.index <= pd.Timestamp(year, season[1], 31))]
        if s.notna().sum() < 150:
            continue
        pre = rain[(rain.index >= pd.Timestamp(year - 1, 11, 1)) & (rain.index < pd.Timestamp(year, season[0], 1))]
        m = s.index.month
        rows.append({
            "year": year,
            f"{prefix}_rain_season_mm": s.sum(),
            f"{prefix}_rain_jun_mm": s[m == 6].sum(),
            f"{prefix}_rain_jul_aug_mm": s[(m == 7) | (m == 8)].sum(),
            f"{prefix}_rain_sep_oct_mm": s[(m == 9) | (m == 10)].sum(),
            f"{prefix}_rain_pre_season_mm": pre.sum() if pre.notna().sum() > 150 else np.nan,
            f"{prefix}_wet_days": int((s >= 1).sum()),
            f"{prefix}_max_daily_rain_mm": s.max(),
            f"{prefix}_longest_dry_spell_days": longest_run(s.fillna(0) < 1.0),
            f"{prefix}_onset_doy": rain_onset_doy(rain.fillna(0), pd.Timestamp(year, season[0], 1)),
        })
    return pd.DataFrame(rows)


def daily_to_features(days, cube_points, municipalities, years, prefix):
    """(n_days, n_points) daily rain -> season rain features per municipality-year."""
    index = pd.DatetimeIndex(days)
    parts = []
    for k, m in enumerate(municipalities[UNIT].itertuples(index=False)):
        f = rain_features(pd.Series(cube_points[:, k], index=index), years, prefix)
        f["state_id"], f["mun_id"] = m.state_id, m.mun_id
        parts.append(f)
    return pd.concat(parts, ignore_index=True)


# --- IMERG ---------------------------------------------------------------------------------------

def _imerg_index(bbox):
    lat_i = lambda x: int(round((x + 89.95) / 0.1))
    lon_i = lambda x: int(round((x + 179.95) / 0.1))
    return lat_i(bbox[0]), lat_i(bbox[1]), lon_i(bbox[2]), lon_i(bbox[3])


def imerg_urls(start, end):
    """day -> (OPeNDAP url, is_late_run). Final Run where available, else the Late Run.

    The Final Run (gauge-adjusted) lags months behind; in October 2026 it ended on 2025-09-30.
    The Late Run is the same algorithm with climatological gauge correction.
    """
    import earthaccess

    urls = {}
    for short, late in [("GPM_3IMERGDL", True), ("GPM_3IMERGDF", False)]:  # Final overwrites Late
        for g in earthaccess.search_data(short_name=short, version="07", temporal=(str(start), str(end))):
            day = pd.Timestamp(g["umm"]["TemporalExtent"]["RangeDateTime"]["BeginningDateTime"][:10]).date()
            if start <= day <= end:
                urls[day] = (_opendap_link(g), late)
    return urls


def imerg_day(session, url, bbox, retries=4):
    """One day of IMERG precipitation (mm/day) over the box, as a (lat, lon) array plus coordinates."""
    la0, la1, lo0, lo1 = _imerg_index(bbox)
    ce = f"/precipitation[0:1:0][{lo0}:1:{lo1}][{la0}:1:{la1}];/lat[{la0}:1:{la1}];/lon[{lo0}:1:{lo1}]"
    last = None
    for attempt in range(retries):
        try:
            r = session.get(url + ".dap.nc4", params={"dap4.ce": ce}, timeout=120)
            r.raise_for_status()
            with h5py.File(io.BytesIO(r.content), "r") as f:
                p = f["precipitation"][0].astype(float).T  # stored (lon, lat) -> (lat, lon)
                p[p < 0] = np.nan
                return p, f["lat"][:], f["lon"][:]
        except Exception as exc:  # transient server errors: back off and retry
            last = exc
            import time
            time.sleep(2 ** attempt)
    raise RuntimeError(f"IMERG {url}: {last!r}")


def fetch_imerg(start, end, bbox, workers=8, directory=DATA_DIR / "imerg"):
    """Daily IMERG over the box from `start` to `end` (dates), cached one .npz per year."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if not earthdata_login():
        raise RuntimeError("Earthdata login failed: set EARTHDATA_TOKEN or ~/.netrc")
    import earthaccess

    session = earthaccess.get_requests_https_session()
    tag = "_".join(f"{v:g}" for v in bbox)
    days_all, cubes, lat, lon = [], [], None, None
    for year in range(start.year, end.year + 1):
        path = directory / f"{year}_{tag}.npz"
        y0, y1 = max(start, date(year, 1, 1)), min(end, date(year, 12, 31))
        days = [y0 + timedelta(d) for d in range((y1 - y0).days + 1)]
        if path.exists():
            z = np.load(path)
            if len(z["days"]) == len(days):
                days_all += list(pd.to_datetime(z["days"]).date)
                cubes.append(z["precip"])
                lat, lon = z["lat"], z["lon"]
                continue
        urls = imerg_urls(y0, y1)
        missing = [d for d in days if d not in urls]
        if missing:
            raise RuntimeError(f"IMERG has no Final or Late file for {len(missing)} days, e.g. {missing[:3]}")
        with ThreadPoolExecutor(workers) as pool:
            results = list(pool.map(lambda d: imerg_day(session, urls[d][0], bbox), days))
        cube = np.stack([r[0] for r in results]).astype(np.float32)
        lat, lon = results[0][1], results[0][2]
        late = np.array([urls[d][1] for d in days])
        np.savez_compressed(path, precip=cube, lat=lat, lon=lon, days=np.array([str(d) for d in days]), late_run=late)
        days_all += days
        cubes.append(cube)
        print(f"IMERG {year}: {len(days)} days ({int(late.sum())} from the Late Run)", flush=True)
    return pd.to_datetime(days_all), np.concatenate(cubes), lat, lon


# --- CHIRPS --------------------------------------------------------------------------------------

CHIRPS_URL = "https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_daily/netcdf/{res}/chirps-v2.0.{year}.days_{res}.nc"


def fetch_chirps(years, bbox, res="p05", directory=DATA_DIR / "chirps"):
    """Daily CHIRPS over the box, read with HTTP range requests (only the box's chunks are fetched)."""
    import fsspec

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    tag = "_".join(f"{v:g}" for v in bbox)
    days_all, cubes, lat_out, lon_out = [], [], None, None
    for year in years:
        path = directory / f"{year}_{res}_{tag}.npz"
        if not path.exists():
            with fsspec.open(CHIRPS_URL.format(res=res, year=year), "rb", block_size=4 * 2**20,
                             client_kwargs={"trust_env": True}) as fh:  # use the HTTPS proxy if set
                with h5py.File(fh, "r") as f:
                    lat, lon = f["latitude"][:], f["longitude"][:]
                    iy = np.where((lat >= bbox[0]) & (lat <= bbox[1]))[0]
                    ix = np.where((lon >= bbox[2]) & (lon <= bbox[3]))[0]
                    cube = f["precip"][:, iy.min():iy.max() + 1, ix.min():ix.max() + 1].astype(np.float32)
                    t = f["time"][:]
                    units = f["time"].attrs["units"].decode() if isinstance(f["time"].attrs["units"], bytes) else f["time"].attrs["units"]
            origin = pd.Timestamp(re.search(r"since (\S+)", units).group(1))
            days = origin + pd.to_timedelta(t, unit="D")
            cube[cube < 0] = np.nan
            np.savez_compressed(path, precip=cube, lat=lat[iy.min():iy.max() + 1], lon=lon[ix.min():ix.max() + 1],
                                days=np.array([str(d.date()) for d in days]))
            print(f"CHIRPS {year}: {len(days)} days", flush=True)
        z = np.load(path)
        days_all += list(pd.to_datetime(z["days"]))
        cubes.append(z["precip"])
        lat_out, lon_out = z["lat"], z["lon"]
    return pd.DatetimeIndex(days_all), np.concatenate(cubes), lat_out, lon_out


# --- Shared Earthdata OPeNDAP helper -------------------------------------------------------------

def _session():
    if not earthdata_login():
        raise RuntimeError("Earthdata login failed: set EARTHDATA_TOKEN or ~/.netrc")
    import earthaccess

    return earthaccess.get_requests_https_session()


def _dap4(session, url, variables, retries=6):
    """Fetch a DAP4 constraint (list of '/path[slices]') as an in-memory HDF5 file."""
    import time

    last = None
    for attempt in range(retries):
        try:
            r = session.get(url + ".dap.nc4", params={"dap4.ce": ";".join(variables)}, timeout=300)
            r.raise_for_status()
            return h5py.File(io.BytesIO(r.content), "r")
        except Exception as exc:
            last = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(f"OPeNDAP {url}: {last!r}")


def _opendap_link(granule):
    for link in granule["umm"].get("RelatedUrls", []):
        if "opendap.earthdata.nasa.gov" in link.get("URL", ""):
            return link["URL"]
    raise ValueError(f"No OPeNDAP link for {granule['umm']['GranuleUR']}")


# --- MODIS NDVI (MOD13C2, monthly, 0.05 deg) -----------------------------------------------------

CMG = 0.05


def _cmg_window(bbox):
    """Row/column ranges of the global 0.05 deg CMG grid (row 0 at 90N, column 0 at 180W)."""
    r0, r1 = int(round((90 - bbox[1]) / CMG)), int(round((90 - bbox[0]) / CMG)) - 1
    c0, c1 = int(round((bbox[2] + 180) / CMG)), int(round((bbox[3] + 180) / CMG)) - 1
    lat = 90 - CMG * (np.arange(r0, r1 + 1) + 0.5)
    lon = -180 + CMG * (np.arange(c0, c1 + 1) + 0.5)
    return (r0, r1, c0, c1), lat, lon


def fetch_ndvi(start, end, bbox, workers=4, directory=DATA_DIR / "modis_ndvi"):
    """Monthly NDVI and EVI over the box (MOD13C2 v061). Low-reliability pixels (snow, cloud) set to NaN.

    Returns (month starts, ndvi cube, evi cube, lat, lon), cached as one .npz.
    """
    import earthaccess

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    tag = "_".join(f"{v:g}" for v in bbox)
    path = directory / f"mod13c2_{start:%Y%m}_{end:%Y%m}_{tag}.npz"
    (r0, r1, c0, c1), lat, lon = _cmg_window(bbox)
    if path.exists():
        z = np.load(path)
        return pd.to_datetime(z["months"]), z["ndvi"], z["evi"], z["lat"], z["lon"]

    session = _session()
    granules = earthaccess.search_data(short_name="MOD13C2", version="061", temporal=(str(start), str(end)))
    group = "/MOD_Grid_monthly_CMG_VI/Data_Fields/"
    names = ["CMG_0_05_Deg_Monthly_NDVI", "CMG_0_05_Deg_Monthly_EVI", "CMG_0_05_Deg_Monthly_pixel_reliability"]

    def one(granule):
        when = pd.Timestamp(granule["umm"]["TemporalExtent"]["RangeDateTime"]["BeginningDateTime"][:10])
        with _dap4(session, _opendap_link(granule), [f"{group}{n}[{r0}:1:{r1}][{c0}:1:{c1}]" for n in names]) as f:
            ndvi, evi, rel = (f[group.strip("/") + "/" + n][:] for n in names)
        bad = (ndvi == -3000) | (rel < 0) | (rel > 1)  # keep good (0) and marginal (1) pixels
        to_float = lambda a: np.where(bad, np.nan, a * 1e-4).astype(np.float32)
        return when, to_float(ndvi), to_float(evi)

    with ThreadPoolExecutor(workers) as pool:
        results = sorted(pool.map(one, granules), key=lambda r: r[0])
    months = pd.DatetimeIndex([r[0] for r in results])
    ndvi, evi = np.stack([r[1] for r in results]), np.stack([r[2] for r in results])
    np.savez_compressed(path, months=np.array(months.strftime("%Y-%m-%d"), dtype="U10"), ndvi=ndvi, evi=evi, lat=lat, lon=lon)
    print(f"MOD13C2: {len(months)} months", flush=True)
    return months, ndvi, evi, lat, lon


def fetch_cropland(bbox, year=2015, directory=DATA_DIR / "modis_landcover"):
    """Share of each 0.05 deg cell that is cropland (IGBP 12) or cropland/natural mosaic (IGBP 14, half weight).

    MCD12C1 has no OPeNDAP service, so the ~1.2 GB global HDF4 file is downloaded once, cut to the box,
    cached as .npz and deleted.
    """
    import earthaccess
    from pyhdf.SD import SD, SDC

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    tag = "_".join(f"{v:g}" for v in bbox)
    path = directory / f"mcd12c1_{year}_{tag}.npz"
    (r0, r1, c0, c1), lat, lon = _cmg_window(bbox)
    if path.exists():
        z = np.load(path)
        return z["cropland"], z["lat"], z["lon"]
    _session()
    granules = earthaccess.search_data(short_name="MCD12C1", version="061", temporal=(f"{year}-01-01", f"{year}-12-31"))
    files = earthaccess.download(granules[:1], str(directory))
    hdf = SD(str(files[0]), SDC.READ)
    pct = hdf.select("Land_Cover_Type_1_Percent")[r0:r1 + 1, c0:c1 + 1, :].astype(np.float32)  # (y, x, 17 classes)
    hdf.end()
    cropland = (pct[:, :, 12] + 0.5 * pct[:, :, 14]) / 100.0
    np.savez_compressed(path, cropland=cropland, lat=lat, lon=lon)
    Path(files[0]).unlink()
    return cropland, lat, lon


def ndvi_features(months, values, years, prefix):
    """Season vegetation features from a monthly Series: peak, May-Oct integral, green-up month, pre-season level."""
    s = pd.Series(values, index=months)
    rows = []
    for year in years:
        season = s[(s.index >= pd.Timestamp(year, 5, 1)) & (s.index <= pd.Timestamp(year, 11, 30))]
        pre = s[(s.index >= pd.Timestamp(year, 3, 1)) & (s.index <= pd.Timestamp(year, 4, 30))]
        if season.notna().sum() < 5:
            continue
        base, peak = pre.mean(), season.max()
        half = base + 0.5 * (peak - base) if np.isfinite(base) else np.nan
        green = season[season >= half].index.min() if np.isfinite(half) else pd.NaT
        rows.append({
            "year": year,
            f"{prefix}_peak": peak,
            f"{prefix}_peak_month": season.idxmax().month,
            f"{prefix}_integral_may_oct": season[season.index.month <= 10].sum(),
            f"{prefix}_jul_aug": season[season.index.month.isin([7, 8])].mean(),
            f"{prefix}_pre_season": base,
            f"{prefix}_amplitude": peak - base,
            f"{prefix}_greenup_month": green.month if pd.notna(green) else np.nan,
        })
    return pd.DataFrame(rows)


def monthly_to_features(months, cube_points, municipalities, years, prefix):
    parts = []
    for k, m in enumerate(municipalities[UNIT].itertuples(index=False)):
        f = ndvi_features(months, cube_points[:, k], years, prefix)
        f["state_id"], f["mun_id"] = m.state_id, m.mun_id
        parts.append(f)
    return pd.concat(parts, ignore_index=True)


# --- SMAP L4 (one granule per day) ---------------------------------------------------------------

SMAP_SHORT, SMAP_VERSION = "SPL4SMGP", "008"


def fetch_smap(start, end, bbox, hour="13:30", workers=6, directory=DATA_DIR / "smap_box"):
    """Daily snapshot (the `hour` UTC 3-hourly window) of root-zone and surface soil moisture over the box.

    Soil moisture changes slowly, so one granule a day is enough for seasonal features. Cached per year.
    """
    import earthaccess
    from src.data_ingestion import smap as smap_point

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    session = _session()
    tag = "_".join(f"{v:g}" for v in bbox)
    grid_path = directory / f"grid_{tag}.npz"
    days_all, roots, surfs = [], [], []
    rows = cols = lat = lon = None

    for year in range(start.year, end.year + 1):
        path = directory / f"{year}_{tag}.npz"
        if path.exists():
            z = np.load(path)
            days_all += list(pd.to_datetime(z["days"]))
            roots.append(z["rootzone"])
            surfs.append(z["surface"])
            lat, lon = z["lat"], z["lon"]
            continue
        y0, y1 = max(start, date(year, 1, 1)), min(end, date(year, 12, 31))
        granules = earthaccess.search_data(short_name=SMAP_SHORT, version=SMAP_VERSION, temporal=(str(y0), str(y1)))
        granules = [g for g in smap_point.latest_builds(granules)
                    if smap_point.granule_info(g)[0].strftime("%H:%M") == hour]
        if not granules:
            continue
        if rows is None:
            if grid_path.exists():
                z = np.load(grid_path)
                rows, cols, lat, lon = tuple(z["rows"]), tuple(z["cols"]), z["lat"], z["lon"]
            else:
                url = _opendap_link(granules[0])
                # Separate requests: cell_lat and cell_lon share the (y, x) dimensions, and one DAP4
                # request cannot slice a shared dimension two different ways.
                with _dap4(session, url, ["/cell_lat[0:1:1623][0:1:0]"]) as f:
                    lats = f["cell_lat"][:, 0]
                with _dap4(session, url, ["/cell_lon[0:1:0][0:1:3855]"]) as f:
                    lons = f["cell_lon"][0, :]
                iy = np.where((lats >= bbox[0]) & (lats <= bbox[1]))[0]
                ix = np.where((lons >= bbox[2]) & (lons <= bbox[3]))[0]
                rows, cols = (int(iy.min()), int(iy.max())), (int(ix.min()), int(ix.max()))
                lat, lon = lats[rows[0]:rows[1] + 1], lons[cols[0]:cols[1] + 1]
                np.savez(grid_path, rows=rows, cols=cols, lat=lat, lon=lon)
        sl = f"[{rows[0]}:1:{rows[1]}][{cols[0]}:1:{cols[1]}]"

        def one(granule):
            with _dap4(session, _opendap_link(granule),
                       [f"/Geophysical_Data/sm_rootzone{sl}", f"/Geophysical_Data/sm_surface{sl}"]) as f:
                rz, sf = f["Geophysical_Data/sm_rootzone"][:], f["Geophysical_Data/sm_surface"][:]
            rz, sf = (np.where(a < 0, np.nan, a).astype(np.float32) for a in (rz, sf))
            return smap_point.granule_info(granule)[0], rz, sf

        with ThreadPoolExecutor(workers) as pool:
            results = sorted(pool.map(one, granules), key=lambda r: r[0])
        days = [pd.Timestamp(r[0].date()) for r in results]
        rz, sf = np.stack([r[1] for r in results]), np.stack([r[2] for r in results])
        np.savez_compressed(path, rootzone=rz, surface=sf, lat=lat, lon=lon, days=np.array([str(d.date()) for d in days]))
        print(f"SMAP {year}: {len(days)} days", flush=True)
        days_all += days
        roots.append(rz)
        surfs.append(sf)
    return pd.DatetimeIndex(days_all), np.concatenate(roots), np.concatenate(surfs), lat, lon


def smap_features(days, rootzone, surface, years):
    """Soil-moisture features per year from daily point series (m3/m3)."""
    rz, sf = pd.Series(rootzone, index=days), pd.Series(surface, index=days)
    rows = []
    for year in years:
        def window(s, m0, m1):
            w = s[(s.index >= pd.Timestamp(year, m0, 1)) & (s.index < pd.Timestamp(year, m1, 1) + pd.offsets.MonthEnd(0) + pd.Timedelta(days=1))]
            return w if w.notna().sum() >= 10 else None
        jun, ja, so, may = window(rz, 6, 6), window(rz, 7, 8), window(rz, 9, 10), window(rz, 5, 5)
        if jun is None or ja is None:
            continue
        rows.append({
            "year": year,
            "smap_rootzone_may": may.mean() if may is not None else np.nan,
            "smap_rootzone_jun": jun.mean(),
            "smap_rootzone_jul_aug": ja.mean(),
            "smap_rootzone_jul_aug_min": ja.min(),
            "smap_rootzone_sep_oct": so.mean() if so is not None else np.nan,
            "smap_surface_jul_aug": sf[ja.index].mean(),
        })
    return pd.DataFrame(rows)


def points_to_features(days, rootzone_pts, surface_pts, municipalities, years):
    parts = []
    for k, m in enumerate(municipalities[UNIT].itertuples(index=False)):
        f = smap_features(days, rootzone_pts[:, k], surface_pts[:, k], years)
        f["state_id"], f["mun_id"] = m.state_id, m.mun_id
        parts.append(f)
    return pd.concat(parts, ignore_index=True)
