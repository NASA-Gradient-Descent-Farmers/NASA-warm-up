"""The modeled farm: site, crops and rotations. Plain data with no PCSE import, so light tools (the dashboard
export, the planner's scoring, tests) can read it without installing the crop model.

wofost_rotations.py runs WOFOST with these definitions; every other module takes the site from here.
"""

# CIMMYT El Batan research station, Texcoco (Valley of Mexico, ~2,250 m).
SITE = {"name": "El Batán, Texcoco", "latitude": 19.53, "longitude": -98.85, "elevation_m": 2250}
DEFAULT_LAT = SITE["latitude"]
DEFAULT_LON = SITE["longitude"]

# One crop per rainy season (May-October in central Mexico).
# - variety: WOFOST parameter set. Grain_maize_202 sown mid-May matures in Nov-Dec at Texcoco.
# - earliest: earliest sowing date (MM-DD).
# - fertilizer: (days after sowing, kg N/ha) applications. Maize: 160 kg N/ha, the highest dose tested on rainfed
#   hybrids at INIFAP's Texcoco station (Alonso-Sanchez et al. 2023, doi:10.28940/terra.v41i0.1577), split half at
#   sowing and half ~40 days later (assumed split). Faba bean: 40 kg N/ha and barley: 60 kg N/ha (assumed).
# - min_grain_n: minimum N concentration in grain/seed (kg N/kg dry matter), used for the grain-N constraint.
CROPS = {
    "maize": {"crop": "maize", "variety": "Grain_maize_202", "earliest": "05-15",
              "fertilizer": [(0, 80), (40, 80)], "min_grain_n": 0.010},
    "barley": {"crop": "barley", "variety": "Spring_barley_301", "earliest": "07-01",
               "fertilizer": [(0, 60)], "min_grain_n": 0.012},
    "fababean": {"crop": "fababean", "variety": "Faba_bean_801", "earliest": "06-15",
                 "fertilizer": [(0, 40)], "min_grain_n": 0.035},
}

ROTATIONS = {
    "maize": ["maize"],
    "maize-barley": ["maize", "barley"],
    "maize-fababean": ["maize", "fababean"],
    "maize-barley-fababean": ["maize", "barley", "fababean"],
}


def fertilizer_kg_ha(crop):
    """Total N (kg/ha) applied to a crop at the standard doses (fertilizer scale 1)."""
    return sum(kg for _, kg in CROPS[crop]["fertilizer"])
