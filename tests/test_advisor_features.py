import numpy as np
import pandas as pd
import pytest

from src.advisor import features, schema


def synthetic_daily(years=12, lat=20.0, seed=0):
    rng = np.random.default_rng(seed)
    index = pd.date_range("2000-01-01", periods=365 * years, freq="D")
    season = np.sin((index.day_of_year.values - 80) / 365 * 2 * np.pi)
    tmean = 15 + 6 * season + rng.normal(0, 1, len(index))
    return pd.DataFrame({
        "T2M": tmean, "T2M_MAX": tmean + 7, "T2M_MIN": tmean - 7,
        "PRECTOTCORR": np.where(rng.random(len(index)) < 0.3, rng.gamma(2, 4, len(index)), 0.0),
    }, index=index)


def test_et0_is_positive_and_seasonal():
    et0 = features.hargreaves_et0(25.0, 15.0, 32.0, 20.0, np.array([172]))
    assert 3 < float(et0[0]) < 8  # mm/day, plausible for a warm tropical day
    winter = features.hargreaves_et0(10.0, 3.0, 17.0, 50.0, np.array([355]))
    assert float(winter[0]) < 1.5


def test_lapse_rate_correction_cools_higher_sites():
    daily = synthetic_daily(1)
    corrected, shift = features.correct_temperature(daily, grid_elevation_m=2600, site_elevation_m=2200)
    assert shift == pytest.approx(2.6)
    assert (corrected["T2M"] - daily["T2M"]).mean() == pytest.approx(2.6)  # site is lower -> warmer


def test_monthly_features_shape_and_ranges():
    climate, years, trend, aridity, threshold = features.monthly_features(synthetic_daily(), 20.0)
    for key, values in climate.items():
        assert len(values) == 12, key
    assert all(0 <= p <= 1 for p in climate["frost_prob"] if p is not None)
    assert len(years) >= 10 and all(len(y["rain_mm"]) == 12 for y in years)
    assert aridity is not None and aridity > 0 and threshold > 0
    assert "tmean_c_per_decade" in trend


def test_frost_probability_detects_cold_nights():
    daily = synthetic_daily()
    daily["T2M_MIN"] = daily["T2M_MIN"] - 20  # freezing nearly all year
    climate, *_ = features.monthly_features(daily, 20.0)
    assert max(p for p in climate["frost_prob"] if p is not None) > 0.8


def test_ndvi_bare_months():
    samples = [(f"2020-{m:02d}-15", 0.15 if m in (1, 2, 3) else 0.6) for m in range(1, 13)]
    mean, p10, bare = features.ndvi_monthly(samples)
    assert bare == [1, 2, 3] and mean[5] == 0.6 and len(p10) == 12


def test_awc_rule_of_thumb_is_bounded():
    assert features.awc_from_texture(None, 30) is None
    assert 70 <= features.awc_from_texture(60, 5) <= 230
    assert features.awc_from_texture(5, 90) < features.awc_from_texture(25, 30)


def test_schema_rejects_missing_layer():
    months = [None] * 12
    profile = {
        "schema_version": schema.SCHEMA_VERSION, "cell_id": "x",
        "location": {"lat": 1, "lon": 2, "region_id": "r", "data_tier": "A"},
        "climate_monthly": {k: months for k in ["tmean_c", "tmin_c", "tmax_c", "rain_mm", "et0_mm", "frost_prob",
                                                "heat_days", "dry_spell_days", "extreme_rain_days"]},
        "years_sample": [], "water": {"aridity_index": None, "soil_moisture_pctl": months, "drought_freq": None,
                                      "water_trend": None},
        "vegetation": {"ndvi_monthly": months, "ndvi_p10_monthly": months, "bare_months": []},
        "soil": {k: None for k in ["soc_g_kg", "clay_pct", "sand_pct", "ph", "n_g_kg", "awc_mm"]},
        "availability": {l: {"status": "missing"} for l in schema.LAYERS},
        "provenance": {},
    }
    schema.validate(profile)
    del profile["availability"]["soil"]
    with pytest.raises(Exception):
        schema.validate(profile)
