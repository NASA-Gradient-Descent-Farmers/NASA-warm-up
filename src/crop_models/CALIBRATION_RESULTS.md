# Calibrating WOFOST rotations to Texcoco farm yields

Run on October 18, 2026 (Python 3.13.1, PCSE 6.0.13). Code: [calibration.py](calibration.py); tests: `tests/test_calibration.py`. Everything is opt-in. Default `wofost_rotations` runs and `data/rotations/*.csv` are unchanged: a fresh default baseline is identical to the saved CSV, and so are re-runs of the `no_fertilizer` and `canicula50` suites.

**Observed:** SIAP rainfed spring–summer yield per sown hectare for Texcoco (`farm_tool.siap_texcoco`). Fields lost to drought or frost count as zero yield.

**Simulated:** water- and N-limited yield with the grain-N constraint, averaged per crop and year over all rotations and phases, as in `farm_tool.farm_gap`.

**Years:**
- Fit: 2006–2021 only. 2005 is spin-up.
- Holdout: 2022–2025, never used for fitting.
- SIAP has no barley before 2008 and no faba bean in 2020–2021.

## Results

| Crop | Run | Fit 2006–2021: sim / obs (t/ha) | RMSE | r | Holdout 2022–2025: sim / obs | RMSE | r |
|---|---|---:|---:|---:|---:|---:|---:|
| Maize | default | 6.34 / 2.56 | 4.24 | 0.36 | 7.63 / 2.98 | 4.66 | 0.92 |
| Maize | calibrated | **2.35** / 2.56 | **0.71** | 0.39 | 2.74 / 2.98 | 0.89 | −0.25 |
| Barley | default | 6.15 / 1.78 | 4.37 | −0.08 | 5.81 / 1.55 | 4.28 | −0.21 |
| Barley | calibrated | **1.65** / 1.78 | **0.28** | −0.11 | 1.30 / 1.55 | 0.41 | 0.21 |
| Faba bean | default | 9.79 / 1.94 | 7.87 | −0.11 | 9.59 / 1.17 | 8.45 | −0.55 |
| Faba bean | calibrated | **1.73** / 1.94 | **0.61** | −0.18 | 1.73 / 1.17 | 0.60 | −0.27 |

Calibration fixes the **level**: holdout errors drop 5–14× and the holdout means are within 0.25 t/ha for maize and barley. The `farm_gap` rescaling factors over 2006–2025 fall from 0.18–0.40 to 1.02–1.10. It does **not** add year-to-year skill. Maize correlation stays ~0.4 in the fit years, and no crop has a meaningful holdout correlation from four years. Treat calibrated yields as realistic averages and risk ranges, not as forecasts for a given year.

The fitted values are in `CALIBRATED`:

| Crop | Phenology (TSUM ×) | Photosynthesis × | Fertilizer N recovery |
|---|---:|---:|---:|
| Maize | 1.0 | 1.0 | 0.20 (default 0.5) |
| Barley | 0.8 | 0.5 | 0.5 |
| Faba bean | 1.0 | 0.45 | 0.5 |
| Site | | | Mineralization 0.25% of soil N per season (default 0.5%) |

## What drives the gap

1. **Level: European cultivars at attainable yields.** Over 2006–2021 the default potential yields are 11.2 t/ha (maize), 12.0 (barley) and 10.0 (faba bean). Water-limited yields are the same: water costs under 1% on average, since the 100 cm IGBP profile holds 236 mm of plant-available water and May–October rain is ~750 mm. So the default only loses yield to N, 44% for maize and 49% for barley. Faba bean fixes 80% of its N (`NFIX_FR`), so nothing pulls it down: 9.8 t/ha simulated against 1.9 observed.
2. **Nitrogen supply.** Default maize takes up ~150 kg N/ha:
   - 80 kg from fertilizer (160 kg × `N_RECOVERY` 0.5);
   - ~64 kg per season from mineralization (0.5% of IGBP's 12.7 t N/ha in 0–100 cm);
   - the rest from carryover.

   This is the lever that matches maize. A fit that lowered photosynthesis instead got the level but lost the year pattern (r ≈ 0.1 vs 0.4), and below ×0.5 the crop barely establishes.
3. **Phenology and frost.** The POWER cell sits at 2,633 m, about 380 m above the El Batán fields, so it runs roughly 2.5 °C colder (standard lapse rate).
   - Grain_maize_202 flowers ~87 days after sowing, which is plausible for Valles Altos hybrids. But it needs about 100 more days of grain fill at these temperatures.
   - As a result, 69% of 2006–2021 maize seasons end at the first night ≤0 °C rather than at maturity. When maturity is reached, its median date is December 5.
   - Frost timing is therefore what drives the model's year-to-year variation. In 2011, late sowing and an October 23 frost give a low year that matches SIAP. In 2010, a November 4 frost gives 1.7 t/ha while SIAP reports 2.9.
   - TSUM ×0.8 matures 75% of maize seasons (median October 28), but it *raises* yields because fewer grain fills are cut short. The fit kept the default maize phenology.
   - The maize grid was limited to TSUM ×0.8–1.0. At ×0.6 maize flowers 56 days after sowing, an early-maturing cultivar Texcoco doesn't grow, and an earlier fit picked it only to flatten year-to-year variation.
4. **Frost threshold and soil depth are minor.** Ending the crop at −2 °C instead of 0 °C adds 0.16 t/ha of maize. A 50 cm soil changes the fit-year means by under 0.05 t/ha; it lowers holdout maize by 1.1 t/ha, through dry 2022–2023.
5. **Why continuous maize fails in 2023.** SIAP reports its best maize year in 20 years (4.0 t/ha). Averaged over rotations, the model also has a good 2023 (8.8 t/ha default, 2.8 calibrated). The near-failure (0.01 t/ha) is continuous maize only, in both default and calibrated runs:
   - The 2022 maize, sown late (June 15), kept transpiring until January 5, 2023. That left under 10 mm of plant-available water on March 1, against 130–200 mm after barley or faba bean.
   - The 2023 crop was sown May 15, after ~24 mm of early-May rain, then got almost no rain in June (a 28-day dry spell).
   - With zero transpiration its seedling leaf area decayed from 0.05 to 0.003, and it never recovered.

   The causes are the slow phenology (late maturity drains the profile), a false start under the onset rule, and WOFOST's lack of re-sowing. With TSUM ×0.8 the same season yields 9.9 t/ha. A re-sowing rule or a later onset threshold would address it more directly than calibration can.

## Method

Knobs, applied through PCSE parameter overrides:
- **Phenology:** TSUM1 and TSUM2 scaled together.
- **Photosynthesis:** a lumped farm-efficiency factor for weeds, pests, disease, plant stand and landraces, scaling `AMAX_REF`, `AMAX_SLP` and `EFFTB`.
- **Fertilizer N recovery** per crop.
- **Site mineralization rate.**

Fitting:
- Coordinate grid search: barley, then faba bean, then maize. Maize goes last because it inherits water and N from the calibrated partners; at the fitted photosynthesis, barley is hardly N-limited and faba bean fixes its own N.
- The objective is the lowest 2006–2021 RMSE. Ties go to higher correlation, then to the candidate closest to the defaults.
- Every candidate's scores are saved to `fit_history.csv`, and the fit takes about 10 minutes on 8 cores.

## Caveats

- **Fertilizer recovery and mineralization can't be told apart.** SIAP only constrains total N supply. Keeping mineralization at the default needs maize fertilizer recovery near 0.05, and even then it fits worse (RMSE about 1.0, mean still about +0.6 t/ha). The fitted half mineralization fits better (RMSE 0.71), but it makes maize very fertilizer-dependent. Calibrated no-fertilizer maize falls to 0.29 t/ha, against 2.35 fertilized; the default goes from 6.34 to 2.03. That response is likely too steep. Use calibrated `no_fertilizer` and `half_fertilizer` runs with care, and refit with on-farm N trials when available.
- **Barley and faba bean sit just above an establishment cliff.** At photosynthesis ×0.4, barley falls to 0.7–1.2 t/ha and faba bean to 0.7–1.1. Stress scenarios such as `rain60` may exaggerate failures for these crops.
- **SIAP limits what can be learned.**
  - The data are municipal estimates with many rounded values (2.6, 2.4).
  - Barley and faba bean cover only 4–12 ha after 2016.
  - Faba bean falls from 2.6 t/ha (2005–2009) to 1.2 (2016–2025), a trend weather can't explain. Hence the +0.55 t/ha holdout bias.
  - The maize loss years 2011 and 2019 (51% and 64% of the area lost) dominate the year signal; the model reproduces 2011 but not 2019.
- **One POWER cell and one soil point** describe the whole municipality.

## Reproduce

```bash
python -m src.crop_models.calibration --sensitivity     # one-at-a-time diagnostics (~2 min)
python -m src.crop_models.calibration --fit             # refit on 2006-2021 (~10 min, 8 cores)
python -m src.crop_models.calibration --simulate        # calibrated baseline -> data/rotations_calibrated/
python -m src.crop_models.calibration --simulate --scenarios baseline rain80 no_fertilizer
```

Calibrated CSVs use the scenario name `<name>_calibrated`, so they can be loaded with the default runs. For example, `farm_gap(load_seasons([path]), siap, scenario="baseline_calibrated")` replaces the notebook's per-crop rescaling factor. `calibration.json` in the output directory records the knobs used.

## Next steps

- Pin phenology with observed flowering and maturity dates from INIFAP/CIMMYT trials, or a lapse-rate correction of POWER temperatures, then refit the yield knobs.
- Constrain the N split with on-farm fertilizer trials, such as the Texcoco dose trial cited in `wofost_rotations.CROPS`.
- Add a re-sowing rule after failed establishment, which drives the 2023 continuous-maize failure.
