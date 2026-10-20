# Crop Models

`wofost_rotations.py` simulates **seasonal crop rotations for rainfed farms in central Mexico** with [WOFOST 8.1](https://www.wur.nl/en/research-results/research-institutes/environmental-research/facilities-tools/software-models-and-databases/wofost.htm), through the Python package [PCSE](https://pcse.readthedocs.io/). It models water, **nitrogen**, **frost** and **drought**, and uses the data from `src/data_ingestion/`:

| Input | Source |
|---|---|
| Daily weather (temperature, rain, radiation, humidity, wind, reference ET) | NASA POWER, downloaded by PCSE |
| Field capacity, wilting point (0-100 cm) | IGBP-DIS (`igbp_soils.py`) |
| Soil N mineralization | IGBP-DIS total soil nitrogen (`igbp_soils.py`) |
| Porosity | GLDAS (`gldas_soils.py`) |
| Soil moisture check | SMAP L4 `sm_rootzone` (`smap.py`), optional |
| Crop parameters | [WOFOST_crop_parameters](https://github.com/ajwdewit/WOFOST_crop_parameters), downloaded by PCSE |

The full method, equations and assumptions are in the technical report: [`docs/technical_report/main.tex`](../../docs/technical_report/main.tex).

## Run it

From the repo root (needs `pip install -r requirements.txt` and, the first time, the Earthdata login for the IGBP download):

```bash
python -m src.crop_models.wofost_rotations                                     # Texcoco, 2005-2025, all rotations
python -m src.crop_models.wofost_rotations --out data/rotations/baseline.csv
python -m src.crop_models.wofost_rotations --rain-factor 0.7                   # 30% less rain all year
python -m src.crop_models.wofost_rotations --rain-factor 0.5 --rain-months 7 8 # stronger canícula (Jul-Aug)
python -m src.crop_models.wofost_rotations --frost-tmin-offset -2              # valley nights 2 °C colder than POWER
python -m src.crop_models.wofost_rotations --n-scale 0                         # no fertilizer
python -m src.crop_models.wofost_rotations --sowing fixed                      # sow on fixed dates, not at rain onset
python -m src.crop_models.wofost_rotations --smap data/smap_texcoco_2023_2024.csv  # compare soil moisture with SMAP
```

All four rotations over 21 seasons at three production levels take ~2 minutes. The default site is CIMMYT's El Batán research station in Texcoco (19.53°N, 98.85°W, ~2,250 m), northeast of Mexico City.

## What it simulates

**Three production levels per season** (yield gap analysis):

| Level | Column | Meaning |
|---|---|---|
| Potential | `yield_potential_t_ha` | Only temperature, sunlight and CO₂ limit the crop |
| Water-limited | `yield_water_t_ha` | Rainfed, unlimited nitrogen |
| Water- and N-limited | `yield_water_n_t_ha` | Rainfed, with the fertilizer below: **the main result** |

**Mexican context** added on top of WOFOST:

- **Rainfed sowing**: crops are sown on the first day from their earliest date with ≥20 mm of rain over the previous 5 days (sown anyway after 45 days). `--sowing fixed` sows on the earliest date.
- **Fertilizer**: maize 160 kg N/ha (80 at sowing + 80 at day 40), the highest dose tested on rainfed hybrids at INIFAP's Texcoco station ([Alonso-Sánchez et al. 2023](https://doi.org/10.28940/terra.v41i0.1577)). Barley 60 and faba bean 40 kg N/ha are assumptions. Half of fertilizer N is assumed lost (recovery 0.5).
- **Soil N supply**: 0.5% per year of the IGBP total soil N in 0-100 cm (64 kg N/ha per season at Texcoco), released March-July.
- **Legumes fix N**: faba bean covers 80% of its N demand from the air (WOFOST parameter `NFIX_FR`).
- **Rotations interact through water and N**: each season (March 1 to end of February) starts from the soil water and mineral N left by the previous one. Half of leftover mineral N is lost before the next crop; half of the N in roots and dead leaves becomes available next season. Stover (rastrojo) is assumed removed for fodder.
- **Grain-N constraint**: WOFOST 8.1 lets grain fill with almost no N (0.26% N in a no-fertilizer test). Yield is capped at grain N ÷ minimum grain N concentration (maize 1.0%, barley 1.2%, faba bean 3.5%). The raw WOFOST value is kept in `yield_water_n_wofost_t_ha`.
- **Frost**: the crop ends on the first night with POWER minimum temperature (+ `--frost-tmin-offset`) at or below 0 °C, from 30 days after sowing.
- **Drought**: per-season rain, July-August (canícula) rain, longest dry spell and water-stress days; dry/normal/wet year classes (terciles of May-October rain); and drier scenarios with `--rain-factor` / `--rain-months`.

Crops and rotations are defined at the top of the script:

| Crop | WOFOST variety | Earliest sowing | Fertilizer (kg N/ha) |
|---|---|---|---|
| maize | `Grain_maize_202` | May 15 | 80 + 80 |
| barley | `Spring_barley_301` | July 1 | 60 |
| faba bean | `Faba_bean_801` | June 15 | 40 |

To add a crop, add it to `CROPS` (any crop/variety PCSE lists). To add a rotation, add a list of crop keys to `ROTATIONS`. WOFOST's wheats are winter wheats that need cold to develop, so they don't work sown in summer.

## Output

`--out` saves one row per simulated season:

| Column | Meaning |
|---|---|
| `rotation`, `phase`, `year`, `crop`, `previous_crop` | Which rotation, which starting crop, the sowing year, this and last season's crop |
| `sowing`, `maturity`, `harvest`, `frost_ended` | Dates; `maturity` empty if the crop didn't mature; `frost_ended` if frost ended it first |
| `yield_potential_t_ha`, `yield_water_t_ha`, `yield_water_n_t_ha` | Grain (or seed) **dry matter**, t/ha, at the three levels. Divide maize by 0.86 for grain at 14% moisture |
| `yield_water_n_wofost_t_ha` | Water- and N-limited yield before the grain-N constraint |
| `water_pct_of_potential`, `water_n_pct_of_water` | How much water, then nitrogen, limited the crop (100 = not at all) |
| `n_fertilizer_kg_ha`, `n_uptake_kg_ha`, `grain_n_kg_ha` | Nitrogen applied, taken up from the soil, and in the grain |
| `soil_water_at_start_mm`, `mineral_n_at_start_kg_ha` | Soil water (0-100 cm) and mineral N carried into the season on March 1 |
| `rain_season_mm`, `rain_jul_aug_mm`, `longest_dry_spell_days`, `water_stress_days` | Drought indicators for the season (sowing to harvest) |
| `year_class`, `rain_may_oct_mm` | Dry / normal / wet (terciles of May-October rain) and that rain |
| `rain_factor` | Rain multiplier of the scenario |

The script also prints a summary per rotation and crop (first year skipped as spin-up), maize yield by the previous crop, and maize yield by year class.

## First results: Texcoco, 2006-2025

Maize, water- and N-limited, t/ha of grain dry matter (failed seasons, <1 t/ha, in parentheses):

| Scenario | Maize every year | Maize-barley | Maize-faba bean | Maize-barley-faba bean |
|---|---|---|---|---|
| Baseline | 6.3 (1) | 6.4 (0) | 6.9 (0) | 6.8 (0) |
| 20% less rain | 5.3 (1) | 6.0 (1) | 6.4 (0) | 6.6 (0) |
| 40% less rain | 2.4 (10) | 2.8 (8) | 2.6 (9) | 3.0 (9) |
| Canícula: half the July-August rain | 5.8 (2) | 6.0 (1) | 6.5 (1) | 6.5 (0) |
| Frost check 2 °C colder | 5.7 (1) | 5.9 (1) | 6.5 (1) | 6.5 (1) |
| No fertilizer | 1.9 (1) | 1.9 (0) | 2.4 (0) | 2.3 (0) |
| Fixed sowing (May 15) | 8.5 (0) | 8.3 (0) | 9.0 (0) | 9.0 (0) |

- **Maize yields are now in a realistic range**: 6.3-6.9 t/ha dry matter (~7.3-8.0 at 14% moisture) vs 4.8-6.5 t/ha measured for rainfed hybrids at Texcoco.
- **Nitrogen is the biggest gap** (40-45%), water a small one (0-8%) except in drought years.
- **Faba bean before maize helps by +0.6 t/ha on average** (better in 11 of 20 years, worse in 4), through nitrogen. It matters most in dry years: 7.8 vs 5.2 t/ha for maize every year.
- **Timing of drought matters more than total rain**: 2023 (478 mm, a 28-day dry spell, 12 mm in June) failed after maize; 2022 (565 mm) didn't.
- **Rotations buffer moderate drying** (20% less rain: maize every year loses 1.0 t/ha, rotations 0.3-0.5), but **not severe drying** (40% less rain: 8-10 of 20 maize seasons fail in every rotation).
- **Frost ended 12 of 20 maize seasons** with rain-onset sowing; sowing in mid-May gives much more (8.3-9.0 t/ha), though the model can't see failed emergence in dry soil.
- **The model's soil N supply is too low for the Texcoco station**: without fertilizer it gives ~2 t/ha, while the Texcoco trial measured 5.2 t/ha unfertilized (5.6 fertilized). Reproducing the trial needs ~95-100 kg N/ha of soil N per season instead of 64, and ~40% less photosynthesis than the European parameters ([CALIBRATION_RESULTS.md](CALIBRATION_RESULTS.md)). The farm-level calibration lowers photosynthesis, which also removes the simulated rotation benefit for maize.
- **Soil moisture vs SMAP**: correlation 0.87 (2023-2024, 0-100 cm).

The report regenerates these tables from the CSVs: `python docs/technical_report/make_tables.py`.

## Exploratory trees, XGBoost and rotation risk

> **Note:** This exploratory XGBoost/tree-surrogate work is not part of the technical documentation in [`docs/technical_report/`](../../docs/technical_report/); the report covers only the WOFOST simulator.

Three additional modules build on the seasonal WOFOST results:

| Module | Experiment |
|---|---|
| `rotation_experiments.py` | Run ten named weather/management scenarios, including half fertilizer combined with moderate drought or canícula |
| `tree_surrogate.py` | Compare a mean-yield baseline, a shallow decision tree, random forest and XGBoost as fast emulators of simulated yield |
| `rotation_risk.py` | Compare rotations with paired-year bootstrap intervals and Monte Carlo samples of multiple crop harvests |

Start with the existing scenario CSVs, **without NASA access or PCSE imports**:

```bash
pip install -r requirements.txt
python -m src.crop_models.tree_surrogate --input data/rotations/*.csv --out-dir data/exploration/planning
python -m src.crop_models.tree_surrogate --input data/rotations/*.csv --feature-set hindcast --out-dir data/exploration/hindcast
python -m src.crop_models.rotation_risk --input data/rotations/*.csv --out-dir data/exploration/risk
```

Generate additional WOFOST simulations, then include them in the analysis:

```bash
python -m src.crop_models.rotation_experiments --scenarios half_fertilizer rain80_half_fertilizer canicula50_half_fertilizer --out-dir data/exploration/scenarios
python -m src.crop_models.tree_surrogate --input data/rotations/*.csv data/exploration/scenarios/*.csv --out-dir data/exploration/combined
python -m src.crop_models.rotation_risk --input data/rotations/*.csv data/exploration/scenarios/*.csv --out-dir data/exploration/combined_risk
```

Alternatively, omit `--scenarios` to regenerate all ten scenarios in a separate directory. This uses the original WOFOST model and its NASA/cache requirements. New runs carry sowing mode, fertilizer scale, rain multiplier and months, frost offset and coordinates in every CSV. A `scenarios.json` manifest records completed runs. Existing CSVs lacking those fields must keep their original registered filenames (`baseline.csv`, `rain80.csv`, etc.); arbitrary filenames need explicit metadata. Use one site per experiment and avoid loading the same run twice.

### Tree experiment design

The default crop is **maize**. Use `--crop barley` or `--crop fababean` for separate experiments, keeping the partner-crop calibration limitations below in mind. Each run removes its first simulated year as spin-up (`--spinup-years 0` disables this).

- **Planning features**: rotation, previous crop, initial water and mineral N, fertilizer plan, sowing policy, and the assumed rain/frost scenario. Scenario forcing is an experimental assumption; a future rain multiplier is not a measured forecast. Realized rain-onset sowing dates are excluded.
- **Hindcast features**: also include realized May–October rain, crop-season July–August rain, longest crop-season dry spell and sowing day of year. Some weather windows depend on harvest timing. This mode explains completed simulations and cannot be used for a pre-season recommendation.
- **Excluded from both**: target yield, other production-level yields, grain N, N uptake, water-stress days, harvest/maturity dates, frost-ended outcome, year classes and scenario/phase/year IDs.
- **Validation**: the latest four calendar years are the holdout. Three expanding-window folds over earlier years select the model by pooled validation RMSE. Every scenario, rotation and phase from a given year stays together. Encoders and preprocessing fit within each fold. This follows the temporal-validation principle described in the [scikit-learn documentation](https://scikit-learn.org/stable/modules/cross_validation.html#time-series-split).
- **Models**: fixed, conservative settings with a reproducible seed; XGBoost uses its [scikit-learn regressor API](https://xgboost.readthedocs.io/en/stable/python/python_api.html#xgboost.XGBRegressor). There is no tuning on holdout years. `--without-xgboost` runs the other models independently.

Outputs include `metrics.csv`, predictions and scores by scenario/rotation, auditable `fold_membership.csv`, readable `decision_tree.txt`, encoded feature importances, `diagnostics.png`, and the CV-selected `surrogate.joblib`. `run.json` records features, development/holdout years, input hashes, seed and package versions. Saved models are fitted on development years only. To replay a saved model:

```python
import joblib
import numpy as np
from src.crop_models.tree_surrogate import build_features

# candidate_seasons contains valid WOFOST-style rows with consistent initial state.
features, _ = build_features(candidate_seasons, feature_set="planning")
model = joblib.load("data/exploration/planning/surrogate.joblib")
predicted_yield = np.maximum(0, model.predict(features))  # same clipping as evaluation
```

These models emulate **WOFOST assumptions**, including its uncalibrated soil N and crop parameters. Feature importances describe fitted splits, not causal rotation effects. Initial soil states are generated by the simulator; do not change a rotation label while keeping incompatible water/N carryover. Use WOFOST for new interventions. Current evaluation tests unseen years at the same site and known scenarios; it does not establish performance at new sites or unseen management regimes.

### Bootstrap and Monte Carlo interpretation

`rotation_risk.py` compares maize harvests against continuous maize by default (`--crop`, `--reference`). It averages repeated crop phases within each rotation/year, then keeps only years shared by all compared rotations. `rotation_effects.csv` reports the mean paired advantage and its 95% bootstrap interval; `excluded_years` exposes incomplete comparisons. Differences within 0.000001 t/ha count as numerical ties.

`harvest_risk.csv` samples 5,000 sets of ten crop harvests by default (`--draws`, `--harvests`, `--seed`). Every rotation receives the same sampled weather years within a scenario. It reports the distribution of mean harvest yield, the fraction of harvests below 1 t/ha (`--failure-threshold`), and the probability of at least one failed harvest. `run.json` records the configuration and input hashes.

The samples assume independent historical years with equal probability. They do not include serial drought persistence, future climate trends, parameter uncertainty, or fresh soil-state transitions. Ten maize harvests span different numbers of calendar years in different rotations. These are **conditional maize-harvest comparisons**, not whole-farm yield, profit, or ten-year rotation returns. The original WOFOST runs provide the crop sequence and carryover dynamics.

Run the offline regression checks with:

```bash
python -m unittest discover -s tests -v
```

Measured exploratory results and their interpretation are in [EXPLORATION.md](EXPLORATION.md).

## Combined ensembles and observed yields

`ensemble_experiments.py` adds Extra Trees, equal averaging of random forest/XGBoost/Extra Trees, a nonnegative blend with weights summing to one, and ridge stacking. Blend weights and the stacker are trained on **inner expanding-year predictions**, inside each outer validation fold. Preprocessing is refitted inside every inner fold. Convex weights use a fixed 0.1 penalty toward equal weights; ridge uses standardized base predictions and fixed alpha 10. Hyperparameters are frozen before examining observed holdout labels. The implementation avoids ordinary stacking folds that can mix past and future years ([stacking API reference](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.StackingRegressor.html)).

```bash
python -m src.crop_models.ensemble_experiments --input data/rotations/*.csv data/exploration/scenarios/*.csv --out-dir data/exploration/ensembles_simulated
python -m src.crop_models.observed_maize
python -m src.crop_models.ensemble_experiments --observations data/observations/texcoco_maize.csv --features previous_yield_t_ha --out-dir data/exploration/ensembles_observed_planning
python -m src.crop_models.ensemble_experiments --observations data/observations/texcoco_maize.csv --features previous_yield_t_ha rain_may_oct_mm --out-dir data/exploration/ensembles_observed_hindcast
```

`observed_maize.py` downloads the [official SIAP municipal annual files](https://nube.agricultura.gob.mx/datosAbiertos/Agricola.php), caches them, and extracts **Estado de México / Texcoco / Primavera-Verano / Temporal / Maíz grano**. It handles the historical crop-name header and parses numeric fields strictly. Annual yield is total production divided by harvested area, with no assumed grain-moisture conversion. Input hashes, filters and URLs are recorded in `data/observations/sources.json`. Raw national files stay in ignored `data/`.

The observed experiment has one municipal observation per year, never copied across simulated rotations or scenarios. Planning uses only the previous year's measured yield; hindcast additionally uses unscaled May–October NASA POWER rain from the baseline weather export. Previous-year yields in later holdout years are available for **annual one-step predictions**, not a forecast of the entire four-year period made at its beginning. Production and harvested area are excluded as predictors because they define the target.

Both targets use three outer expanding-year folds and reserve 2022–2025 for evaluation by default. For simulations, those years were already inspected in earlier experiments, so this is an exploratory reuse of that holdout. SIAP labels form a separate observed target. Outputs include metrics, row-level holdout predictions, a fitted CV-selected model, inner/outer year membership, blend weights and input hashes. `paired_uncertainty.csv` resamples whole holdout years jointly and reports the selected model's RMSE advantage over each alternative; positive values favor the selected model. Four holdout years give limited uncertainty estimates.

SIAP municipal averages contain no field rotation history, fertilizer treatments, or paired intervention outcomes. They test municipal yield prediction; they **cannot validate the simulated causal benefit of crop rotation**. Errors on SIAP's reported grain basis cannot be directly equated to errors against WOFOST dry-matter yields. Results are recorded in [ENSEMBLE_RESULTS.md](ENSEMBLE_RESULTS.md).

## Limitations

- **Crop parameters are European.** Barley and especially faba bean tonnages are not credible (faba bean seed ~10 t/ha simulated vs 1-2 t/ha typical in Mexico). Compare maize across rotations, not partner-crop tonnages.
- **Several nitrogen settings are assumptions** (mineralization rate, losses, residue release, fertilizer recovery, minimum grain N, barley and faba bean doses). Rotation benefits depend on them.
- **Not modeled**: pests, diseases, weeds, phosphorus, hail, intercropping (milpa), common bean (frijol), oats, irrigation.
- **Coarse weather**: POWER's grid cell around Texcoco sits at 2,633 m vs ~2,250 m in the valley, and shows few frosts (none in 2021-2024). `--frost-tmin-offset` tests colder nights.
- **Frost is all-or-nothing**: the crop ends at the first frost; there's no partial damage.
- **Rain scenarios** change rain only, not temperature or radiation.

## Next steps

1. **Calibrate** against observed yields (INIFAP/CIMMYT trials at Texcoco, SIAP municipal statistics).
2. **Station weather** (SMN, Chapingo) to correct POWER temperatures, especially for frost.
3. **SMAP at sowing**: use SMAP root-zone moisture to set the soil water at the start of each season.
4. **Supplemental irrigation** as a drought adaptation option.
5. **Decisions and RL**: score rotations with prices and costs, then move to [CropGym](https://pypi.org/project/cropgym/), a reinforcement-learning environment built on PCSE.
