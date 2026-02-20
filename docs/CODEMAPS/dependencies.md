<!-- Generated: 2026-02-20 | Files scanned: 4 | Token estimate: ~400 -->

# Dependencies — Arlington Zoning Analyzer

## Python Version
Requires **Python 3.11+** (pandas 3.0 + numpy 2.4 constraint).

## Core Libraries

| Library | Version | Purpose |
|---------|---------|---------|
| `geopandas` | latest | Spatial data I/O, spatial joins, CRS management |
| `shapely` | latest | Geometry operations, lot metric calculations |
| `pandas` | 3.0+ | Tabular data processing |
| `numpy` | 2.4+ | Numeric calculations |
| `pyogrio` | latest | Fast GeoPackage/GeoJSON I/O backend for geopandas |
| `requests` | latest | HTTP downloads from Arlington Open Data APIs |
| `folium` / Leaflet | latest | Interactive HTML map generation |

## External Services

| Service | Auth | Purpose |
|---------|------|---------|
| Arlington GIS Open Data | None | Parcel, zoning, GLUP, building height GeoJSON |
| Arlington Open Data API | None | Property records (paginated REST) |
| Arlington Open Data API | None | Assessment records (paginated REST) |

**Key API base URLs:**
- GIS: `gisdata-arlgis.opendata.arcgis.com/api/download/v1/items/...`
- Property: `datahub-v2.arlingtonva.us/api/RealEstate/Property`
- Assessment: `datahub-v2.arlingtonva.us/api/RealEstate/Assessment`

## Standard Library Usage
- `pathlib.Path` — all file path operations
- `json` — config loading, API response parsing
- `logging` — structured console output
- `dataclasses` — result objects (DevelopmentPotentialResult, etc.)
- `argparse` — CLI argument parsing in scripts
- `datetime` — data freshness checks

## Dev Dependencies
- `pytest` — unit tests (`tests/`)
- `jupyter` / `jupyterlab` — analysis notebooks (`notebooks/`)

## No External Infrastructure Required
- No database
- No message queue
- No web server
- All data cached locally under `data/`
