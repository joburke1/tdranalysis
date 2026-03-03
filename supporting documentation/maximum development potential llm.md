# Arlington R-District TDR Analysis: Calculation Reference

## Scope
Policy analysis pipeline for Transfer of Development Rights (TDR) in Arlington County's R zoning districts. Analyzes one-family dwellings by-right. Source: ACZO effective 10/1/2025, Articles 3 and 5; coverage rules from Article 3 §3.2.5.

This is a **four-stage pipeline**. Results are policy estimates, not appraisals.

## Pipeline Overview

```
Stage 1: Max Development Potential  →  max_footprint_sf, max_gfa_sf, max_lot_coverage_sf
Stage 2: Current Built              →  current_gfa_sf, gfa_source
Stage 3: Available Rights           →  available_gfa_sf, utilization_pct, status flags
Stage 4: Valuation                  →  estimated_value_low, estimated_value_high
```

---

## Stage 1: Maximum Development Potential

### Inputs
- `DISTRICT`: R-5 | R-6 | R-8 | R-10 | R-20
- `LOT_AREA_SF`: assessor's `lotSizeQty` (preferred) → parcel geometry fallback
- `PORCH`: boolean (≥60 sf qualifying front porch; use `false` in bulk analysis)
- `REAR_GARAGE`: boolean (detached rear garage; use `false` in bulk analysis)

### Lot Dimensions
```
DEPTH_FT  = longest dimension of minimum rotated bounding rectangle (geometry)
WIDTH_FT  = LOT_AREA_SF / DEPTH_FT  (derived; ensures width × depth = authoritative area)
AREA_SF   = lotSizeQty from property API if available; else geometry.area
```
CRS: EPSG:2283 (VA State Plane North, feet).

### Table A: Footprint Limits (ACZO §3.2.5.A)
| District | Base % | +Porch % | Base Cap (sf) | +Porch Cap (sf) |
|----------|--------|----------|--------------|----------------|
| R-20     | 16     | 19       | 4,480        | 5,320          |
| R-10     | 25     | 28       | 3,500        | 3,920          |
| R-8      | 25     | 28       | 2,800        | 3,136          |
| R-6      | 30     | 33       | 2,520        | 2,772          |
| R-5      | 34     | 37       | 2,380        | 2,590          |

### Table B: Lot Coverage Limits — % of lot area (ACZO §3.2.5.A)
| District | Base | +Porch | +Garage | +Both |
|----------|------|--------|---------|-------|
| R-20     | 25   | 28     | 30      | 33    |
| R-10     | 32   | 35     | 37      | 40    |
| R-8      | 35   | 38     | 40      | 43    |
| R-6      | 40   | 43     | 45      | 48    |
| R-5      | 45   | 48     | 50      | 53    |

### Table C: District Minimums
| District | Min Lot Area (sf) | Min Lot Width (ft) |
|----------|--------------------|-------------------|
| R-20     | 20,000             | 100               |
| R-10     | 10,000             | 80                |
| R-8      | 8,000              | 70                |
| R-6      | 6,000              | 60                |
| R-5      | 5,000              | 50                |

### Calculation
```
1. MAX_FOOTPRINT_SF = MIN(LOT_AREA_SF × [Table A pct], [Table A cap])
   Note: Pipeline simplification — §3.2.5.A.2 undersize bonus not implemented.
         Pipeline applies LOT_AREA × pct for all lots, which understates the
         allowable footprint for undersized lots. Correct implementation requires
         setback geometry analysis. See README: Assumptions and Limitations.

2. MAX_COVERAGE_SF = LOT_AREA_SF × [Table B pct]

3. MAX_GFA_SF = MAX_FOOTPRINT_SF × ASSUMED_STORIES
   ASSUMED_STORIES = 2.5  (R districts: 35 ft height limit → 2–3 stories)

4. MAX_DWELLING_UNITS = 1  (one-family districts, by-right)

5. CONFORMANCE (informational only, does not change limits):
   is_conforming = (LOT_AREA_SF >= min_lot_area AND WIDTH_FT >= min_lot_width)
   conformance_status: "conforming" | "undersized" | "narrow" | "both_deficient"
```

---

## Stage 2: Current Built Estimate

### Inputs (from Arlington property API + assessment API)
| Field | Source | Description |
|-------|--------|-------------|
| `grossFloorAreaSquareFeetQty` | Property API | Direct GFA measurement |
| `improvementValueAmt` | Assessment API | Assessed improvement (structure) value |
| `landValueAmt` | Assessment API | Assessed land value (used in Stage 4) |
| `noOfStories` | Property API | Story count |
| `yearBuilt` | Property API | Year of construction |
| `lotSizeQty` | Property API | Assessor-recorded lot area (used in Stage 1) |

### GFA Source Priority
```
IF grossFloorAreaSquareFeetQty > 0:
    gfa_source = "property_api"
    current_gfa_sf = grossFloorAreaSquareFeetQty

ELSE IF improvementValueAmt > 0 AND neighborhood_rate > 0:
    gfa_source = "estimated"
    current_gfa_sf = improvementValueAmt / NEIGHBORHOOD_IMPROVEMENT_RATE_MEDIAN

ELSE:
    gfa_source = "not_available"
    current_gfa_sf = None  → parcel excluded from Stage 3 and Stage 4
```

### Analyzability Gate
```
IF has_building = True AND current_gfa_sf = None:
    is_analyzable = False
    → Stage 3 and Stage 4 skipped to avoid overstating available capacity
```

### Neighborhood Improvement Rate Calibration
Runs once before bulk parcel analysis. Derives a neighborhood-specific $/sf rate from recent construction.

```
SAMPLE:
  yearBuilt >= (analysis_year - 10)
  AND grossFloorAreaSquareFeetQty > 0
  AND improvementValueAmt > 0

MINIMUM SAMPLE SIZE: 5 parcels
  If fewer: NEIGHBORHOOD_RATE = fallback value from valuation_params.json ($185/sf default)

RATE per parcel:
  rate_i = improvementValueAmt_i / (MAX_FOOTPRINT_SF_i × ASSUMED_STORIES)

NEIGHBORHOOD_RATE_MEDIAN = median(rate_i for all sample parcels)
NEIGHBORHOOD_RATE_LOW    = NEIGHBORHOOD_RATE_MEDIAN - 1 × std_dev  (floored at $50/sf)
NEIGHBORHOOD_RATE_HIGH   = NEIGHBORHOOD_RATE_MEDIAN + 1 × std_dev
```

### Current Footprint Estimate
```
IF current_gfa_sf AND noOfStories > 0:
    current_footprint_sf = current_gfa_sf / noOfStories
ELSE:
    current_footprint_sf = None
```

---

## Stage 3: Available Development Rights

### Calculation
```
MAX_GFA_SF          = MAX_FOOTPRINT_SF × ASSUMED_STORIES (2.5)

AVAILABLE_GFA_SF    = MAX_GFA_SF - current_gfa_sf
AVAILABLE_FOOTPRINT = MAX_FOOTPRINT_SF - current_footprint_sf
AVAILABLE_UNITS     = MAX_DWELLING_UNITS - current_dwelling_units
GFA_UTILIZATION_PCT = current_gfa_sf / MAX_GFA_SF × 100

Note: Negative available values = legal nonconforming (existing building
      exceeds by-right zoning limit for the current district)
```

### Status Flags
```
is_vacant         = NOT has_building
is_overdeveloped  = GFA_UTILIZATION_PCT > 100.0
is_underdeveloped = GFA_UTILIZATION_PCT < 80.0  (UNDERDEVELOPED_THRESHOLD_PCT)
```

### TDR Potential Classification
```
tdr_potential:
  "full"        if is_vacant
  "none"        if is_overdeveloped
  "substantial" if is_underdeveloped (and not vacant)
  "limited"     if 80% ≤ GFA_UTILIZATION_PCT ≤ 100%
  null          if utilization is indeterminate (insufficient data)
```

| tdr_potential | Condition | Output column value |
|--------------|-----------|---------------------|
| full | Vacant lot | "full" |
| substantial | Utilization < 80% | "substantial" |
| limited | Utilization 80–100% | "limited" |
| none | Utilization > 100% | "none" |

### Known Gap: Lot Coverage
Lot coverage available rights are **not computed**. The pipeline reports the maximum allowable lot coverage (`MAX_COVERAGE_SF`) but cannot determine actual impervious surface from county property records. Actual coverage would require GIS analysis of aerial imagery or permit records.

---

## Stage 4: Valuation

### Inputs
| Input | Source |
|-------|--------|
| `available_gfa_sf` | Stage 3 |
| `available_dwelling_units` | Stage 3 |
| `max_gfa_sf` | Stage 3 |
| `assessed_land_value` | `landValueAmt` from assessment API |
| Market parameters | `config/valuation_params.json` |

### Early Exit Conditions
```
IF is_overdeveloped:
    is_valueable = False  (no capacity to value)

IF available_gfa_sf <= 0 AND available_dwelling_units <= 0:
    is_valueable = False  (no available rights)
```

### Method 1: Land Residual
```
REQUIRES: assessed_land_value > 0, max_gfa_sf > 0, available_gfa_sf > 0

land_rate  = assessed_land_value / max_gfa_sf
value_low  = available_gfa_sf × land_rate × land_residual_discount_low
value_high = available_gfa_sf × land_rate × land_residual_discount_high
```

Input sources:
- `assessed_land_value` = `landValueAmt` from Arlington assessment API (land value only, excluding structures)
- `max_gfa_sf` = Stage 1 output (max_footprint × 2.5 stories)
- `available_gfa_sf` = Stage 3 output (max_gfa_sf − current_gfa_sf)
- `land_residual_discount_low/high` = calibrated parameter in `config/valuation_params.json`
  Represents the fraction of the derived land rate a TDR buyer would pay. Accounts for the
  fact that TDR rights convey partial development capacity, not fee-simple ownership, and
  for transaction costs and negotiation. Calibrate from observed TDR transaction prices
  divided by the pipeline's implied land rate for the same parcels. Typical range: 0.50–0.85.

### Estimated Value Range
```
ESTIMATED_VALUE_LOW  = land_residual.low_estimate
ESTIMATED_VALUE_HIGH = land_residual.high_estimate
```

### Configurable Parameters (config/valuation_params.json)
| Key | Type | Used In | Description and Calibration |
|-----|------|---------|----------------------------|
| `land_residual_discount_factor.low/high` | float (0–1) | Land Residual | Fraction of implied land rate a TDR buyer pays. Accounts for non-fee-simple nature of TDR rights, transaction costs, and negotiation. Calibrate: observed TDR price ÷ pipeline's implied land_rate for same parcel. Typical range 0.50–0.85. |
| `residential_improvement_value_per_sf.fallback_value` | float | Stage 2 | Static $/sf used when neighborhood calibration has < 5 recent-build samples. Calibrate from current residential construction cost indices or assessor documentation. |

---

## Coverage Definitions

**Main building footprint includes:** attached garages, bay windows with floor space, chimneys, porches, decks ≥4 ft above grade, balconies ≥4 ft projection, connected breezeways.

**Lot coverage includes:** main footprint + accessory buildings (>150 sf or ≥2 stories) + driveways/parking + patios ≥8 in above grade + detached decks ≥4 ft above grade + gazebos/pergolas + stoops ≥4 ft above grade + in-ground pools.

**Excluded from coverage:** HVAC equipment, above-ground pools, sidewalks, basement steps/areaways, temporary structures, play equipment, furniture, hot tubs, small accessory buildings (≤150 sf and <2 stories).

---

## Assumptions and Simplifications

1. **Assumed stories = 2.5** for max GFA estimation. R districts allow 35 ft height.

2. **§3.2.5.A.2 undersized lot bonus not implemented.** Pipeline applies `LOT_AREA × pct` for all lots. This understates the allowable footprint for undersized lots (which are entitled to the same SF cap as standard lots). Correct implementation requires setback geometry analysis to verify the standard footprint fits on the smaller lot.

3. **Porch and rear garage bonuses not applied in bulk analysis.** Base limits used; results are conservative.

4. **Lot coverage available rights not computed.** Actual impervious coverage not available from county records.

5. **By-right analysis only.** Special exceptions, site plans, and variances not modeled.

6. **Lot area source.** Assessor's `lotSizeQty` preferred (92.8% of residential parcels). Geometry fallback for remainder. Width derived as `area / depth`.

7. **One-family only.** Two-family, townhouse, and multi-family use types not modeled.

8. **Split-zoned parcels.** Pipeline uses the more restrictive district when a parcel straddles two zoning boundaries.

---

## Example: Parcel 23026006

R-6 district, 7,678 sf lot (assessor), porch=false, garage=false:

| Step | Calculation | Result |
|------|-------------|--------|
| Max footprint | MIN(7,678 × 0.30, 2,520) = MIN(2,303, 2,520) | 2,303 sf |
| Max coverage | 7,678 × 0.40 | 3,071 sf |
| Max GFA | 2,303 × 2.5 | 5,758 sf |
| Current GFA | from property API | 3,996 sf |
| Available GFA | 5,758 − 3,996 | 1,762 sf |
| GFA utilization | 3,996 / 5,758 × 100 | 69.4% → UNDERDEVELOPED |
| TDR value | land residual method | $119,630–$352,300 |
