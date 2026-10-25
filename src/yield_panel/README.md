# Yield panel

A **municipality × year × crop** panel for rainfed spring-summer crops in Mexico, and models that test whether NASA weather explains year-to-year yield and crop failure better than each municipality's average plus a trend.

Walkthroughs:
- [`Notebooks/yield_panel.ipynb`](../../Notebooks/yield_panel.ipynb): the panel, the bar, POWER-only models.
- [`Notebooks/yield_panel_sources.ipynb`](../../Notebooks/yield_panel_sources.ipynb): adds IMERG, CHIRPS, MODIS NDVI, SMAP and IGBP, the ablation, and the SIAP district check.
- [`Notebooks/yield_planning.ipynb`](../../Notebooks/yield_planning.ipynb): all of Mexico, SIAP back to 1980, the pre-season planning model and a 2026 outlook.

**Start from the shared data package** (`python -m src.yield_panel.share export` makes it; ~50 MB of Parquet) to skip every download. See [Shared data](#shared-data).

## Data

| Piece | Source | Notes |
|---|---|---|
| Outcomes | [SIAP municipal statistics](https://nube.agricultura.gob.mx/datosAbiertos/Agricola.php), one national file per year (2003 on) | Filtered to *Primavera-Verano*, *temporal*. `yield_t_ha` = production ÷ harvested area; `failure_rate` = lost ÷ sown area |
| Municipality points | `municipalities.csv`: INEGI catalogue of localities ([via this repo](https://github.com/eduardoarandah/coordenadas-estados-municipios-localidades-de-mexico-json), 2018 extract) | Median position and altitude of each municipality's rural localities (the seat when there are fewer than 3). Municipalities created after 2018 are missing and reported by `build.py` |
| Weather | NASA POWER daily, one request per grid cell (municipalities in the same ~55 × 65 km cell share it) | 16 season features per year (`weather.WEATHER_FEATURES`), May-October season plus the previous Nov-Apr rain |
| Soils | GLDAS texture, sand/silt/clay, porosity | Static; used only by the boosted model (fixed effects absorb anything constant) |

Build it (cached under `data/`):

```bash
python -m src.yield_panel.build                         # central Mexico (11 states), 2003-2025
python -m src.yield_panel.build --states all --crops maize bean sorghum
```

## Models (`models.py`)

| Model | What it predicts for municipality *m* in year *t* |
|---|---|
| `mean` | *m*'s training average |
| `mean_trend` | *m*'s own level + one shared trend: **the bar** |
| `fe_weather` | bar + linear weather effects, fixed-effects ("within") regression with squared rain, degree-day and Tmax terms |
| `gbm_weather` | bar + gradient boosting on the leftover, from weather anomalies, location, altitude, soil and *m*'s level |

**Evaluation:** expanding window, one year ahead. Each test year is predicted from earlier years only, and all models are scored on the same rows. Skill = 1 − RMSE / RMSE(bar). The bootstrap resamples whole test years, since municipalities in a year share related weather shocks. `tests/test_yield_panel.py` checks that tampering with future years leaves predictions unchanged.

**What a win means:** the model has learned the weather → outcome response, so it can replay past or scenario seasons for a municipality (`risk_profile`). It uses the realized season's weather, so it is **not a pre-season forecast**.

## More sources (`gridded.py`, `enrich.py`, `ablation.py`)

Each one is pulled as a box over the panel (server-side subsetting where available), cached under `data/`, and averaged around each municipality point:

| Source | Product | Grid | Years | Sampling |
|---|---|---|---|---|
| IMERG | GPM_3IMERGDF v07 (Final); Late Run (GPM_3IMERGDL) where the Final Run has not been released (after 2025-09-30 as of Oct 2026) | 0.1° daily | 2002- | 15 km mean |
| CHIRPS | v2.0 daily, HTTP range reads of the annual netCDF | 0.05° | 2002- | 10 km mean |
| MODIS | MOD13C2 v061 monthly NDVI/EVI, weighted by MCD12C1 v061 cropland share (IGBP 12 + half of 14) | 0.05° | 2003- | 15 km |
| SMAP | SPL4SMGP v008 root-zone and surface moisture, the 13:30 UTC granule each day | 9 km | 2015-04- | 10 km mean |
| IGBP-DIS | field capacity, wilting point, available water, bulk density, soil C and N | ~9 km | static | point |

```bash
export EARTHDATA_TOKEN=...                      # urs.earthdata.nasa.gov -> Generate Token; never commit it
python -m src.yield_panel.enrich                # ~30 min of downloads the first time, then ~4 min
python -m src.yield_panel.ablation              # ~35 min; CSVs in data/yield_panel/ablation/
```

### Findings (central Mexico, maize, bean, sorghum; test years 2014-2025)

- **Better rain does not help.** IMERG and CHIRPS agree with POWER only moderately (year-to-year correlation within municipalities 0.71-0.78), yet swapping or adding them changes skill by about ±1 point, never significantly.
- **NDVI helps failure, not yield.** For maize failure rate, POWER + NDVI reaches +8.8% skill at municipality level with a bootstrap interval above zero. NDVI partly measures the outcome (failed fields are less green), so it supports in-season monitoring, not pre-season choices.
- **SMAP (2015+) and IGBP soils add nothing** measurable on this design.
- **Much of the municipal variation is SIAP district reporting.** Within the same POWER cell and year, the bar's residuals correlate about 0.6 between municipalities of the same district (DDR), against 0.05-0.18 for yield (0.22-0.29 for failure) between municipalities of different districts. About a third of yields are exactly identical to another municipality's in the same district-year.
- **At district level the models do better.** Aggregating to SIAP districts (the unit the numbers are effectively estimated at), maize failure with POWER + NDVI reaches +21% skill (interval above zero), and POWER alone +13% (interval touching zero). Bean and sorghum still do not beat the bar.

## Limitations

- POWER cells are coarse; farmland elevation can differ a lot from the cell's.
- SIAP's *temporal* label is municipal; some rainfed areas get supplemental water.
- Municipal SIAP values are partly district estimates; treat districts as the unit of observation.
- No previous-crop information, so no rotation effects.

## All of Mexico (2,211 municipalities, 31 states)

`python -m src.yield_panel.build --states all` then `enrich` and `ablation` on the national panel. Gridded sources are read and sampled one year at a time (a national IMERG year is ~90 MB, CHIRPS ~340 MB), so memory stays bounded (the workspace this was built on had 8 GB).

Nationally, more results clear the bar (95% interval above zero, test years 2014-2025):

| Level | Crop | Target | Best significant set | Skill |
|---|---|---|---|---|
| District | maize | failure | POWER + NDVI | +17% |
| District | maize | failure | POWER only (weather) | +12% |
| District | bean | failure | POWER + NDVI / POWER only | +13% / +11% |
| District | sorghum | failure | POWER + IMERG | +6% |
| Municipality | bean | failure | POWER + NDVI / POWER only | +11% / +9% |
| Municipality | maize | failure | POWER + NDVI | +7% |

Yield still does not beat the bar except bean (+2-3%). The SIAP district pattern holds nationally: within the same weather cell, residual correlation is 0.46-0.64 between municipalities of the same district versus 0.06-0.29 across districts, and 31-39% of yields are exact copies within a district-year.

## Longer history (`historic.py`)

SIAP's open municipal files start in 2003. The archived annual files (formerly sagarpa.gob.mx, mirrored on [datamx.io](https://datamx.io/dataset/estadistica-agropecuaria)) add districts for 1999-2002 and states for 1980-2002; district codes match the 2003+ files. Crop names changed over time ("MAIZ GRANO SIN CLASIFICAR", "MAIZ GRANO (AMARILLO)"; seed, forage and popcorn variants excluded), and variety rows are additive. National rainfed maize area joins smoothly at both seams (6.76 → 6.91 Mha in 1998/99, 6.58 → 6.53 in 2002/03).

District and state features are sown-area-weighted averages of municipality features, with each municipality's mean 2003-2025 sown area as a fixed weight. With realized-season weather, the long district panel (training from 1999) confirms the failure results: maize +9-10%, bean +9%, sorghum +5%, all significant.

## Planning model (`planning.py`, `plan_build.py`)

Only information available by April 30: ocean indices (ONI, Nino 3.4, tropical North Atlantic, PDO from NOAA; AMO left out because its series lags), the indices interacted with latitude, longitude, altitude and typical rain, pre-season POWER weather (Nov-Apr rain, Mar-Apr rain, temperature, humidity), last season's weather, last season's yield and failure, and Mar-Apr NDVI.

```bash
python -m src.yield_panel.plan_build build       # municipal 2003-2025, district 1999-2025, state 1982-2025
python -m src.yield_panel.plan_build evaluate    # ~40 min with OMP_NUM_THREADS=1 on 2 cores
python -m src.yield_panel.plan_build outlook     # 2026 district outlook (fetches Nov 2025-Apr 2026 POWER)
```

Findings (states tested on 31 years, districts 16, municipalities 12):

- **Ocean indices never beat the bar**, for any crop, target or level, even with 31 test years. The national failure years do cluster in La Nina springs (2009, 2011), but this does not translate into skill one year ahead at state or district level.
- **Pre-season weather and NDVI do not help either**, except pre-season weather for state maize yield (+9%).
- **Last season's yield predicts this season's yield**: maize +18-31%, bean +2-9%, sorghum +7-12%, significant at every level. The bar's straight-line trend misses slow shifts in yield level; part of this persistence is SIAP's own reporting.
- **Nothing known before sowing predicts failure risk.** For failure, the honest pre-season answer is each unit's own history.

`plan_build.outlook` therefore uses, for each crop and target, the most skilful planning set whose interval stayed above zero, and the bar when none did. For 2026 that means yield from last season's outcome (10-90% ranges narrower than the bar's: maize by ~23%, bean and sorghum by ~12%) and failure risk from history. NASA GEOS-S2S seasonal forecasts (in the NMME archive at the IRI Data Library) are the natural next input; the library now requires a free account.

## Shared data

```bash
python -m src.yield_panel.share export    # data/shared/*.parquet + manifest.json (row counts, columns, sha256)
python -m src.yield_panel.share check     # verify checksums after unzipping
```

```python
from src.yield_panel import share
panel = share.load("panel_national")      # also: panel_central, districts_1999_2025, states_1980_2025,
                                          # power_municipal_1982_2025, chirps_municipal_1999_2025,
                                          # planning_municipal / _district / _state, climate_indices
```

Raw caches (gridded boxes, POWER cells, SIAP annual files; ~3.5 GB for central + national) are not in the package; every step re-creates them on demand.
