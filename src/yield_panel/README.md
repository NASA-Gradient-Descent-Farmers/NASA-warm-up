# Yield panel

A **municipality × year × crop** panel for rainfed spring-summer crops in Mexico, and models that test whether NASA weather explains year-to-year yield and crop failure better than each municipality's average plus a trend.

Walkthrough: [`Notebooks/yield_panel.ipynb`](../../Notebooks/yield_panel.ipynb).

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

## Limitations

- POWER cells are coarse; farmland elevation can differ a lot from the cell's.
- SIAP's *temporal* label is municipal; some rainfed areas get supplemental water.
- No previous-crop information, so no rotation effects.
- SMAP and NDVI are not yet included (both need Earthdata).
