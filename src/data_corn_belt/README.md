# Corn Belt point data

Point selected for the first exploratory analysis: Ames, Iowa (42.03°N, 93.47°W),
the Corn Belt reference site already listed in `src/data_ingestion/common.py`.

The point-level tables produced for the EDA are:

| File | Source | Coverage / resolution |
|---|---|---|
| `power_ames_2005_2025.csv` | NASA POWER, agroclimatology | Daily, 2005-01-01 through 2025-12-31, UTC (full original range) |
| `power_ames_2015_2025.csv` | NASA POWER, agroclimatology | Daily analysis slice, 2015-03-31 through 2025-12-31, UTC |
| `smap_ames_2015_2025.csv` | SMAP L4 SPL4SMGP v008 | 3-hourly, 2015-03-31 through 2025-12-31; nearest 9 km pixel |
| `smap_ames_2024.csv` | SMAP L4 SPL4SMGP v008 | Original 2024-only extract, retained for reference |
| `gldas_soils_ames.csv` | GLDAS soils | Static values at the nearest 0.25° cell |
| `igbp_soils_ames.csv` | IGBP-DIS / ORNL DAAC 569 | Static 0-100 cm values at the containing ~9 km cell |
| `corn_belt_daily_2015_2025.csv` | Combined POWER, SMAP, GLDAS, IGBP | One daily row on the common 2015-03-31–2025-12-31 axis |

SMAP SPL4SMGP starts on **2015-03-31**, so the common analysis period starts then,
not on January 1, 2015. The combined daily table averages SMAP's eight 3-hourly
observations per day, joins daily POWER, and repeats the static soil attributes as
context. Its soil columns are not daily soil measurements. The original 2005–2025 POWER
file and original static-soil files are kept unchanged.

These are compact, extracted point data intended for analysis. GLDAS and IGBP source
grids are global and remain in the download cache under the repository's git-ignored
`data/gldas/` and `data/igbp/` directories; they are not duplicated here. The SMAP
reader requests the selected pixel from NASA OPeNDAP and only falls back to streaming
granules when that service is unavailable.

The EDA notebook is `Notebooks/corn_belt/01_data_eda.ipynb`. The point is a regional
representative, not a field boundary; global soil products and SMAP should not be
treated as field measurements. IGBP soil layers are static estimates from an older
global soil database.

## Current download status

- POWER (2005–2025): downloaded to `power_ames_2005_2025.csv` (7,670 daily rows).
- POWER analysis slice (2015-03-31–2025-12-31): `power_ames_2015_2025.csv` (3,929 daily rows).
- SMAP (2015-03-31–2025-12-31): `smap_ames_2015_2025.csv` (31,432 3-hourly rows); nearest
  9 km pixel center is 42.043°N, 93.501°W. All included dates have eight values per day.
- Combined analysis table: `corn_belt_daily_2015_2025.csv` (3,929 daily rows), with
  SMAP daily means and static GLDAS/IGBP soil context attached.
- The earlier 2024-only SMAP extract remains at `smap_ames_2024.csv` (2,928 rows).
- GLDAS: downloaded and extracted to `gldas_soils_ames.csv`; nearest 0.25° cell center
  is 42.125°N, 93.375°W.
- IGBP: downloaded and extracted to `igbp_soils_ames.csv` (seven static soil properties).

Annual SMAP point-download checkpoints are stored under the git-ignored
`data/smap_ames_chunks/` directory; the source-resolution 2015–2025 extract is the
combined CSV in this folder.

The SMAP downloader now reads the small coordinate vectors and variable metadata via
OPeNDAP before requesting point values. This avoids opening a global HDF5 granule just
to locate the pixel. Earthdata authentication is required for SMAP and IGBP.
