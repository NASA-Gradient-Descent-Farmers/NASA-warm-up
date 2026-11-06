# Campo Verde (dashboard)

**Campo Verde** is a static React + TypeScript + Vite web app for farmers and advisors in Texcoco, built on the model results in this repo. Spanish first (English on a toggle).

The planner reads small JSON files exported from the Python outputs, so it runs without Python or PCSE, and nothing in the browser re-runs a crop model. The map step is the exception: it needs internet (map tiles and NASA's climate service).

## Home

The app opens on a home page: a leaf grows from a stem while the title and four lotería-style cards arrive ("¡Hola, agricultor! ¿Qué es lo que buscas?"). Choosing a card sends a leaf growing from the click point until it fills the screen, the page changes underneath, and the leaf turns away. Brand mark in the header returns home the same way. The leaf is plain SVG and CSS/Web Animations (`src/lib/leaf.ts` draws it, veins included, from one outline); `prefers-reduced-motion` skips every animation. Display type is Fraunces, bundled with the app (`@fontsource-variable/fraunces`), so it works offline.

## Where is your field?

After a first card pick (or from "cambiar" on the home page and the pin chip in the header) comes "¿Dónde está tu parcela?": a map where the farmer taps to drop a pin and drags it to adjust. A returning farmer skips it. The map is Leaflet over OpenStreetMap, with a NASA GIBS "Blue Marble" satellite layer (about 500 m per pixel, for seeing the land around rather than the exact spot). The one site the crop model covers, El Batán, is drawn with a 25 km circle.

Every crop-model number in the app is for El Batán, so the pin gets an honest verdict instead of silently reusing Texcoco's numbers:

| Verdict | When | What the app says |
|---|---|---|
| inside | within 25 km of El Batán (about one NASA POWER weather cell) | the planner applies |
| near | 25-100 km, and annual rain within 20% and mean temperature within 2 °C of El Batán's | a reference, not tuned to the field |
| outside | beyond 100 km, or 25-100 km with a different climate | the numbers are Texcoco's: compare options, not figures for the field |

Those thresholds are our judgment calls, not NASA's or the model's (`src/lib/coverage.ts`). A verdict other than "inside" also shows as a note on every planner page.

**Climate from NASA.** For the pin and for El Batán the browser asks NASA POWER's climatology service for rain, mean temperature and the coldest night, and shows them side by side (a monthly rain chart with a table view). Checked against POWER's own daily data at El Batán: climatology rain gives 895 mm a year against 912 mm for 2011-2020, with the same monthly shape. One trap: climatology `T2M_MIN` is each month's *extreme*, not the average of the daily minimums (January at El Batán: -4.5 °C, against a mean of +4.3 °C and a lowest day of -3.5 °C in 2015-2024), so the app calls it "coldest night" and says so.

**Privacy.** The pin is stored only in this browser (`localStorage`). NASA POWER is sent the location rounded to 0.1° (about 11 km, finer than its weather cell, so nothing is lost), and the map tiles come from OpenStreetMap and NASA GIBS, which see the area being viewed. The page says this next to the map.

## Screens

| Screen | Status | Reads |
|---|---|---|
| Strategy planner (NSGA fronts, live prices) | built | `public/data/grid.json`, `meta.json` |
| Rotation economics | data exported, screen planned | `scenarios.json` (priced live by `src/lib/economics.ts`) |
| Reality check (WOFOST vs SIAP) | data exported, screen planned | `reality.json` |
| Weather / drought what-ifs | data exported, screen planned | `scenarios.json` (seasons and maize risk) |

**Strategy planner.** Pick a crop model (calibrated to SIAP, or standard WOFOST), say how much each objective matters, and the app shows the trade-off curve of rotation, fertilizer and stover decisions and suggests a compromise. Click a point (or a table row) to see its plan.

**Live prices.** Grain prices, other costs, the nitrogen price and the stover price are editable. Changing one re-scores all 4,284 strategies in the browser (about 50 ms) and recomputes the curve and the suggestion; when the new figures change the suggestion, the plan card says what it was at the original figures. SIAP's latest price per crop is listed next to each grain price. How it works:

- `grid.json` holds the WOFOST season outcomes the planner scores from (design years 2006–2021, every rotation at each fertilizer scale, both parameter sets). `src/lib/planner.ts` is a port of `nsga_planner.Grid` / `Planner` / `brute_force`.
- `src/lib/front.ts` ports `pareto_front` and `choose`. A weight of 0 narrows the five-objective front to the other objectives (exact, up to ties; tested against re-scoring the whole lattice).
- Tests check the port against the Python: the live front must equal the front `nsga_planner.py` saved (`src/lib/fixtures/reference_fronts.json`, written by the exporter) strategy by strategy, the four compromises of [`NSGA_RESULTS.md`](../src/crop_models/NSGA_RESULTS.md) must come out, and so must its picks when the faba bean and stover prices change.
- The bad-year share and the tie decimals come from `meta.json` (`planner`), written from `nsga_planner.py`, so the two never drift apart.
- Prices, production costs, the nitrogen price and the stover price are the planner's placeholders (only grain prices are sourced), and the two crop models disagree about fertilizer; the app says so on every screen.

**Data for the other tabs.** `scenarios.json` holds the ten WOFOST scenario suites of `rotation_experiments.py` (baseline, drier, canícula, colder nights, less or no fertilizer, fixed sowing) for both parameter sets, 2006–2025 after a spin-up year: each season's crop, yield, fertilizer and whether frost ended it, each year's May–October rain and dry/normal/wet class, and the paired-year maize risk of `rotation_risk.py`. `reality.json` holds SIAP's Texcoco series (yield per sown ha, lost share, price) and `farm_tool.farm_gap` per parameter set. Both load only when one of those tabs opens (`loadFarmData`). `src/lib/economics.ts` ports `farm_tool.rotation_economics` and is tested against it (`src/lib/fixtures/reference_economics.json`).

## Run it

The exported JSON is committed, so you only need this when the model results change. From the repo root (needs `pip install -r requirements.txt`; about 2 minutes for the planner, an hour for the twenty scenario runs):

```bash
python -m src.crop_models.nsga_planner --build-grid --model calibrated --out-dir data/nsga/calibrated
python -m src.crop_models.nsga_planner --model default --out-dir data/nsga/default
python -m src.crop_models.rotation_experiments --out-dir data/rotations
python -m src.crop_models.calibration --simulate --scenarios baseline rain80 rain60 canicula50 frost_minus2 \
    no_fertilizer fixed_sowing half_fertilizer rain80_half_fertilizer canicula50_half_fertilizer
python -m src.crop_models.dashboard_export
```

The exporter refuses fronts that were not computed from the current `data/nsga/grid.csv` and scenario folders that lack any of the ten scenarios. It does not need PCSE.

Then:

```bash
cd dashboard
npm install
npm run dev      # http://localhost:5173
npm test         # planner, front and economics logic against the Python results, translation key parity
npm run build    # type-check and build to dist/ (relative paths: serve from any folder)
```

## Layout

```text
public/data/        JSON from dashboard_export.py (meta.json, grid.json, scenarios.json, reality.json)
src/lib/            types, JSON loading, planner scoring, Pareto front and compromise choice, rotation economics,
                    number formats, distance, NASA climate, coverage verdict, saved pin
src/lib/fixtures/   Python's saved fronts and rotation economics, for the ports' tests only
src/i18n/           en.ts is the source of truth for keys; es.ts must match (tested)
src/components/     scatter chart (SVG), plan card, weights panel, front table
src/screens/        the home page, the map step and one file per tab
src/hooks/          the pin's coverage verdict and NASA climate
src/home.css        home page, leaf and transition styles (and the shared palette)
src/where.css       the map step
```

Colours follow the repo's data-viz palette (rotation = marker shape, nitrogen lost = blue ramp, suggested plan = orange ring) and switch with the system light/dark setting.
