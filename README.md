# Arlington Zoning Analyzer

A Python tool for analyzing maximum by-right residential development potential for parcels in Arlington County, Virginia based on the Zoning Ordinance.

## Overview

This tool determines what can be built on a residential parcel "by-right" (without special permits) and estimates the monetary value of unused development rights. Analysis is based on:

- **Zoning District**: R-20, R-10, R-10T, R-8, R-6, R-5, R15-30T, R2-7
- **Lot Dimensions**: Area, width, depth calculated from parcel geometry
- **Development Standards**: Height, coverage, and footprint limits from the Zoning Ordinance
- **Current Built Conditions**: Year built, GFA, dwelling units from property and assessment records
- **Market Parameters**: Configurable valuation inputs for estimating rights value

Disclaimer: The analysis is based on **Article 5 (Residential Districts)** and **Article 3 (Density and Dimensional Standards)** of the Arlington County Zoning Ordinance. A copy of the zoning code downloaded from https://www.arlingtonva.us/Government/Programs/Building/Codes-Ordinances/Zoning on October 1, 2025 is provided for reference, however the code may have changed. This project is a point in time implementation intended to support policy analysis. Do not use for other purposes.

## Features

- Download and cache GIS data from Arlington County's Open Data Portal
- Spatial join of parcels to zoning districts
- Calculate lot metrics (area, width, depth) from geometry
- Validate conformance against zoning requirements
- **4-stage analysis pipeline**: Development Potential → Current Built → Available Rights → Valuation (3-method)
- Identify limiting factors for development
- Estimate unused development rights (GFA, footprint, dwelling units)
- **Multi-method valuation**: Three independent methods with confidence ratings
- **Neighborhood calibration**: Derives local improvement rates from recent construction
- Automated anomaly detection with tiered data quality flags
- Interactive HTML maps, GeoPackage/GeoJSON for GIS, CSV exports

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

### 3. Run the Analysis (single neighborhood)

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
- `*_analysis.geojson` — GeoJSON for web mapping
- `*_analysis.csv` — Flat CSV for review in Excel
- `*_summary.txt` — Human-readable statistics
- `*_data_dictionary.csv` — Column definitions for the analysis output
- `map.html` — Self-contained interactive HTML map (no web server required)

### 4. Generate a Standalone Map

```bash
# Generate map for a neighborhood (also runs automatically after analysis):
python scripts/generate_map.py --neighborhood "Lyon Park"

# Generate from a specific GeoJSON file:
python scripts/generate_map.py --geojson data/results/Lyon\ Park/lyon_park_analysis.geojson

# Specify output location:
python scripts/generate_map.py --neighborhood "Lyon Park" --output my_map.html
```

The map is color-coded by development status and capacity, with tooltips showing full parcel details and a sidebar with neighborhood statistics.

### 5. Batch Processing (all neighborhoods)

```bash
python scripts/run_analysis.py --all-neighborhoods
```

This runs every civic association neighborhood sequentially and also saves
a combined `data/results/all_neighborhoods_combined.csv`.

### 6. Refresh Data

```bash
# Force re-download of all source datasets:
python scripts/run_analysis.py --neighborhood "Lyon Park" --force-refresh
```

### 7. Advanced Options

```bash
# Skip download, use cached data:
python scripts/run_analysis.py --neighborhood "Lyon Park" --skip-download

# Skip processing, load from pre-processed file:
python scripts/run_analysis.py --neighborhood "Lyon Park" --skip-process

# Custom directories:
python scripts/run_analysis.py --neighborhood "Lyon Park" \
  --data-dir data/raw --output-dir data/results --config-dir config

# Verbose logging:
python scripts/run_analysis.py --neighborhood "Lyon Park" --log-level DEBUG
```

### 8. Python API (single parcel)

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
├── config/                      # Zoning rules and market parameters
│   ├── residential_districts.json  # By-right development standards by zone
│   ├── setback_rules.json          # Setback and yard requirements
│   ├── data_dictionary.json        # Output column definitions (40 fields)
│   └── valuation_params.json       # Market parameters for rights valuation
├── data/                        # Data directory (gitignored)
│   ├── raw/                     # Downloaded GeoJSON files
│   ├── processed/               # Enriched GeoPackage files
│   └── results/                 # Analysis outputs by neighborhood
├── scripts/
│   ├── run_analysis.py          # Main analysis pipeline runner
│   ├── run_anomaly_check.py     # Data quality anomaly detection
│   ├── generate_map.py          # Interactive HTML map generator
│   └── verify_env.py            # Environment/dependency checker
├── src/
│   ├── data/                    # Data download and processing
│   │   ├── downloader.py
│   │   └── processor.py
│   ├── geometry/                # Lot metric calculations
│   │   └── lot_metrics.py
│   ├── rules/                   # Zoning rules engine
│   │   ├── engine.py
│   │   └── validators.py
│   └── analysis/                # 4-stage analysis pipeline
│       ├── development_potential.py  # Stage 1: Maximum by-right potential
│       ├── current_built.py          # Stage 2: Current building conditions
│       ├── available_rights.py       # Stage 3: Remaining development capacity
│       ├── valuation.py              # Stage 4: Monetary value of rights
│       └── anomaly_detection.py      # Data quality QA
├── tests/                       # Unit tests
├── notebooks/                   # Jupyter notebooks
├── requirements.txt
└── README.md
```

## Analysis Pipeline

The pipeline runs four stages sequentially for each parcel:

### Stage 1: Development Potential (`development_potential.py`)
Calculates the maximum allowable building based on zoning rules:
- Validates lot conformance (area, width)
- Applies height, coverage, and footprint limits from the Zoning Ordinance
- Identifies limiting factors (what constrains development)

### Stage 2: Current Built (`current_built.py`)
Extracts what is currently built from property and assessment records:
- GFA source priority: (1) property API, (2) estimated from improvement value, (3) not available
- Falls back to GFA estimation from improvement value when property API is silent (common for Arlington residential)
- Derives a **neighborhood improvement rate** ($/SF) from homes built in the last 10 years; falls back to $185/SF when sample is insufficient

### Stage 3: Available Rights (`available_rights.py`)
Computes remaining unused development capacity:
- `Available Rights = Maximum Potential − Current Built`
- Classifies parcels as `vacant`, `underdeveloped` (<80% GFA utilization), or `overdeveloped` (grandfathered above limit)

### Stage 4: Valuation (`valuation.py`)
Estimates monetary value of unused rights using three independent methods:
1. **Land Residual** — Land $/SF (from assessed value) × available GFA × discount factor
2. **Assessment Ratio** — Assessed land value × market-to-assessment ratio × availability fraction
3. **Price Per SF** — Configurable $/SF × available GFA

Returns a composite range (min low → max high of applicable methods) with a HIGH/MEDIUM/LOW confidence rating.

## Calculation Procedures

The `calculation proceedures/` directory contains step-by-step documentation of how maximum development potential is calculated from zoning rules and parcel geometry:

- **maximum development potential human.md** — Written for human readers, explaining the calculation methodology in plain language.
- **maximum development potential llm.md** — Structured for LLM consumption, providing the same calculation logic in a format optimized for AI-assisted analysis and code generation.

These documents serve as the authoritative reference for the analysis logic implemented in `src/`.

## Configuration

Zoning rules and market parameters are stored in JSON configuration files in the `config/` directory. These can be updated without modifying code.

### residential_districts.json

Contains by-right development standards for each residential district:
- Minimum lot area and width
- Maximum height
- Maximum lot coverage percentages
- Maximum building footprint percentages and caps
- Parking requirements

### setback_rules.json

Contains setback and yard requirements from Article 3, §3.2.

### valuation_params.json

Contains configurable market parameters that should be calibrated to current conditions:

| Parameter | Description |
|-----------|-------------|
| `market_to_assessment_ratio` | low: 1.0 / high: 1.15 — converts assessed value to market value |
| `price_per_available_gfa_sf` | low: $100 / high: $200 per SF of available GFA |
| `land_residual_discount_factor` | low: 0.6 / high: 0.85 — accounts for risk, demolition, carrying costs |
| `residential_improvement_value_per_sf` | Fallback $185/SF (used when neighborhood rate has insufficient sample) |
| `confidence_thresholds` | Min land value ($100k) and min available GFA (500 SF) for HIGH confidence |
| `neighborhood_rate_calibration` | lookback_years: 10, min_sample: 5 homes for local rate derivation |

### data_dictionary.json

Defines all 40 output columns with labels, descriptions, data sources, and examples. Also exported as `*_data_dictionary.csv` alongside each analysis run.

## Output

### Output Fields

| Field | Description |
|-------|-------------|
| `parcel_id` | Parcel identifier |
| `street_address` | Street address |
| `neighborhood` | Civic association neighborhood |
| `zoning_district` | Zoning district code |
| `is_split_zoned` | Whether parcel spans multiple zones |
| `lot_area_sf` | Calculated lot area (sq ft) |
| `lot_width_ft` | Calculated lot width (ft) |
| `lot_depth_ft` | Calculated lot depth (ft) |
| `is_conforming` | Whether lot meets zoning minimums |
| `conformance_status` | conforming / nonconforming / unknown |
| `limiting_factors` | What constrains development |
| `year_built` | Year existing structure was built |
| `property_type` | Property class code from assessor |
| `current_gfa_sf` | Current gross floor area (sq ft) |
| `current_stories` | Story count of existing structure |
| `land_value` | Assessed land value ($) |
| `improvement_value` | Assessed improvement value ($) |
| `gfa_source` | How GFA was determined (property_api / estimated_from_improvement_value / not_available) |
| `max_footprint_sf` | Maximum allowable building footprint |
| `max_gfa_sf` | Maximum allowable gross floor area |
| `max_height_ft` | Maximum building height |
| `max_dwelling_units` | Maximum dwelling units by-right |
| `available_gfa_sf` | Remaining GFA capacity (negative = overdeveloped) |
| `available_footprint_sf` | Remaining footprint capacity |
| `available_dwelling_units` | Remaining unit capacity |
| `gfa_utilization_pct` | Percentage of max GFA currently used |
| `development_status` | vacant / underdeveloped / overdeveloped |
| `est_value_low` | Lower bound estimated value of unused rights ($) |
| `est_value_high` | Upper bound estimated value of unused rights ($) |
| `valuation_confidence` | HIGH / MEDIUM / LOW / not_applicable |
| `neighborhood_imp_rate_median` | Median $/SF from recent neighborhood construction |
| `neighborhood_imp_rate_low` | Low end of neighborhood improvement rate range |
| `neighborhood_imp_rate_high` | High end of neighborhood improvement rate range |
| `neighborhood_imp_rate_sample` | Number of recent homes used to derive rate |
| `spot_check_result` | Manual review result (confirmed / excluded / incorrect) |
| `spot_check_notes` | Notes from manual spot check |
| `spot_check_date` | Date of manual spot check |

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

### Anomaly Detection Thresholds

| Threshold | Value | Use |
|-----------|-------|-----|
| `LOT_AREA_REMNANT` | 1,000 SF | Auto-exclude: unbuildable lot |
| `LOT_AREA_MARGINAL` | 2,000 SF | Flag: marginal buildability |
| `LOT_WIDTH_REMNANT` | 15 ft | Auto-exclude: too narrow |
| `IMPROVEMENT_VALUE_UNRELIABLE` | $30,000 | Flag: GFA estimate unreliable |
| `ZSCORE_THRESHOLD` | 2.5 | Flag: statistical outlier |

## Assumptions and Limitations

1. **By-right only**: Does not analyze special exception or site plan scenarios
2. **One-family focus**: Currently analyzes one-family dwelling potential only
3. **Lot area source**: When the assessor's `lotSizeQty` is available (92.8% of residential parcels), it is used as the authoritative lot area. The remaining parcels fall back to polygon geometry area, which may differ from the legal survey by 1-3%.
4. **Lot width and depth**: Lot depth is the long dimension of the minimum rotated bounding rectangle (MBR) of the parcel polygon. Lot width is derived from `lot area / depth` when assessor area is available, or from the MBR short dimension otherwise. These are geometric approximations and may not match legal lot dimensions.
5. **Undersized lot footprint provision not implemented**: Per §3.2.5.A.2, nonconforming (undersized) lots are entitled to the same maximum building footprint in square feet as a standard-sized lot in their zoning district. The pipeline does not implement this provision — it calculates max footprint as `lot_area × footprint_pct`, which **understates** the allowable footprint for undersized lots. Implementing this correctly would also require setback analysis to confirm the standard footprint physically fits on the smaller lot, which is not yet available. Parcels meeting or exceeding the minimum lot area for their district are not affected.
6. **Split zoning**: Parcels spanning multiple zones are flagged but use primary zone only
7. **Setbacks**: Setback calculations are not yet implemented (requires street geometry)
8. **Valuation**: Market parameter estimates are approximate; calibrate `valuation_params.json` to current conditions before use

## Data Sources

- **Parcels**: REA Property Polygons from Arlington Open Data
- **Zoning**: Zoning Polygons from Arlington Open Data
- **GLUP**: General Land Use Plan from Arlington Open Data

Data is maintained in Virginia State Plane North (EPSG:2283) for accurate area calculations.

## Legal Disclaimer

This tool is for informational purposes only. The output should not be construed as legal or professional advice. Always consult the official Arlington County Zoning Ordinance and work with qualified professionals for actual development projects.

## License

[Add license information]
