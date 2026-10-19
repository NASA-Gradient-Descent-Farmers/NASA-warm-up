"""Build the figures of calibration.tex from the default and calibrated runs and the fit history.

Run the calibration first (python -m src.crop_models.calibration --fit, then --simulate), then, from the repo root:
    python docs/technical_report/make_calibration_figures.py
"""

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.crop_models.calibration import CALIBRATION_YEARS, crop_year_yields  # noqa: E402
from src.crop_models.farm_tool import siap_texcoco  # noqa: E402

DEFAULT_RUN = ROOT / "data" / "rotations" / "baseline.csv"
CALIBRATED_DIR = ROOT / "data" / "rotations_calibrated"
OUT = Path(__file__).resolve().parent / "figures"

INK, INK_2, MUTED, GRID = "#0b0b0b", "#52514e", "#8a8984", "#e4e3df"
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
CROPS = {"maize": "Maize", "barley": "Barley", "fababean": "Faba bean"}

plt.rcParams.update({
    "font.size": 9, "axes.edgecolor": MUTED, "axes.labelcolor": INK_2, "xtick.color": INK_2,
    "ytick.color": INK_2, "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
    "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True, "legend.frameon": False,
    "lines.linewidth": 1.5, "lines.markersize": 4.5, "savefig.bbox": "tight",
})


def yearly(path):
    seasons = pd.read_csv(path)
    return crop_year_yields(seasons[seasons["year"] > seasons["year"].min()])


def levels_figure(default, calibrated, siap):
    """Mean 2006-2021 yield per crop: default WOFOST, calibrated WOFOST and SIAP."""
    observed = siap.set_index(["crop", "year"])["yield_sown_t_ha"]
    rows = []
    for crop in CROPS:
        years = [y for y in CALIBRATION_YEARS if (crop, y) in observed.index]
        rows.append([default[crop].loc[years].mean(), calibrated[crop].loc[years].mean(),
                     observed[crop].loc[years].mean()])
    fig, ax = plt.subplots(figsize=(6.2, 2.8))
    width = 0.26
    for i, (label, color) in enumerate((("Default WOFOST", ORANGE), ("Calibrated WOFOST", BLUE),
                                        ("SIAP (observed)", INK_2))):
        xs = [c + (i - 1) * (width + 0.02) for c in range(len(CROPS))]
        values = [row[i] for row in rows]
        ax.bar(xs, values, width, color=color, label=label)
        for x, v in zip(xs, values):
            ax.text(x, v + 0.15, f"{v:.1f}", ha="center", va="bottom", fontsize=8, color=INK)
    ax.set_xticks(range(len(CROPS)), CROPS.values())
    ax.set_ylabel("Mean yield 2006–2021 (t/ha)")
    ax.grid(axis="x", visible=False)
    ax.legend(ncol=3, loc="upper center", bbox_to_anchor=(0.5, 1.16))
    fig.savefig(OUT / "calibration_levels.pdf")


def years_figure(default, calibrated, siap):
    """Year-by-year calibrated and observed yields, with the holdout years shaded."""
    observed = siap.set_index(["crop", "year"])["yield_sown_t_ha"]
    fig, axes = plt.subplots(3, 1, figsize=(6.2, 6.4), sharex=True)
    for ax, (crop, name) in zip(axes, CROPS.items()):
        ax.axvspan(2021.5, 2025.5, color="#f1f0ec", zorder=0)
        obs = observed[crop].reindex(range(2006, 2026))
        ax.plot(obs.index, obs.values, color=INK, marker="o", label="SIAP (observed)")
        cal = calibrated[crop].loc[2006:2025]
        ax.plot(cal.index, cal.values, color=BLUE, marker="s", label="Calibrated WOFOST")
        ax.set_title(name, loc="left", fontsize=9.5, color=INK)
        ax.set_ylabel("t/ha")
        ax.set_ylim(0, max(obs.max(), cal.max()) * 1.2)
        ax.text(2023.5, ax.get_ylim()[1] * 0.95, "holdout", ha="center", va="top", fontsize=8, color=INK_2)
    axes[0].legend(ncol=2, loc="upper center", bbox_to_anchor=(0.5, 1.42))
    axes[-1].set_xticks(range(2006, 2026, 2))
    fig.savefig(OUT / "calibration_years.pdf")


def maize_grid_figure(history):
    """Maize step of the fit: mean yield and RMSE against fertilizer N recovery, per mineralization rate."""
    maize = history[(history["crop"] == "maize") & (history["tsum_scale"] == 1.0)]
    fig, axes = plt.subplots(1, 2, figsize=(6.4, 2.7))
    styles = {0.005: (ORANGE, "o", "0.5% (default)"), 0.00375: (AQUA, "^", "0.375%"), 0.0025: (BLUE, "s", "0.25%")}
    for rate, (color, marker, label) in styles.items():
        g = maize[maize["mineralization_rate"] == rate].sort_values("n_recovery")
        for ax, column in zip(axes, ("simulated_mean_t_ha", "rmse_t_ha")):
            ax.plot(g["n_recovery"], g[column], color=color, marker=marker, label=label)
            last = g.iloc[-1]
            ax.annotate(label, (last["n_recovery"], last[column]), xytext=(4, 0), textcoords="offset points",
                        va="center", fontsize=7.5, color=INK_2)
    axes[0].axhline(maize["observed_mean_t_ha"].iloc[0], color=INK, linestyle="--", linewidth=1)
    axes[0].text(0.6, maize["observed_mean_t_ha"].iloc[0] - 0.15, "SIAP mean", ha="right", va="top",
                 fontsize=7.5, color=INK)
    best = maize.sort_values("rmse_t_ha").iloc[0]
    axes[1].scatter([best["n_recovery"]], [best["rmse_t_ha"]], s=70, facecolors="none", edgecolors=INK,
                    linewidths=1.2, zorder=5)
    axes[1].annotate("chosen", (best["n_recovery"], best["rmse_t_ha"]), xytext=(0, -14),
                     textcoords="offset points", ha="center", fontsize=7.5, color=INK)
    axes[0].set_ylabel("Mean maize yield 2006–2021 (t/ha)")
    axes[1].set_ylabel("RMSE vs SIAP (t/ha)")
    for ax in axes:
        ax.set_xlabel("Fertilizer N recovery")
        ax.set_xlim(0.07, 0.62)
    axes[0].set_title("Lines: soil N mineralized per season", loc="left", fontsize=8, color=INK_2)
    fig.tight_layout(w_pad=2.5)
    fig.savefig(OUT / "calibration_maize_grid.pdf")


def photosynthesis_figure(history):
    """Barley and faba bean steps: mean yield against the photosynthesis scale, per phenology scale."""
    fig, axes = plt.subplots(1, 2, figsize=(6.4, 2.7), sharey=True)
    styles = {0.8: (BLUE, "s"), 0.9: (AQUA, "^"), 1.0: (ORANGE, "o")}
    for ax, crop in zip(axes, ("barley", "fababean")):
        g = history[(history["crop"] == crop) & (history["n_recovery"] == 0.5)]
        for tsum, (color, marker) in styles.items():
            line = g[g["tsum_scale"] == tsum].sort_values("photosynthesis_scale")
            ax.plot(line["photosynthesis_scale"], line["simulated_mean_t_ha"], color=color, marker=marker,
                    label=f"TSUM ×{tsum:g}")
        ax.axhline(g["observed_mean_t_ha"].iloc[0], color=INK, linestyle="--", linewidth=1)
        ax.text(g["photosynthesis_scale"].max(), g["observed_mean_t_ha"].iloc[0] - 0.15, "SIAP mean", ha="right",
                va="top", fontsize=7.5, color=INK)
        best = g.sort_values("rmse_t_ha").iloc[0]
        ax.scatter([best["photosynthesis_scale"]], [best["simulated_mean_t_ha"]], s=70, facecolors="none",
                   edgecolors=INK, linewidths=1.2, zorder=5)
        ax.set_title(CROPS[crop], loc="left", fontsize=9.5, color=INK)
        ax.set_xlabel("Photosynthesis scale")
    axes[0].set_ylabel("Mean yield 2006–2021 (t/ha)")
    axes[0].legend(fontsize=7.5, loc="upper left")
    fig.tight_layout(w_pad=1.5)
    fig.savefig(OUT / "calibration_photosynthesis.pdf")


def main():
    OUT.mkdir(exist_ok=True)
    siap = siap_texcoco(ROOT / "data" / "observations")
    default, calibrated = yearly(DEFAULT_RUN), yearly(CALIBRATED_DIR / "baseline.csv")
    history = pd.read_csv(CALIBRATED_DIR / "fit_history.csv")
    knobs = history["label"].map(json.loads).apply(pd.Series)
    history = pd.concat([knobs, history], axis=1)
    levels_figure(default, calibrated, siap)
    years_figure(default, calibrated, siap)
    maize_grid_figure(history)
    photosynthesis_figure(history)
    print(f"Saved figures to {OUT}")


if __name__ == "__main__":
    main()
