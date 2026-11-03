# Multi-objective planning with NSGA-II / NSGA-III

First version, October 25, 2026 (Python 3.13.1, PCSE 6.0.13, pymoo 0.6.2). Code: [nsga_planner.py](nsga_planner.py); tests: `tests/test_nsga_planner.py`. Everything is opt-in: the only change to existing code is two extra columns in the season table (`stover_dm_t_ha`, `root_dm_t_ha`). A typeset, line-by-line explanation of the maths (equations, worked numbers, code mapping) is in [docs/walkthroughs/nsga_planner.pdf](../../docs/walkthroughs/nsga_planner.pdf), built from [nsga_planner.tex](../../docs/walkthroughs/nsga_planner.tex).

**Short version.** The pipeline works end to end on real simulator output, and NSGA matches an exact brute-force search where that can be checked. But what it recommends is set by two things the data cannot settle yet: **how much yield nitrogen buys** (the default and the calibrated WOFOST disagree completely) and **placeholder prices and costs**, including a faba bean price whose latest SIAP value (2025: 5,030 MXN/t) is 0.30 × the three-year median used (16,524). Read the results as a demonstration of the method and of those sensitivities, not as farm advice.

One fertilizer statement survives both models, with a caveat. When the two models are weighed equally (shortfalls normalized by each model's range), the dose that minimizes the worst-case income shortfall is 72–100 kg N/ha for maize, 48–132 across the price changes tried: below the current 160 and above zero. Measured in absolute pesos instead, the default model's 8× larger money dominates and that dose rises to 176–200 kg. So it is a hedge by construction, not a finding about nitrogen.

## The problem

A **strategy** is three decisions, evaluated over the 2006–2021 weather years (the calibration fit years; 2022–2025 is a holdout):

| Decision | Values |
|---|---|
| Rotation | maize, maize–barley, maize–faba bean, maize–barley–faba bean |
| Fertilizer scale | 0 to 1.25 × the crop doses of `wofost_rotations.CROPS` (maize 160 kg N/ha), in 50 steps |
| Stover retention | 0 to 100% of the stover left in the field, in 20 steps (the simulator otherwise assumes it is removed for fodder) |

Five **objectives**, each a farm-level mean over the years (phases of a rotation averaged, as in `farm_tool.rotation_economics`):

| Objective | Formula | Stands for | Data behind it |
|---|---|---|---|
| `yield_t_ha` ↑ | grain dry matter | yield | POWER weather → WOFOST |
| `net_mxn_ha` ↑ | grain × SIAP price − other costs − N price × dose + stover price × stover removed | economic gain | SIAP prices (real); costs, N price, stover price (**placeholders**) |
| `n_loss_kg_ha` ↓ | dose − (N uptake − N uptake with no fertilizer), floored at 0 | nature: fertilizer N the crop did not take up | WOFOST N uptake |
| `c_input_t_ha` ↑ | 0.45 × (roots + retained stover) | long-term soil capital | WOFOST biomass |
| `cvar_net_mxn_ha` ↑ | mean net income of the worst quarter of years (4 of 16) | long-term resilience | year-to-year variability of POWER weather |

**Where the four NASA datasets enter.** POWER drives every WOFOST season and sets the variability behind the bad-year objective. IGBP-DIS gives field capacity, wilting point and the soil N that mineralizes each year (the soil carbon stock, 130 t C/ha, is recorded in `grid.json` for context only: no objective reads it). GLDAS gives porosity. SMAP is **not** used by this module: it validated the simulated root-zone water earlier (a correlation of 0.87 for 2023–2024, see the README; correlation ignores bias and scale, and compares one field with a 9 km cell), and is the natural next input for drought resilience and the soil water at sowing.

**What the objectives really measure.**
- **`n_loss_kg_ha` is close to a restatement of the dose, not a measured loss.** In the default world the crop takes up half the fertilizer by construction (`N_RECOVERY = 0.5`), so the loss is about 0.495 × dose. In the calibrated world the crop ignores fertilizer, so the loss is about the dose. Leftover mineral N (about 3% of the dose over 16 years) is a standing stock, not a loss.
- **Retention is accounting only.** It changes no simulated yield or nitrogen; it moves stover between income and carbon at a fixed price, 1,000 MXN/t ÷ 0.45 = 2,222 MXN per t of carbon.
- **`c_input_t_ha` is a flow.** There is no decomposition, no soil carbon stock and no N pool, so it is the driver of an equilibrium, not a trajectory.
- **`cvar_net_mxn_ha` is a mean of four numbers** (the worst four of 16 years, no confidence interval). In the calibrated world the worst years are frost-truncated seasons: yield correlates −0.65 with the share of seasons ended by frost and −0.2 with season rain, so "bad-year income" is mostly a frost and sowing-date measure (the POWER cell is about 2.5 °C colder than the fields; CALIBRATION_RESULTS.md).
- **Default-world money and carbon are inflated twice.** The grain-N rule caps grain, but stover and roots are not capped, so default maize makes 16 t/ha of stover beside 6.3 t/ha of grain, and stover income is about 92% of the default pure-maize net at zero fertilizer.
- **SIAP prices are on a reported basis** with no moisture conversion, against yields in dry matter: revenue is understated by roughly 14% for maize, a second-order effect.

Not simulated: the effect of retained stover on soil N or water, price changes over time, N2O and fertilizer-manufacturing emissions.

## How it is computed

1. `--build-grid` runs WOFOST for every rotation at fertilizer scales 0, 0.25, …, 1.25 with the default parameters and with the SIAP-calibrated ones (`calibration.CALIBRATED`): 2,016 seasons, about a minute on 8 cores (`data/nsga/grid.csv`, `grid.json` with the knobs, site soil and versions).
2. `Planner` interpolates the grid linearly along the fertilizer scale and scores a strategy in about 60 µs. This replaces a 3–10 s WOFOST run per candidate (the notebook's "faster what-ifs" idea).
3. `optimize` runs **NSGA-II** with up to three objectives and **NSGA-III** (Das–Dennis reference directions) with four or more, on pymoo's mixed-variable GA: the rotation is a categorical gene, fertilizer and retention are integer steps. It returns the non-dominated strategies of the final population.
4. `brute_force` scores the whole 4,284-strategy lattice, so the exact front is known and the search can be checked (`front_quality`: IGD+ and hypervolume ratio against it). `pareto_front` compares objectives rounded to 9 decimals (`FRONT_DECIMALS`), so floating-point noise cannot keep a strategy on a front.
5. `RobustPlanner` (optional) wraps several worlds (the default and calibrated parameters) and returns the worst range-normalized shortfall per objective, so the same search can look for strategies that hold up in both.
6. `choose` picks one compromise from a front with a weighted Chebyshev distance to the ideal point. The default weights put soil carbon (0.30), bad-year income and N loss (0.20 each) first, as the team asked; "profit-first" is the contrast.

**Interpolation caveats.** The real simulation chains seasons, so a season at scale 0.6 would see 0.6-history, while interpolation mixes the histories of neighbouring nodes. Predicting each interior node from its two neighbours (twice the real spacing, so it overstates the error) gave at most 0.075 t/ha error in a 16-year mean of default yield, and up to 3.4 kg N/ha in the calibrated N-uptake mean, because calibrated uptake jumps between nodes 0 and 0.25. The calibrated picks are at scale 0, but the 231 maize strategies on the five-objective calibrated front all lie inside the first cell [0, 0.25], whose interior was never simulated: a finer grid at low doses is worth building before trusting that region.

**The lattice.** With real-valued fertilizer and retention, NSGA-II was slow to reach the box bounds, where these nearly linear trade-offs have their optima (IGD+ stuck near 0.13 on the test fixture). The lattice makes the bounds ordinary values and lets brute force and NSGA search the same set. On the real grid the gain is smaller (an emulation of the real-coded run gave IGD+ about 0.01–0.02 there).

## Evidence

### What the grid says about nitrogen

Mean 2006–2021 yield by fertilizer scale (1.0 = the current doses), t/ha of grain dry matter:

| Parameters | Crop | 0 | 0.25 | 0.5 | 0.75 | 1.0 | 1.25 |
|---|---|---:|---:|---:|---:|---:|---:|
| Default | maize | 2.03 | 3.11 | 4.12 | 5.14 | 6.34 | 7.47 |
| Default | barley | 3.90 | 4.41 | 4.97 | 5.56 | 6.15 | 6.72 |
| Default | faba bean | 9.77 | 9.78 | 9.79 | 9.80 | 9.81 | 9.82 |
| Calibrated | maize | 2.31 | 2.32 | 2.32 | 2.32 | 2.32 | 2.32 |
| Calibrated | barley | 1.81 | 1.81 | 1.81 | 1.81 | 1.81 | 1.81 |
| Calibrated | faba bean | 1.77 | 1.77 | 1.77 | 1.77 | 1.77 | 1.77 |

**The calibrated model has no fertilizer response at all** (N uptake saturates by scale 0.25), because the calibration absorbed the Texcoco yield gap into photosynthesis (×0.47), so growth is limited by carbon, not nitrogen (CALIBRATION_RESULTS.md: the trial's no-fertilizer ratio is 0.93, the model's 0.995). The default model responds almost linearly. Any optimizer will therefore say "no fertilizer" with the calibrated model and "about 85–100% of the dose" with the default one. This is a property of the models, not an agronomic finding.

### The fronts

Compromises chosen from the **exact** brute-force fronts (4,284 strategies, all five objectives). N scale 1.0 = 160 kg N/ha for maize.

| Parameters | Pick | Rotation | N scale | Retention | Net MXN/ha | N lost kg/ha | C input t/ha |
|---|---|---|---:|---:|---:|---:|---:|
| Calibrated | sustainability-first | maize–faba bean | 0.00 | 0.90 | 11,457 | 0 | 0.59 |
| Calibrated | profit-first | maize | 0.00 | 0.00 | 5,895 | 0 | 0.11 |
| Default | sustainability-first | maize–faba bean | 0.85 | 1.00 | 89,255 | 42 | 6.12 |
| Default | profit-first | maize–faba bean | 0.97 | 0.75 | 94,178 | 48 | 4.87 |

Default-model money and carbon figures are about 8× the calibrated ones (its yields are 2.5–5× SIAP's and its maize stover 16 t/ha); only compare strategies **within** a model.

**The five-objective front is huge and mostly not decision-relevant**: 483 of 4,284 strategies (calibrated) and 1,377 (default). Pure maize and maize–barley stay on it only through a 0.02–0.27 t/ha tonnage edge over maize–faba bean, despite far lower income; 231 of the calibrated front's strategies are maize at the 11 lattice points inside the first interpolation cell, where yield rises only 0.012 t/ha (0.5%) at a cost of 33 kg N lost. That slope is below the model's noise. This is dominance resistance: more objectives make almost everything non-dominated. Yield and income also conflict only because tonnes of different crops are not equally valuable. Treat four objectives (yield, income, N loss, soil carbon) as the working set, and add bad-year income as a constraint or a tie-breaker.

### How well NSGA covers the exact front

Three seeds, worst shown; 100 generations for NSGA-II, 200 for four objectives and 150 for five. Population: 100 for NSGA-II, the number of reference directions (84 for four objectives, 126 for five) for NSGA-III.

| Parameters | Objectives | Algorithm | Exact front | Found | IGD+ | Hypervolume ratio |
|---|---|---|---:|---:|---:|---:|
| Calibrated | income, N loss, soil C | NSGA-II | 26 | 26 | 0.000 | 1.000 |
| Calibrated | yield, income, N loss, soil C | NSGA-III | 252 | 77 | 0.006 | 0.981 |
| Calibrated | all five | NSGA-III | 483 | 118 | 0.005 | 0.970 |
| Default | income, N loss, soil C | NSGA-II | 1,377 | 100 | 0.025 | 0.965 |
| Default | yield, income, N loss, soil C | NSGA-III | 1,377 | 84 | 0.029 | 0.954 |
| Default | all five | NSGA-III | 1,377 | 126 | 0.033 | 0.961 |

IGD+ is the mean normalized distance from each exact-front point to the found front (0 = covered); the hypervolume ratio is found / exact (1 = same). A run takes 3–11 s.

- **NSGA-II on three objectives is exact whenever the front fits in the population** (26 of 26) and keeps 96.5% of the hypervolume when it does not (1,377 exact points, population 100).
- **NSGA-III on four or five objectives covers 95–98% of the hypervolume**, returning its whole non-dominated final population. What limits it is the population size (77–126 strategies returned, against fronts of 252–1,377), not the search; the two calibrated counts are below the population because rounding-noise ties are removed.
- **Correction.** An earlier version of the code, and of this document, read pymoo's `result.X`. For NSGA-III that is only the first-front member closest to each *occupied* reference direction (16–18 of 84), which made the search look like it plateaued at 89–94% and prompted an unsupported "thin front, extremes missed" explanation. The final population holds many more non-dominated strategies, and the archive of everything evaluated contains essentially the whole exact front.
- **At this size the search saves no work.** An instrumented run (independent review) found NSGA visiting about 1,300–1,600 distinct lattice strategies for the calibrated world, 2,700–3,000 for the default and 4,246 of 4,284 for the robust run, against 4,284 for brute force.
- Because the returned front is sampled, **picks from an NSGA front are not the picks from the exact front**. In a space this small, choose from the brute-force front.

### Robustness of the picks

All from the exact fronts; calibrated model unless stated.

**1. Prices decide the rotation and the stover decision.** Picks when the SIAP faba bean price (16,524 MXN/t, the median of its last three years, from 10–12 ha of faba bean a year) and the placeholder stover price (1,000 MXN/t) change:

| Faba bean price × | Stover MXN/t | Sustainability-first | Profit-first |
|---:|---:|---|---|
| 1.0 | 0 | maize, retention 1.0 | maize, retention 1.0 |
| 1.0 | 1,000 | maize–faba bean, 0.90 | maize, 0.00 |
| 1.0 | 3,000 | maize–faba bean, 0.90 | maize, 0.00 |
| 0.5 | 1,000 | maize–faba bean, 0.95 | maize, 0.30 |
| 0.25 | 1,000 | maize, 0.55 | maize, 0.35 |

N scale is 0 in all of these (calibrated model). Sustainability-first favors faba bean unless the bean price falls to about a quarter of the price used, and **SIAP's own 2025 price (5,030 MXN/t) is 0.30×**: one more year of data like that would put the recommendation on the maize side of this table. Retention falls as the stover price rises.

**2. The two parameter sets disagree about fertilizer, and the mistakes cost different things.** Each compromise scored in both worlds (net MXN/ha / N lost kg N/ha):

| Plan (from the exact front) | Rotation, maize N, retention | If the calibrated model is right | If the default model is right |
|---|---|---:|---:|
| Calibrated, sustainability-first | maize–faba bean, 0 kg N, 0.90 | 11,457 / 0 | 78,184 / 0 |
| Calibrated, profit-first | maize, 0 kg N, 0.00 | 5,895 / 0 | 15,945 / 0 |
| Default, sustainability-first | maize–faba bean, 136 kg N, 1.00 | 9,213 / **85** | 89,255 / 42 |
| Default, profit-first | maize–faba bean, 156 kg N, 0.75 | 9,198 / **97** | 94,178 / 48 |

Best possible net income: 12,528 (calibrated) and 106,995 (default). Betting on near-zero N with faba bean in the rotation loses 12% of income if nitrogen does pay (78.2k vs 89.3k), and 83% for pure maize (15.9k vs 94.2k). Betting on full N loses 19% of income and leaks 85–97 kg N/ha if it does not. Faba bean does most of the income work in both worlds; the nitrogen decision is what the models disagree on. A fertilizer trial on farm soils would resolve it, and is worth more than any amount of search.

**3. Held-out years (2022–2025)** keep the order of the two NSGA-front picks of the calibrated model: net income 11,598 (sustainability-first) vs 6,158 (profit-first), against 11,397 vs 5,895 in the design years. The worst-quarter income rose (4,914 → 8,843 and −4,187 → 2,814), but with four years this is the single worst year, and the calibrated model barely responds to drought (2023, with 340 mm of season rain, still gives 2.0 t/ha of maize), so this does not test resilience.

## Robust search across the two nitrogen worlds

`--model robust` (`RobustPlanner`) searches for strategies that hold up whichever set of WOFOST parameters is right. In each world, a strategy's **shortfall** on an objective is its distance from the best strategy of that world's lattice, as a share of that world's range (0 = best attainable, 1 = worst). The robust objective is the **worst shortfall over the two worlds**, minimized: a minimax-regret flavour whose units do not depend on the default model's inflated yields. The same NSGA machinery runs on top of it.

Results on the real grid (design years 2006–2021, placeholder economics; worst of three seeds):

| Objectives | Algorithm | Exact front | Found | IGD+ | Hypervolume ratio |
|---|---|---:|---:|---:|---:|
| income, N loss, soil C | NSGA-II | 738 | 100 | 0.017 | 0.971 |
| yield, income, N loss, soil C | NSGA-III, 286 directions | 1,727 | 286 | 0.016 | 0.977 |

**The robust fertilizer dose.** The income shortfall in the default world falls as fertilizer rises (about 0.0009 per kg N) and in the calibrated world it rises (about 0.0012 per kg N, which is the N price spread over that world's income range); the dose where the worse of the two is smallest (the minimax dose) is the highest dose worth considering, since beyond it both income and N lost get worse. On the two-objective robust front (income, N lost) the entire front is maize–faba bean with maize N between 0 and 88 kg/ha, and every dose above 88 is dominated.

| Rotation (retention 0) | Minimax maize N, kg/ha | Calibrated: net / N lost | Default: net / N lost |
|---|---:|---:|---:|
| maize | 100 | 3,488 / 92 | 36,375 / 49 |
| maize–barley | 84 | 2,375 / 54 | 26,989 / 29 |
| maize–faba bean | 88 | 11,153 / 55 | 95,902 / 27 |
| maize–barley–faba bean | 72 | 7,905 / 39 | 70,339 / 19 |

**What the hedge buys.** For maize–faba bean at 88 kg N/ha (retention 0), income is 89% of the best attainable in the calibrated world and 90% in the default one. The plan tuned to the calibrated model alone gets 91% and 73%; the plan tuned to the default model alone gets 74% and 83%. The price is nitrogen: 55 kg N/ha not taken up if the calibrated model is right (27 if the default is), against 0 for the zero-fertilizer plan.

**How firm is the number?** Not very, in two ways.
- **Prices.** At retention 0, over N price 10–50 MXN/kg, faba bean price × 0.5–1, and stover price 0–1,000, the minimax maize dose ranges from **48 to 132 kg N/ha** for maize–faba bean (100–148 for maize alone).
- **The definition of regret.** For maize–faba bean at the placeholder prices the minimax dose is 88 kg with range-normalized shortfalls (the repo's choice), 84 kg with the shortfall as a share of the best attainable income, and **176 kg with absolute pesos**. Absolute pesos let the default world's 8× larger money decide, so the hedge simply follows the default model. Range normalization treats the two worlds equally, which is a modelling choice, not a fact; so is treating them as equally plausible.

**Weaknesses of the shortfall.** The calibrated yield range is narrow (1.97–2.31 t/ha, against 6.8 in the default world), so any rotation difference reads as a large shortfall (0.78 for both picks below wherever faba bean is in the rotation): leave yield out of the robust objectives unless tonnage is the goal. The range includes dominated corners (the calibrated N-loss range reaches maize at 200 kg N, 192 kg lost, while the exact front's worst is 33), so N-loss shortfalls depend on the grid's upper bound of 1.25. The ideal point is per objective and not jointly attainable.

**Weighted picks from a large robust front are unstable.** The four-objective exact front has 1,727 strategies, and the Chebyshev compromise (`choose`) lands on 128 kg N/ha for sustainability-first and 4 kg N/ha for profit-first on the exact front, and on 104 and 8 kg N/ha on this NSGA-III front; with price changes it moves between maize and maize–faba bean and between 4 and 152 kg N/ha. On the exact front 36 strategies score within 0.01 of the best, spanning 0–140 kg N, so the dose is decided in the fourth decimal; in profit-first 547 strategies tie exactly at the minimum score and `choose` returns the first row; and because the ranges come from the front itself, "profit-first" can give up 53% of attainable income to avoid a 0.27 t/ha tonnage gap. Use the minimax dose and the two-objective front above as the robust statement, not a weighted pick.

The holdout columns (`*_holdout`) of a robust front measure shortfall against the best strategy in 2022–2025, so they are not the same size as the design-year shortfalls.

## What this does and does not show

- **At this size NSGA is a check, not a necessity.** Four rotations × two stepped decisions is 4,284 strategies; brute force is exact and takes a second. NSGA earns its place when the decision space grows: per-crop fertilizer doses and split timing, sowing date, and above all a **multi-year crop sequence** with carryover (3¹⁰ sequences × doses), where enumeration is impossible and each evaluation is a WOFOST run.
- **What drives the result is not the algorithm:** the nitrogen response, the faba bean price, and the stover price.
- **Soil capital is a proxy.** "Sustainable" here means "returns carbon and leaks little nitrogen", not a simulated 30-year trajectory.
- **Partner crops are weak.** Barley and faba bean yields are fit to 4–12 ha of SIAP area per year (CALIBRATION_RESULTS.md; faba bean alone is 10–12 ha), and faba bean carries almost all of the income advantage.
- **Rotation effects are interpolated, not simulated per strategy** (see the interpolation caveats above).
- **Float noise (found by review, fixed).** `pareto_front` used to compare objectives exactly, and interpolation leaves differences of about 4×10⁻¹⁶ t/ha in yield, so 21 calibrated strategies (maize–faba bean at scale 0.025) stayed on the five-objective front through rounding error alone: the calibrated fronts were 504 and 273 strategies instead of 483 and 252, the robust four-objective front 1,730 instead of 1,727, and the calibrated sustainability-first pick was one of those survivors (4 kg N/ha at scale 0.025, now 0 kg at scale 0). Objectives are now compared at 9 decimals, with tests.

## Reproduce

```bash
python -m src.crop_models.nsga_planner --build-grid                              # needs PCSE, cached POWER/IGBP/GLDAS; ~1-2 min
python -m src.crop_models.nsga_planner --model calibrated --generations 150 --out-dir data/nsga/calibrated
python -m src.crop_models.nsga_planner --model default --generations 150 --out-dir data/nsga/default
python -m src.crop_models.nsga_planner --model calibrated --objectives yield_t_ha net_mxn_ha n_loss_kg_ha c_input_t_ha --generations 200 --out-dir data/nsga/calibrated_4obj
python -m src.crop_models.nsga_planner --model default --objectives yield_t_ha net_mxn_ha n_loss_kg_ha c_input_t_ha --generations 200 --out-dir data/nsga/default_4obj
python -m src.crop_models.nsga_planner --model robust --objectives net_mxn_ha n_loss_kg_ha c_input_t_ha --out-dir data/nsga/robust_3obj
python -m src.crop_models.nsga_planner --model robust --objectives yield_t_ha net_mxn_ha n_loss_kg_ha c_input_t_ha --partitions 10 --generations 150 --out-dir data/nsga/robust_4obj
python -m unittest tests.test_nsga_planner                                       # offline
```

Each output directory has `front.csv` (decisions, objectives, and `*_holdout` columns), `brute_force_front.csv`, `front.png`, and `run.json` (seed, economics, front quality, grid hash). The commands use the default seed 1, so the quality figures printed by a single run differ slightly from the worst-of-three-seeds figures in the tables. PCSE re-downloads POWER weather after 90 days, so a rebuilt grid after about 2027-01-10 will differ slightly.

## Next steps

1. **Grow the decision space until NSGA is needed:** per-crop doses (small hook in `season_agromanagement`), then a multi-year crop sequence evaluated with live WOFOST through `calibration.Runner`.
2. **Finer grid at low doses** (for example scales 0.05, 0.1, 0.15) for the calibrated world, where the decisions sit inside the first cell.
3. **Replace the placeholders:** FIRA production costs, an N price series, a sourced stover price, and a faba bean price that does not hinge on 10–12 ha of SIAP area.
4. **Simulate soil carbon:** a simple pool model (RothC/AMG-style) started from the IGBP carbon stock, so sustainability becomes a trajectory.
5. **Use SMAP:** SMAP root-zone percentiles as a drought benchmark and as the soil water at sowing.
6. **Cap default-world stover and roots** like grain, or report the default world without stover income.
7. **Other sites:** the NSGA machinery is site-independent, but only Texcoco has calibrated crop parameters.
