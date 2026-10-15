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
- **The model probably underestimates soil nitrogen**: without fertilizer it gives ~2 t/ha, while the Texcoco trial measured 5.2 t/ha unfertilized. Calibrating soil N supply is the first priority.
- **Soil moisture vs SMAP**: correlation 0.87 (2023-2024, 0-100 cm).

The report regenerates these tables from the CSVs: `python docs/technical_report/make_tables.py`.

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
