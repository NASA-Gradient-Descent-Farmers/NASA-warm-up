# Rotation comparison (`comparar_rotaciones`)

Compares a farmer's current rotation with three alternatives, for **any of Mexico's 191 SIAP districts**, rainfed (*temporal*) or irrigated (*riego*). Each rotation gets nine indicators, each with a 0-100 score, an evidence level and a source. Each one also gets a Spanish explanation card: why it is suggested, the evidence, benefits, risks, information gaps and what to check with a local technician.

Every number and every sentence is produced by code. An LLM (e.g. the WhatsApp assistant) only has to phrase the result, so it cannot invent agronomy.

```python
from src.rotations.compare import comparar_rotaciones, to_json

out = comparar_rotaciones(
    "Villa de Zaachila", "maíz", estado="Oaxaca",   # municipality or SIAP district; current rotation as text
    agua="temporal",                                # or "riego"
    prioridades=["riesgo", "suelo"],                # any of: ingreso, riesgo, agua, suelo, erosion, plagas, forraje
    residuo="pastoreo",                             # stover: dejar, pastoreo, sacar, quemar
    tiene_animales=True, mes_siembra=None, pendiente="ligera",   # plana / ligera / fuerte
    propuestas=["maíz - frijol"],                   # optional rotations the farmer wants compared too
    costos={"maíz": 9000},                          # optional: the farmer's cost per ha per season (MXN)
    rendimiento_propio={"maíz": 1.5},               # optional: the farmer's yield in a normal year (t/ha)
)
print(to_json(out))
```

Rotation text: years are separated by `-`, `,` or `→`. `/` separates the spring-summer crop from the autumn-winter crop: `"maíz/garbanzo - sorgo"`. `milpa` means maize + bean + squash. If a crop is grown in the district mostly in autumn-winter (e.g. irrigated maize in Sinaloa), it is placed there automatically.

Build the tables once (~3 min with the SIAP and POWER caches; otherwise it downloads them):

```bash
python -m src.rotations.build          # SIAP history and NASA POWER climate
python -m src.rotations.observed       # MODIS NDVI and SMAP by month (needs the yield-panel caches, ~10 min)
```

Or skip the build: the repo already includes the tables in `data/shared/` (the `rotations_*` files, refreshed with `python -m src.yield_panel.share export`). The tool reads `data/shared/` when `data/rotations/` is empty.

## How it decides what to propose

Alternatives use **only crops that the district already grows** in the same cycle and water regime, with at least 100 ha a year and at least 1% of the area of the district's main crop. So the climate, the market and the local know-how for them already exist. Smaller ("niche") crops are listed separately, and the farmer can ask to compare them.

| Template | Proposes |
|---|---|
| `leguminosa` | alternate the main crop with a local legume (the two with the highest value per ha) |
| `milpa` | maize + bean + squash on the same field, where maize and bean are both grown |
| `sequia` (temporal) | alternate with a more drought-tolerant local crop |
| `menos_agua` (riego) | alternate with the local crop that needs the least irrigation, if it saves ≥10% |
| `invierno` / `verano` | add a crop in the empty cycle, where the district grows crops in that cycle |
| `forraje` | add a forage crop (only if the farmer has animals) |
| `ingreso` | alternate with the local crop of highest value per ha |

Candidates are scored with the farmer's priorities: a chosen priority counts 3, the others 1. The tool keeps the best three of different kinds, preferring alternatives that show the farmer a crop not already on screen. The cards show every trade-off and never hide them behind a single winner.

## Indicators

| Indicator | Unit | How | Evidence |
|---|---|---|---|
| `ingreso` | MXN/ha/yr | SIAP production per sown ha (last 10 yr, losses count as zero) × SIAP rural price (median of last 5 yr). Gross: no costs | high in the district, medium if from the state, low if national |
| `ingreso_p10` | MXN/ha/yr | 10th percentile over 2003-2025 at fixed recent prices: a bad year | same |
| `riesgo` | share of years | years with production per sown ha below half its median | same |
| `agua` | temporal: % of crop water need met by effective rain in a dry year (1 in 5); riego: net irrigation mm | FAO-56 crop coefficients × ET0 (FAO-56 Penman-Monteith from NASA POWER, 2001-2025, wind 2 m/s); USDA-SCS effective rain; winter crops on residual moisture get the root zone's stored water | medium |
| `nitrogeno` | kg N/ha/yr | legume fixation (Ndfa × crop N ÷ NHI × 1.5 for roots) − N in harvest − N in removed residue. No fertilizer or manure | low |
| `carbono` | t C/ha/yr | humified C from residue left (15%) and roots (40%), residues from IPCC 2006 ratios | low |
| `erosion` | % | share of erosive rain (modified Fournier index) on unprotected soil, from the crop calendar's canopy + residue cover; scaled by slope in the score | medium |
| `plagas` | % | share of crop changes that switch plant family (mixtures count half) | rule |
| `forraje` | t DM/ha/yr | forage crops + residue taken for animals | medium |

With costs (below), three more: `ganancia` (profit, MXN/ha/yr), `ganancia_p10` (profit in a bad year) and `prob_perdida` (share of years where costs exceed the harvest's value). Without them, two break-even costs instead: `costo_equilibrio` (the most a hectare can cost per year before losing money in an average year) and `costo_equilibrio_8de10` (before losing in 8 of 10 years).

Comparisons with the current rotation use the same historical years for both. Income differences come with a 90% year-bootstrap interval. They are called "clear" only if the interval excludes zero **and** the yields are observed in the district (not for milpa, whose yields are assumed).

## Costs and the farmer's own numbers

Only the farmer's own costs (`costos`) enter the calculations. Open cost data for Mexico are scarce: FIRA's Agrocostos system is not downloadable, and the few public summaries we found are irrigated autumn-winter crops in **Sinaloa**, for commercial farms that assume high yields (e.g. 12 t/ha maize). Applying them to a smallholder, or pairing them with SIAP's lower district yields, would mix two different farms.

`tables/costs.csv` therefore serves only as a reference to quote. When a cost is missing, `costos.pregunta_sugerida` asks for it, and where FIRA publishes a figure for the same crop, cycle, water regime and state, the question includes it: "Como referencia, FIRA estima unos $48,400/ha … ¿El tuyo es parecido?". The figures are also listed under `costos.referencias_para_preguntar`. Without the farmer's cost, the tool gives the break-even costs, and for each alternative the most the unknown crop can cost to leave the farmer as much as the current rotation does.

Profit replaces gross income in the scores only when the current rotation's costs are known and at least three alternatives have known costs. Alternatives without costs are then left out and listed under `costos.sin_costo_no_mostradas`.

`rendimiento_propio` sets a crop's yield level for this farm (ratio to the district's median production per sown ha, between 0.2 and 5). SIAP still supplies the year-to-year pattern.

## What NASA satellites add (`observed.py`)

| Observation | Use in the tool |
|---|---|
| MODIS NDVI (MOD13C2, 0.05°, 2003-2025), cropland-weighted (MCD12C1) within 15 km | `tu_lugar` says when the area's farmland is typically least and most green, and whether that matches the calendar the tool assumed for the current rotation (if not, it asks for sowing and harvest dates) |
| SMAP root-zone moisture (SPL4SMGP, 0-100 cm, 2015-2025) | Relative wetness at sowing (0 = the municipality's dry reference, 1 = its wet reference) sets how much stored water a crop sown on residual moisture gets in the water balance. If it is below 30%, the card warns that sowing on residual moisture is risky without supplementary irrigation |

## Data

| Piece | Source | File |
|---|---|---|
| Yields, losses, prices, areas for 19 crops, both cycles and water regimes, 2003-2025 | SIAP open data (district level, with state and national fallback) | `siap_stats.py` |
| Climate per municipality (2,463) and district (191) | NASA POWER daily (MERRA-2 cells): rain, Tmin/Tmax, RH, radiation → monthly normals, frost probability (nights ≤2 °C), heat days (≥35 °C), and year-by-year rain and ET0 | `climate.py` |
| Rain correction | CHIRPS (satellite + gauges) / POWER season and off-season ratios per municipality. Median ≈1.0, but 0.6-0.85 in the Valles Centrales of Oaxaca and Texcoco | `climate.rain_correction` |
| Crop traits | `tables/crops.csv`, with sources and evidence per column in `tables/crop_sources.csv` | `catalog.py` |
| Reference costs to quote when asking (never used in calculations) | `tables/costs.csv`, FIRA (Sinaloa, irrigated autumn-winter) | `costs.py` |
| Farmland greenness and soil moisture by month | NASA MODIS NDVI and SMAP | `observed.py` |

## Known gaps (also shown to the farmer)

- **Costs only from the farmer.** Without them the tool gives break-even costs rather than profit.
- **No previous-crop effect on yield** (e.g. maize after bean yielding more). This is the main thing a crop model (DSSAT/WOFOST) would add.
- **Milpa yields are assumed:** maize 85%, bean 25% and squash 15% of their sole-crop yields (LER 1.25; Yu et al. 2015 report a mean of 1.22 for annual intercrops).
- **N and C use international coefficients.** They are good for comparing options, not for predicting soil change.
- **SIAP is district-level, not field-level.** POWER cells are ~50 km, so cold valley bottoms get more frost than shown.
- **Default sowing date is the start of the rains** (FAO growing period, rain ≥ half of ET0). Highland farmers often sow earlier with residual moisture, so ask for `mes_siembra`.
- **Some crop coefficients were transcribed from memory** of FAO-56 / IPCC tables and are flagged "verificar" in `crop_sources.csv`.

## Work that can be split up

| Task | Who | Effort |
|---|---|---|
| Check every value in `tables/crops.csv` against FAO-56 Tables 11, 12, 22 and IPCC 2006 Table 11.2; add INIFAP values for Mexican varieties | non-coder | 1-2 days |
| Review the Spanish card text with an agronomist or extension agent | non-coder | 1 day |
| More reference figures for `tables/costs.csv` (quoted when asking, never computed with): FIRA Agrocostos summaries or INIFAP technology packages for rainfed crops in the demo states, each with its source and season | non-coder | 1-2 days |
| DSSAT (DSSATTools) or WOFOST runs for N and C carryover and the previous-crop effect, for the demo districts | coder | 3-5 days |
| MCP tool wrapper (the function already returns JSON) | coder | ½ day |

Tests: `python -m pytest tests/test_rotations.py`.
