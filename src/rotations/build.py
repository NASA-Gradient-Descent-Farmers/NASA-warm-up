"""Build every table the rotation tool needs (~3 min once the SIAP and POWER caches exist).

    python -m src.rotations.build

1. SIAP district x crop history (data/siap/ annual files, downloaded if missing)
2. NASA POWER monthly normals per municipality and district (data/power_cells/, fetched if missing),
   with rain corrected by CHIRPS where data/yield_panel/chirps_municipal_1999_2025.csv exists
3. MODIS NDVI and SMAP root-zone moisture by month (observed.py), when the yield-panel caches exist
"""

from src.yield_panel import weather

from . import climate, observed, siap_stats


def fetch_missing_cells():
    municipalities = weather.assign_cells(weather.load_municipalities())
    cells = municipalities.drop_duplicates("cell_id")
    for cell in cells.itertuples(index=False):
        weather.fetch_cell(cell.cell_lat, cell.cell_lon, 1981, 2025)


def main():
    siap_stats.build()
    fetch_missing_cells()
    climate.build()
    if observed.NDVI_FILE.exists():   # MODIS / SMAP caches come from the yield-panel pipeline (src.yield_panel.enrich)
        observed.build()


if __name__ == "__main__":
    main()
