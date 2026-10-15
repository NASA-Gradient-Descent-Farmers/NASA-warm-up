"""Build the report's LaTeX tables from the rotation simulations in data/rotations/.

Run the simulations first (commands in the report's Reproducibility section), then, from the repo root:
    python docs/technical_report/make_tables.py
"""

import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "data" / "rotations"
OUT = Path(__file__).resolve().parent / "tables"

SCENARIOS = {
    "baseline": "Baseline",
    "rain80": "20\\% less rain",
    "rain60": "40\\% less rain",
    "canicula50": "Canícula: $-$50\\% rain Jul--Aug",
    "frost_minus2": "Frost check 2\\,°C colder",
    "no_fertilizer": "No fertilizer",
    "fixed_sowing": "Fixed sowing (May 15)",
}
ROTATION_NAMES = {
    "maize": "Maize every year",
    "maize-barley": "Maize--barley",
    "maize-fababean": "Maize--faba bean",
    "maize-barley-fababean": "Maize--barley--faba bean",
}
CROP_NAMES = {"maize": "maize", "barley": "barley", "fababean": "faba bean"}


def load(name):
    df = pd.read_csv(RUNS / f"{name}.csv", parse_dates=["sowing"])
    return df[df["year"] > df["year"].min()]  # first year is spin-up


def tabular(df, columns, align, caption, label, note=None, size="small"):
    """A booktabs table. `columns` maps DataFrame columns to header text; values are pre-formatted strings."""
    lines = [r"\begin{table}[htbp]", r"\centering", rf"\{size}", r"\setlength{\tabcolsep}{3.5pt}" if size != "small" else "", rf"\caption{{{caption}}}", rf"\label{{{label}}}",
             # Shrink to the text width only if the table is wider than it.
             r"\resizebox{\ifdim\width>\linewidth\linewidth\else\width\fi}{!}{%",
             rf"\begin{{tabular}}{{{align}}}", r"\toprule", " & ".join(columns.values()) + r" \\", r"\midrule"]
    for _, row in df.iterrows():
        lines.append(" & ".join(str(row[c]) for c in columns) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}}"]
    if note:
        lines.append(rf"\par\smallskip\parbox{{0.95\linewidth}}{{\footnotesize {note}}}")
    lines.append(r"\end{table}")
    return "\n".join(lines) + "\n"


def baseline_summary(s):
    g = s.groupby(["rotation", "crop"], sort=False).agg(
        y=("yield_water_n_t_ha", "mean"), sd=("yield_water_n_t_ha", "std"),
        yw=("yield_water_t_ha", "mean"), yp=("yield_potential_t_ha", "mean"),
        failed=("yield_water_n_t_ha", lambda x: int((x < 1).sum())), frost=("frost_ended", "sum"),
        nup=("n_uptake_kg_ha", "mean"), n=("year", "size")).reset_index()
    g["Rotation"] = g["rotation"].map(ROTATION_NAMES)
    g["Crop"] = g["crop"].map(CROP_NAMES)
    g["Y"] = g["y"].map("{:.1f}".format)
    g["CV"] = (100 * g["sd"] / g["y"]).map("{:.0f}".format)
    g["Yw"] = g["yw"].map("{:.1f}".format)
    g["Yp"] = g["yp"].map("{:.1f}".format)
    g["gw"] = (100 * (1 - g["yw"] / g["yp"])).clip(lower=0).map("{:.0f}".format)  # rainfed can edge past potential
    g["gn"] = (100 * (1 - g["y"] / g["yw"])).map("{:.0f}".format)
    g["F"] = g["failed"].astype(str)
    g["Fr"] = g["frost"].astype(int).astype(str)
    g["N"] = g["nup"].map("{:.0f}".format)
    return tabular(
        g, {"Rotation": "Rotation", "Crop": "Crop", "Y": "$Y_{wn}$", "CV": "CV (\\%)", "Yw": "$Y_w$", "Yp": "$Y_p$",
            "gw": "Water gap (\\%)", "gn": "N gap (\\%)", "F": "Failed", "Fr": "Frost", "N": "N uptake"},
        "llrrrrrrrrr",
        "Baseline results at Texcoco, 2006--2025 (20 seasons per crop and rotation). Yields are grain or seed dry "
        "matter in t/ha: $Y_{wn}$ water- and N-limited (with the grain-N constraint), $Y_w$ water-limited, $Y_p$ "
        "potential. CV: coefficient of variation of $Y_{wn}$ across years. Failed: seasons with $Y_{wn} < 1$ t/ha. "
        "Frost: seasons ended by frost before maturity. N uptake in kg N/ha.",
        "tab:baseline", size="footnotesize")


def maize_by_previous(s):
    m = s[(s["crop"] == "maize") & s["previous_crop"].notna()]
    g = m.groupby("previous_crop")["yield_water_n_t_ha"].agg(["count", "mean", "min", "max"]).reset_index()
    g["Prev"] = g["previous_crop"].map(CROP_NAMES)
    for c in ("mean", "min", "max"):
        g[c] = g[c].map("{:.1f}".format)
    return tabular(g, {"Prev": "Previous crop", "count": "Seasons", "mean": "Mean", "min": "Min", "max": "Max"},
                   "lrrrr", "Maize yield ($Y_{wn}$, t/ha) by the crop grown the season before (baseline).",
                   "tab:prev")


def maize_by_class(s, classes):
    m = s[s["crop"] == "maize"]
    p = m.pivot_table(index="rotation", columns="year_class", values="yield_water_n_t_ha", aggfunc="mean")
    p = p.reindex(index=list(ROTATION_NAMES), columns=["dry", "normal", "wet"]).reset_index()
    p["Rotation"] = p["rotation"].map(ROTATION_NAMES)
    for c in ("dry", "normal", "wet"):
        p[c] = p[c].map("{:.1f}".format)
    head = {c: f"{c.capitalize()} ({classes[c]})" for c in ("dry", "normal", "wet")}
    return tabular(p, {"Rotation": "Rotation", **head}, "lrrr",
                   "Mean maize yield ($Y_{wn}$, t/ha) by year class. Classes are terciles of May--October rain "
                   "over 2005--2025; ranges in mm.", "tab:yearclass")


def scenarios_table(frames):
    rows = []
    for key, s in frames.items():
        m = s[s["crop"] == "maize"]
        g = m.groupby("rotation")["yield_water_n_t_ha"]
        row = {"Scenario": SCENARIOS[key]}
        for rot in ROTATION_NAMES:
            vals = g.get_group(rot)
            row[rot] = f"{vals.mean():.1f} ({int((vals < 1).sum())})"
        rows.append(row)
    df = pd.DataFrame(rows)
    return tabular(df, {"Scenario": "Scenario", **{r: ROTATION_NAMES[r] for r in ROTATION_NAMES}}, "lrrrr",
                   "Mean maize yield ($Y_{wn}$, t/ha) by scenario and rotation, 2006--2025; in parentheses, "
                   "the number of failed maize seasons ($<1$ t/ha).", "tab:scenarios")


def year_table(s):
    mono = s[(s["rotation"] == "maize")].set_index("year")
    after_fb = s[(s["rotation"] == "maize-fababean") & (s["crop"] == "maize")].set_index("year")
    rows = []
    for year in sorted(s["year"].unique()):
        r = mono.loc[year]
        rows.append({"Year": year, "Class": r["year_class"], "Sow": r["sowing"].strftime("%b %d"),
                     "Rain": f"{r['rain_season_mm']:.0f}", "JA": f"{r['rain_jul_aug_mm']:.0f}",
                     "Spell": f"{r['longest_dry_spell_days']:.0f}", "Stress": f"{r['water_stress_days']:.0f}",
                     "W0": f"{r['soil_water_at_start_mm']:.0f}",
                     "Mono": f"{r['yield_water_n_t_ha']:.1f}", "AfterFB": f"{after_fb.loc[year, 'yield_water_n_t_ha']:.1f}",
                     "Frost": "yes" if r["frost_ended"] else ""})
    df = pd.DataFrame(rows)
    return tabular(
        df, {"Year": "Year", "Class": "Class", "Sow": "Sowing", "Rain": "Season rain", "JA": "Jul--Aug rain",
             "Spell": "Dry spell", "Stress": "Stress days", "W0": "Soil water Mar 1", "Mono": "Maize (mono)",
             "AfterFB": "Maize after faba", "Frost": "Frost end"},
        "rlrrrrrrrrl",
        "Year by year, maize every year (baseline): rain from sowing to harvest (mm), July--August rain (mm), longest "
        "run of days with $<1$ mm rain during the season, days with water-stress factor $<0.5$, soil water in the "
        "0--100 cm profile on March 1 (mm; wilting point = 137 mm), and maize yield ($Y_{wn}$, t/ha) in "
        "monoculture vs after faba bean.", "tab:years", size="footnotesize")


def smap_check(log):
    m = re.search(r"\((\w[\w-]*), (\d+) days\): correlation WOFOST vs SMAP root zone r=([\d.]+)", log)
    if not m:
        return "% SMAP comparison not found in baseline.log\n"
    rotation, n, r = m.groups()
    return (f"\\newcommand{{\\smapR}}{{{r}}}\n\\newcommand{{\\smapDays}}{{{n}}}\n"
            f"\\newcommand{{\\smapRotation}}{{{ROTATION_NAMES.get(rotation, rotation)}}}\n")


def main():
    OUT.mkdir(exist_ok=True)
    frames = {k: load(k) for k in SCENARIOS if (RUNS / f"{k}.csv").exists()}
    base = frames["baseline"]
    years = pd.read_csv(RUNS / "baseline.csv").drop_duplicates("year")
    classes = {}
    for c in ("dry", "normal", "wet"):
        rain = years.loc[years["year_class"] == c, "rain_may_oct_mm"]
        classes[c] = f"{rain.min():.0f}--{rain.max():.0f} mm, {len(rain)} yr"
    (OUT / "baseline.tex").write_text(baseline_summary(base))
    (OUT / "previous_crop.tex").write_text(maize_by_previous(base))
    (OUT / "year_class.tex").write_text(maize_by_class(base, classes))
    (OUT / "scenarios.tex").write_text(scenarios_table(frames))
    (OUT / "years.tex").write_text(year_table(base))
    (OUT / "smap.tex").write_text(smap_check((RUNS / "baseline.log").read_text()))
    print(f"Wrote {len(list(OUT.glob('*.tex')))} tables to {OUT.relative_to(ROOT)} from {len(frames)} runs")


if __name__ == "__main__":
    main()
