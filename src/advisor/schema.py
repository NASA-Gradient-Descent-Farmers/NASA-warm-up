"""The SiteProfile contract: every location, pilot or fallback, is described by this same structure.

Units (SI, enforced everywhere): temperature degC, rain / ET mm, elevation m, slope degrees,
soil carbon g/kg, clay / sand % (mass), N g/kg, AWC mm per 100 cm, dates UTC.
Months are always 12-element lists, index 0 = January.
"""

SCHEMA_VERSION = "0.1"

# Layers whose status is tracked in `availability` (ok | fallback | missing).
LAYERS = ["weather", "elevation", "soil", "vegetation", "soil_moisture", "extreme_rain", "water_trend"]
STATUSES = ["ok", "fallback", "missing"]


def _month_array(item_type="number"):
    return {"type": "array", "items": {"type": [item_type, "null"]}, "minItems": 12, "maxItems": 12}


SITE_PROFILE_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["schema_version", "cell_id", "location", "climate_monthly", "years_sample", "water",
                 "vegetation", "soil", "availability", "provenance"],
    "properties": {
        "schema_version": {"const": SCHEMA_VERSION},
        "cell_id": {"type": "string"},
        "location": {
            "type": "object",
            "required": ["lat", "lon", "region_id", "data_tier"],
            "properties": {
                "lat": {"type": "number", "minimum": -90, "maximum": 90},
                "lon": {"type": "number", "minimum": -180, "maximum": 180},
                "elevation_m": {"type": ["number", "null"]},
                "slope_deg": {"type": ["number", "null"]},
                "region_id": {"type": "string"},
                "data_tier": {"enum": ["A", "B"]},
            },
        },
        "climate_monthly": {
            "type": "object",
            "required": ["tmean_c", "tmin_c", "tmax_c", "rain_mm", "et0_mm", "frost_prob", "heat_days",
                         "dry_spell_days", "extreme_rain_days"],
            "properties": {key: _month_array() for key in
                           ["tmean_c", "tmin_c", "tmax_c", "rain_mm", "et0_mm", "frost_prob", "heat_days",
                            "dry_spell_days", "extreme_rain_days"]},
        },
        "years_sample": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["year", "rain_mm", "frost_days", "heat_days", "tmean_c"],
                "properties": {"year": {"type": "integer"}, **{k: _month_array() for k in
                                                               ["rain_mm", "frost_days", "heat_days", "tmean_c"]}},
            },
        },
        "climate_trend": {"type": "object"},
        "water": {
            "type": "object",
            "required": ["aridity_index", "soil_moisture_pctl", "drought_freq", "water_trend"],
            "properties": {
                "aridity_index": {"type": ["number", "null"]},
                "soil_moisture_pctl": _month_array(),
                "drought_freq": {"type": ["number", "null"]},
                "water_trend": {"type": ["number", "null"]},
            },
        },
        "vegetation": {
            "type": "object",
            "required": ["ndvi_monthly", "ndvi_p10_monthly", "bare_months"],
            "properties": {
                "ndvi_monthly": _month_array(),
                "ndvi_p10_monthly": _month_array(),
                "bare_months": {"type": "array", "items": {"type": "integer", "minimum": 1, "maximum": 12}},
            },
        },
        "soil": {
            "type": "object",
            "required": ["soc_g_kg", "clay_pct", "sand_pct", "ph", "n_g_kg", "awc_mm"],
            "properties": {k: {"type": ["number", "null"]} for k in
                           ["soc_g_kg", "clay_pct", "sand_pct", "ph", "n_g_kg", "awc_mm"]},
        },
        "availability": {
            "type": "object",
            "required": LAYERS,
            "properties": {layer: {"type": "object", "required": ["status"],
                                   "properties": {"status": {"enum": STATUSES}, "reason": {"type": "string"}}}
                           for layer in LAYERS},
        },
        "provenance": {"type": "object"},
    },
}


def empty_months():
    return [None] * 12


def validate(profile):
    """Raise jsonschema.ValidationError if `profile` breaks the contract."""
    import jsonschema

    jsonschema.validate(profile, SITE_PROFILE_SCHEMA)

