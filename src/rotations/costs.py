"""Production costs per hectare: only the farmer's own figures enter the calculations.

Open cost data for Mexico are scarce: FIRA's Agrocostos system is not downloadable, and the few public
summaries we found (tables/costs.csv) are irrigated autumn-winter crops in Sinaloa, for commercial farms
that assume high yields (e.g. 12 t/ha maize). Applying them to a smallholder, or pairing them with SIAP's
lower district yields, would mix two different farms. So the table is only a reference the assistant can
quote when it asks the farmer for their cost ("FIRA estima ... ¿el tuyo es parecido?"); without the
farmer's figure the tool reports break-even costs instead of profit.
"""

from functools import lru_cache

import numpy as np
import pandas as pd

from . import catalog


@lru_cache(maxsize=1)
def reference():
    return pd.read_csv(catalog.DATA / "costs.csv")


def cost_for(place, crop, cycle):
    """The farmer's cost for one season ({'valor', 'fuente', 'evidencia'}), or None."""
    if crop in place.costs:
        return {"valor": float(place.costs[crop]), "fuente": "tu dato", "evidencia": "alta", "url": None,
                "temporada": None}
    return None


def reference_for(place, crop, cycle):
    """A published cost for the same crop, cycle, water regime and state, to quote when asking; or None."""
    t = reference()
    hit = t[(t["crop"] == crop) & (t["cycle"] == cycle) & (t["water"] == place.water)
            & (t["state"].map(catalog.plain) == catalog.plain(place.state))]
    if hit.empty:
        return None
    row = hit.iloc[0]
    return {"cultivo": catalog.name(crop), "mxn_ha": float(row.cost_mxn_ha), "temporada": row.season,
            "rendimiento_supuesto_t_ha": float(row.yield_assumed_t_ha), "fuente": row.source, "url": row.url,
            "nota": row.nota}


def own_yield_factor(place, crop, per_sown):
    """Ratio of the farmer's normal-year yield to the district's median production per sown ha (0.2-5)."""
    if crop not in place.own_yield:
        return None
    median = float(per_sown[per_sown.index > per_sown.index.max() - 10].median())
    if not np.isfinite(median) or median <= 0:
        return None
    return float(np.clip(place.own_yield[crop] / median, 0.2, 5.0))
