"""Offline checks for src/yield_panel (synthetic data; no network)."""

import unittest

import numpy as np
import pandas as pd

from src.yield_panel import models as pm
from src.yield_panel import siap, weather


def siap_frame():
    """A tiny SIAP-like year with the quirks of the real files."""
    return pd.DataFrame({
        " Anio": [2020] * 7,
        "IdEstado": [11, 11, 11, 11, 11, 15, 15],
        "IdMunicipio": [7, 7, 7, 7, 7, 99, 99],
        "IdCiclo": [2, 2, 2, 1, 2, 2, 2],
        "IdModalidad": [2, 2, 1, 2, 2, 2, 2],
        "NomUnidad": ["Tonelada"] * 6 + ["Tonelada"],
        "NomCultivo Sin Um": ["Maíz grano", "MAÍZ GRANO", "Maíz grano", "Maíz grano", "Frijol", "Maíz grano", "Tomate rojo"],
        "Sembrada": [100, 50, 999, 999, 40, 200, 5],
        "Cosechada": [80, 50, 999, 999, 30, 0, 5],
        "Siniestrada": [20, 0, 0, 0, 10, 200, 0],
        "VolumenProduccion": [240, 150, 9999, 9999, 21, 0, 50],
    })


class TestSiap(unittest.TestCase):
    def test_extract_filters_and_aggregates(self):
        panel = siap.extract_panel(siap.normalize(siap_frame()))
        maize = panel[(panel.crop == "maize") & (panel.mun_id == 7)].iloc[0]
        # Irrigated and autumn-winter rows are excluded; the two rainfed PV rows are summed.
        self.assertEqual(maize.sown_ha, 150)
        self.assertAlmostEqual(maize.yield_t_ha, 390 / 130)
        self.assertAlmostEqual(maize.failure_rate, 20 / 150)
        bean = panel[panel.crop == "bean"].iloc[0]
        self.assertAlmostEqual(bean.yield_t_ha, 0.7)
        # Total loss: no harvested area, so yield is undefined but failure is 1.
        texcoco = panel[(panel.mun_id == 99) & (panel.crop == "maize")].iloc[0]
        self.assertTrue(np.isnan(texcoco.yield_t_ha))
        self.assertEqual(texcoco.failure_rate, 1.0)
        self.assertNotIn("tomate", " ".join(panel.crop))

    def test_clean_drops_small_and_short_series(self):
        rows = [{"crop": "maize", "state_id": 1, "mun_id": m, "year": y, "sown_ha": s, "yield_t_ha": 2.0}
                for m, s, n in [(1, 500, 12), (2, 500, 5), (3, 10, 12)] for y in range(2000, 2000 + n)]
        clean = siap.clean_panel(pd.DataFrame(rows), min_sown_ha=50, min_years=10)
        self.assertEqual(sorted(clean.mun_id.unique()), [1])


class TestWeather(unittest.TestCase):
    def test_snap_to_merra2_grid(self):
        lat, lon = weather.snap(20.52, -100.82)
        self.assertEqual((float(lat), float(lon)), (20.5, -100.625))
        # Points within the same cell share a centre; the next cell over does not.
        self.assertEqual(weather.snap(20.3, -100.9)[1], weather.snap(20.6, -100.4)[1])
        self.assertNotEqual(weather.snap(20.3, -100.95)[1], weather.snap(20.3, -100.3)[1])

    def test_reference_table(self):
        munis = weather.load_municipalities()
        self.assertGreater(len(munis), 2400)
        self.assertFalse(munis.duplicated(["state_id", "mun_id"]).any())
        celaya = munis[(munis.state_id == 11) & (munis.mun_id == 7)].iloc[0]
        self.assertEqual(celaya.municipality, "Celaya")
        self.assertTrue(20 < celaya.lat < 21 and -101.2 < celaya.lon < -100.5)

    def test_season_features(self):
        days = pd.date_range("2019-01-01", "2020-12-31")
        rain = np.zeros(len(days))
        rain[(days.year == 2020) & (days.month == 6) & (days.day >= 10)] = 5.0  # June 10-30
        daily = pd.DataFrame({"PRECTOTCORR": rain, "T2M": 20.0, "T2M_MAX": 28.0, "T2M_MIN": 12.0,
                              "RH2M": 60.0, "ALLSKY_SFC_SW_DWN": 20.0}, index=days)
        f = weather.season_features(daily, [2020]).iloc[0]
        self.assertAlmostEqual(f.rain_season_mm, 21 * 5.0)
        self.assertAlmostEqual(f.rain_jun_mm, 105.0)
        self.assertEqual(f.rain_jul_aug_mm, 0)
        self.assertEqual(f.onset_doy, pd.Timestamp("2020-06-13").dayofyear)  # 4th wet day: 20 mm over 5 days
        self.assertEqual(f.longest_dry_spell_days, 123)  # July 1 - October 31
        self.assertAlmostEqual(f.gdd_10_30, 184 * 10.0)


def synthetic_panel(signal=True, n_units=60, years=range(2003, 2026), seed=1):
    rng = np.random.default_rng(seed)
    rows = []
    for m in range(n_units):
        level = rng.normal(2.5, 0.8)
        climate = rng.normal(700, 150)
        for y in years:
            rain = climate + rng.normal(0, 120)
            dry = rng.integers(5, 30)
            effect = 0.003 * (rain - climate) - 0.04 * dry if signal else 0.0
            rows.append({"state_id": 1, "mun_id": m, "year": y, "rain_season_mm": rain, "longest_dry_spell_days": dry,
                         "alt_m": 1800.0, "yield_t_ha": level + 0.03 * (y - 2003) + effect + rng.normal(0, 0.2)})
    return pd.DataFrame(rows)


class TestModels(unittest.TestCase):
    features = ["rain_season_mm", "longest_dry_spell_days"]

    def evaluate(self, panel):
        panel, feats = pm.add_terms(panel, self.features)
        models = pm.make_models(feats, ["alt_m"])
        preds = pm.rolling_evaluation(panel, "yield_t_ha", models, range(2016, 2026))
        return pm.score(preds, models), preds

    def test_beats_bar_when_weather_matters(self):
        table, preds = self.evaluate(synthetic_panel(signal=True))
        self.assertGreater(table.loc["fe_weather", "skill_vs_bar"], 0.3)
        self.assertGreater(table.loc["gbm_weather", "skill_vs_bar"], 0.1)
        self.assertGreater(pm.bootstrap_skill(preds, "fe_weather", draws=200)["ci_low"], 0)

    def test_no_gain_without_signal(self):
        table, _ = self.evaluate(synthetic_panel(signal=False))
        self.assertLess(table.loc["fe_weather", "skill_vs_bar"], 0.05)

    def test_fixed_effects_recover_coefficients(self):
        panel = synthetic_panel(signal=True)
        fit = pm.FixedEffects(["year", *self.features], alpha=0.0).fit(panel, "yield_t_ha")
        self.assertAlmostEqual(fit.coef_["year"], 0.03, delta=0.005)
        self.assertAlmostEqual(fit.coef_["rain_season_mm"], 0.003, delta=0.0005)
        self.assertAlmostEqual(fit.coef_["longest_dry_spell_days"], -0.04, delta=0.005)

    def test_no_future_leakage(self):
        panel, feats = pm.add_terms(synthetic_panel(), self.features)
        models = pm.make_models(feats)
        before = pm.rolling_evaluation(panel, "yield_t_ha", models, [2018])
        changed = panel.copy()
        changed.loc[changed.year > 2018, "yield_t_ha"] += 100.0  # tamper with the future
        after = pm.rolling_evaluation(changed, "yield_t_ha", models, [2018])
        pd.testing.assert_frame_equal(before, after)

    def test_risk_profile_one_row_per_weather_year(self):
        panel, feats = pm.add_terms(synthetic_panel(), self.features)
        model = pm.FixedEffects(["year", *feats]).fit(panel, "yield_t_ha")
        profile = pm.risk_profile(model, panel, panel, (1, 0), 2025, self.features)
        self.assertEqual(len(profile), panel.year.nunique())
        self.assertTrue(np.isfinite(profile.prediction).all())


if __name__ == "__main__":
    unittest.main()
