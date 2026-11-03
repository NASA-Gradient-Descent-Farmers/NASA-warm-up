# NSGA multi-objective planning: what it is and what happened

For anyone who has not followed this work. It explains what the NSGA planner does, what the runs showed, what was wrong along the way, and how far to trust it.

| Read this | For |
|---|---|
| this page | the plain-language story |
| [`src/crop_models/NSGA_RESULTS.md`](../../src/crop_models/NSGA_RESULTS.md) | the findings, tables and caveats |
| [`nsga_planner.pdf`](nsga_planner.pdf) (source: [`nsga_planner.tex`](nsga_planner.tex)) | the maths, 22 pages: numbered equations, worked numbers, `file:line` references into the code |
| [`src/crop_models/nsga_planner.py`](../../src/crop_models/nsga_planner.py) | the code |

## The question

A rainfed farm in Texcoco, Mexico, has to choose a crop rotation, how much fertilizer to apply, and whether to leave crop residue (stover) in the field. "Best" means several things that pull in different directions: more grain, more money, less nitrogen lost to the environment, more carbon returned to the soil, and surviving bad years. No single plan wins on all of them.

NSGA-II and NSGA-III are search algorithms that return the **set of best trade-offs** (the Pareto front) instead of one winner. The planner uses them to explore that set.

## Where the inputs come from

The pipeline upstream of the NSGA work (see [`src/crop_models/README.md`](../../src/crop_models/README.md)):

1. Four NASA datasets: POWER (daily weather), SMAP (soil moisture), GLDAS and IGBP-DIS (soil properties).
2. The WOFOST crop simulator turns weather and soil into simulated yields for maize, barley and faba bean.
3. The simulator was calibrated against real Texcoco farm yields from SIAP (the Mexican agriculture statistics service).

That produced **two versions of the model**, which matter for everything below:

- **Default:** European crop parameters. Simulated yields are 2.5-5x what Texcoco farms get, and fertilizer matters a lot.
- **Calibrated:** matches real farm yields, but in doing so nitrogen stopped limiting growth. Maize yield barely changes with fertilizer.

## What was built

[`nsga_planner.py`](../../src/crop_models/nsga_planner.py) works in stages:

1. Run the simulator once for every rotation at six fertilizer levels, under both model versions (`--build-grid`, about a minute).
2. Score any strategy (rotation, fertilizer amount, stover retained) by interpolating that grid, in microseconds.
3. Run NSGA-II (up to 3 objectives) or NSGA-III (4 or more) on top, over five objectives: yield, net income, nitrogen lost, carbon returned to the soil, income in the worst quarter of years.
4. Check the search against brute force: all 4,284 possible strategies are scored, so the true front is known.
5. Pick one compromise from a front with user-set weights (sustainability weighted most by default).
6. Optionally search for strategies that hold up under **both** model versions at once (`--model robust`).

## What the runs showed

- **The search works.** On three objectives NSGA finds the exact front. On four or five it covers 95-98% of it.
- **At this size NSGA is not needed.** There are only 4,284 strategies and brute force takes about a second. NSGA would matter for a multi-year crop-sequence problem, which has not been built.
- **The nitrogen answer comes from the model, not from agronomy.** The calibrated model says use no fertilizer. The default model says use about 85-100% of today's dose. Neither is evidence about real farms; a fertilizer trial on farm soils would settle it.
- **The money results rest on placeholders.** Production costs, the nitrogen price and the stover price are guesses. The faba bean price is the median of three SIAP years (16,524 MXN/t), but the latest year (2025) is 5,030; at the lower price the "plant faba bean" recommendation flips to plain maize.
- **The robust search suggests a hedge:** roughly 50-130 kg N/ha for maize with faba bean in the rotation, below today's 160 and above zero. That depends on how regret is measured; in absolute pesos it rises to 176-200 kg. It is a hedge by construction, not a finding about nitrogen.
- **Soil sustainability is a proxy.** The planner measures carbon returned to the soil, not a simulated soil carbon stock.

## Problems found and fixed during review

An independent review of the first version found three issues, all fixed and covered by tests:

- NSGA-III looked like it stalled at 89-94% coverage. That was a reporting bug (the code read a thinned result from the library); the final population covers 95-98%.
- The "worst 20% of years" objective was really the worst 25% (4 of 16 years); it is now labelled that way.
- Floating-point rounding noise (differences of about 1e-16) kept 21 strategies on the calibrated fronts and produced one of the picks. Objectives are now compared at 9 decimals. This moved the calibrated sustainability-first pick from 4 kg N/ha to 0.

## How far to trust it

This is a demonstration of the method and of how sensitive the answer is, **not farm advice**. The conclusions are set by two inputs the data cannot settle yet: how much yield nitrogen buys, and the placeholder prices and costs. The calibrated fronts also sit in a fertilizer range (0-0.25 of today's dose) that was never simulated directly, only interpolated.

## How to run it

```bash
pip install -r requirements.txt                                     # adds pymoo
python -m src.crop_models.nsga_planner --build-grid                 # needs PCSE and a NASA Earthdata login; ~1-2 min on 8 cores
python -m src.crop_models.nsga_planner --model calibrated --out-dir data/nsga/calibrated
python -m src.crop_models.nsga_planner --model robust --out-dir data/nsga/robust
python -m unittest tests.test_nsga_planner                          # offline, no PCSE
```

The generated grid and fronts live under `data/`, which is git-ignored, so they are not in the repository; rebuild them with the commands above. The exact commands behind every table are in the Reproduce section of [`NSGA_RESULTS.md`](../../src/crop_models/NSGA_RESULTS.md).

## What is not done

- A multi-year crop-sequence search, which is where NSGA would earn its place.
- A finer fertilizer grid near zero.
- Sourced production costs, fertilizer and stover prices.
- A real soil-carbon model, so sustainability becomes a trajectory instead of a flow.
- Using SMAP in the objectives (today it only validated the simulated soil water earlier).
