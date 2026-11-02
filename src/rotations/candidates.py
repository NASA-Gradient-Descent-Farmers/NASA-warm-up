"""Rotation text parsing and the alternative rotations proposed for a place.

Alternatives use only crops with a SIAP record in the farmer's district (same cycle and water regime), so the
climate, the market and the know-how for them already exist locally. Each alternative comes from a template
that names why it is proposed.
"""

import re

from . import catalog
from .indicators import NICHE_SHARE, district_largest_crop, history, plan_seasons, water_deficit

ALIASES = {
    "maiz": "maize", "maiz grano": "maize", "elote": "maize", "frijol": "bean", "sorgo": "sorghum",
    "trigo": "wheat", "cebada": "barley", "avena": "oats", "avena grano": "oats", "avena forrajera": "oats_forage",
    "maiz forrajero": "maize_forage", "ensilado": "maize_forage", "sorgo forrajero": "sorghum_forage",
    "haba": "faba", "garbanzo": "chickpea", "cacahuate": "peanut", "mani": "peanut", "soya": "soybean",
    "soja": "soybean", "espelon": "cowpea", "frijol x pelon": "cowpea", "frijol pelon": "cowpea", "caupi": "cowpea",
    "ebo": "vetch", "veza": "vetch", "janamargo": "vetch", "calabaza": "squash_seed", "pipian": "squash_seed",
    "ajonjoli": "sesame", "sesamo": "sesame", "amaranto": "amaranth", "cartamo": "safflower", "milpa": "milpa",
}
ALIASES.update({k: k for k in catalog.crops().index})
FALLOW = {"descanso", "nada", "barbecho", "sin cultivo", "ninguno"}


def crop_key(text):
    key = catalog.plain(text).replace("_", " ").strip()
    if key in ALIASES:
        return ALIASES[key]
    key = key.replace(" ", "_")
    if catalog.is_known(key):
        return key
    raise ValueError(f"No reconozco el cultivo '{text}'")


def parse_rotation(text):
    """'maíz - frijol', 'maiz/garbanzo, sorgo' -> [{'pv': 'maize', 'oi': 'chickpea'}, {'pv': 'sorghum'}].

    Years are separated by '-', ',', ';' or '→'; '/' separates the spring-summer crop from the winter crop.
    """
    if isinstance(text, list):
        return [{k: v for k, v in year.items() if v} for year in text]
    years = []
    for chunk in re.split(r"\s*(?:->|→|,|;|\s-\s|-)\s*", text.strip()):
        if not chunk:
            continue
        parts = [p.strip() for p in chunk.split("/")]
        year = {}
        for cycle, part in zip(("pv", "oi"), parts):
            if part and catalog.plain(part) not in FALLOW:
                year[cycle] = crop_key(part)
        years.append(year)
    if not years or not any(years):
        raise ValueError("La rotación está vacía")
    return years


def describe(rotation):
    out = []
    for i, year in enumerate(rotation, 1):
        if year.get("pv") and year.get("oi"):
            text = f"{catalog.name(year['pv'])} y después {catalog.name(year['oi'])} (otoño-invierno)"
        elif year.get("pv"):
            text = catalog.name(year["pv"])
        elif year.get("oi"):
            text = f"{catalog.name(year['oi'])} (otoño-invierno)"
        else:
            text = "descanso"
        out.append(f"Año {i}: {text}")
    return " → ".join(out) if len(out) > 1 else out[0] + " (cada año)"


def assign_cycles(place, rotation):
    """Move a crop given without a cycle to autumn-winter when the district grows it mostly then.

    In irrigated Sinaloa or Sonora, 'maíz' means the autumn-winter crop; in rainfed central Mexico it means
    spring-summer. Only single-crop years are moved.
    """
    out = []
    for year in rotation:
        if set(year) == {"pv"} and year["pv"] not in catalog.COMPOSITES:
            pv, oi = history(place, year["pv"], "pv"), history(place, year["pv"], "oi")
            pv_ha = pv["sown_ha"] if pv and pv["level"] == "distrito" else 0.0
            oi_ha = oi["sown_ha"] if oi and oi["level"] == "distrito" else 0.0
            if oi_ha > 2 * pv_ha:
                out.append({"oi": year["pv"]})
                continue
        out.append(dict(year))
    return out


def signature(rotation):
    """Rotations equal up to a cyclic shift have the same signature."""
    seq = [tuple(sorted(y.items())) for y in rotation]
    shifts = [tuple(seq[i:] + seq[:i]) for i in range(len(seq))]
    return min(shifts)


def local_crops(place, cycle, min_ha=100.0, niche=False):
    """Crops with a district-level SIAP history for this cycle and water regime, largest area first.

    Crops sown on less than `min_ha` or less than NICHE_SHARE of the district's largest crop are niche crops:
    returned only with niche=True (they may fit only part of the district, and their market is small).
    """
    biggest = district_largest_crop(place, cycle)
    floor = max(min_ha, NICHE_SHARE * biggest[1]) if biggest else min_ha
    out = []
    for crop in catalog.crops().index:
        h = history(place, crop, cycle)
        if h and h["level"] == "distrito" and (h["sown_ha"] < floor) == niche and h["sown_ha"] >= 10:
            out.append((crop, h))
    return sorted(out, key=lambda x: -x[1]["sown_ha"])


def niche_crops(place, current):
    """Spanish lines naming the district's niche crops not in the current rotation."""
    in_current = {c for y in current for c in y.values()}
    lines = []
    for cycle in ("pv", "oi"):
        for crop, h in local_crops(place, cycle, niche=True):
            if crop not in in_current:
                lines.append(f"{catalog.name(crop)} ({'primavera-verano' if cycle == 'pv' else 'otoño-invierno'}): "
                             f"~{h['sown_ha']:,.0f} ha al año")
    return lines


def _income(h):
    return h["expected"] * h["price"]


def generate(place, current, has_animals=False):
    """[(template, rotation)] alternatives to `current`.

    The main cycle is the one the current rotation uses most (spring-summer unless every crop is in
    autumn-winter); alternatives swap crops within that cycle or add a crop in the other one.
    """
    traits = catalog.crops()
    main_cycle = "pv" if any(y.get("pv") for y in current) else "oi"
    other = "oi" if main_cycle == "pv" else "pv"
    local = {"pv": local_crops(place, "pv"), "oi": local_crops(place, "oi")}
    mains = [y[main_cycle] for y in current if y.get(main_cycle)]
    keys = [c for c, _ in local[main_cycle]]
    main = max(mains, key=mains.count) if mains else (keys[0] if keys else None)
    if main is None:
        return []
    main_single = main if main not in catalog.COMPOSITES else "maize"
    in_current = {c for y in current for c in y.values()}
    pool = [(c, h) for c, h in local[main_cycle] if c not in in_current]
    two_year = lambda c: [{main_cycle: main_single}, {main_cycle: c}]
    out = []

    legumes = [(c, h) for c, h in pool if traits.loc[c, "leguminosa"] and traits.loc[c, "uso"] == "grano"]
    for c, h in sorted(legumes, key=lambda x: -_income(x[1]))[:2]:
        out.append(("leguminosa", two_year(c)))

    if main_cycle == "pv" and {"maize", "bean"} <= set(keys) and "milpa" not in in_current:
        out.append(("milpa", [{**y, "pv": "milpa"} if y.get("pv") == "maize" else dict(y) for y in current]
                    if "maize" in in_current else [{"pv": "milpa"}]))

    if place.water == "riego":                      # irrigated: the crop that needs the least irrigation
        def need(rotation):
            years = plan_seasons(place, rotation)
            return water_deficit(place, [s for y in years for s in y])[0] / len(rotation)
        now = need(current)
        options = [[{main_cycle: c}, {main_cycle: main_single}] for c, h in pool if traits.loc[c, "uso"] == "grano"]
        options = [(r, need(r)) for r in options]
        options = [x for x in options if x[1] < 0.9 * now]
        if options:
            out.append(("menos_agua", min(options, key=lambda x: x[1])[0]))
    else:                                           # rainfed: a more drought-tolerant crop
        tolerant = [(c, h) for c, h in pool if traits.loc[c, "sequia"] > traits.loc[main_single, "sequia"]
                    and traits.loc[c, "uso"] == "grano"]
        if tolerant:
            c = max(tolerant, key=lambda x: x[1]["sown_ha"])[0]
            out.append(("sequia", [{main_cycle: c}, {main_cycle: main_single}]))

    second = [(c, h) for c, h in local[other] if c not in in_current]
    if second and all(not y.get(other) for y in current):
        legume_2 = [x for x in second if traits.loc[x[0], "leguminosa"]]
        pick = (legume_2 or second)[0][0]
        out.append(("invierno" if other == "oi" else "verano", [{**y, other: pick} for y in current]))
        forage_2 = [x for x in second if traits.loc[x[0], "uso"] == "forraje"]
        if has_animals and forage_2 and forage_2[0][0] != pick:
            out.append(("forraje", [{**y, other: forage_2[0][0]} for y in current]))

    forage = [(c, h) for c, h in pool if traits.loc[c, "uso"] == "forraje"]
    if has_animals and forage:
        out.append(("forraje", two_year(forage[0][0])))

    grains = [(c, h) for c, h in pool if traits.loc[c, "uso"] == "grano"]
    if grains:
        out.append(("ingreso", two_year(max(grains, key=lambda x: _income(x[1]))[0])))

    seen, unique = {signature(current)}, []
    for template, rotation in out:
        if signature(rotation) not in seen:
            seen.add(signature(rotation))
            unique.append((template, rotation))
    return unique
