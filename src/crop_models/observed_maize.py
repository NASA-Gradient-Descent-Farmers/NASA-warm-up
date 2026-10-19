"""Download official SIAP municipal maize observations and prepare a one-site benchmark.

Source: https://nube.agricultura.gob.mx/datosAbiertos/Agricola.php
Filter: Estado de México (15), Texcoco (99), Primavera-Verano (2), Temporal (2), Maíz grano.
Yield is production / harvested area, as reported; no assumed moisture conversion.
"""

import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import requests

URL = "https://nube.agricultura.gob.mx/index.php?view=10AE434F-A2158368-A120BC5A-EDF4AFAA&ANIO={year}"


def extract_texcoco(frame, year):
    frame = frame.rename(columns=lambda c: c.strip().lower())
    frame = frame.rename(columns={"nomcultivo sin um": "nomcultivo"})  # SIAP's 2015 export
    if "nomcultivo" not in frame:
        raise ValueError(f"Unexpected schema for {year}: {list(frame.columns)}")
    selected = frame[
        (frame.idestado == 15)
        & (frame.idmunicipio == 99)
        & (frame.idciclo == 2)
        & (frame.idmodalidad == 2)
        & (frame.nomcultivo.str.casefold() == "maíz grano")
    ]
    if selected.empty or not (selected.anio == year).all():
        raise ValueError(f"Missing or mismatched Texcoco rainfed maize observations for {year}")
    quantities = selected[["cosechada", "volumenproduccion", "sembrada"]].apply(pd.to_numeric, errors="raise")
    if not np.isfinite(quantities.to_numpy()).all():
        raise ValueError(f"Missing or invalid area/production in {year}")
    area, production, sown = quantities.sum().tolist()
    if not np.isfinite([area, production, sown]).all() or area <= 0 or production < 0 or sown < area:
        raise ValueError(f"Invalid area or production in {year}")
    return {
        "year": year,
        "observed_yield_t_ha": production / area,
        "harvested_ha": area,
        "sown_ha": sown,
        "production_t": production,
        "source_rows": len(selected),
    }


def fetch(year, directory):
    path = directory / f"{year}.csv"
    if not path.exists():
        response = requests.get(URL.format(year=year), timeout=90)
        response.raise_for_status()
        # Validate before caching; error pages must not become permanent inputs.
        from io import BytesIO

        frame = pd.read_csv(BytesIO(response.content), encoding="cp1252", low_memory=False)
        extract_texcoco(frame, year)
        path.write_bytes(response.content)
    row = extract_texcoco(pd.read_csv(path, encoding="cp1252", low_memory=False), year)
    print(f"Loaded observed year {year}", flush=True)
    return row, {
        "year": year,
        "url": URL.format(year=year),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def prepare(rows, weather):
    observed = pd.DataFrame(rows).sort_values("year")
    if observed.year.duplicated().any():
        raise ValueError("Duplicate observed years")
    # Require consecutive calendar years; never label a distant observation as last year's yield.
    observed["previous_yield_t_ha"] = observed.observed_yield_t_ha.shift()
    observed.loc[observed.year.diff() != 1, "previous_yield_t_ha"] = np.nan
    rain = weather[["year", "rain_may_oct_mm"]].drop_duplicates()
    if rain.year.duplicated().any():
        raise ValueError("Weather must contain a single unscaled rain total per year")
    joined = observed.merge(rain, on="year", how="left", validate="one_to_one")
    if joined.rain_may_oct_mm.isna().any():
        raise ValueError("Missing baseline weather years; extend the WOFOST weather export")
    return joined.dropna(subset=["previous_yield_t_ha"]).reset_index(drop=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-year", type=int, default=2005)
    parser.add_argument("--end-year", type=int, default=2025)
    parser.add_argument("--weather", type=Path, default=Path("data/rotations/baseline.csv"))
    parser.add_argument("--out-dir", type=Path, default=Path("data/observations"))
    args = parser.parse_args()
    if args.start_year < 2003 or args.end_year < args.start_year:
        parser.error("Municipal series starts in 2003; end-year must follow start-year")
    weather = pd.read_csv(args.weather)
    if not (weather.rain_factor == 1).all():
        parser.error("Weather must come from the baseline, unscaled simulation")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(lambda year: fetch(year, args.out_dir), range(args.start_year, args.end_year + 1))
        )
    rows, sources = zip(*results)
    pd.DataFrame(rows).sort_values("year").to_csv(args.out_dir / "texcoco_raw_annual.csv", index=False)
    prepared = prepare(rows, weather)
    prepared.to_csv(args.out_dir / "texcoco_maize.csv", index=False)
    metadata = {
        "source_page": "https://nube.agricultura.gob.mx/datosAbiertos/Agricola.php",
        "filters": {"state": 15, "municipality": 99, "cycle": 2, "water_mode": 2, "crop": "Maíz grano"},
        "yield_basis": "production tonnes / harvested hectares; reported basis; no moisture conversion",
        "sources": sources,
        "weather": {
            "path": str(args.weather.resolve()),
            "sha256": hashlib.sha256(args.weather.read_bytes()).hexdigest(),
        },
        "limitations": "Municipal averages have no rotation history, fertilizer doses, or field matching.",
    }
    (args.out_dir / "sources.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Prepared {len(prepared)} observed years in {args.out_dir / 'texcoco_maize.csv'}")


if __name__ == "__main__":
    main()
