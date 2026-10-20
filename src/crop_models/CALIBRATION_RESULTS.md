# Calibrating WOFOST rotations to Texcoco farm yields

Second version, October 19, 2026 (Python 3.13.1, PCSE 6.0.13). The step-by-step explanation is in [docs/technical_report/calibration.pdf](../../docs/technical_report/calibration.pdf). Code: [calibration.py](calibration.py); tests: `tests/test_calibration.py`, `tests/test_farm_tool.py`. Everything is opt-in: default `wofost_rotations` runs and `data/rotations/*.csv` are unchanged.

**Observed:** SIAP rainfed spring–summer yield per sown hectare for Texcoco (`farm_tool.siap_texcoco`). Fields lost to drought or frost count as zero yield.

**Simulated:** water- and N-limited yield, combined as SIAP would see it (`farm_tool.simulated_like_siap`).
- **Maize** is weighted by SIAP crop areas. Last year's barley or faba bean area caps how much maize follows them, and the rest is maize after maize. That rest is 93% of the maize area on average in 2006–2021, and over 97% since 2019.
- **Barley and faba bean** are averaged over all rotations, since SIAP can't tell what they follow.

**Years:**
- Fit: 2006–2021 only.
- Holdout: 2022–2025. It was never used to choose knobs, but it was looked at while designing the first version.

## Results

| Crop | Prediction | Fit 2006–2021: sim / obs (t/ha) | RMSE | r | skill | Holdout: sim / obs | RMSE | skill |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Maize | default | 6.47 / 2.56 | 4.49 | 0.35 | −5.4 | 5.50 / 2.98 | 4.49 | −4.6 |
| Maize | calibrated | **2.31** / 2.56 | 1.07 | 0.11 | −0.53 | 2.35 / 2.98 | 1.03 | −0.29 |
| Maize | SIAP mean (climatology) | 2.56 / 2.56 | **0.70** | | 0 | 2.56 / 2.98 | **0.80** | 0 |
| Barley | default | 6.15 / 1.78 | 4.37 | −0.08 | −22.8 | 5.81 / 1.55 | 4.28 | −17.4 |
| Barley | calibrated | **1.84** / 1.78 | 0.25 | −0.03 | −0.37 | 1.55 / 1.55 | 0.21 | 0.08 |
| Barley | SIAP mean (climatology) | 1.78 / 1.78 | **0.18** | | 0 | 1.78 / 1.55 | 0.23 | 0 |
| Faba bean | default | 9.79 / 1.94 | 7.87 | −0.11 | −15.0 | 9.59 / 1.17 | 8.45 | −9.9 |
| Faba bean | calibrated | **1.75** / 1.94 | 0.61 | −0.17 | −0.23 | 1.78 / 1.17 | 0.62 | 0.20 |
| Faba bean | SIAP mean (climatology) | 1.94 / 1.94 | **0.49** | | 0 | 1.94 / 1.17 | 0.78 | 0 |

Skill is 1 − RMSE / RMSE(climatology); above 0 beats the SIAP average.

Persistence (last year's SIAP yield) has these RMSEs:

| Crop | Fit | Holdout |
|---|---:|---:|
| Maize | 0.97 | 1.25 |
| Barley | 0.17 | 0.05 |
| Faba bean | 0.38 | 0.08 |

What the results say:
- **The level is fixed.** The calibrated means are within 0.06–0.25 t/ha of SIAP in the fit years. The `farm_gap` factors go from 0.42 / 0.28 / 0.18 to 1.14 / 0.98 / 1.01.
- **It doesn't beat the SIAP average year by year.** Climatology wins in the fit years for every crop and in the holdout for maize. Persistence beats everything for barley and faba bean, whose SIAP series barely change.
- **Year pattern:** calibrated maize swings about as much as SIAP (SD 0.88 vs 0.72 t/ha) but in the wrong years (r 0.11). Faba bean is too steady (0.23 vs 0.51) and misses SIAP's decline over time.
- **Use:** calibrated runs give realistic levels for scenarios, not forecasts.

## Fitted knobs (`CALIBRATED`)

| Crop | Phenology (TSUM ×) | Photosynthesis × | Fertilizer N recovery |
|---|---:|---:|---:|
| Maize | 0.8 | 0.47 | 0.5 (default) |
| Barley | 0.9 | 0.475 | 0.5 (default) |
| Faba bean | 0.9 | 0.475 | 0.5 (default) |
| Site | | | Mineralization 0.5% of soil N per season (default) |

**The fertilizer-trial constraint:**
- **The trial:** at INIFAP Texcoco, maize gave 5.2 t/ha unfertilized vs 5.6 t/ha with 160 kg N/ha (Alonso-Sánchez et al. 2023).
- **The rule:** maize candidates must keep their no-fertilizer / fertilized ratio within 0.1 of 0.93. 56 of the 88 passed, and the chosen one has 0.995.
- **What it rules out:** the first calibration cut nitrogen instead, giving a ratio of 0.12. Without the constraint the best candidate still cuts nitrogen (RMSE 0.87, ratio 0.26).

**Grid edges:**
- Maize phenology sits on the agronomic lower bound of ×0.8.
- Its N supply ties with higher supplies, because nitrogen no longer limits it; the tie goes to the defaults.

## What drives the gap

1. **European cultivars at attainable yields.** Potential yields are 11.2 / 12.0 / 10.0 t/ha, and water costs under 1% on average (236 mm plant-available water, ~770 mm May–October rain).
2. **Nitrogen was the default model's only brake** on maize and barley, but the Texcoco trial says nitrogen barely limits maize there. With that constraint, maize reaches the farm level only through low photosynthesis, a lumped stand-in for weeds, pests, disease, plant stand and landraces. There yields climb steeply: 2.0 t/ha at ×0.45, 2.8 at ×0.5.
3. **Phenology and frost.** The POWER cell is at 2,633 m, about 380 m above the fields, so its weather is ~2.5 °C colder. At default TSUM, 69% of maize seasons end by frost (median maturity December 5). The calibrated ×0.8 cycle matures in 75% of seasons, in about 155 days.
4. **Frost threshold and soil depth are minor.** Each changes fit-year means by under 0.4 t/ha.
5. **2023:**
   - In the default model, continuous maize nearly fails (0.01 t/ha). The late 2022 crop drained the profile, then came a false start and a dry June. With area weighting this dominates the default model's 2023.
   - Calibrated maize gives 2.0 t/ha in every rotation, against SIAP's 4.0.

## Rotation results need a second look

- **No rotation effect once calibrated.** Calibrated maize after barley or faba bean yields 2.32 t/ha, the same as maize after maize (2.31).
- **The default baseline benefit is one year.** Maize–faba bean's +0.63 t/ha over continuous maize (EXPLORATION.md) comes entirely from the 2023 continuous-maize failure; without 2023 it's −0.003.
- **The half-fertilizer benefit came through nitrogen.** With 20% less rain and half fertilizer, the default model's +1.0 t/ha (+0.94 over 2006–2021) came through nitrogen, which hardly limits calibrated maize.
- **SIAP can't settle it.** Field data on fertilizer response and rotations are needed.

## What changed from the first version

An independent review found these problems in version 1, each now fixed:

| Problem in version 1 | Fix |
|---|---|
| Maize was averaged over rotations equally. Re-weighted by real areas, its holdout RMSE was 2.27, not 0.89. | Maize is weighted by SIAP areas. |
| No naive baselines were reported. | Climatology, persistence and a skill score are reported. |
| The nitrogen choice sat on the grid edge and contradicted the trial (no-fertilizer ratio 0.12 vs 0.93). | The trial constraint applies, and photosynthesis may compete. |
| Barley's ×0.8 phenology was a coarse-grid artifact. | The photosynthesis grid is finer. |
| Diagnostics printed holdout scores. | Diagnostics score fit years only. |
| The notebook's `my_scenario` duplicated the baseline. | `load_scenarios` skips repeated runs: 704 → 640 maize training rows, training mean 5.12 → 5.00. |
| Docs drifted from the code. | Docs corrected, PCSE pinned to 6.0.13, run metadata recorded. |

## Caveats

- **One station trial decides the nitrogen split.** Farms may be more N-limited than the station.
- **Photosynthesis is a lumped knob.** It isn't a measurement of any one loss.
- **Phenology is bounded by judgment.** There are no observed flowering or maturity dates.
- **The observations are coarse.** SIAP is municipal and often rounded. Recent barley and faba bean areas are 4–12 ha (31 and 18 ha of barley in 2017–2018).
- **One weather cell and one soil point** represent the whole municipality.
- **The weather will change.** PCSE re-downloads POWER weather after 90 days (cache dated 2026-10-12), so saved runs can't be reproduced exactly after about 2027-01-10. `calibration.json` records the weather date, git commit and PCSE version.

## Reproduce

```bash
python -m src.crop_models.calibration --sensitivity     # one-at-a-time diagnostics, fit years (~2 min)
python -m src.crop_models.calibration --fit             # refit (~13 min, 8 cores); writes fit_history.csv, fitted_knobs.json
python -m src.crop_models.calibration --simulate        # calibrated baseline -> data/rotations_calibrated/
python docs/technical_report/make_calibration_figures.py
```

Calibrated CSVs use the scenario name `<name>_calibrated`, so default and calibrated runs can be loaded together; `farm_gap(load_seasons([path]), siap, scenario="baseline_calibrated")` compares one with SIAP.

## Next steps

- Pin phenology with observed flowering and maturity dates, or a lapse-rate correction of POWER temperatures.
- Get on-farm fertilizer and rotation trials to separate nitrogen from other losses.
- Add a re-sowing rule after failed establishment.
- Simulate POWER 1984–2025 (42 seasons) for the surrogates; they currently see only 16 weather years.
