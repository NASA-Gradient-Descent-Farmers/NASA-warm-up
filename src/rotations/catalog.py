"""Crop traits and the composite crops (milpa) used by the rotation tool."""

import unicodedata
from functools import lru_cache
from pathlib import Path

import pandas as pd

DATA = Path(__file__).parent / "tables"   # not "data/": the repo ignores data/ folders

# Milpa: maize + bean + squash on the same field. Partial land-equivalent ratios (share of each crop's
# monoculture yield). Sum 1.25, close to the 1.22 mean LER of annual intercrops in Yu et al. 2015
# (Field Crops Research 184:133-144). Evidence: low, needs local validation.
MILPA = {"maize": 0.85, "bean": 0.25, "squash_seed": 0.15}

COMPOSITES = {"milpa": MILPA}
COMPOSITE_NAMES = {"milpa": "milpa (maíz-frijol-calabaza)"}


def plain(text):
    """Lower case without accents, for matching SIAP names and farmer text."""
    text = unicodedata.normalize("NFKD", str(text).strip().casefold())
    return "".join(c for c in text if not unicodedata.combining(c))


@lru_cache(maxsize=1)
def crops():
    table = pd.read_csv(DATA / "crops.csv").set_index("key")
    table["leguminosa"] = table["leguminosa"].astype(bool)
    return table


@lru_cache(maxsize=1)
def sources():
    return pd.read_csv(DATA / "crop_sources.csv")


def siap_names():
    """plain SIAP crop name -> crop key."""
    return {plain(name): key for key, name in crops()["siap"].items()}


def name(key):
    return COMPOSITE_NAMES.get(key) or crops().loc[key, "nombre"]


def components(key):
    """{crop: partial land-equivalent ratio}; a plain crop is {crop: 1.0}."""
    return COMPOSITES.get(key, {key: 1.0})


def families(key):
    return {crops().loc[c, "familia"] for c in components(key)}


def is_known(key):
    return key in COMPOSITES or key in crops().index
