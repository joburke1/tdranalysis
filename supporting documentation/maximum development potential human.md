# Arlington County R-District Development Rights Analysis: Methodology Guide

## Purpose and Context

This document describes the methodology used in the Arlington County TDR (Transfer of Development Rights) analysis pipeline. The pipeline analyzes residential parcels in Arlington's R zoning districts to estimate:

1. The maximum building size allowed by current by-right zoning (development potential)
2. What is currently built on each parcel (current built)
3. How much unused building capacity exists (available rights)
4. The estimated market value of those unused rights (TDR valuation)

This is a **policy analysis tool**, not a permit guide. Results inform TDR program design, neighborhood capacity assessments, and advocacy analysis. They are not appraisals or legal determinations.

---

## Analysis Pipeline Overview

The pipeline runs four sequential stages for each parcel:

| Stage | Question | Key Inputs | Output |
|-------|----------|------------|--------|
| 1. Development Potential | What can be built by-right? | Lot area, zoning district | Max footprint, max GFA |
| 2. Current Built | What is actually built? | Property records, assessments | Current GFA |
| 3. Available Rights | What capacity is unused? | Stage 1 minus Stage 2 | Available GFA, utilization % |
| 4. Valuation | What are those rights worth? | Available rights, assessed land value | Estimated value range |

Stage 1 results are available for all R-district parcels. Stages 3 and 4 require both zoning and property records for the parcel.

## Data Sources

| Data | Source | Coverage |
|------|--------|----------|
| Parcel geometry | Arlington County GIS | All parcels |
| Lot area | Property API `lotSizeQty` → geometry fallback | ~92.8% have assessor-recorded area |
| Zoning district | Arlington zoning GIS layer | All parcels |
| Zoning rules | `config/residential_districts.json` | By-right standards, ACZO effective 10/1/2025 |
| Gross floor area | Property API `grossFloorAreaSquareFeetQty` → improvement value estimate | Varies by parcel |
| Assessed land value | Assessment API `landValueAmt` | Used for valuation methods 1 and 2 |
| Improvement value | Assessment API `improvementValueAmt` | Used to estimate GFA when direct measure unavailable |
| Market parameters | `config/valuation_params.json` | Must be calibrated to current conditions |

Parcel geometry is projected in EPSG:2283 (Virginia State Plane North, feet). All spatial calculations use this projection directly.

---

## Stage 1: Maximum Development Potential

### What This Measures

The maximum gross floor area (GFA) that could be built on a parcel under Arlington's current by-right zoning rules — without requiring a special exception, site plan, or variance.

Arlington's residential districts do **not** use Floor-Area Ratio (FAR). Instead, building size is constrained by three independent limits applied simultaneously:

- **Main building footprint** — the ground-floor area of the main structure
- **Lot coverage** — total impervious surface across the entire lot
- **Height** — capped at 35 feet in all R districts

### Footprint Calculation

The allowable main building footprint is the **lesser** of a percentage of lot area and a hard square-footage cap:

```
MAX_FOOTPRINT = MIN(LOT_AREA × footprint_pct, footprint_cap_sf)
```

**Footprint Limits by District (ACZO §3.2.5.A):**

| District | Min Lot Area | Base % | Base Cap | +Front Porch % | +Front Porch Cap |
|----------|-------------|--------|----------|----------------|-----------------|
| R-20 | 20,000 sf | 16% | 4,480 sf | 19% | 5,320 sf |
| R-10 | 10,000 sf | 25% | 3,500 sf | 28% | 3,920 sf |
| R-8 | 8,000 sf | 25% | 2,800 sf | 28% | 3,136 sf |
| R-6 | 6,000 sf | 30% | 2,520 sf | 33% | 2,772 sf |
| R-5 | 5,000 sf | 34% | 2,380 sf | 37% | 2,590 sf |

A front porch bonus applies when a qualifying front porch of at least 60 square feet is present on the front elevation. In bulk analysis, the pipeline uses base limits (no porch bonus) as a conservative estimate.

On smaller lots, the percentage calculation governs (lot × pct < cap). On larger lots, the hard cap governs. The cap represents an absolute ceiling regardless of lot size.

### Lot Coverage Limits

Lot coverage limits the total impervious surface including the house, driveway, patios, detached structures, and decks. These limits vary by district and whether a front porch and/or detached rear garage is present.

**Lot Coverage Limits (ACZO §3.2.5.A, % of lot area):**

| District | Base | +Front Porch | +Detached Garage | +Both |
|----------|------|-------------|-----------------|-------|
| R-20 | 25% | 28% | 30% | 33% |
| R-10 | 32% | 35% | 37% | 40% |
| R-8 | 35% | 38% | 40% | 43% |
| R-6 | 40% | 43% | 45% | 48% |
| R-5 | 45% | 48% | 50% | 53% |

**What counts toward coverage:** main building footprint, plus accessory buildings over 150 sf or two or more stories, driveways, patios raised 8 or more inches above grade, detached decks 4 or more feet above grade, gazebos and pergolas, stoops 4 or more feet above grade, and in-ground pools.

**Not counted:** HVAC equipment, above-ground pools, sidewalks, basement steps, small accessory buildings at or under 150 sf with fewer than two stories, play equipment, hot tubs.

### GFA Estimation

The pipeline estimates maximum GFA by multiplying the max footprint by an assumed story count. R districts allow a maximum height of 35 feet, which typically accommodates 2 to 3 stories depending on construction type and roof pitch. The pipeline uses 2.5 stories as a standard assumption:

```
MAX_GFA = MAX_FOOTPRINT × 2.5
```

This is an approximation. A fully maximized parcel could support anywhere from 2 to 3 finished stories within the height limit.

### Lot Dimensions and Conformance

**Lot area** is taken from the Arlington County property API (`lotSizeQty`) when available, as this reflects the legal lot area recorded by the assessor. When not available, area is computed from the parcel polygon geometry.

**Lot depth** is measured as the longest dimension of the minimum rotated bounding rectangle fitted to the parcel polygon. **Lot width** is derived as `lot_area / lot_depth` rather than measured directly from geometry — this ensures the product of width and depth equals the authoritative lot area.

The `lot_area_source` field in outputs indicates whether area came from the assessor (`assessor`) or was computed from geometry (`geometry`). Width is labeled `derived` or `geometry` accordingly.

**Conformance** is assessed against district minimums:

| Status | Condition |
|--------|-----------|
| Conforming | Meets or exceeds both minimum lot area and minimum lot width |
| Undersized | Below minimum lot area |
| Narrow | Meets area requirement but below minimum width |
| Both deficient | Below both minimums |

---

## Stage 2: Current Built Estimate

### What This Measures

The gross floor area (GFA) of the building currently on the parcel, drawn from county property records. GFA is the total finished interior floor area across all stories.

### GFA Source Priority

The pipeline uses the most authoritative available source in this order:

**1. Property API direct measurement** (`grossFloorAreaSquareFeetQty`): Floor area reported directly by the assessor. Most reliable. Labeled `property_api` in outputs.

**2. Improvement value estimate**: When the property API does not report floor area — common for single-family homes — GFA is estimated from the assessed improvement value:

```
ESTIMATED_GFA = IMPROVEMENT_VALUE / NEIGHBORHOOD_IMPROVEMENT_RATE
```

Labeled `estimated` in outputs. Accuracy depends on how well the neighborhood rate is calibrated.

**3. Not available**: If neither source is available, GFA is left blank and the parcel is excluded from Stage 3 and Stage 4 analysis. If a building is confirmed by a year-built record but GFA cannot be estimated, the parcel is marked non-analyzable to avoid overstating available capacity.

### Neighborhood Improvement Rate Calibration

The improvement rate — dollars per square foot of GFA — is calibrated from recently-built homes in the analysis dataset before individual parcel analysis runs:

- **Sample**: homes built within the last 10 years with both an improvement value and a property API floor area
- **Minimum**: 5 parcels required; falls back to a static $185/sf if fewer are available
- **Rate per parcel**: `improvement_value / (max_footprint × assumed_stories)`
- **Point estimate**: median of sample rates
- **Range**: median ± 1 standard deviation, floored at $50/sf to exclude extreme outliers

This neighborhood-calibrated rate replaces a static fallback, reducing systematic bias in areas with significant recent construction activity.

---

## Stage 3: Available Development Rights

### What This Measures

The remaining unused development capacity on a parcel — the difference between what zoning allows and what is currently built. This is the core quantity for TDR analysis: available rights represent what could theoretically be transferred to a receiving site.

### Calculation

```
AVAILABLE_GFA       = MAX_GFA - CURRENT_GFA
AVAILABLE_FOOTPRINT = MAX_FOOTPRINT - CURRENT_FOOTPRINT
AVAILABLE_UNITS     = MAX_DWELLING_UNITS - CURRENT_DWELLING_UNITS
GFA_UTILIZATION     = CURRENT_GFA / MAX_GFA × 100%
```

Negative values indicate the existing building exceeds what current zoning would allow by-right — a legal nonconforming condition.

### Parcel Classification

| TDR Potential | Condition | Interpretation |
|--------------|-----------|----------------|
| Full | No building on parcel | All development rights potentially available |
| Substantial | GFA utilization below 80% | Significant unused capacity; likely TDR candidate |
| Limited | GFA utilization 80%–100% | Substantially built out; limited remaining capacity |
| None | GFA utilization above 100% | Nonconforming use; no TDR value in current analysis |

### Data Limitation: Lot Coverage

Available lot coverage is **not computed**. The pipeline reports the allowable lot coverage limit for each parcel but cannot determine how much impervious surface is actually present, because that data is not available from county property records. Computing actual lot coverage would require GIS analysis of aerial imagery or permit records.

---

## Stage 4: TDR Value Estimation

### What This Measures

The estimated market value of a parcel's available development rights if sold as TDR credits. This is a policy estimate, **not a property appraisal or formal valuation**. Results represent an order-of-magnitude range useful for program design and should not be used as a basis for individual transactions.

Market parameters must be calibrated to current conditions before analysis. See `config/valuation_params.json`.

### Four Valuation Methods

The pipeline applies four independent methods and combines their results into a composite range. Not all methods are applicable to every parcel; methods are skipped when required inputs are missing.

#### 1. Land Residual Method
Derives a land value rate per square foot of buildable GFA from the county's assessed land value, then applies that rate to unused capacity with a discount factor.

```
land_rate  = assessed_land_value / max_gfa_sf
value_low  = available_gfa_sf × land_rate × discount_low
value_high = available_gfa_sf × land_rate × discount_high
```

Requires: assessed land value > 0, max GFA > 0, available GFA > 0.

**How inputs are determined:**

- **`assessed_land_value`**: Arlington's assessed value of the land only, separate from any structure. Taken directly from the county assessment API field `landValueAmt`. Arlington assessments target 100% of market value, though this may lag in a rapidly rising market.

- **`max_gfa_sf`** and **`available_gfa_sf`**: Computed in Stages 1 and 3 respectively. Dividing assessed land value by total allowable GFA yields an implied land cost per buildable square foot; multiplying by available GFA isolates the unused portion.

- **`discount_low` / `discount_high`** (`land_residual_discount_factor` in `config/valuation_params.json`): A fraction between 0 and 1 representing what a TDR buyer would actually pay relative to that implied land rate. The discount accounts for the fact that TDR rights convey only the right to build additional floor area — not fee-simple land ownership — and for negotiation, transaction costs, and market uncertainty. A discount of 0.65 means the buyer pays $0.65 for each dollar of implied land value. This is the most judgment-intensive parameter in the model. In the absence of observed TDR transactions, values typically range from 0.50 to 0.85; calibrate from comparable TDR markets or developer interviews.

### Configurable Market Parameters

All market parameters are stored in `config/valuation_params.json` and must be calibrated to current conditions before use. The parameter file itself documents the current values and the date they were last updated.

| Parameter | Used In | What It Represents | How to Calibrate |
|-----------|---------|-------------------|-----------------|
| `land_residual_discount_factor` (low/high) | Land Residual | Fraction of the implied land rate a TDR buyer would pay. Reflects that TDR rights are not fee-simple ownership and that transaction costs and negotiation reduce achievable prices. | Observed TDR transaction prices divided by the pipeline's implied land rate for the same parcels. In the absence of local transactions, use comparable TDR markets (0.50–0.85 is a common range). |
| `residential_improvement_value_per_sf` (fallback) | Stage 2 GFA estimate | Static $/sf used to estimate GFA from improvement value when neighborhood calibration has fewer than 5 recent-build samples. | Current replacement cost per sf for residential construction in the area; consult local construction cost indices or assessor documentation. |

---

## Assumptions and Known Simplifications

See the [README](../README.md#assumptions-and-limitations) for the authoritative list. Key items:

1. **GFA estimation uses a fixed story multiplier (2.5).** Actual stories depend on floor heights, ceiling heights, and roof configuration. Some parcels may support more or fewer stories within the 35-foot height limit.

2. **The §3.2.5.A.2 undersized lot footprint allowance is not implemented.** Undersized lots are legally entitled to the same footprint SF cap as a standard-sized lot in their district, which could allow a higher footprint percentage on a small lot than the pipeline calculates. Implementing this provision requires setback analysis to verify the standard footprint physically fits on the smaller lot.

3. **Lot coverage available rights are not computed.** Actual impervious coverage data is not available from county records.

4. **By-right analysis only.** Special exceptions, site plans, and variances are not modeled.

5. **Porch and garage bonuses are not applied in bulk analysis.** The pipeline uses base coverage and footprint limits as a conservative estimate.

6. **Lot area uses the assessor's recorded area** (`lotSizeQty`) when available. Lot width is derived from `area / depth` rather than measured from geometry directly.
