import unittest

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.tree import DecisionTreeRegressor

from src.crop_models.ensemble_experiments import TemporalEnsemble, evaluate
from src.crop_models.observed_maize import extract_texcoco, prepare


class EnsembleTests(unittest.TestCase):
    def setUp(self):
        self.x = pd.DataFrame({"year": np.repeat(range(2005, 2017), 2), "signal": np.arange(24)})
        self.y = np.arange(24, dtype=float)
        self.base = {
            str(depth): Pipeline(
                [
                    ("features", ColumnTransformer([("numeric", "passthrough", ["signal"])])),
                    ("model", DecisionTreeRegressor(max_depth=depth, random_state=42)),
                ]
            )
            for depth in (1, 3)
        }

    def test_inner_predictions_are_temporal_and_blend_is_convex(self):
        for method in ("convex", "ridge"):
            model = TemporalEnsemble(self.base, method).fit(self.x, self.y)
            for split in model.meta_membership_:
                self.assertLess(max(split["train_years"]), min(split["validation_years"]))
            if method == "convex":
                self.assertAlmostEqual(sum(model.weights_), 1)
                self.assertTrue((model.weights_ >= 0).all())

    def test_holdout_labels_cannot_change_blend_selection_or_weights(self):
        models = {m: TemporalEnsemble(self.base, m) for m in ("equal", "convex", "ridge")}
        first = evaluate(self.x, self.y, self.x.year.to_numpy(), models, test_years=2, folds=2)
        changed = self.y.copy()
        changed[-4:] += 100
        second = evaluate(self.x, changed, self.x.year.to_numpy(), models, test_years=2, folds=2)
        self.assertEqual(first[3], second[3])
        pd.testing.assert_frame_equal(
            first[0][first[0].split != "holdout"], second[0][second[0].split != "holdout"]
        )
        np.testing.assert_allclose(first[2]["convex"].weights_, second[2]["convex"].weights_)

    def test_official_yield_uses_area_weighted_production_and_excludes_irrigation(self):
        frame = pd.DataFrame(
            {
                "Idestado": [15] * 3,
                "Idmunicipio": [99] * 3,
                "Idciclo": [2] * 3,
                "Idmodalidad": [2, 2, 1],
                "Nomcultivo": ["Maíz grano"] * 3,
                "Anio": [2024] * 3,
                "Cosechada": [10, 30, 100],
                "Sembrada": [10, 30, 100],
                "Volumenproduccion": [20, 120, 1000],
            }
        )
        row = extract_texcoco(frame, 2024)
        self.assertEqual(row["observed_yield_t_ha"], 3.5)
        self.assertEqual(row["source_rows"], 2)
        historical = extract_texcoco(frame.rename(columns={"Nomcultivo": "Nomcultivo Sin UM"}), 2024)
        self.assertEqual(historical, row)

    def test_lag_does_not_bridge_missing_years(self):
        rows = [{"year": y, "observed_yield_t_ha": float(y - 2000)} for y in [2005, 2006, 2008, 2009]]
        weather = pd.DataFrame({"year": [2005, 2006, 2008, 2009], "rain_may_oct_mm": [500] * 4})
        prepared = prepare(rows, weather)
        self.assertEqual(prepared.year.tolist(), [2006, 2009])
        self.assertEqual(prepared.previous_yield_t_ha.tolist(), [5.0, 8.0])


if __name__ == "__main__":
    unittest.main()
