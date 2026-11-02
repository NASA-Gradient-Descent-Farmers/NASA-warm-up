"""Panel models of municipal yield and failure rate, and their year-by-year evaluation.

All models are fitted per crop on a municipality x year panel. Each municipality is a "unit".

| Model         | Prediction for municipality m in year t                                        |
|---------------|--------------------------------------------------------------------------------|
| mean          | m's average over the training years                                            |
| mean_trend    | m's own level + one trend shared by all municipalities   <- the bar to beat    |
| fe_weather    | mean_trend + linear effects of that season's weather (fixed-effects regression)|
| gbm_weather   | mean_trend + gradient boosting on the leftover, from weather anomalies,        |
|               | location, altitude, soil and m's typical level                                 |

`fe_weather` is the standard panel ("within") estimator: the municipality effects absorb everything that
does not change over time (soil, typical management, market access), so the weather coefficients are
learned only from how each municipality's own yield moves from year to year with its own weather.

The weather features describe the *realized* season. A good score means the model has learned how
yield responds to weather, which is what is needed to run a municipality through many past (or
scenario) seasons. It is not a pre-season forecast: the season's weather is unknown at sowing.
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

UNIT = ["state_id", "mun_id"]

QUADRATIC = ["rain_season_mm", "gdd_10_30", "tmax_season_c"]


def add_terms(panel, weather_features, quadratic=QUADRATIC):
    """Add squared terms for a few features, so effects can bend (e.g. too little and too much rain)."""
    out = panel.copy()
    extra = []
    for f in quadratic:
        if f in weather_features:
            out[f"{f}_sq"] = out[f] ** 2
            extra.append(f"{f}_sq")
    return out, list(weather_features) + extra


def _unit_means(frame, cols):
    return frame.groupby(UNIT)[cols].mean()


class FixedEffects:
    """y_mt = a_m + x_mt . b, fitted by demeaning within each municipality (ridge on standardized x)."""

    def __init__(self, features, alpha=1.0):
        self.features, self.alpha = list(features), alpha

    def fit(self, frame, target):
        d = frame.dropna(subset=[target, *self.features])
        cols = [target, *self.features]
        means = d.groupby(UNIT)[cols].transform("mean")
        X = (d[self.features] - means[self.features]).to_numpy(float)
        y = (d[target] - means[target]).to_numpy(float)
        scale = X.std(axis=0)
        scale[scale == 0] = 1.0
        Xs = X / scale
        beta_s = np.linalg.solve(Xs.T @ Xs + self.alpha * np.eye(Xs.shape[1]), Xs.T @ y)
        self.coef_ = pd.Series(beta_s / scale, index=self.features)
        unit = _unit_means(d, cols)
        self.unit_effect_ = unit[target] - unit[self.features].to_numpy(float) @ self.coef_.to_numpy()
        return self

    def predict(self, frame):
        effect = frame.set_index(UNIT).index.map(self.unit_effect_)
        return np.asarray(effect, float) + frame[self.features].to_numpy(float) @ self.coef_.to_numpy()


class UnitMean:
    def fit(self, frame, target):
        self.mean_ = frame.dropna(subset=[target]).groupby(UNIT)[target].mean()
        return self

    def predict(self, frame):
        return np.asarray(frame.set_index(UNIT).index.map(self.mean_), float)


class BoostedResidual:
    """mean_trend plus a gradient-boosted model of what it leaves unexplained.

    Weather enters both raw and as anomalies from each municipality's training average, so the trees
    can learn "a dry year for this place" as well as "a dry place".
    """

    def __init__(self, weather_features, static_features=(), seed=0):
        self.weather, self.static, self.seed = list(weather_features), list(static_features), seed

    def _design(self, frame):
        means = frame.set_index(UNIT).index
        anomalies = frame[self.weather].to_numpy(float) - self.weather_means_.reindex(means).to_numpy(float)
        level = np.asarray(means.map(self.level_), float)[:, None]
        return np.hstack([anomalies, frame[self.weather + self.static].to_numpy(float), level])

    def fit(self, frame, target):
        d = frame.dropna(subset=[target])
        self.base_ = FixedEffects(["year"]).fit(d, target)
        self.weather_means_ = _unit_means(d, self.weather)
        self.level_ = d.groupby(UNIT)[target].mean()
        residual = d[target].to_numpy(float) - self.base_.predict(d)
        self.gbm_ = HistGradientBoostingRegressor(
            max_iter=300, learning_rate=0.05, max_depth=3, min_samples_leaf=50, l2_regularization=1.0,
            early_stopping=False, random_state=self.seed,
        ).fit(self._design(d), residual)
        return self

    def predict(self, frame):
        return self.base_.predict(frame) + self.gbm_.predict(self._design(frame))


def make_models(weather_features, static_features=()):
    return {
        "mean": lambda: UnitMean(),
        "mean_trend": lambda: FixedEffects(["year"], alpha=0.0),
        "fe_weather": lambda: FixedEffects(["year", *weather_features]),
        "gbm_weather": lambda: BoostedResidual(weather_features, static_features),
    }


def clip_target(target, values):
    return np.clip(values, 0, 1) if target == "failure_rate" else np.clip(values, 0, None)


def rolling_evaluation(panel, target, models, test_years, min_train_years=8):
    """Expanding-window, one-year-ahead evaluation.

    For each test year t, every model is fitted on years < t only and predicts year t, for the
    municipalities that have at least `min_train_years` training observations. Every model is scored
    on exactly the same rows.
    """
    rows = []
    needed = set().union(*(getattr(f(), "features", []) for f in models.values())) - {"year"}
    for t in test_years:
        train = panel[(panel["year"] < t)].dropna(subset=[target])
        counts = train.groupby(UNIT)["year"].transform("nunique")
        train = train[counts >= min_train_years]
        units = train[UNIT].drop_duplicates()
        test = panel[panel["year"] == t].dropna(subset=[target, *needed]).merge(units, on=UNIT)
        if test.empty or train.empty:
            continue
        out = test[[*UNIT, "year", target]].rename(columns={target: "observed"})
        for name, factory in models.items():
            model = factory().fit(train, target)
            out[name] = clip_target(target, model.predict(test))
        rows.append(out.dropna())
    return pd.concat(rows, ignore_index=True)


def rmse(error):
    return float(np.sqrt(np.mean(np.square(error))))


def score(predictions, models, bar="mean_trend"):
    """RMSE, MAE and skill against the bar: 1 - RMSE / RMSE(bar). Positive = beats the bar."""
    obs = predictions["observed"]
    table = pd.DataFrame({
        "rmse": {m: rmse(predictions[m] - obs) for m in models},
        "mae": {m: float(np.mean(np.abs(predictions[m] - obs))) for m in models},
    })
    table["skill_vs_bar"] = 1 - table["rmse"] / table.loc[bar, "rmse"]
    table["rows"] = len(predictions)
    table["years"] = predictions["year"].nunique()
    return table


def score_by_year(predictions, models):
    return predictions.groupby("year").apply(
        lambda g: pd.Series({m: rmse(g[m] - g["observed"]) for m in models}), include_groups=False)


def bootstrap_skill(predictions, model, bar="mean_trend", draws=2000, seed=0):
    """95% interval for the RMSE improvement over the bar, resampling whole test years.

    Rows within a year share the same weather shocks, so years (not rows) are the independent units.
    """
    rng = np.random.default_rng(seed)
    years = predictions["year"].unique()
    # Per-year sums of squared errors and row counts: a resample's RMSE is sqrt(sum SSE / sum n) over the drawn
    # years, identical to recomputing it on the concatenated rows, without building a table per draw.
    err = predictions.assign(_bar=(predictions[bar] - predictions["observed"]) ** 2,
                             _mod=(predictions[model] - predictions["observed"]) ** 2)
    per_year = err.groupby("year")[["_bar", "_mod"]].agg(["sum", "size"])
    sse_bar = per_year[("_bar", "sum")].reindex(years).to_numpy()
    sse_mod = per_year[("_mod", "sum")].reindex(years).to_numpy()
    n = per_year[("_bar", "size")].reindex(years).to_numpy()
    position = {y: i for i, y in enumerate(years)}
    diffs = []
    for _ in range(draws):
        idx = np.array([position[y] for y in rng.choice(years, len(years))])
        count = n[idx].sum()
        diffs.append(np.sqrt(sse_bar[idx].sum() / count) - np.sqrt(sse_mod[idx].sum() / count))
    point = rmse(predictions[bar] - predictions["observed"]) - rmse(predictions[model] - predictions["observed"])
    low, high = np.percentile(diffs, [2.5, 97.5])
    return {"model": model, "rmse_gain": point, "ci_low": low, "ci_high": high, "years": len(years)}


def risk_profile(model, panel, weather, unit, as_of_year, weather_features):
    """Run one municipality through every historical season's weather, with the trend held at `as_of_year`.

    `model` must already be fitted (e.g. on all years). Returns one prediction per weather year.
    """
    state_id, mun_id = unit
    static = panel[(panel["state_id"] == state_id) & (panel["mun_id"] == mun_id)].iloc[[-1]]
    seasons = weather[(weather["state_id"] == state_id) & (weather["mun_id"] == mun_id)]
    rows = seasons[["year", *weather_features]].rename(columns={"year": "weather_year"})
    scenario = static.drop(columns=[c for c in static if c in weather_features or c == "year"]).merge(rows, how="cross")
    scenario["year"] = as_of_year
    scenario, _ = add_terms(scenario, weather_features)
    return scenario[["weather_year"]].assign(prediction=model.predict(scenario))
