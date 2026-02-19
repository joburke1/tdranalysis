# Arlington Zoning Analyzer

A Python tool for analyzing maximum by-right residential development potential for parcels in Arlington County, Virginia based on the Zoning Ordinance.

## Overview

This tool determines what can be built on a residential parcel "by-right" (without special permits) based on:

- **Zoning District**: R-20, R-10, R-10T, R-8, R-6, R-5, R15-30T, R2-7
- **Lot Dimensions**: Area, width, depth calculated from parcel geometry
- **Development Standards**: Height, coverage, and footprint limits from the Zoning Ordinance

Disclaimer: The analysis is based on **Article 5 (Residential Districts)** and **Article 3 (Density and Dimensional Standards)** of the Arlington County Zoning Ordinance.  A copy of the zoning code downloaded from https://www.arlingtonva.us/Government/Programs/Building/Codes-Ordinances/Zoning on October 1, 2025 is provided for reference, however the code may have changed. This project is a point in time implementation intended to support policy analysis.  Do not use for other purposes.

## Features

- Download and cache GIS data from Arlington County's Open Data Portal
- Spatial join of parcels to zoning districts
- Calculate lot metrics (area, width, depth) from geometry
- Validate conformance against zoning requirements
- Determine maximum building footprint, lot coverage, and height
- Identify limiting factors for development

## Requirements

- **Python 3.11+** (required by pandas 3.0 and numpy 2.4)

## Installation

```bash
# Clone the repository
git clone <repository-url>
cd arlington-zoning-analyzer

# Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

## Quick Start

### 1. Set Up Virtual Environment

```bash
# Create virtual environment
python -m venv venv

# Activate it
venv\Scripts\activate     # Windows
# source venv/bin/activate  # macOS/Linux

# Install dependencies
pip install -r requirements.txt
```

### 2. Verify Environment

```bash
python scripts/verify_env.py
```

All checks should pass (the "data not downloaded" warning is expected on first run).

### 3. Run the MVP Analysis (single neighborhood)

```bash
# Download data + process + analyze a single neighborhood:
python scripts/run_analysis.py --neighborhood "Lyon Park"

# See all available neighborhoods (after first download+process):
python scripts/run_analysis.py --list-neighborhoods

# Check how fresh the downloaded data is:
python scripts/run_analysis.py --check-data
```

Results are saved to `data/results/{neighborhood}/`:
- `*_analysis.gpkg` — GeoPackage with all analysis columns (open in QGIS)
- `*_analysis.csv` — Flat CSV for review in Excel
- `*_summary.txt` — Human-readable statistics

### 4. Batch Processing (all neighborhoods)

```bash
python scripts/run_analysis.py --all-neighborhoods
```

This runs every civic association neighborhood sequentially and also saves
a combined `data/results/all_neighborhoods_combined.csv`.

### 5. Refresh Data

```bash
# Force re-download of all source datasets:
python scripts/run_analysis.py --neighborhood "Lyon Park" --force-refresh
```

### 6. Python API (single parcel)

```python
from shapely.geometry import box
from src.analysis import analyze_development_potential

# Create a test parcel (60ft x 100ft = 6,000 sf)
parcel_geometry = box(0, 0, 60, 100)

result = analyze_development_potential(
    geometry=parcel_geometry,
    zoning_district="R-6",
    parcel_id="test-parcel"
)

print(f"Conforming: {result.is_conforming}")
print(f"Max Building Footprint: {result.max_building_footprint_sf:,.0f} sf")
print(f"Max Height: {result.max_height_ft} ft")
```

## Project Structure

```
arlington-zoning-analyzer/
├── calculation proceedures/     # Calculation methodology documentation
│   ├── maximum development potential human.md
│   └── maximum development potential llm.md
├── config/                      # Zoning rules configuration
│   ├── residential_districts.json
│   └── setback_rules.json
├── data/                        # Data directory (gitignored)
│   ├── raw/                     # Downloaded GeoJSON files
│   └── processed/               # Enriched GeoPackage files
├── src/
│   ├── data/                    # Data download and processing
│   │   ├── downloader.py
│   │   └── processor.py
│   ├── geometry/                # Lot metric calculations
│   │   └── lot_metrics.py
│   ├── rules/                   # Zoning rules engine
│   │   ├── engine.py
│   │   └── validators.py
│   └── analysis/                # Development potential analysis
│       └── development_potential.py
├── tests/                       # Unit tests
├── notebooks/                   # Jupyter notebooks
├── requirements.txt
└── README.md
```

## Calculation Procedures

The `calculation proceedures/` directory contains step-by-step documentation of how maximum development potential is calculated from zoning rules and parcel geometry:

- **maximum development potential human.md** — Written for human readers, explaining the calculation methodology in plain language.
- **maximum development potential llm.md** — Structured for LLM consumption, providing the same calculation logic in a format optimized for AI-assisted analysis and code generation.

These documents serve as the authoritative reference for the analysis logic implemented in `src/`.

## Configuration

Zoning rules are stored in JSON configuration files in the `config/` directory. These can be updated when the Zoning Ordinance changes without modifying code.

### residential_districts.json

Contains by-right development standards for each residential district:
- Minimum lot area and width
- Maximum height
- Maximum lot coverage percentages
- Maximum building footprint percentages and caps
- Parking requirements

### setback_rules.json

Contains setback and yard requirements from Article 3, §3.2.

## Output

The `DevelopmentPotentialResult` object contains:

| Field | Description |
|-------|-------------|
| `parcel_id` | Parcel identifier |
| `zoning_district` | Zoning district code |
| `lot_area_sf` | Calculated lot area (sq ft) |
| `lot_width_ft` | Calculated lot width (ft) |
| `is_conforming` | Whether lot meets minimum requirements |
| `limiting_factors` | What's constraining development |
| `max_height_ft` | Maximum building height |
| `max_building_footprint_sf` | Maximum main building footprint |
| `max_lot_coverage_sf` | Maximum total lot coverage |
| `max_dwelling_units` | Maximum dwelling units by-right |

## Neighborhood Validation Runbook

Repeatable process for validating analysis results when adding a new civic association neighborhood. Derived from the Alcova Heights validation.

### Step 1: Run the Analysis

```bash
python scripts/run_analysis.py --neighborhood "Neighborhood Name"
```

Review the console summary. Key things to check:
- **Parcel count**: Does the number of residential parcels seem reasonable for the neighborhood size?
- **Exclusion counts**: Review each filter's exclusion count in the log output. Large numbers may indicate the neighborhood has unusual zoning or property characteristics.
- **Neighborhood improvement rate**: Check the derived $/SF rate and sample size. If the fallback ($185/SF) was used, the neighborhood has fewer than 5 homes built in the last 10 years — results should be interpreted with extra caution.
- **Development status breakdown**: Expect most parcels to be "underdeveloped" in established neighborhoods. A high count of "vacant" or "overdeveloped" parcels warrants investigation.

### Step 2: Run Anomaly Detection

```bash
python scripts/run_anomaly_check.py --neighborhood "Neighborhood Name"
```

This produces `anomaly_report.csv` and `anomaly_summary.txt` in the results directory. Review:
- **auto-exclude tier**: These have disqualifying data problems. The pipeline already handles the most common cases (non-residential classes, remnant parcels, no-GFA-data buildings), but check if any new patterns appear.
- **flag-for-review tier**: These need manual spot-checking. Common flags:
  - `building_detected_no_gfa_data` — now auto-excluded by the pipeline
  - `statistical_outlier` — large/small values relative to the zoning district
  - `low_improvement_value` — GFA estimate may be unreliable
  - `unusual_property_type` — HOA common areas or other edge cases
- **Impact on aggregates**: Compare clean-tier totals vs full analysis. If >10% of aggregate value comes from flagged parcels, the analysis needs more spot-checking before use.

### Step 3: Spot-Check Vacant Parcels

All parcels classified as "vacant" (development_status = "vacant") should be manually verified:

1. Open the analysis CSV and filter to `development_status = vacant`
2. For each vacant parcel, look up the address on the Arlington County assessor website: `https://propertysearch.arlingtonva.us`
3. Verify: Is the lot actually vacant? Is it buildable (not a park, utility easement, etc.)?
4. Check if the parcel meets the 80% conforming lot size threshold for its zoning district

Record results in `data/results/{neighborhood}/spot_checks.csv`:
```csv
parcel_id,spot_check_result,spot_check_notes,spot_check_date
23027001,confirmed,Vacant lot confirmed,2026-02-19
23003002,excluded,Commercial building in residential zone,2026-02-19
```

Valid `spot_check_result` values:
- `confirmed` — parcel analysis is correct; include in results
- `excluded` — parcel should be removed from analysis (will be auto-excluded on next run)
- `vacant-confirmed-buildable` — vacant and verified as buildable lot
- `incorrect` — data issue identified; add details in notes

### Step 4: Spot-Check Flagged Parcels

Review parcels from the anomaly report's "flag-for-review" tier:

1. **Statistical outliers**: Look up parcels with high Z-scores on the assessor website. Large lots in established neighborhoods are typically valid (not data errors). Unusually low values may indicate assessment data lag.
2. **Low improvement value**: Parcels with improvement value < $30,000 produce unreliable GFA estimates. Verify on the assessor site whether the building is a shed, garage, or legitimate residence.
3. **Split-zoned parcels**: If the neighborhood has many split-zoned parcels, check a sample to confirm the primary zone assignment is correct.

### Step 5: Re-run and Verify

After adding spot check records:

```bash
python scripts/run_analysis.py --neighborhood "Neighborhood Name" --skip-download
python scripts/run_anomaly_check.py --neighborhood "Neighborhood Name"
```

Verify:
- Excluded parcels are removed from analysis
- Anomaly report shows fewer flag-for-review parcels
- Aggregate values are stable (no large swings from spot-check exclusions)

### Automated Pipeline Filters (applied before analysis)

These filters run automatically on every analysis — no manual intervention needed:

| Filter | What it removes | Rationale |
|--------|----------------|-----------|
| Zoning district | Non-R-5/R-6/R-8/R-10/R-20 zones | By-right standards only apply to one-family districts |
| Property class 201/210 | Commercial vacant land, parking | Non-residential use |
| Class 510 remnants | Vacant parcels < 80% of min lot size | Alley strips, unbuildable remnants |
| No property API record | Parcels with no address or class | Administrative parcels, unregistered strips |
| No GFA data | Building exists but no improvement value | GFA estimation impossible; analysis unreliable |
| Spot check exclusions | Parcels marked "excluded" in spot_checks.csv | Persistent manual review decisions |

## Limitations

1. **By-right only**: Does not analyze special exception or site plan scenarios
2. **One-family focus**: Currently analyzes one-family dwelling potential only
3. **Lot width calculation**: Uses minimum bounding rectangle method, which may not match legal definition for irregular lots
4. **Split zoning**: Parcels spanning multiple zones are flagged but use primary zone
5. **Setbacks**: Setback calculations are not yet implemented (requires street geometry)

## Data Sources

- **Parcels**: REA Property Polygons from Arlington Open Data
- **Zoning**: Zoning Polygons from Arlington Open Data
- **GLUP**: General Land Use Plan from Arlington Open Data

Data is maintained in Virginia State Plane North (EPSG:2283) for accurate area calculations.

## Legal Disclaimer

This tool is for informational purposes only. The output should not be construed as legal or professional advice. Always consult the official Arlington County Zoning Ordinance and work with qualified professionals for actual development projects.

## License

[Add license information]
