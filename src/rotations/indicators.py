"""Indicators for one crop season in one place, and for a whole rotation.

A rotation is a list of years; each year has a main crop (spring-summer, `pv`) and optionally a second crop
(autumn-winter, `oi`). Every indicator is per hectare per year, averaged over the rotation's years.

| indicator | unit | how | evidence |
|---|---|---|---|
| ingreso | MXN/ha/yr | SIAP production per sown ha (last 10 yr) x SIAP price (last 5 yr median) | high (district) |
| ingreso_p10 | MXN/ha/yr | 10th percentile over historical years, at fixed recent prices | high (district) |
| riesgo | share of years | years with production per sown ha < half its median (2003-2025) | high (district) |
| agua | mm/yr | crop water need not covered by effective rain (FAO-56 Kc x POWER ET0) | medium |
| nitrogeno | kg N/ha/yr | legume fixation - N exported in harvest and removed residue; no fertilizer | low |
| carbono | t C/ha/yr | humified carbon from residues and roots left in the field | low |
| erosion | % | share of erosive rain (modified Fournier) falling on unprotected soil | medium |
| plagas | % | share of crop changes that switch plant family | rule |
| forraje | t DM/ha/yr | forage harvested + residue taken for animals | medium |
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import catalog
from .costs import cost_for

DAYS = np.array([31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])
MONTH_OF_DAY = np.repeat(np.arange(12), DAYS)          # 365 days -> month index 0..11
MONTH_NAMES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
               "noviembre", "diciembre"]
RECENT_YIELD_YEARS = 10
RECENT_PRICE_YEARS = 5
MIN_YEARS = 8
MIN_SOWN_HA = 10.0
BAD_YEAR = 0.5            # a bad year: production per sown ha below half its median
C_FRACTION = 0.45         # carbon share of plant dry matter
HUMIFIED = {"above": 0.15, "below": 0.40}   # Mattila & Rajala crop rotation tool (Zenodo 10256220)
BELOWGROUND_N = 1.5       # whole-plant N / shoot N for legumes (literature range ~1.3-2.0)

# Residue management: share of the above-ground residue that leaves the field.
RESIDUE = {"dejar": 0.0, "pastoreo": 0.5, "sacar": 0.8, "quemar": 1.0}
RESIDUE_LABELS = {"dejar": "se deja en la parcela", "pastoreo": "se pastorea", "sacar": "se saca para forraje o venta",
                  "quemar": "se quema"}
EVIDENCE_RANK = {"alta": 3, "media": 2, "baja": 1, "regla": 1, "sin datos": 0}


@dataclass
class Place:
    state_id: int
    ddr: int
    state: str
    ddr_name: str
    water: str                       # "temporal" or "riego"
    climate: pd.DataFrame            # 12 rows, month 1..12
    siap: pd.DataFrame               # SIAP rows for the whole country, with outcomes
    climate_years: pd.DataFrame | None = None   # year x month rain and ET0, 2001-2025
    municipality: str | None = None
    sowing_month: int | None = None  # farmer's main sowing month (1-12), overrides the rain-based default
    soil_water_mm_m: float = 120.0   # plant-available water per metre of soil (loam; ~70 sand, ~170 clay loam)
    notes: list = field(default_factory=list)
    costs: dict = field(default_factory=dict)       # crop key -> farmer's cost, MXN/ha per season
    own_yield: dict = field(default_factory=dict)   # crop key -> farmer's normal-year yield, t/ha
    observed: pd.DataFrame | None = None            # 12 rows: MODIS NDVI and SMAP root-zone moisture by month

    @property
    def lgp(self):
        """FAO agro-ecological zones growing period: months with rain >= half of ET0 (from April on)."""
        wet = (self.climate["rain"] >= 0.5 * self.climate["et0"]).to_numpy()
        start = next((m for m in range(3, 10) if wet[m]), None)
        if start is None:
            return None
        end = start
        while end + 1 < 12 and wet[end + 1]:
            end += 1
        return start, end            # month indices 0..11


# --- SIAP history ----------------------------------------------------------------------------------

NICHE_SHARE = 0.01        # a crop sown on <1% of the area of the district's main crop is a niche crop


def district_largest_crop(place, cycle):
    """(crop, mean sown ha over the last 10 years) of the district's largest crop in this cycle and regime."""
    t = place.siap
    t = t[(t["state_id"] == place.state_id) & (t["ddr"] == place.ddr) & (t["cycle"] == cycle)
          & (t["water"] == place.water) & (t["year"] > t["year"].max() - RECENT_YIELD_YEARS)]
    if t.empty:
        return None
    area = t.groupby("crop")["sown_ha"].sum() / RECENT_YIELD_YEARS
    return area.idxmax(), float(area.max())


def history(place, crop, cycle):
    """Yearly SIAP outcomes for a crop at the most local level with enough years: district, state, nation."""
    t = place.siap
    t = t[(t["crop"] == crop) & (t["cycle"] == cycle) & (t["water"] == place.water)]
    levels = [("distrito", "alta", t[(t["state_id"] == place.state_id) & (t["ddr"] == place.ddr)]),
              ("estado", "media", t[t["state_id"] == place.state_id]),
              ("nacional", "baja", t)]
    for level, evidence, rows in levels:
        years = rows.groupby("year")[["sown_ha", "production_t", "value_mxn", "lost_ha", "harvested_ha"]].sum()
        years = years[years["sown_ha"] >= MIN_SOWN_HA]
        if len(years) >= MIN_YEARS:
            return _summarize(years, level, evidence)
    return None


def _summarize(years, level, evidence):
    per_sown = years["production_t"] / years["sown_ha"]
    price = (years["value_mxn"] / years["production_t"].where(years["production_t"] > 0)).dropna()
    last = years.index.max()
    recent = per_sown[per_sown.index > last - RECENT_YIELD_YEARS]
    return {
        "level": level, "evidence": evidence, "years": int(len(years)),
        "sown_ha": float(years["sown_ha"][years.index > last - RECENT_YIELD_YEARS].mean()),
        "per_sown": per_sown,                                   # t per sown ha by year
        "expected": float(recent.mean()),                       # t per sown ha, recent
        "failure": float((years["lost_ha"] / years["sown_ha"]).clip(0, 1).mean()),
        "price": float(price[price.index > last - RECENT_PRICE_YEARS].median()) if len(price) else np.nan,
    }


# --- Calendar and water ----------------------------------------------------------------------------

def stage_lengths(place, crop, sow_day):
    """FAO-56 stage lengths scaled by temperature: longer in cool places, shorter in warm ones (crops.csv t_ref, t_base)."""
    c = catalog.crops().loc[crop]
    nominal = np.array([c.d_ini, c.d_des, c.d_med, c.d_fin], float)
    tmean = ((place.climate["tmin"] + place.climate["tmax"]) / 2).to_numpy()
    days = (sow_day + np.arange(int(nominal.sum()))) % 365
    t_season = tmean[MONTH_OF_DAY[days]].mean()
    factor = np.clip((c.t_ref - c.t_base) / max(t_season - c.t_base, 0.1), 0.8, 1.6)
    return np.round(nominal * factor).astype(int), float(factor)


def kc_curve(crop, lengths):
    c = catalog.crops().loc[crop]
    ini, dev, mid, late = lengths
    return np.concatenate([np.full(ini, c.kc_ini), np.linspace(c.kc_ini, c.kc_med, dev, endpoint=False),
                           np.full(mid, c.kc_med), np.linspace(c.kc_med, c.kc_fin, late)])


def effective_rain(monthly_mm):
    """USDA-SCS monthly effective rainfall, as used in FAO CROPWAT."""
    p = np.asarray(monthly_mm, float)
    return np.where(p <= 250, p * (125 - 0.2 * p) / 125, 125 + 0.1 * p)


def sowing_day(place, cycle, after_day=None):
    """Day of year (0-364) a season starts."""
    lgp = place.lgp
    if cycle == "pv":
        if place.sowing_month:
            day = int(DAYS[:place.sowing_month - 1].sum()) + 10
        elif place.water == "riego":
            day = 120                                                # ~May 1
        elif lgp is None:
            day = 181                                                # July 1; flagged by the caller
        else:
            day = int(DAYS[:lgp[0]].sum()) + 10
    else:
        day = 325 if place.water == "riego" else (int(DAYS[:lgp[1] + 1].sum()) % 365 if lgp else 305)
    if after_day is not None and _days_between(after_day, day) < 7:
        day = (after_day + 7) % 365
    return day


def _days_between(a, b):
    return (b - a) % 365


@dataclass
class Season:
    crop: str                    # crop key or "milpa"
    cycle: str
    sow_day: int
    length: int
    occupancy: np.ndarray        # 365 days, canopy cover 0..1
    etc_month: np.ndarray        # mm by month
    present_month: np.ndarray    # share of each month in the field
    frost: float                 # share of years with a night <= 2 °C while a frost-sensitive crop is in the field
    heat_days: float             # days >= 35 °C during the middle of the season (heat-sensitive crops)
    stretch: float               # stage-length factor (temperature)

    @property
    def harvest_day(self):
        return (self.sow_day + self.length) % 365


def season(place, crop, cycle, after_day=None):
    parts = catalog.components(crop)
    lead = max(parts, key=parts.get)                                # milpa follows maize
    sow = sowing_day(place, cycle, after_day)
    lengths, stretch = stage_lengths(place, lead, sow)
    kc = kc_curve(lead, lengths)
    if crop in catalog.COMPOSITES:                                   # squash guides keep the canopy longer
        kc = np.maximum(kc, 0.9 * kc.max() * (np.arange(len(kc)) > lengths[0]))
        kc[-lengths[3]:] = np.linspace(kc[-lengths[3]], catalog.crops().loc[lead, "kc_fin"], lengths[3])
    days = (sow + np.arange(len(kc))) % 365
    et0_day = (place.climate["et0"].to_numpy() / DAYS)[MONTH_OF_DAY]
    etc_month = np.bincount(MONTH_OF_DAY[days], weights=kc * et0_day[days], minlength=12)
    present = np.bincount(MONTH_OF_DAY[days], minlength=12) / DAYS
    occupancy = np.zeros(365)
    cover = np.concatenate([np.linspace(0.1, 0.3, lengths[0]), np.linspace(0.3, 1.0, lengths[1]),
                            np.ones(lengths[2]), np.linspace(1.0, 0.6, lengths[3])])
    occupancy[days] = np.maximum(occupancy[days], cover)

    c = catalog.crops().loc[list(parts)]
    # Frost matters until the grain fills: count months up to the middle of the late stage.
    sensitive = days[: lengths[0] + lengths[1] + lengths[2] + lengths[3] // 2]
    months = np.flatnonzero(np.bincount(MONTH_OF_DAY[sensitive], minlength=12) >= 10)
    frost = 0.0
    if (c["helada"] == 0).any():
        frost = float(place.climate["frost_prob"].to_numpy()[months].max()) if len(months) else 0.0
    elif (c["helada"] == 1).any():
        frost = 0.5 * float(place.climate["frost_prob"].to_numpy()[months].max()) if len(months) else 0.0
    mid = days[lengths[0] + lengths[1]: lengths[0] + lengths[1] + lengths[2]]
    heat = 0.0
    if (c["calor"] < 2).any() and len(mid):
        heat = float(np.bincount(MONTH_OF_DAY[mid], minlength=12) @ (place.climate["heat_days"].to_numpy() / DAYS))
    return Season(crop, cycle, sow, len(kc), occupancy, etc_month, present, frost, heat, stretch)


def water_deficit(place, seasons, rain=None, et0=None):
    """mm of crop water need not covered by effective rain (irrigation need under riego).

    A winter crop sown on residual moisture under temporal starts with a full root zone, which is credited.
    `rain` / `et0` are 12 monthly values for one year (default: the normals); ETc scales with that year's ET0.
    """
    normal_et0 = place.climate["et0"].to_numpy()
    rain = place.climate["rain"].to_numpy() if rain is None else np.asarray(rain, float)
    scale = np.ones(12) if et0 is None else np.asarray(et0, float) / np.maximum(normal_et0, 1e-6)
    peff = effective_rain(rain)
    total = demand = 0.0
    for s in seasons:
        etc = s.etc_month * scale
        deficit = np.maximum(etc - peff * s.present_month, 0).sum()
        if s.cycle == "oi" and place.water == "temporal":
            depth = max(catalog.crops().loc[c, "raiz_m"] for c in catalog.components(s.crop))
            deficit = max(deficit - depth * place.soil_water_mm_m * stored_fraction(place, s), 0.0)
        total += deficit
        demand += etc.sum()
    return total, demand


def stored_fraction(place, s):
    """Share of the root zone's available water present at sowing: SMAP relative wetness, else full."""
    from .observed import relative_moisture

    value = relative_moisture(place.observed, int(MONTH_OF_DAY[s.sow_day]) + 1)
    return 1.0 if value is None else value


def water_by_year(place, seasons):
    """Deficit in each historical year (2001-2025), mm; the normals when yearly climate is missing."""
    if place.climate_years is None or place.climate_years.empty:
        return pd.DataFrame([water_deficit(place, seasons)], columns=["deficit", "demand"])
    out = {}
    for year, g in place.climate_years.groupby("year"):
        g = g.sort_values("month")
        if len(g) == 12:
            out[year] = water_deficit(place, seasons, g["rain"].to_numpy(), g["et0"].to_numpy())
    return pd.DataFrame.from_dict(out, orient="index", columns=["deficit", "demand"])


# --- Per-season production, nitrogen, carbon, forage ------------------------------------------------

def production(place, crop, cycle):
    """Expected t per sown ha of each component, its history and price; milpa scales by partial LER."""
    from .costs import own_yield_factor

    out = {}
    for part, share in catalog.components(crop).items():
        h = history(place, part, cycle)
        if h is None:
            return None
        # The farmer's sole-crop yield sets the level (also for that crop inside milpa, whose shares are
        # relative to sole crops); SIAP keeps the year-to-year pattern.
        factor = own_yield_factor(place, part, h["per_sown"])
        if factor is not None:
            h = {**h, "per_sown": h["per_sown"] * factor, "expected": h["expected"] * factor}
        out[part] = {"share": share, "own_yield_factor": factor, **h}
    return out


def nutrient_carbon(crop, prod, residue_removed):
    """kg N balance, t humified C and t DM forage per ha for one season."""
    traits = catalog.crops()
    n_bal = c_hum = forage = 0.0
    for part, p in prod.items():
        t = traits.loc[part]
        harvest = p["share"] * p["expected"]                       # as reported (fresh for forages)
        harvest_dm = harvest * t.ms_producto
        residue_dm = t.res_pendiente * harvest_dm + t.res_intercepto * p["share"]
        roots_dm = t.raiz_ratio * (harvest_dm + residue_dm)
        n_harvest = harvest * t.n_producto_kg_t
        n_residue_out = residue_dm * residue_removed * t.n_residuo * 1000
        fixed = 0.0
        if t.leguminosa:
            fixed = t.ndfa * (n_harvest / t.nhi) * BELOWGROUND_N
        n_bal += fixed - n_harvest - n_residue_out
        kept_above = residue_dm * (1 - residue_removed)
        c_hum += C_FRACTION * (kept_above * HUMIFIED["above"] + roots_dm * HUMIFIED["below"])
        forage += harvest_dm if t.uso == "forraje" else residue_dm * residue_removed * t.forraje_residuo
    return n_bal, c_hum, forage


# --- Rotation-level indicators ------------------------------------------------------------------

def plan_seasons(place, rotation):
    """Seasons of each rotation year, the winter crop sown after the summer harvest."""
    years = []
    for year in rotation:
        pv = season(place, year["pv"], "pv") if year.get("pv") else None
        oi = None
        if year.get("oi"):
            oi = season(place, year["oi"], "oi", after_day=pv.harvest_day if pv else None)
        years.append([s for s in (pv, oi) if s is not None])
    return years


def erosion_exposure(place, years, residue_removed):
    """Share of erosive rain (modified Fournier, p_m^2 / P) that falls on unprotected soil.

    Living canopy protects in proportion to its cover; residue left in the field protects ~half as well
    until the next crop's canopy closes.
    """
    rain = place.climate["rain"].to_numpy()
    erosive = rain ** 2 / max(rain.sum(), 1)
    shares = []
    for seasons in years:
        canopy = np.zeros(365)
        for s in seasons:
            canopy = np.maximum(canopy, s.occupancy)
        residue_cover = 0.5 * (1 - residue_removed) if any(_has_residue(s.crop) for s in seasons) else 0.0
        protected = np.maximum(canopy, residue_cover)
        monthly = np.bincount(MONTH_OF_DAY, weights=protected, minlength=12) / DAYS
        shares.append(float((erosive * (1 - monthly)).sum() / max(erosive.sum(), 1e-9)))
    return float(np.mean(shares))


def _has_residue(crop):
    t = catalog.crops()
    return any(t.loc[p, "uso"] != "forraje" for p in catalog.components(crop))


def family_breaks(rotation):
    """Share of consecutive crops (cyclic) that switch plant family.

    A change to a crop of another family counts 1; a change that keeps some families, or repeating a mixed
    crop such as milpa (several families on the field at once), counts 0.5; repeating one family counts 0.
    """
    sequence = [c for year in rotation for c in (year.get("pv"), year.get("oi")) if c]
    if not sequence:
        return 0.0
    scores = []
    for a, b in zip(sequence, sequence[1:] + sequence[:1]):
        fa, fb = catalog.families(a), catalog.families(b)
        if not fa & fb:
            scores.append(1.0)
        elif fa != fb or len(fb) > 1:
            scores.append(0.5)
        else:
            scores.append(0.0)
    return float(np.mean(scores))


def bare_months(years):
    """Months (1-12) with less than 30% canopy in every rotation year."""
    canopy = np.zeros((len(years), 365))
    for i, seasons in enumerate(years):
        for s in seasons:
            canopy[i] = np.maximum(canopy[i], s.occupancy)
    monthly = np.stack([np.bincount(MONTH_OF_DAY, weights=c, minlength=12) / DAYS for c in canopy])
    return [m + 1 for m in range(12) if (monthly[:, m] < 0.3).all()]


def income_series(prod):
    """MXN per sown ha by historical year at fixed recent prices, summed over components."""
    series = None
    for part, p in prod.items():
        s = p["share"] * p["per_sown"] * p["price"]
        series = s if series is None else series.add(s, fill_value=np.nan)
    return series.dropna()


def evaluate(place, rotation, residue="dejar"):
    """All indicators for a rotation, with the evidence behind each."""
    removed = RESIDUE[residue]
    years = plan_seasons(place, rotation)
    seasons = [s for y in years for s in y]
    gaps, warnings = [], []
    yearly_income, evidence_levels, n_total, c_total, forage_total = [], [], 0.0, 0.0, 0.0
    per_season = []
    for s in seasons:
        prod = production(place, s.crop, s.cycle)
        if prod is None:
            gaps.append(f"Sin registros de SIAP de {catalog.name(s.crop)} ({_cycle(s.cycle)}, {place.water}) "
                        "ni en el distrito, ni en el estado ni a nivel nacional")
            per_season.append({"season": s, "prod": None})
            continue
        income = income_series(prod)
        yearly_income.append(income)
        n, c, f = nutrient_carbon(s.crop, prod, removed)
        n_total, c_total, forage_total = n_total + n, c_total + c, forage_total + f
        levels = {p["level"] for p in prod.values()}
        evidence_levels.append(min((p["evidence"] for p in prod.values()), key=EVIDENCE_RANK.get))
        per_season.append({"season": s, "prod": prod, "levels": levels, "cost": cost_for(place, s.crop, s.cycle),
                           "income_mean": float(income.mean())})
        if s.frost >= 0.2:
            warnings.append(f"{catalog.name(s.crop).capitalize()}: en {s.frost:.0%} de los años hubo al menos una noche "
                            f"≤2 °C mientras el cultivo estaría en campo (sembrando en {MONTH_NAMES[MONTH_OF_DAY[s.sow_day]]})")
        biggest = district_largest_crop(place, s.cycle)
        for part, p in prod.items():
            if p["level"] != "distrito" or biggest is None or part == biggest[0]:
                continue
            if p["sown_ha"] < 100 or p["sown_ha"] < NICHE_SHARE * biggest[1]:
                warnings.append(
                    f"{catalog.name(part).capitalize()}: en tu distrito se siembran ~{p['sown_ha']:,.0f} ha al año "
                    f"(contra ~{biggest[1]:,.0f} ha de {catalog.name(biggest[0])}). Es un cultivo de nicho: quizá solo "
                    "se da en algunas partes del distrito, su rendimiento viene de esas parcelas y el mercado es chico")
        if s.cycle == "oi" and place.water == "temporal" and place.observed is not None:
            from .observed import relative_moisture
            wet = relative_moisture(place.observed, int(MONTH_OF_DAY[s.sow_day]) + 1)
            if wet is not None and wet < 0.3:
                warnings.append(f"{catalog.name(s.crop).capitalize()}: según SMAP (NASA), en "
                                f"{MONTH_NAMES[MONTH_OF_DAY[s.sow_day]]} el suelo de tu zona suele estar casi seco "
                                f"({wet:.0%} entre lo más seco y lo más húmedo de 2015-2025); sembrar con humedad "
                                "residual es arriesgado sin riego de auxilio")
        if s.heat_days >= 3:
            warnings.append(f"{catalog.name(s.crop).capitalize()}: ~{s.heat_days:.0f} días ≥35 °C a mitad del ciclo en un año típico")

    n_years = len(rotation)
    combined = _rotation_income(yearly_income, years, per_season)
    water = water_by_year(place, seasons)
    deficit = water["deficit"] / n_years
    coverage = 1 - water["deficit"] / water["demand"].where(water["demand"] > 0)
    result = {
        "ingreso": float(combined.mean()) if combined is not None else np.nan,
        "ingreso_p10": float(combined.quantile(0.1)) if combined is not None else np.nan,
        "riesgo": _bad_year_share(per_season),
        "agua": float(deficit.median()),
        "agua_seco": float(deficit.quantile(0.8)),
        "agua_cubierta": float(coverage.quantile(0.2)),     # share of crop water need met by rain, dry year
        "nitrogeno": n_total / n_years,
        "carbono": c_total / n_years,
        "erosion": erosion_exposure(place, years, removed),
        "plagas": family_breaks(rotation),
        "forraje": forage_total / n_years,
    }
    costs = [item.get("cost") for item in per_season if item["prod"] is not None]
    known = [c["valor"] for c in costs if c]
    cost_per_year = sum(known) / n_years if known else 0.0
    net = None
    if combined is not None and costs and all(costs):
        net = combined - cost_per_year
        result.update({"ganancia": float(net.mean()), "ganancia_p10": float(net.quantile(0.1)),
                       "prob_perdida": float((net < 0).mean())})
    else:
        result.update({"ganancia": np.nan, "ganancia_p10": np.nan, "prob_perdida": np.nan})
    if combined is not None:     # most a hectare can cost per year: on average, and to not lose in 8 of 10 years
        result.update({"costo_equilibrio": float(combined.mean()), "costo_equilibrio_8de10": float(combined.quantile(0.2))})
    evidence = min(evidence_levels, key=EVIDENCE_RANK.get) if evidence_levels else "sin datos"
    return {"values": result, "income_by_year": combined, "net_by_year": net, "cost_per_year": cost_per_year,
            "missing_costs": sorted({item["season"].crop for item in per_season if item["prod"] is not None and not item["cost"]}),
            "seasons": per_season, "years": years,
            "bare_months": bare_months(years), "gaps": gaps, "warnings": sorted(set(warnings)),
            "siap_evidence": evidence}


def _rotation_income(yearly_income, years, per_season):
    """Mean income per rotation year in each historical year (as if every season had that year's weather)."""
    if not yearly_income:
        return None
    frame = pd.concat(yearly_income, axis=1)
    frame = frame.dropna() if frame.dropna().shape[0] >= MIN_YEARS else frame
    return frame.sum(axis=1, min_count=1).dropna() / len(years)


def _bad_year_share(per_season):
    shares = []
    for item in per_season:
        if item["prod"] is None:
            continue
        income = income_series(item["prod"])
        shares.append(float((income < BAD_YEAR * income.median()).mean()))
    return float(np.mean(shares)) if shares else np.nan


def _cycle(cycle):
    return {"pv": "primavera-verano", "oi": "otoño-invierno"}[cycle]
