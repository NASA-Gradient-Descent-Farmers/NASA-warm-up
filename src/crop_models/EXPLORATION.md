# Crop-rotation exploration

Initial experiments run on October 18, 2026. Commands, feature definitions and interpretation are in [README.md](README.md#exploratory-trees-xgboost-and-rotation-risk). CSVs, fitted models and figures are generated under the ignored `data/exploration/` directory.

Runtime: Python 3.13.1, NumPy 2.5.3, pandas 3.0.6, PCSE 6.0.13, scikit-learn 1.9.1, XGBoost 3.4.1 and joblib 1.6.0.

## Tree benchmarks on the seven existing scenarios

Inputs: `data/rotations/{baseline,rain80,rain60,canicula50,frost_minus2,no_fertilizer,fixed_sowing}.csv`. Target: maize grain dry matter from the water- and N-limited WOFOST model. The 2005 spin-up year is excluded, leaving 560 maize rows over **20 shared weather years**, not 560 independent climates.

Development years: 2006–2021. Expanding validation windows: 2010–2013, 2014–2017 and 2018–2021. Untouched holdout: 2022–2025, 112 maize rows. Seed 42; fixed model settings, with selection by pooled development validation RMSE.

| Model | Planning CV RMSE | Planning holdout RMSE | Hindcast CV RMSE | Hindcast holdout RMSE |
|---|---:|---:|---:|---:|
| Mean baseline | 3.199 | 3.495 | 3.199 | 3.495 |
| Decision tree | **2.757** | 3.137 | 2.939 | 4.363 |
| Random forest | 2.804 | 2.972 | 2.520 | 3.895 |
| XGBoost | 2.779 | 3.000 | **2.471** | 3.459 |

All errors are t/ha. **Planning selects the decision tree; hindcast selects XGBoost.** The random forest's lower planning holdout error is a reported evaluation result; holdout results do not change model selection.

The planning XGBoost beats the mean baseline on the holdout, but its error remains large and its validation score is close to the simpler tree. Hindcast XGBoost improves its validation score while generalizing worse to 2022–2025 (holdout R² −0.032). The current data do not establish a reliable yield forecast or a reason to replace WOFOST with XGBoost for crop-sequence interventions.

Useful next experiments are fixed-calendar weather features (especially frost-relevant minimum temperatures), more independent weather years/sites, and calibrated soil N supply. Subsequent tuning needs development-only validation and a fresh holdout. The hindcast's crop-season windows and realized sowing dates are retrospective information.

## Paired rotation effects

The same historical years are paired across rotations before bootstrap resampling. Selected comparisons, with 5,000 bootstrap draws and 20 paired years each:

| Scenario | Rotation | Mean maize advantage over continuous maize (t/ha) | 95% bootstrap interval |
|---|---|---:|---:|
| Baseline | Maize–faba bean | +0.634 | [−0.340, +2.116] |
| Baseline | Maize–barley–faba bean | +0.537 | [−0.338, +1.823] |
| 20% less rain | Maize–barley–faba bean | +1.239 | [+0.184, +2.465] |
| No fertilizer | Maize–faba bean | +0.456 | [+0.019, +1.041] |

The baseline rotation benefit varies enough across years for its interval to include zero. These intervals resample historical variability **under fixed simulator assumptions**. They exclude uncertainty in nitrogen mineralization, residue release, fertilizer recovery and crop calibration; they are not confidence intervals for a measured farm treatment effect.

The accompanying Monte Carlo output samples ten maize harvests at a time and reports mean-yield percentiles and failure risk. These harvest counts are conditional on maize being grown, so they cannot be interpreted as equal calendar periods or whole-rotation profits.

## Three additional WOFOST scenarios

Each new scenario runs all four rotations and phases over 2005–2025 at Texcoco: 168 seasonal rows per scenario, each evaluated at three production levels. Half fertilizer scales **every crop's** fertilizer plan by 0.5 (maize: 80 kg N/ha). Mean maize dry-matter yields over 2006–2025:

| Scenario | Continuous maize | Maize–barley | Maize–faba bean | Maize–barley–faba bean |
|---|---:|---:|---:|---:|
| Half fertilizer | 4.107 | 4.095 | 4.548 | 4.449 |
| 20% less rain + half fertilizer | 3.883 | 4.055 | 4.889 | 4.734 |
| Half July–August rain + half fertilizer | 4.086 | 3.930 | 4.294 | 4.393 |

All values are t/ha. Under 20% less rain and half fertilizer, maize–faba bean has a paired mean advantage of +1.007 t/ha, with a 95% bootstrap interval of [+0.181, +1.961] in the combined ten-scenario risk run. The rainfall response is not monotonic in every rotation; these experiments combine rain-onset sowing, nitrogen and water carryover. Investigate individual years and sowing dates before interpreting such responses agronomically.

## Planning benchmark on all ten scenarios

The combined dataset has 800 post-spin-up maize rows over the **same 20 weather years**. Development and holdout years, features and model settings are unchanged. There are now 160 holdout maize rows.

| Model | CV RMSE (t/ha) | Holdout RMSE (t/ha) | Holdout R² |
|---|---:|---:|---:|
| Mean baseline | 2.908 | 3.225 | −0.051 |
| Decision tree | 2.645 | 3.034 | 0.071 |
| Random forest | 2.561 | 2.726 | 0.250 |
| XGBoost | **2.519** | 2.771 | 0.224 |

**XGBoost is selected by development-year CV** and saved in `data/exploration/combined/surrogate.joblib`. Its holdout MAE is 2.076 t/ha. Adding scenarios changes the evaluation distribution; the lower overall RMSE does not by itself demonstrate improved performance on the original seven scenarios or on farms. The added simulations provide management combinations, not additional independent climate histories.

## Reproduction

```bash
python -m src.crop_models.tree_surrogate --input data/rotations/*.csv --out-dir data/exploration/planning
python -m src.crop_models.tree_surrogate --input data/rotations/*.csv --feature-set hindcast --out-dir data/exploration/hindcast
python -m src.crop_models.rotation_risk --input data/rotations/*.csv --out-dir data/exploration/risk
python -m src.crop_models.rotation_experiments --scenarios half_fertilizer rain80_half_fertilizer canicula50_half_fertilizer --out-dir data/exploration/scenarios
python -m src.crop_models.tree_surrogate --input data/rotations/*.csv data/exploration/scenarios/*.csv --out-dir data/exploration/combined
python -m src.crop_models.rotation_risk --input data/rotations/*.csv data/exploration/scenarios/*.csv --out-dir data/exploration/combined_risk
```

Per-run JSON manifests contain input hashes and configurations. Keep the original scenario filenames when reading the older exports, which lack management metadata.
