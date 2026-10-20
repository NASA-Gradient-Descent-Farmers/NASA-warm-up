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
from src.crop_models.calibration import (CALIBRATION_YEARS, TRIAL_NO_N_RATIO, TRIAL_TOLERANCE,  # noqa: E402
                                         CALIBRATED)
from src.crop_models.farm_tool import siap_texcoco, simulated_like_siap  # noqa: E402

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


def yearly(path, siap):
    """Simulated yield per crop and year as SIAP would see it (maize weighted by SIAP areas)."""
    seasons = pd.read_csv(path)
    return simulated_like_siap(seasons[seasons["year"] > seasons["year"].min()], siap)


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


def years_figure(calibrated, siap):
    """Year-by-year calibrated and observed yields and the fit-year SIAP mean, holdout years shaded."""
    observed = siap.set_index(["crop", "year"])["yield_sown_t_ha"]
    fig, axes = plt.subplots(3, 1, figsize=(6.2, 6.4), sharex=True)
    for ax, (crop, name) in zip(axes, CROPS.items()):
        ax.axvspan(2021.5, 2025.5, color="#f1f0ec", zorder=0)
        obs = observed[crop].reindex(range(2006, 2026))
        ax.plot(obs.index, obs.values, color=INK, marker="o", label="SIAP (observed)")
        cal = calibrated[crop].loc[2006:2025]
        ax.plot(cal.index, cal.values, color=BLUE, marker="s", label="Calibrated WOFOST")
        ax.axhline(obs.loc[list(CALIBRATION_YEARS)].mean(), color=MUTED, linestyle="--", linewidth=1,
                   label="SIAP mean 2006–2021 (naive baseline)")
        ax.set_title(name, loc="left", fontsize=9.5, color=INK)
        ax.set_ylabel("t/ha")
        ax.set_ylim(0, max(obs.max(), cal.max()) * 1.2)
        ax.text(2023.5, ax.get_ylim()[1] * 0.95, "holdout", ha="center", va="top", fontsize=8, color=INK_2)
    axes[0].legend(ncol=3, loc="upper center", bbox_to_anchor=(0.5, 1.42), fontsize=8)
    axes[-1].set_xticks(range(2006, 2026, 2))
    fig.savefig(OUT / "calibration_years.pdf")


def maize_grid_figure(history):
    """Maize step of the search at the chosen phenology: mean yield and fertilizer response against
    photosynthesis, one line per N supply (fertilizer recovery, mineralization)."""
    tsum = CALIBRATED["maize"]["tsum_scale"]
    maize = history[(history["crop"] == "maize") & (history["tsum_scale"] == tsum)]
    supplies = maize[["n_recovery", "mineralization_rate"]].drop_duplicates().sort_values("mineralization_rate")
    colors = [MUTED, ORANGE, AQUA, BLUE]
    markers = ["x", "o", "^", "s"]
    fig, axes = plt.subplots(1, 2, figsize=(6.4, 2.9))
    for (_, supply), color, marker in zip(supplies.iterrows(), colors, markers):
        g = maize[(maize["n_recovery"] == supply["n_recovery"])
                  & (maize["mineralization_rate"] == supply["mineralization_rate"])].sort_values("photosynthesis_scale")
        label = f"recovery {supply['n_recovery']:g}, soil {100 * supply['mineralization_rate']:g}%"
        for ax, column in zip(axes, ("simulated_mean_t_ha", "fertilizer_ratio")):
            ax.plot(g["photosynthesis_scale"], g[column], color=color, marker=marker, label=label)
    axes[0].axhline(maize["observed_mean_t_ha"].iloc[0], color=INK, linestyle="--", linewidth=1)
    axes[0].text(1.0, maize["observed_mean_t_ha"].iloc[0] - 0.2, "SIAP mean", ha="right", va="top",
                 fontsize=7.5, color=INK)
    axes[1].axhspan(TRIAL_NO_N_RATIO - TRIAL_TOLERANCE, min(1.0, TRIAL_NO_N_RATIO + TRIAL_TOLERANCE),
                    color="#f1f0ec", zorder=0)
    axes[1].axhline(TRIAL_NO_N_RATIO, color=INK, linestyle="--", linewidth=1)
    axes[1].text(1.0, TRIAL_NO_N_RATIO - 0.07, "Texcoco trial (5.2 / 5.6) ± 0.1", ha="right", fontsize=7.5,
                 color=INK)
    chosen = maize[(maize["photosynthesis_scale"] == CALIBRATED["maize"]["photosynthesis_scale"])
                   & (maize["n_recovery"] == CALIBRATED["maize"]["n_recovery"])
                   & (maize["mineralization_rate"] == CALIBRATED["site"]["mineralization_rate"])].iloc[0]
    for ax, column in zip(axes, ("simulated_mean_t_ha", "fertilizer_ratio")):
        ax.scatter([chosen["photosynthesis_scale"]], [chosen[column]], s=80, facecolors="none", edgecolors=INK,
                   linewidths=1.2, zorder=5)
        ax.set_xlabel("Maize photosynthesis scale")
    axes[0].set_ylabel("Mean maize yield 2006–2021 (t/ha)")
    axes[1].set_ylabel("Yield without / with fertilizer")
    axes[1].set_ylim(0, 1.05)
    axes[0].legend(fontsize=7, loc="upper left", title="N supply", title_fontsize=7)
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
        ax.text(g["photosynthesis_scale"].min(), g["observed_mean_t_ha"].iloc[0] + 0.05, "SIAP mean", ha="left",
                va="bottom", fontsize=7.5, color=INK)
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
    default, calibrated = yearly(DEFAULT_RUN, siap), yearly(CALIBRATED_DIR / "baseline.csv", siap)
    history = pd.read_csv(CALIBRATED_DIR / "fit_history.csv")
    knobs = history["label"].map(json.loads).apply(pd.Series)
    history = pd.concat([knobs, history], axis=1)
    levels_figure(default, calibrated, siap)
    years_figure(calibrated, siap)
    maize_grid_figure(history)
    photosynthesis_figure(history)
    print(f"Saved figures to {OUT}")


if __name__ == "__main__":
    main()
