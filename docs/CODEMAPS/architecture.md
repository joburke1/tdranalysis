<!-- Generated: 2026-02-20 | Files scanned: 15 | Token estimate: ~650 -->

# Architecture � Arlington Zoning Analyzer

## System Type
CLI data analysis pipeline. No web server, no database. Reads from external APIs and local file cache; writes to local files.

## High-Level Flow

```
External APIs / GIS Portal
        |
        v
  [1] ArlingtonDataDownloader     data/raw/*.geojson + *.json (cached)
        |
        v
  [2] DataProcessor               data/processed/parcels_enriched.gpkg
        |  spatial join: parcels <- zoning, neighborhoods
        |  tabular join: parcels <- property API, assessment API
        v
  [3] Neighborhood Filter          gdf filtered to target civic assoc.
        |  exclusion filters (6 sequential rules)
        v
  [4] Analysis Pipeline (per parcel)
        |  Stage 1: analyze_development_potential()  max by-right potential
        |  Stage 2: analyze_current_built()          existing building GFA
        |  Stage 3: calculate_available_rights()     remaining capacity
        |  Stage 4: calculate_valuation()            monetary value estimate
        v
  [5] Output Writers
        +- *_analysis.gpkg            GeoPackage for QGIS
        +- *_analysis.geojson         for web/Leaflet maps
        +- *_analysis.csv             for Excel/review
        +- *_summary.txt              human-readable stats
        +- *_data_dictionary.csv      column definitions
        +- map.html                   self-contained Leaflet map
```

## Entry Points

| Script | Purpose |
|--------|---------|
| `scripts/run_analysis.py` | Full pipeline runner (primary entry point) |
| `scripts/run_anomaly_check.py` | Standalone data quality QA pass |
| `scripts/generate_map.py` | Standalone interactive HTML map generator |
| `scripts/verify_env.py` | Dependency/environment checker |

## Module Map

```
src/
+-- data/
|   +-- downloader.py     ArlingtonDataDownloader -- fetch + cache raw data
|   +-- processor.py      DataProcessor -- spatial joins, enrichment
+-- geometry/
|   +-- lot_metrics.py    calculate_lot_metrics() -- area, width, depth
+-- rules/
|   +-- engine.py         ZoningRulesEngine -- loads config -> DevelopmentStandards
|   +-- validators.py     validate_lot_conformance() -- lot meets zoning minimums
+-- analysis/
    +-- development_potential.py  Stage 1 -- max allowable GFA/footprint/height
    +-- current_built.py          Stage 2 -- GFA + year built from records
    +-- available_rights.py       Stage 3 -- remaining capacity = max - current
    +-- valuation.py              Stage 4 -- 4-method monetary value estimate
    +-- anomaly_detection.py      QA -- tiered data quality flags
```

## Exclusion Filter Chain

```
1. Non-residential zoning (not R-5/R-6/R-8/R-10/R-20)
2. Property class 201/210 (commercial vacant / parking)
3. Class 510 remnants (vacant parcel < 80% of min lot size)
4. No property API record (no address or class code)
5. No GFA data (building exists, improvement value absent)
6. Spot check exclusions (parcel marked "excluded" in spot_checks.csv)
```

## Data Flow Per Parcel

```
parcel row (GeoDataFrame)
  |
  +- geometry -> lot_metrics -> lot_area_sf, lot_width_ft, lot_depth_ft
  |
  +- zoning_district + lot metrics -> rules/engine -> DevelopmentStandards
  |                                -> development_potential -> DevelopmentPotentialResult
  |
  +- property/assessment fields -> current_built -> CurrentBuiltResult
  |                               (GFA priority: property_api -> improvement_value -> N/A)
  |
  +- DevelopmentPotentialResult + CurrentBuiltResult
  |   -> available_rights -> AvailableRightsResult
  |     (available_gfa_sf, gfa_utilization_pct, development_status)
  |
  +- AvailableRightsResult + land_value + neighborhood_rate
      -> valuation -> ValuationResult
        (est_value_low, est_value_high)
```
