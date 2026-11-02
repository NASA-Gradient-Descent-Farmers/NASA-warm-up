"""0-100 scores on fixed scales, farmer-priority weights, and paired comparisons with the current rotation.

Scales are fixed (not rescaled to the rotations being compared) so that small differences are not blown up
into large score gaps.
"""

import numpy as np

# indicator -> (value that scores 0, value that scores 100)
SCALES = {
    "ingreso": (0, 40000),
    "ingreso_p10": (0, 30000),
    "ganancia": (-10000, 30000),        # profit, MXN/ha/yr
    "ganancia_p10": (-15000, 20000),
    "riesgo": (0.4, 0.0),
    "agua_temporal": (0.3, 1.0),        # share of crop water need met by rain in a dry year
    "agua_riego": (800, 0),             # irrigation need, mm per year
    "nitrogeno": (-120, 40),
    "carbono": (0.0, 1.0),
    "erosion": (0.6, 0.0),
    "plagas": (0.0, 1.0),
    "forraje": (0.0, 8.0),
}
SLOPE = {"plana": 0.5, "ligera": 1.0, "fuerte": 2.0}

PRIORITIES = {           # farmer priority -> indicators it covers
    "ingreso": ["ingreso"],
    "riesgo": ["ingreso_p10", "riesgo"],
    "agua": ["agua"],
    "suelo": ["nitrogeno", "carbono"],
    "erosion": ["erosion"],
    "plagas": ["plagas"],
    "forraje": ["forraje"],
}
PRIORITY_LABELS = {
    "ingreso": "ingreso", "riesgo": "menos riesgo de perder la cosecha", "agua": "ahorrar o aprovechar el agua",
    "suelo": "fertilidad y materia orgánica del suelo", "erosion": "proteger el suelo de la erosión",
    "plagas": "romper ciclos de plagas y enfermedades", "forraje": "forraje para animales",
}
PRIORITY_WEIGHT = 3.0


def scale(name, value):
    lo, hi = SCALES[name]
    if value is None or not np.isfinite(value):
        return None
    return float(np.clip(100 * (value - lo) / (hi - lo), 0, 100))


def scores(values, water, slope="ligera", net=False):
    """0-100 per indicator. With net=True income scores use profit (income minus costs)."""
    out = {}
    if net:
        values = {**values, "ingreso": values["ganancia"], "ingreso_p10": values["ganancia_p10"]}
    for name, value in values.items():
        if name == "agua":
            out[name] = (scale("agua_temporal", values["agua_cubierta"]) if water == "temporal"
                         else scale("agua_riego", value))
        elif name == "erosion":
            out[name] = scale("erosion", value * SLOPE.get(slope, 1.0))
        elif name in ("ingreso", "ingreso_p10") and net:
            out[name] = scale("ganancia" if name == "ingreso" else "ganancia_p10", value)
        elif name in SCALES and name not in ("ganancia", "ganancia_p10"):
            out[name] = scale(name, value)
    return out


def weights(priorities):
    w = {}
    for group, names in PRIORITIES.items():
        g = PRIORITY_WEIGHT if group in priorities else 1.0
        for name in names:
            w[name] = g / len(names)
    return w


def weighted(score, priorities):
    w = weights(priorities)
    used = {k: v for k, v in score.items() if k in w and v is not None}
    total = sum(w[k] for k in used)
    return sum(w[k] * v for k, v in used.items()) / total if total else None


def paired_difference(series, baseline, draws=2000, seed=0):
    """Mean difference by historical year with a 90% year-bootstrap interval."""
    if series is None or baseline is None:
        return None
    joined = series.to_frame("a").join(baseline.to_frame("b"), how="inner").dropna()
    if len(joined) < 5:
        return None
    diff = (joined["a"] - joined["b"]).to_numpy()
    rng = np.random.default_rng(seed)
    boot = diff[rng.integers(0, len(diff), (draws, len(diff)))].mean(axis=1)
    lo, hi = np.quantile(boot, [0.05, 0.95])
    return {"media": float(diff.mean()), "intervalo_90": [float(lo), float(hi)], "años": int(len(diff)),
            "clara": bool(lo > 0 or hi < 0)}
