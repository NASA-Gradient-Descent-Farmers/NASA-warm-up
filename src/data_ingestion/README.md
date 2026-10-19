# Data Ingestion

One script per data source. Each script:

1. **Tests the connection** to the source (prints `[OK]` / `[FAIL]`).
2. **Pulls data** for a point (time series) or a set of sites (static soil layers).
3. **Previews the first 5 records** (`--rows N` to change), and optionally saves a CSV (`--out data/<name>.csv`).

The functions inside each script (`test_connection`, `fetch_*` / `search_granules`, `extract_*`, `to_dataframe`) are importable, so the scripts can be combined into one pipeline later.

| Source | Script | What it gives | Resolution | Login needed |
|---|---|---|---|---|
| [NASA POWER](https://power.larc.nasa.gov/docs/services/api/temporal/daily/) | `power.py` | Daily weather: temperature, precipitation, humidity, wind, solar radiation | 0.5° x 0.625° (meteo), 1° (solar) | No |
| [SMAP L4 SPL4SMGP v8](https://nsidc.org/data/spl4smgp/versions/8) | `smap.py` | 3-hourly surface (0-5 cm), root-zone (0-100 cm) and profile soil moisture, surface temperature | 9 km | **Yes** (to read values) |
| [GLDAS soils](https://ldas.gsfc.nasa.gov/gldas/soils) | `gldas_soils.py` | Soil texture class, sand/silt/clay fractions, porosity (static) | 0.25° | No |
| [IGBP-DIS soils (ORNL DAAC 569)](https://doi.org/10.3334/ORNLDAAC/569) | `igbp_soils.py` | Field capacity, wilting point, available water capacity, bulk density, soil C and N, thermal capacity (static, 0-100 cm) | 5 arc-min (~9 km) | **Yes** (to download) |

`common.py` holds shared helpers: the 5 sample farm sites used for previews, the Earthdata login, and the nearest-grid-cell lookup.

---

## Setup

From the repo root:

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### NASA Earthdata login (SMAP and IGBP)

1. Create a free account at [urs.earthdata.nasa.gov](https://urs.earthdata.nasa.gov/users/new).
2. Save your credentials once to `~/.netrc` (you'll be prompted for username and password):

   ```bash
   python -c "import earthaccess; earthaccess.login(strategy='interactive', persist=True)"
   ```

   Or set environment variables instead: `EARTHDATA_USERNAME` and `EARTHDATA_PASSWORD` (or `EARTHDATA_TOKEN`).

The scripts never prompt for a password. Without a login, `smap.py` and `igbp_soils.py` still test the connection and search NASA CMR, and preview granule metadata instead of values.

---

## Usage

Run everything **from the repo root** with `python -m`:

```bash
python -m src.data_ingestion.power
python -m src.data_ingestion.smap
python -m src.data_ingestion.gldas_soils
python -m src.data_ingestion.igbp_soils
```

### POWER: daily weather (`power.py`)

```bash
python -m src.data_ingestion.power --lat 20.52 --lon -100.82 --start 20240101 --end 20241231 --time-standard UTC --out data/power.csv
```

- Endpoint `/api/temporal/daily/point`, community `AG` (agroclimatology).
- Dates are `YYYYMMDD`. Data runs from 1981-01-01 to near real time.
- `--time-standard` is `LST` (local solar time, the API default) or `UTC`. Use `UTC` when joining with SMAP.
- Missing values (`-999`) become `NaN`.
- API limits: at most 20 parameters per point request. Don't hammer the same grid cell repeatedly, because NASA may block the client.

### SMAP L4: soil moisture (`smap.py`)

```bash
python -m src.data_ingestion.smap --lat 20.52 --lon -100.82 --start 2024-07-01 --end 2024-07-07 --out data/smap.csv
```

- Dates are `YYYY-MM-DD`. Each day has 8 granules. Each value is the **average over a 3-hour window**, and the timestamp is the window's center in UTC (01:30 = 00:00-03:00 UTC, 04:30, ...).
- **Speed:** each granule is a ~140 MB HDF5 file in which every variable is one compressed block for the whole globe, so even streaming one pixel downloads ~4 MB per variable (~25 s per granule). Instead, the script asks NASA's **OPeNDAP** server for only the pixel and runs 16 requests in parallel (`--workers`): a week takes ~30 s, a year ~6 min. If OPeNDAP fails for a granule after 3 tries, it falls back to streaming that granule's HDF5 (`earthaccess.open` + `h5py`).
- OPeNDAP returns values rounded to 6 significant digits (e.g. `0.25712` instead of `0.2571201`), far finer than the product's accuracy (see [Reliability](#reliability-and-limitations)).
- The pixel is the 9 km cell whose center is nearest to the point; the output shows its center coordinates. It's found once per run (~6 s) because the grid is the same in every granule.
- CMR returns several processing builds for the same timestamp (e.g. `Vv8010` and the reprocessed `Vv8012`). The script keeps only the latest build.
- Default variables: `sm_surface`, `sm_rootzone`, `sm_profile` (m³/m³), `surface_temp` (K). Pick any of the 45 in [SMAP variables](#smap-variables) with `--variables`, e.g. `--variables sm_rootzone sm_rootzone_pctl precipitation_total_surface_flux`. A misspelled name fails with the list of valid ones. Fill values (`-9999`) become `NaN`.
- NSIDC notice: SMAP products had a geolocation issue from 14 May to 28 July 2026, and that period is being reprocessed. Avoid it, or re-pull it later.

In Python:

```python
from src.data_ingestion import smap
from src.data_ingestion.common import earthdata_login

earthdata_login()
granules = smap.search_granules(20.52, -100.82, "2024-01-01", "2024-12-31")
df, units, pixel = smap.extract_point(granules, 20.52, -100.82, variables=["sm_rootzone", "precipitation_total_surface_flux"])
```

### GLDAS: soil parameters (`gldas_soils.py`)

```bash
python -m src.data_ingestion.gldas_soils --site 20.52,-100.82 --site 42.03,-93.47 --out data/gldas_soils.csv
```

- Downloads three small netCDF4 files (< 2 MB total) once into `data/gldas/`: soil texture (`GLDASp5_soiltexture_025d.nc4`), sand/silt/clay fractions (`GLDASp4_soilfraction_025d.nc4`) and porosity (`GLDASp5_porosity_025d.nc4`).
- The grid covers 60°S to 90°N at 0.25°. Values come from the nearest cell (`grid_lat`/`grid_lon` columns show which one).
- Texture uses the Noah/FAO 16-class codes (1 Sand, 2 Loamy Sand, 3 Sandy Loam, 4 Silt Loam, 5 Silt, 6 Loam, 7 Sandy Clay Loam, 8 Silty Clay Loam, 9 Clay Loam, 10 Sandy Clay, 11 Silty Clay, 12 Clay, 13 Organic, 14 Water, 15 Bedrock, 16 Other). The codes are stored as floats with rounding noise, so the script rounds them.
- Fractions and porosity are unitless (0-1).

### IGBP-DIS: soil hydraulic and chemical properties (`igbp_soils.py`)

```bash
python -m src.data_ingestion.igbp_soils --site 20.52,-100.82 --out data/igbp_soils.csv
```

- Downloads 7 ARC/INFO ASCII grids (~31 MB each, ~220 MB total, ~30 s) once into `data/igbp/`, then reads the cell containing each site.
- All layers are for the **0-100 cm** soil depth. Units, from the dataset's public companion files ([`comp/`](https://data.ornldaac.earthdata.nasa.gov/public/global_soil/IGBP-SurfaceProducts/comp/readme.txt)):

  | Column | Units | Notes |
  |---|---|---|
  | `field_capacity` | mm of water in 0-100 cm | at -10 kPa. Divide by 1000 for m³/m³ (comparable to SMAP `sm_rootzone`) |
  | `wilting_point` | mm of water in 0-100 cm | at -1500 kPa. Divide by 1000 for m³/m³ |
  | `profile_available_water_capacity` | mm | field capacity minus wilting point: the water plants can use |
  | `bulk_density` | g/cm³ | |
  | `soil_carbon_density` | kg/m² | |
  | `total_nitrogen_density` | g/m² | |
  | `thermal_capacity` | MJ/m³/K | of dry soil. The companion file says J/m³/K, but values range 0-2.02, which only makes sense in MJ |

- The grid is 4320 x 1686 cells of 1/12° (~9 km), from 56.5°S to 84°N. `NODATA` is `-2` and becomes `NaN`.
- Underlying data are from 1950-1996 (static soil properties), estimated from the FAO-UNESCO Soil Map of the World and a global database of soil profiles. Values change little between regions; see [Reliability](#reliability-and-limitations).

---

## Original formats

| Source | Format as NASA serves it | Grid | Time |
|---|---|---|---|
| POWER | JSON from a web API: `properties.parameter.<VAR>.<YYYYMMDD> = value`, fill `-999` | 0.5° x 0.625° (~50 km) weather, 1° solar | Daily |
| SMAP L4 | HDF5 (`.h5`), ~140 MB per granule, one granule per 3-hour window for the whole globe. Each variable is a 1624 x 3856 float32 array in `Geophysical_Data/`; `cell_lat` / `cell_lon` give each cell's center. Fill `-9999`. Each granule also has a `.qa` report and an `.iso.xml` metadata file | EASE-Grid 2.0, 9 km equal-area, ~85°S-85°N | 3-hourly averages |
| GLDAS soils | netCDF4 (HDF5 underneath), three small files; each variable has shape `(1, 600, 1440)` (one time step x lat x lon), fill `-9999` | 0.25° regular lat/lon, 60°S-90°N | Static |
| IGBP-DIS | ARC/INFO ASCII grid (`.dat`): a 6-line text header (`ncols`, `nrows`, `xllcorner`, `yllcorner`, `cellsize`, `NODATA_value`) then the values row by row from the north | 1/12° (~9 km), 56.5°S-84°N | Static |

### SMAP variables

SMAP L4 is not a raw satellite image: NASA runs a land-surface model driven by observed weather and keeps correcting it with SMAP's microwave measurements. That's why it has no gaps and can estimate the root zone, which the satellite can't see. All 45 variables in `Geophysical_Data`:

| Group | Variables | Units | Meaning |
|---|---|---|---|
| Soil moisture | `sm_surface` (0-5 cm), `sm_rootzone` (0-100 cm), `sm_profile` (surface to bedrock) | m³/m³ | Volume of water per volume of soil |
| | `sm_surface_wetness`, `sm_rootzone_wetness`, `sm_profile_wetness` | 0-1 | 0 = completely dry, 1 = saturated, on the model's own soil scale |
| | `sm_rootzone_pctl`, `sm_profile_pctl` | % | Percentile against the model's climatology at that cell; low = drought |
| Temperature | `surface_temp`, `soil_temp_layer1` ... `soil_temp_layer6` (shallow to deep) | K | Subtract 273.15 for °C |
| Water fluxes | `precipitation_total_surface_flux`, `snowfall_surface_flux`, `land_evapotranspiration_flux`, `soil_water_infiltration_flux`, `overland_runoff_flux`, `baseflow_flux`, `snow_melt_flux`, `free_surface_water_on_peat_flux` | kg m⁻² s⁻¹ | Rates. x 10800 = mm per 3-hour window; a daily mean x 86400 = mm/day |
| Energy | `heat_flux_latent`, `heat_flux_sensible`, `heat_flux_ground`, `net_downward_shortwave_flux`, `net_downward_longwave_flux`, `radiation_shortwave_downward_flux`, `radiation_longwave_absorbed_flux` | W/m² | Sunlight in, and heat used for evaporation, warming air and warming soil |
| Land state | `land_fraction_saturated`, `land_fraction_unsaturated`, `land_fraction_wilting`, `land_fraction_snow_covered` | 0-1 | Share of the cell saturated, normal, at wilting point, or under snow |
| Vegetation | `leaf_area_index` (m²/m²), `vegetation_greenness_fraction` (0-1), `mwrtm_vegopacity` (unitless) | | Leaf area, share of green leaves, how much vegetation blocks the microwave signal |
| Snow and groundwater | `snow_mass` (kg/m²), `snow_depth` (m), `depth_to_water_table_from_surface` (m) | | |
| Air near the ground | `temp_lowatmmodlay` (K), `specific_humidity_lowatmmodlay` (kg/kg), `windspeed_lowatmmodlay` (m/s), `surface_pressure` (Pa), `height_lowatmmodlay` (m) | | Weather that drives the model, at its lowest atmospheric layer |

---

## Reliability and limitations

**Short version:** SMAP L4 is a validated NASA product, and the checks below show the pipeline reads it correctly and that it behaves physically at a real farm site. It's good for exploration, features and models of *regional* soil conditions and their changes. It is not a field sensor: for field-level decisions, check it against local measurements.

**Published accuracy.** Against in-situ sensors at NASA's core validation sites, L4 soil moisture had an unbiased RMSE of **0.038 m³/m³ (surface)** and **0.030 m³/m³ (root zone)** at 9 km, meeting the mission target of 0.04 ([Reichle et al. 2017](https://doi.org/10.1175/JHM-D-17-0063.1); that study used an earlier version, and we didn't find published figures for version 8). "Unbiased" means a constant offset is removed first, so day-to-day changes are more trustworthy than the absolute level.

**What we checked** (Celaya, all of 2024, 2,928 time steps):

| Check | Result |
|---|---|
| OPeNDAP values vs direct HDF5 reads | Identical to 6 significant digits (56 time steps) |
| Pixel lookup vs a full 2-D nearest search | Same cell at all 5 sample sites; cell centers 2.8-4.8 km from the point |
| Completeness | 2,928 / 2,928 steps, no duplicates, no gaps in moisture or temperature |
| Physical range | `sm_surface` 0.11-0.47, `sm_rootzone` 0.23-0.45 m³/m³ |
| SMAP's rain input vs POWER rain | Annual 728 vs 727 mm; daily correlation 0.69; agree on rain vs no rain (>1 mm) on 94% of days |
| Soil moisture reacts to POWER rain | `sm_surface` rises 0.019 m³/m³ on average on days with >5 mm, falls 0.003 on dry days |
| Seasonal cycle | Root zone ~0.23 in the April-May dry season, ~0.39 in the July-September rainy season |
| SMAP land surface temp vs POWER air temp | Monthly correlation 0.99 |

The rain comparison is between two different NASA processing chains, not two independent rain gauges, so it confirms consistency rather than ground truth.

**Limitations to keep in mind:**

- **9 km, not a field.** The pixel averages fields, roads and towns. Treat differences smaller than ~0.03-0.04 m³/m³ (the error above) as noise when comparing absolute values between sites.
- **The root zone is modeled.** The satellite only senses the top ~5 cm; root-zone and profile moisture come from the model, constrained by those surface observations.
- **Percentiles have big gaps.** `sm_rootzone_pctl` and `sm_profile_pctl` were `-9999` (missing) for about a third of 2024 at Celaya, in long dry-season blocks (Jan 1-27, Apr 2-Jun 3, Nov 30-Dec 31). This is in NASA's files, not a pipeline bug. Check coverage before using them; `*_wetness` had no gaps.
- **Soil descriptions differ between products** (see [Using the data](#using-the-data-for-exploration-and-models)).
- **2026 reprocessing.** Data from 14 May to 28 July 2026 had a geolocation error and is being replaced ([NSIDC notice](https://nsidc.org/data/user-resources/data-announcements/user-notice-smap-data-reprocessing)).
- **POWER** is a ~50 km model of the weather, not a weather station.
- **Static soils are coarse.** GLDAS porosity is assigned by texture class (every "Loam" cell has 0.437). IGBP comes from 1950-1996 soil surveys and varies little: field capacity is 375-419 mm at all 5 sample sites, on 3 continents. Use them as context, not field truth.

---

## Using the data for exploration and models

Run Python from the repo root so `src` is importable. From a notebook in `Notebooks/`, add the repo root first:

```python
import sys; sys.path.insert(0, "..")
```

A daily table for one site, joining all four sources (tested; a year takes ~7 min, mostly SMAP):

```python
from src.data_ingestion import gldas_soils, igbp_soils, power, smap
from src.data_ingestion.common import earthdata_login

lat, lon = 20.52, -100.82
start, end = "2024-01-01", "2024-12-31"
earthdata_login()

# Daily weather, in UTC days to line up with SMAP.
weather = power.to_dataframe(power.fetch_daily_point(lat, lon, start.replace("-", ""), end.replace("-", ""),
                                                     time_standard="UTC"))

# 3-hourly SMAP -> daily means (3-hour windows never cross midnight UTC).
granules = smap.search_granules(lat, lon, start, end)
sm, units, pixel = smap.extract_point(granules, lat, lon,
                                      variables=["sm_surface", "sm_rootzone", "sm_rootzone_wetness",
                                                 "precipitation_total_surface_flux"])
sm_daily = sm.resample("D").mean()
sm_daily["smap_precip_mm"] = sm_daily.pop("precipitation_total_surface_flux") * 86400  # mean rate -> mm/day

# Static soil properties for the site, repeated on every day.
site = [("Celaya", lat, lon)]
gldas_soils.download()
igbp_soils.download(igbp_soils.search_granules())
soil = gldas_soils.extract_points(site).iloc[0]
igbp = igbp_soils.extract_points(site).iloc[0]

features = weather.join(sm_daily, how="inner")
features["porosity"] = soil["porosity"]
features["field_capacity"] = igbp["field_capacity"] / 1000  # mm in 0-100 cm -> m3/m3
features["wilting_point"] = igbp["wilting_point"] / 1000
features.to_csv("data/features_celaya_2024.csv")
```

Things to get right:

- **Time zones.** SMAP is UTC. Pull POWER with `time_standard="UTC"` (`--time-standard UTC`) so a "day" means the same 24 hours in both. Celaya is UTC-6, so a UTC day runs 18:00-18:00 local.
- **States vs rates.** Average states (moisture, temperature) over a day; convert rates (kg m⁻² s⁻¹) to mm before summing.
- **Different scales.** POWER is ~50 km, GLDAS ~25 km, SMAP and IGBP ~9 km. None of them sees a single field: treat values as the regional conditions around the farm.
- **Don't mix soil scales naively.** Each product describes the soil differently. At Celaya, SMAP's own model implies a porosity of ~0.52 (`sm_rootzone / sm_rootzone_wetness`), while GLDAS says 0.437 and IGBP's field capacity is 0.414. For crop water stress, prefer SMAP's own `*_wetness`, `*_pctl` or `land_fraction_wilting`, or normalize SMAP moisture per site (e.g. min-max over several years), rather than comparing SMAP m³/m³ directly with IGBP field capacity and wilting point.
- **Features aren't independent.** SMAP root-zone moisture, evapotranspiration and percentiles are model outputs driven by precipitation, so they're strongly correlated with rain features. That's fine for prediction, but keep it in mind when reading feature importance, and only use values available at prediction time (no future SMAP days in a feature window).
- **Cache pulls.** Save each pull with `--out` / `to_csv` under `data/` (git-ignored) and load the CSV in notebooks instead of re-pulling.

---

## Sample sites

Previews default to these agricultural sites (defined in `common.py`):

| Site | Lat | Lon |
|---|---|---|
| Ames, IA (US Corn Belt) | 42.03 | -93.47 |
| Fresno, CA (Central Valley) | 36.74 | -119.79 |
| Celaya, GTO (Bajío, MX) | 20.52 | -100.82 |
| Pergamino (Pampas, AR) | -33.89 | -60.57 |
| Ludhiana (Punjab, IN) | 30.90 | 75.85 |

## Adding a new source

Create `src/data_ingestion/<source>.py` following the same pattern:

- A module docstring with the dataset link and usage.
- `test_connection()` that returns `True`/`False` and prints `[OK]`/`[FAIL]`.
- A fetch/search function, plus one that returns a tidy `pandas.DataFrame` (dates or sites as the index, fill values set to `NaN`).
- `main()` with `--rows` (default 5) and `--out`.
- Put downloads under `data/<source>/`, which is git-ignored.

Then add a row to the table at the top of this file.
