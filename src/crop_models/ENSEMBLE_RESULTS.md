# Ensemble experiments against simulations and observed yields

Run date: October 18, 2026. Reproduction commands and method are in [README.md](README.md#combined-ensembles-and-observed-yields). All model settings were fixed before inspecting SIAP holdout labels. The original simulation holdout was already examined in earlier work and remains exploratory.

## Observed municipal results

Source: [SIAP official municipal agricultural statistics](https://nube.agricultura.gob.mx/datosAbiertos/Agricola.php), annual files 2005–2025. Filters: Estado de México (15), Texcoco (99), Primavera-Verano (2), Temporal (2), Maíz grano. Each selected year contains one source row. Yield is production / harvested hectares on the reported grain basis. No moisture conversion or synthetic rotation labels are applied.

The lag feature leaves 20 usable years (2006–2025). Models train on 2006–2021 and use three expanding validation windows, 2010–2013, 2014–2017 and 2018–2021. Evaluation is on four previously unexamined **observed targets** from 2022–2025. Predictions use the latest published annual series; this is a retrospective backtest, not a test of historical data-release vintages or live forecast deployment.

| Model | Planning CV RMSE | Planning holdout RMSE | Hindcast CV RMSE | Hindcast holdout RMSE |
|---|---:|---:|---:|---:|
| Training mean | 0.472 | 0.731 | 0.472 | 0.731 |
| Previous year's yield | 0.500 | 1.254 | 0.500 | 1.254 |
| Random forest | 0.493 | 0.833 | 0.469 | 0.841 |
| XGBoost | **0.468** | 0.775 | **0.461** | 0.870 |
| Extra Trees | 0.485 | 0.755 | 0.476 | 0.769 |
| Equal blend | 0.481 | 0.787 | 0.467 | 0.826 |
| Convex blend | 0.481 | 0.784 | 0.467 | 0.829 |
| Ridge stack | 0.648 | 0.719 | 0.576 | 0.729 |

Errors are t/ha. Planning uses previous-year observed yield only. Hindcast also uses actual May–October rain from the baseline NASA POWER weather export, which is unavailable at planting. Lagged yields within the holdout support successive annual one-step predictions; this is not a four-year-ahead forecast.

**CV selects XGBoost in both modes, but it fails to beat the training mean on the observed holdout.** Planning XGBoost has MAE 0.644 t/ha and R² −0.301. Planning equal blending has R² −0.339. Ridge's slightly lower holdout error does not make it the selected model: its earlier-year validation is substantially worse. There is no demonstrated ensemble gain against the observed baseline.

The planning selected model's RMSE advantage over the mean is **−0.044 t/ha**, with a paired-year bootstrap 95% interval of **[−0.170, +0.027]**. Positive advantages favor the selected model. Four years provide weak uncertainty estimates; they do not establish a reliable ranking among these models.

Observed holdout yields, retained without smoothing:

| Year | SIAP rainfed maize yield (t/ha) |
|---|---:|
| 2022 | 2.600 |
| 2023 | 4.000 |
| 2024 | 2.180 |
| 2025 | 3.137 |

The 2023 municipal yield is high despite low POWER rain at the modeled point. This exposes a representativeness issue that a more complex model alone cannot resolve: municipal harvested-area averages, local rainfall and management histories need investigation. We do not infer a causal weather response from four observations.

## Simulation emulator results

The ten existing/new WOFOST scenarios provide 800 maize rows but only 20 weather years. The same 2006–2021 development and 2022–2025 evaluation windows are retained.

| Model | CV RMSE (t/ha) | Holdout RMSE (t/ha) |
|---|---:|---:|
| Training mean | 2.908 | 3.225 |
| Random forest | 2.561 | 2.726 |
| XGBoost | 2.519 | 2.771 |
| Extra Trees | 2.502 | 2.545 |
| Equal blend | **2.501** | 2.625 |
| Convex blend | 2.506 | 2.602 |
| Ridge stack | 2.681 | 2.770 |

CV selects equal blending by a very small margin over Extra Trees. Equal blending reduces holdout RMSE by about 5.3% relative to XGBoost, while Extra Trees alone has a lower holdout error. The equal blend's paired-year RMSE advantage over Extra Trees is −0.080 t/ha, interval [−0.485, +0.137]. Model combination does not establish superiority over the best individual tree ensemble.

## What this establishes

- Blending can modestly improve emulation of the existing simulator. It does not make simulated labels into observations.
- With the current observed sample and predictors, ensemble complexity does not establish better real yield prediction than a simple mean baseline.
- SIAP has no field-level previous-crop, rotation or fertilizer records. These results do **not** validate the earlier simulated rotation benefits.
- Next evidence should be matched field/year rotation trials with cultivar, fertilizer, sowing dates, soil and weather. More municipal years/sites and fixed-calendar temperature/rainfall features can support a separate municipal prediction task, evaluated on fresh observations.

## Saved artifacts and checks

Outputs are under `data/exploration/ensembles_simulated/`, `ensembles_observed_planning/` and `ensembles_observed_hindcast/`. They include metrics, predictions, whole-year bootstrap comparisons, importable fitted models, inner/outer year membership, blend weights and input hashes. Observed runs also produce `observed_predictions.png`. Raw official files and their URL/hash manifest are in `data/observations/`.

All 14 regression tests pass, including temporal stacking, holdout-label invariance, irrigation filtering, historical header mapping and missing-year lag handling. Saved observed models replay the reported holdout predictions. Runtime uses scikit-learn 1.9.1, XGBoost 3.4.1 and SciPy 1.18.1; manifests record package versions.
