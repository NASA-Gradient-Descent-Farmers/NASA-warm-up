# The NSGA planner and the rotation tool: what lines up and what does not

Two pieces of work sit side by side in this repo and were built separately:

| | NSGA planner (`src/crop_models/nsga_planner.py`) | Rotation tool (`src/rotations`, `comparar_rotaciones`) |
|---|---|---|
| Question | Which mix of rotation, fertilizer and stover handling trades off yield, income, N loss, soil carbon and bad-year income? | How does the farmer's rotation compare with three alternatives that the district already grows? |
| Where | One site, Texcoco (19.53, -98.85) | Any of Mexico's 191 SIAP districts, rainfed or irrigated |
| How | WOFOST simulations (default and SIAP-calibrated parameters) on a fertilizer grid, searched with NSGA-II / III | SIAP district history, FAO-56 water, IPCC residue and N coefficients; no simulation |
| Decisions | Rotation, fertilizer scale (0-1.25 x the crop doses), stover retention (0-1) | Rotation, stover handling (`residuo`); fertilizer is not a decision |

Each side fills a gap the other lists. The rotation tool's README lists as known gaps that it has no previous-crop effect on yield (which "a crop model (DSSAT/WOFOST) would add") and that its N and C come from international coefficients; the WOFOST season chain carries soil water and mineral N from one season to the next. The planner's weak spots are one site, placeholder costs and prices, and a carbon objective that is a flow, not a measurement, which are what the tool's district history, evidence levels and IPCC coefficients provide.

## Definitions side by side

| Quantity | Planner | Rotation tool | Comparable? |
|---|---|---|---|
| Unit of analysis | Texcoco *municipality* (SIAP municipal series) | SIAP *district* (DDR) that contains the place; falls back to state, then nation | No, see the cross-check |
| Price | SIAP `preciomediorural`, median of the latest 3 years | SIAP value ÷ production, median of the latest 5 years | Yes: within 5% at Texcoco |
| Income | `net_mxn_ha` = grain + stover sold − placeholder costs − N price x dose | `ingreso` is gross (grain only); profit only with costs the farmer gives | Only the gross grain part |
| Costs | Placeholders (`PLACEHOLDER_COSTS`: maize 14,000 MXN/ha) | None unless the farmer gives them; FIRA figures are only quoted when asking | No |
| Fertilizer | Decision variable | Not modelled: SIAP yields embed current practice | No |
| Nitrogen | `n_loss_kg_ha` = dose − extra N uptake | `nitrogeno` = fixation − N removed, with no fertilizer | No: complementary |
| Carbon | `c_input_t_ha` = 0.45 x (roots + retained stover): total carbon returned | `carbono` = humified C: 0.45 x (0.15 x residue left + 0.40 x roots), IPCC 2006 ratios | No: different quantities |
| Residue | `retention` 0-1; removed stover is sold at a placeholder price | `residuo`: `dejar` removes 0, `pastoreo` 0.5, `sacar` 0.8, `quemar` 1.0 of the residue | Roughly: retention ≈ 1 − removed share |
| Bad-year risk | `cvar_net_mxn_ha`: mean net income of the worst quarter of *simulated* years | `ingreso_p10` and `riesgo` (share of years below half the median), from *observed* SIAP 2003-2025 | No |
| Crop names | `maize`, `barley`, `fababean` | `maize`, `barley`, `faba`; `fababean`, `faba bean` and `haba` are accepted | Yes (`tests/test_planner_alignment.py` guards it) |

## Cross-check at Texcoco

A one-off comparison on 2 November 2026 (not part of the test suite): the planner's four rotations through `comparar_rotaciones("Texcoco", ...)`. It used the local `data/nsga/grid.csv`, the 2006-2021 design years and fertilizer scale 1.0. One site and 16 years, so read it as a sanity check, not a validation.

**Gross grain income, MXN/ha/yr** (grain only, no stover, no costs):

| Rotation | Rotation tool (SIAP, district) | Planner, calibrated | Planner, default |
|---|---:|---:|---:|
| maize | 26,668 | 18,457 (0.69 x) | 51,733 (1.9 x) |
| maize-barley | 18,069 | 14,011 (0.78 x) | 39,901 (2.2 x) |
| maize-faba bean | 31,551 | 23,838 (0.76 x) | 106,788 (3.4 x) |
| maize-barley-faba bean | 24,133 | 19,061 (0.79 x) | 81,928 (3.4 x) |

Both put maize-faba bean first and maize-barley last. The two in the middle are close in the planner and swap order. The default WOFOST parameters give 2-3.4 x the tool's income, in line with `NSGA_RESULTS.md`, which notes that their yields are 2.5-5 x SIAP's; the calibrated ones sit below the tool.

**Why the calibrated model sits below the tool: municipality versus district.** Yield per sown hectare over the latest 10 years:

| Crop | Municipality (planner's series) | District (rotation tool) |
|---|---:|---:|
| maize | 2.77 t/ha on 1,163 ha | 3.66 t/ha on 31,466 ha |
| barley | 1.62 t/ha on 13 ha | 2.08 t/ha on 1,206 ha |
| faba bean | 1.37 t/ha on 12 ha | 2.21 t/ha on 209 ha |

Simulated maize yield tracks the district series better than the municipal one (correlation 0.52 against 0.11 over 16 years). With so few years that is suggestive, not conclusive. The district is also what the rotation tool treats as the unit SIAP numbers are effectively estimated at (`src/yield_panel/README.md`).

**Year-to-year variability of maize yield, 2006-2021:**

| Series | Coefficient of variation | Worst quarter as a share of the mean |
|---|---:|---:|
| Planner, calibrated WOFOST | 0.38 | 0.46 |
| SIAP, Texcoco municipality | 0.28 | 0.64 |
| SIAP, Texcoco district | 0.15 | 0.82 |

The simulated bad years are worse than the observed ones, so `cvar_net_mxn_ha` probably overstates bad-year losses (`NSGA_RESULTS.md` traces the worst years to frost-truncated seasons). A district averages many farms, so a single farm's real risk lies between the municipal and district rows.

**Stover and roots, maize at scale 1.0** (t dry matter/ha), against the rotation tool's IPCC ratios at the same grain yield:

| | Stover | Roots | Total carbon input |
|---|---:|---:|---:|
| Calibrated WOFOST | 1.53 | 0.25 | 0.80 t C |
| IPCC ratios at 2.31 t grain | 2.99 | 1.17 | 1.87 t C |
| Default WOFOST | 15.47 | 2.61 | 8.14 t C |
| IPCC ratios at 6.48 t grain | 7.29 | 3.03 | 4.64 t C |

The IPCC estimate sits between the two models: the calibrated one has about half the stover and a fifth of the roots (it was calibrated on grain only), and the default one has about twice the stover.

**Faba bean price.** The planner's 2025 price (5,030 MXN/t) comes from 10 ha. The district series also drops in 2025 (9,713 MXN/t on 135 ha, against 16,200-16,500 in 2022-2024), but less.

## Suggestions for joining them

- Decide the spatial unit. Either validate the calibrated WOFOST against the district series, or run the rotation tool at municipal level, but not one against the other as they stand.
- Use the IPCC residue ratios (`src/rotations/tables/crops.csv`) as an independent check on `stover_dm_t_ha` and `root_dm_t_ha` before trusting `c_input_t_ha`.
- Check the `cvar_net_mxn_ha` spread against the observed SIAP variability before using it as a constraint.
- Map `retention` to `residuo` explicitly if a result from one side is shown next to the other.
- Keep costs out of any shared number until a sourced figure exists; both sides agree that none is available for rainfed central Mexico.

## Plumbing the two sides share

- **Tests:** run `python -m pytest tests`. It runs everything. `python -m unittest discover -s tests` still works but only runs the unittest-style modules and skips the pytest-style functions in `test_rotations.py` and `test_assistant.py`.
- **`data/rotations/`** holds two unrelated things: the planner side's WOFOST scenario `*.csv` files (`farm_tool.scenario_files` reads only `*.csv`) and the rotation tool's built `*.parquet` tables (`siap_stats.read` reads only named `.parquet` files, falling back to `data/shared/`). They do not collide while each side keeps its extension. Do not write a CSV from the rotation tool there, or a Parquet file from the planner side.
- **SIAP is downloaded twice.** `src/crop_models/observed_maize.py` caches the yearly files in `data/observations/`, `src/yield_panel/siap.py` in `data/siap/`. Both use the same URL. They were not merged because the planner side records input hashes for its reproducibility checks.
