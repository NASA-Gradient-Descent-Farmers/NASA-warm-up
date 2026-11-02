"""Build the municipality x year x crop panel: SIAP outcomes + NASA POWER season weather + GLDAS soils.

Usage (from the repo root):
    python -m src.yield_panel.build                                  # central Mexico, 2003-2025
    python -m src.yield_panel.build --states all --crops maize bean
    python -m src.yield_panel.build --states 11 14 16 22 --start 2005 --end 2025 --out data/yield_panel/bajio.csv

Downloads are cached under data/ (SIAP ~25 national files; one POWER file per grid cell).
"""

import argparse
from pathlib import Path

import pandas as pd

from src.data_ingestion.common import DATA_DIR
from src.yield_panel import siap, weather

# Aguascalientes, Guanajuato, Hidalgo, Jalisco, México, Michoacán, Morelos, Puebla, Querétaro, Tlaxcala, Zacatecas
CENTRAL_STATES = [1, 11, 13, 14, 15, 16, 17, 21, 22, 29, 32]

# Implausible municipal rainfed yields (t/ha), treated as data errors.
MAX_YIELD = {"maize": 15, "bean": 5, "sorghum": 15, "wheat": 10, "barley": 10, "oats": 10}


def build_panel(years, crops=None, states=None, min_sown_ha=50.0, min_years=10, workers=4, with_soils=True):
    """Return (panel, info). `states=None` means all states."""
    crops = {k: siap.DEFAULT_CROPS[k] for k in (crops or siap.DEFAULT_CROPS)}
    outcomes = siap.load_panel(years, crops)
    if states:
        outcomes = outcomes[outcomes["state_id"].isin(states)]
    outcomes = siap.clean_panel(outcomes, min_sown_ha=min_sown_ha, min_years=min_years, max_yield=MAX_YIELD)

    munis = weather.load_municipalities()
    used = outcomes[["state_id", "mun_id"]].drop_duplicates()
    located = used.merge(munis, on=["state_id", "mun_id"], how="left", indicator=True)
    unlocated = located[located["_merge"] == "left_only"][["state_id", "mun_id"]]
    munis = located[located["_merge"] == "both"].drop(columns="_merge")

    season, munis, failed_cells = weather.build_weather(munis, years, workers=workers)
    static = munis[["state_id", "mun_id", "state", "municipality", "lat", "lon", "alt_m", "cell_id"]]
    if with_soils:
        static = static.merge(weather.build_soils(munis), on=["state_id", "mun_id"], how="left")

    panel = (outcomes.merge(static, on=["state_id", "mun_id"], how="inner")
             .merge(season.drop(columns="cell_id"), on=["state_id", "mun_id", "year"], how="inner"))
    info = {
        "rows": len(panel),
        "municipalities": panel[["state_id", "mun_id"]].drop_duplicates().shape[0],
        "crops": panel.groupby("crop").size().to_dict(),
        "years": f"{panel['year'].min()}-{panel['year'].max()}",
        "power_cells": munis["cell_id"].nunique(),
        "unlocated_municipalities": unlocated.values.tolist(),
        "failed_cells": failed_cells,
    }
    return panel.sort_values(["crop", "state_id", "mun_id", "year"]).reset_index(drop=True), info


def main():
    parser = argparse.ArgumentParser(description="Build the SIAP + POWER + GLDAS municipal panel.")
    parser.add_argument("--start", type=int, default=2003)
    parser.add_argument("--end", type=int, default=2025)
    parser.add_argument("--states", nargs="+", default=[str(s) for s in CENTRAL_STATES],
                        help="INEGI state codes, or 'all' (default: central Mexico)")
    parser.add_argument("--crops", nargs="+", default=list(siap.DEFAULT_CROPS), choices=list(siap.DEFAULT_CROPS))
    parser.add_argument("--min-sown-ha", type=float, default=50.0)
    parser.add_argument("--min-years", type=int, default=10)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--no-soils", action="store_true")
    parser.add_argument("--out", type=Path, default=DATA_DIR / "yield_panel" / "panel.csv")
    args = parser.parse_args()

    states = None if args.states == ["all"] else [int(s) for s in args.states]
    panel, info = build_panel(range(args.start, args.end + 1), args.crops, states, args.min_sown_ha,
                              args.min_years, args.workers, with_soils=not args.no_soils)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(args.out, index=False)
    for key, value in info.items():
        print(f"{key}: {value}")
    print(f"Saved {len(panel)} rows to {args.out}")


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    main()
