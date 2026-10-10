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

- Dates are `YYYY-MM-DD`. Each day has 8 granules (3-hourly, timestamps in UTC at the window center: 01:30, 04:30, ...).
- Each granule is a ~140 MB HDF5 file. The script **streams only the pixel it needs** (`earthaccess.open` + `h5py`) instead of downloading whole files. Long ranges still take a while (roughly a few seconds per granule).
- CMR returns several processing builds for the same timestamp (e.g. `Vv8010` and the reprocessed `Vv8012`). The script keeps only the latest build.
- Variables come from the `Geophysical_Data` group: `sm_surface`, `sm_rootzone`, `sm_profile` (m³/m³), `surface_temp` (K). Fill values (`-9999`) become `NaN`.
- NSIDC notice: SMAP products had a geolocation issue from 14 May to 28 July 2026, and that period is being reprocessed. Avoid it, or re-pull it later.

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

- Downloads 7 ARC/INFO ASCII grids (~31 MB each, ~220 MB total) once into `data/igbp/`, then reads the cell containing each site.
- All layers are for the **0-100 cm** soil depth. Soil carbon density is in kg/m². ⚠️ The other units (expected: field capacity, wilting point and PAWC in mm of water; bulk density in g/cm³; total N in g/m²) are documented in `comp/readme.txt`, which sits behind the Earthdata login. Confirm them after the first download.
- Underlying data are from 1950-1996 (static soil properties).

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
