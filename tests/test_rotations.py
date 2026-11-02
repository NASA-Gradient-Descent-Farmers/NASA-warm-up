"""Tests for the rotation comparison tool (src/rotations). Synthetic data except the last test, which runs on
the built tables when they exist (python -m src.rotations.build)."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.rotations import candidates, catalog, climate, indicators, scoring
from src.rotations.indicators import Place


def test_crop_table_is_complete():
    t = catalog.crops()
    numeric = ["ms_producto", "kc_ini", "kc_med", "kc_fin", "d_ini", "d_des", "d_med", "d_fin", "raiz_m",
               "n_producto_kg_t", "res_pendiente", "res_intercepto", "raiz_ratio", "n_residuo"]
    assert t[numeric].notna().all().all()
    assert t.loc[t["leguminosa"], ["ndfa", "nhi"]].notna().all().all()
    assert set(catalog.MILPA) <= set(t.index)
    assert len(set(t["siap"].map(catalog.plain))) == len(t)


def test_parse_rotation():
    assert candidates.parse_rotation("maíz - frijol") == [{"pv": "maize"}, {"pv": "bean"}]
    assert candidates.parse_rotation("Maiz/Garbanzo, sorgo") == [{"pv": "maize", "oi": "chickpea"}, {"pv": "sorghum"}]
    assert candidates.parse_rotation("milpa") == [{"pv": "milpa"}]
    assert candidates.parse_rotation("avena forrajera→haba") == [{"pv": "oats_forage"}, {"pv": "faba"}]
    with pytest.raises(ValueError):
        candidates.parse_rotation("mango")


def test_signature_ignores_cyclic_shift():
    a = [{"pv": "maize"}, {"pv": "bean"}]
    assert candidates.signature(a) == candidates.signature(a[::-1])
    assert candidates.signature(a) != candidates.signature([{"pv": "maize"}])


def test_family_breaks():
    assert indicators.family_breaks([{"pv": "maize"}]) == 0.0
    assert indicators.family_breaks([{"pv": "maize"}, {"pv": "bean"}]) == 1.0
    assert indicators.family_breaks([{"pv": "maize"}, {"pv": "sorghum"}]) == 0.0
    assert indicators.family_breaks([{"pv": "milpa"}]) == 0.5


def test_effective_rain_matches_usda_scs():
    assert indicators.effective_rain([0])[0] == 0
    assert indicators.effective_rain([100])[0] == pytest.approx(84.0)
    assert indicators.effective_rain([300])[0] == pytest.approx(155.0)


def test_et0_is_plausible():
    days = pd.date_range("2020-07-01", periods=5)
    daily = pd.DataFrame({"T2M_MAX": 30.0, "T2M_MIN": 15.0, "RH2M": 55.0, "ALLSKY_SFC_SW_DWN": 22.0}, index=days)
    et0 = climate.et0_penman_monteith(daily, 20.5, 1750)
    assert ((et0 > 3.5) & (et0 < 6.5)).all()


def test_scales_and_weights():
    assert scoring.scale("riesgo", 0.0) == 100 and scoring.scale("riesgo", 0.4) == 0
    assert scoring.scale("ingreso", 1e9) == 100
    w = scoring.weights(["agua"])
    assert w["agua"] == scoring.PRIORITY_WEIGHT and w["ingreso"] == 1.0


def test_paired_difference_detects_a_clear_gain():
    years = pd.Index(range(2003, 2026))
    base = pd.Series(np.random.default_rng(0).normal(10000, 2000, len(years)), index=years)
    better = base + 3000
    d = scoring.paired_difference(better, base)
    assert d["clara"] and d["media"] == pytest.approx(3000)
    assert not scoring.paired_difference(base, base)["clara"]


def synthetic_place(water="temporal"):
    month = np.arange(1, 13)
    rain = np.array([5, 5, 5, 10, 40, 120, 150, 140, 120, 50, 10, 5], float)
    clim = pd.DataFrame({"month": month, "rain": rain, "et0": np.full(12, 130.0), "tmin": np.full(12, 12.0),
                         "tmax": np.full(12, 28.0), "frost_prob": [0.3, 0.2] + [0.0] * 8 + [0.1, 0.3],
                         "frost_nights": 0.0, "heat_days": 0.0, "rain_p20": rain * 0.7})
    rows = []
    rng = np.random.default_rng(1)
    for year in range(2003, 2026):
        for crop, t_ha, price in [("maize", 2.5, 5000), ("bean", 0.8, 16000), ("squash_seed", 0.5, 30000),
                                  ("sorghum", 3.0, 4000)]:
            sown = 1000.0
            prod = sown * t_ha * rng.uniform(0.4, 1.3)
            rows.append({"year": year, "state_id": 1, "ddr": 1, "crop": crop, "cycle": "pv", "water": water,
                         "sown_ha": sown, "harvested_ha": sown * 0.95, "lost_ha": sown * 0.05, "production_t": prod,
                         "value_mxn": prod * price})
        prod = 1000 * 1.0
        rows.append({"year": year, "state_id": 1, "ddr": 1, "crop": "chickpea", "cycle": "oi", "water": water,
                     "sown_ha": 500.0, "harvested_ha": 500.0, "lost_ha": 0.0, "production_t": 500.0,
                     "value_mxn": 500.0 * 9000})
    return Place(state_id=1, ddr=1, state="Prueba", ddr_name="Prueba", water=water, climate=clim,
                 siap=pd.DataFrame(rows))


def test_evaluate_rotation_on_synthetic_place():
    place = synthetic_place()
    mono = indicators.evaluate(place, [{"pv": "maize"}])
    legume = indicators.evaluate(place, [{"pv": "maize"}, {"pv": "bean"}])
    winter = indicators.evaluate(place, [{"pv": "maize", "oi": "chickpea"}])
    assert mono["siap_evidence"] == "alta" and not mono["gaps"]
    assert legume["values"]["nitrogeno"] > mono["values"]["nitrogeno"]
    assert legume["values"]["plagas"] == 1.0 and mono["values"]["plagas"] == 0.0
    assert winter["values"]["ingreso"] > mono["values"]["ingreso"]
    assert len(winter["bare_months"]) < len(mono["bare_months"])
    assert 0 <= mono["values"]["erosion"] <= 1
    assert mono["values"]["agua"] >= 0 and 0 <= mono["values"]["agua_cubierta"] <= 1


def test_more_residue_left_means_more_carbon_less_forage():
    place = synthetic_place()
    kept = indicators.evaluate(place, [{"pv": "maize"}], residue="dejar")["values"]
    taken = indicators.evaluate(place, [{"pv": "maize"}], residue="sacar")["values"]
    assert kept["carbono"] > taken["carbono"] and kept["forraje"] < taken["forraje"]
    assert kept["nitrogeno"] > taken["nitrogeno"]


def test_alternatives_only_use_local_crops():
    place = synthetic_place()
    local = {"maize", "bean", "squash_seed", "sorghum", "chickpea", "milpa"}
    options = candidates.generate(place, [{"pv": "maize"}])
    assert options
    for template, rotation in options:
        assert {c for y in rotation for c in y.values()} <= local
    assert "milpa" in {t for t, _ in options} and "invierno" in {t for t, _ in options}


def test_missing_crop_is_reported_not_invented():
    place = synthetic_place()
    e = indicators.evaluate(place, [{"pv": "maize"}, {"pv": "peanut"}])
    assert e["gaps"] and "cacahuate" in e["gaps"][0]


@pytest.mark.skipif(not Path("data/rotations/climate_district.parquet").exists(), reason="tables not built")
def test_comparar_rotaciones_on_real_data():
    from src.rotations.compare import comparar_rotaciones, to_json
    r = comparar_rotaciones("Celaya", "maíz", estado="Guanajuato", prioridades=["agua", "suelo"])
    assert r["lugar"]["distrito"] == "Celaya"
    assert len(r["rotaciones"]) >= 3 and r["rotaciones"][0]["id"] == "actual"
    for x in r["rotaciones"]:
        assert set(x["tarjeta"]) >= {"por_que", "evidencia", "beneficios", "riesgos", "vacios", "revisar_con_tecnico"}
        assert x["indicadores"]["ingreso"]["evidencia"] in {"alta", "media", "baja"}
    assert to_json(r)


def test_costs_give_profit_and_loss_years():
    place = synthetic_place()
    place.costs = {"maize": 9000.0}
    e = indicators.evaluate(place, [{"pv": "maize"}])
    v = e["values"]
    assert v["ganancia"] == pytest.approx(v["ingreso"] - 9000)
    assert 0 <= v["prob_perdida"] <= 1 and v["costo_equilibrio"] == pytest.approx(v["ingreso"])
    unknown = indicators.evaluate(place, [{"pv": "maize"}, {"pv": "bean"}])
    assert np.isnan(unknown["values"]["ganancia"]) and unknown["missing_costs"] == ["bean"]


def test_only_farmer_costs_enter_calculations_references_are_quoted():
    from src.rotations import costs
    place = synthetic_place(water="riego")
    place.state = "Sinaloa"
    assert costs.cost_for(place, "maize", "oi") is None            # published FIRA cost is not used silently
    ref = costs.reference_for(place, "maize", "oi")
    assert ref and ref["mxn_ha"] > 0 and "FIRA" in ref["fuente"]
    assert costs.reference_for(place, "maize", "pv") is None        # same crop, cycle, regime and state only
    place.state = "Prueba"
    assert costs.reference_for(place, "maize", "oi") is None
    place.costs = {"maize": 30000.0}
    assert costs.cost_for(place, "maize", "oi")["fuente"] == "tu dato"


def test_own_yield_sets_the_level_but_keeps_the_pattern():
    place = synthetic_place()
    base = indicators.production(place, "maize", "pv")["maize"]
    place.own_yield = {"maize": 2 * float(base["per_sown"][base["per_sown"].index > 2015].median())}
    mine = indicators.production(place, "maize", "pv")["maize"]
    assert mine["own_yield_factor"] == pytest.approx(2.0)
    assert np.allclose(mine["per_sown"] / base["per_sown"], 2.0)


def test_smap_wetness_sets_stored_water_for_residual_moisture_crops():
    place = synthetic_place()
    wet = indicators.evaluate(place, [{"pv": "maize", "oi": "chickpea"}])["values"]["agua"]
    month = np.arange(1, 13)
    place.observed = pd.DataFrame({"month": month, "ndvi": np.r_[np.full(5, 0.3), np.full(5, 0.6), [0.4, 0.3]],
                                   "smap_relative": np.full(12, 0.1)})
    dry = indicators.evaluate(place, [{"pv": "maize", "oi": "chickpea"}])
    assert dry["values"]["agua"] > wet
    assert any("SMAP" in w for w in dry["warnings"])


def test_low_green_months_from_ndvi():
    from src.rotations import observed
    obs = pd.DataFrame({"month": np.arange(1, 13), "ndvi": [0.3, 0.3, 0.3, 0.3, 0.32, 0.4, 0.55, 0.6, 0.6, 0.5, 0.4, 0.33]})
    low, high = observed.low_green_months(obs)
    assert set(low) >= {1, 2, 3, 4} and set(high) >= {8, 9}
