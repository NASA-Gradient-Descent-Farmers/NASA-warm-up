"""Climate-twin reference library: curated agricultural sites worldwide with their climate signature (NASA POWER).

The list of crops grown at each site is TEAM-CURATED from general knowledge and UNVERIFIED. Replace it with
MapSPAM / FAOSTAT / national crop maps before making any claim. Crop ids match web/public/data/crops.json.

Usage: .venv/bin/python -m src.advisor.build_references
Writes web/public/data/reference_sites.json
"""

import json
from pathlib import Path

from src.data_ingestion import power

from . import features, pull

OUT = Path(__file__).resolve().parents[2] / "web" / "public" / "data" / "reference_sites.json"

# (id, name, lat, lon, crops grown)
SITES = [
    ("ames_us", "Ames, Iowa (USA)", 42.03, -93.47, ["maize", "soybean"]),
    ("hutchinson_us", "Kansas, USA", 38.06, -97.93, ["wheat", "sorghum", "soybean", "maize", "alfalfa"]),
    ("london_ca", "Ontario, Canada", 43.0, -81.2, ["maize", "soybean", "wheat"]),
    ("texcoco_mx", "Texcoco, Mexico", 19.53, -98.85, ["maize", "bean", "faba", "wheat"]),
    ("celaya_mx", "Bajío, Mexico", 20.52, -100.82, ["maize", "sorghum", "wheat", "bean", "alfalfa"]),
    ("culiacan_mx", "Sinaloa, Mexico", 24.8, -107.4, ["maize", "sorghum", "bean"]),
    ("bogota_co", "Bogotá plateau, Colombia", 4.8, -74.1, ["maize", "bean"]),
    ("pergamino_ar", "Pampas, Argentina", -33.89, -60.57, ["soybean", "maize", "wheat"]),
    ("cordoba_ar", "Córdoba, Argentina", -31.4, -64.2, ["soybean", "maize", "wheat", "sorghum", "alfalfa"]),
    ("londrina_br", "Paraná, Brazil", -23.3, -51.2, ["soybean", "maize", "wheat"]),
    ("sorriso_br", "Mato Grosso, Brazil", -12.5, -55.7, ["soybean", "maize", "sorghum"]),
    ("talca_cl", "Central Chile", -35.4, -71.6, ["wheat", "maize", "alfalfa"]),
    ("ludhiana_in", "Punjab, India", 30.9, 75.85, ["wheat", "maize"]),
    ("karnal_in", "Haryana, India", 29.7, 76.98, ["wheat", "maize"]),
    ("solapur_in", "Maharashtra, India", 17.7, 75.9, ["sorghum", "soybean", "maize"]),
    ("faisalabad_pk", "Punjab, Pakistan", 31.4, 73.1, ["wheat", "maize", "alfalfa"]),
    ("shijiazhuang_cn", "North China Plain", 38.0, 114.5, ["wheat", "maize"]),
    ("harbin_cn", "Heilongjiang, China", 45.75, 126.6, ["maize", "soybean"]),
    ("korat_th", "Northeast Thailand", 14.97, 102.1, ["maize", "soybean", "bean"]),
    ("nakuru_ke", "Rift Valley, Kenya", -0.3, 36.07, ["maize", "bean", "wheat"]),
    ("debrezeit_et", "Ethiopian highlands", 8.75, 38.98, ["wheat", "faba", "sorghum", "maize"]),
    ("kano_ng", "Kano, Nigeria", 12.0, 8.5, ["sorghum", "maize", "bean"]),
    ("niamey_ne", "Sahel, Niger", 13.5, 2.1, ["sorghum"]),
    ("harare_zw", "Zimbabwe", -17.8, 31.05, ["maize", "soybean", "bean"]),
    ("bethlehem_za", "Free State, South Africa", -28.2, 28.3, ["maize", "soybean", "wheat", "sorghum"]),
    ("tanta_eg", "Nile Delta, Egypt", 30.8, 31.0, ["maize", "wheat", "alfalfa"]),
    ("meknes_ma", "Meknès, Morocco", 33.9, -5.5, ["wheat", "faba", "alfalfa"]),
    ("seville_es", "Andalusia, Spain", 37.4, -5.98, ["wheat", "faba", "alfalfa"]),
    ("valladolid_es", "Castile, Spain", 41.65, -4.72, ["wheat", "alfalfa"]),
    ("chartres_fr", "Beauce, France", 48.45, 1.5, ["wheat", "faba", "maize"]),
    ("cremona_it", "Po valley, Italy", 45.13, 10.03, ["maize", "wheat", "soybean", "alfalfa"]),
    ("poltava_ua", "Ukraine", 49.6, 34.55, ["wheat", "maize", "soybean"]),
    ("toowoomba_au", "Queensland, Australia", -27.56, 151.95, ["wheat", "sorghum"]),
    ("merredin_au", "Western Australia", -31.5, 118.3, ["wheat", "faba"]),
]


def main():
    sites = json.loads(OUT.read_text())["sites"] if OUT.exists() else []
    done = {s["id"] for s in sites}
    for i, (sid, name, lat, lon, grown) in enumerate(SITES, start=1):
        if sid in done:
            continue
        print(f"[{i}/{len(SITES)}] {name}", flush=True)
        payload, status = pull.pull_power(lat, lon)
        if payload is None:
            print("    skipped:", status["reason"], flush=True)
            continue
        daily = power.to_dataframe(payload)
        climate, _, _, aridity, _ = features.monthly_features(daily, lat)
        sites.append({"id": sid, "name": name, "lat": lat, "lon": lon, "grown": grown,
                      "tmean_c": climate["tmean_c"], "rain_mm": climate["rain_mm"], "aridity_index": aridity})
        OUT.write_text(json.dumps({"_meta": {"status": "crops grown are TEAM-CURATED and UNVERIFIED",
                                              "climate": "NASA POWER 1991-2024 monthly means"}, "sites": sites}))
    print(f"{len(sites)} reference sites in {OUT}")


if __name__ == "__main__":
    main()

