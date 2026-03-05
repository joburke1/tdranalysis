<!-- Generated: 2026-02-20 | Files scanned: 6 | Token estimate: ~500 -->

# Data � Arlington Zoning Analyzer

## External Data Sources

| Source | Format | URL / API |
|--------|--------|-----------|
| REA Property Polygons | GeoJSON | gisdata-arlgis.opendata.arcgis.com |
| Zoning Polygons | GeoJSON | gisdata-arlgis.opendata.arcgis.com |
| General Land Use Plan (GLUP) | GeoJSON | gisdata-arlgis.opendata.arcgis.com |
| Building Heights | GeoJSON | gisdata-arlgis.opendata.arcgis.com |
| Property records | JSON (paginated REST) | datahub-v2.arlingtonva.us/api/RealEstate/Property |
| Assessment records | JSON (paginated REST) | datahub-v2.arlingtonva.us/api/RealEstate/Assessment |

## Local File Layout

```
data/
+-- raw/                         Downloaded and cached
|   +-- parcels.geojson
|   +-- zoning.geojson
|   +-- glup.geojson
|   +-- building_heights.geojson
|   +-- property.json
|   +-- assessment.json
+-- processed/
|   +-- parcels_enriched.gpkg    Spatial + tabular join output (CRS: EPSG:2283)
+-- results/
    +-- {neighborhood}/
    |   +-- *_analysis.gpkg
    |   +-- *_analysis.geojson
    |   +-- *_analysis.csv
    |   +-- *_summary.txt
    |   +-- *_data_dictionary.csv
    |   +-- map.html
    |   +-- spot_checks.csv      (manual; auto-applied on re-run)
    |   +-- anomaly_report.csv
    |   +-- anomaly_summary.txt
    +-- all_neighborhoods_combined.csv
```

## CRS

All spatial data is reprojected to **EPSG:2283** (NAD83 / Virginia State Plane North, ft) for accurate area calculations.

## Key Join Fields

| Join | Left key | Right key |
|------|----------|-----------|
| Parcels -> Zoning | geometry (spatial) | geometry (spatial) |
| Parcels -> Neighborhoods | geometry (spatial) | geometry (spatial) |
| Parcels -> Property | `RPCMSTR` | `realEstatePropertyCode` |
| Parcels -> Assessment | `RPCMSTR` | `realEstatePropertyCode` |

## Configuration Schemas

### config/residential_districts.json
Per-district development standards (keyed by district code, e.g. "R-6"):
- `min_lot_area_sf`, `min_lot_area_per_unit_sf`, `min_lot_width_ft`
- `max_height_ft`, `max_lot_coverage_pct`
- `max_footprint_pct`, `max_footprint_cap_sf`
- `parking_spaces_per_unit`

### config/setback_rules.json
Yard and setback requirements from Article 3, �3.2 (keyed by district):
- `front_yard_ft`, `side_yard_ft`, `rear_yard_ft`

### config/valuation_params.json
Market parameters for rights valuation:
- `land_residual_discount_factor`: {low, high} � default 0.55 / 0.75
- `residential_improvement_value_per_sf`: fallback $185/SF
- `neighborhood_rate_calibration`: lookback_years=10, min_sample=5

### config/data_dictionary.json
Column definitions for all 40 output fields (label, description, source, example).
Also exported as `*_data_dictionary.csv` alongside each analysis run.

## Spot Checks Schema

`data/results/{neighborhood}/spot_checks.csv`:
```
parcel_id, spot_check_result, spot_check_notes, spot_check_date
```
Valid results: confirmed | excluded | vacant-confirmed-buildable | incorrect

Parcels with `spot_check_result = excluded` are auto-removed on next run.
