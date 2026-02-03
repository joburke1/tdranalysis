# Arlington County R District: Max Building Size Calculation

## Scope
One-family dwellings in R-5, R-6, R-8, R-10, R-20 districts. Source: ACZO effective 10/1/2025, Articles 3 & 5.

## Core Concept
R districts do NOT use FAR. Building size = Footprint × Stories, constrained by:
1. Main building footprint (ground area)
2. Lot coverage (total impervious)
3. Height (35 ft max, all R districts)

## Inputs Required
- `DISTRICT`: R-5|R-6|R-8|R-10|R-20
- `LOT_AREA`: sq ft
- `PORCH`: boolean (≥60 sf on front elevation, excluding wrap-around/side)
- `REAR_GARAGE`: boolean (detached garage in rear yard)

## Lookup Tables

### Table A: Footprint Limits
| District | Base % | +Porch % | Base Cap | +Porch Cap |
|----------|--------|----------|----------|------------|
| R-5      | 34     | 37       | 2380     | 2590       |
| R-6      | 30     | 33       | 2520     | 2772       |
| R-8      | 25     | 28       | 2800     | 3136       |
| R-10     | 25     | 28       | 3500     | 3920       |
| R-20     | 16     | 19       | 4480     | 5320       |

### Table B: Lot Coverage Limits (%)
| District | Base | +Porch | +Garage | +Both |
|----------|------|--------|---------|-------|
| R-5      | 45   | 48     | 50      | 53    |
| R-6      | 40   | 43     | 45      | 48    |
| R-8      | 35   | 38     | 40      | 43    |
| R-10     | 32   | 35     | 37      | 40    |
| R-20     | 25   | 28     | 30      | 33    |

### Table C: Standard Lot Sizes
R-5: 5000 | R-6: 6000 | R-8: 8000 | R-10: 10000 | R-20: 20000

## Calculation Procedure

```
1. MAX_FOOTPRINT = MIN(
     LOT_AREA × [Table A percentage],
     [Table A cap]
   )
   Note: Undersized lots use same cap as standard lots.

2. MAX_COVERAGE = LOT_AREA × [Table B percentage]

3. Verify footprint fits within buildable area after setbacks (see §3.2.6).

4. ESTIMATED_GFA = MAX_FOOTPRINT × STORIES
   Where STORIES ≈ 2-3 (based on 35 ft height limit)
```

## Coverage Definitions

**Main building footprint includes:** attached garages, bay windows with floor space, chimneys, porches, decks ≥4ft above grade, balconies ≥4ft projection, connected breezeways.

**Lot coverage includes:** main footprint + accessory buildings (>150sf or ≥2 stories) + driveways/parking + patios ≥8in above grade + detached decks ≥4ft above grade + gazebos/pergolas + stoops ≥4ft above grade + in-ground pools.

**Excluded from coverage:** HVAC equipment, above-ground pools, sidewalks, basement steps/areaways, temporary structures, play equipment, furniture, hot tubs, small accessory buildings (≤150sf and <2 stories).

## Special Rules
- **Undersized lots:** Get same sq ft cap as standard lot in district (§3.2.5.A.2)
- **Non-one-family uses:** 56% max coverage unless modified by district/permit (§3.2.5.B)
- **100+ acre lots:** May get 55ft height by use permit if 150ft setback from all lines (§5.x.x.C)

## Example
R-6, 7200 sf lot, porch=true, garage=false:
- Footprint: MIN(7200×0.33, 2772) = MIN(2376, 2772) = 2376 sf
- Coverage: 7200×0.43 = 3096 sf
- Est. GFA: 2376 × 2.5 = 5940 sf
