"""Crop-rotation comparison for Mexican farms (the `comparar_rotaciones` tool).

Modules:
- catalog:   crop traits (tables/crops.csv) and their sources (tables/crop_sources.csv)
- siap_stats: SIAP district x crop x cycle x water-regime history, 2003-2025
- climate:   monthly climate normals per municipality and district from NASA POWER
- indicators: per-crop and per-rotation indicators (income, risk, water, N, C, cover, pests, forage)
- candidates: alternative rotations built from crops the district already grows
- cards:     Spanish explanation cards
- compare:   comparar_rotaciones(), the entry point
"""
