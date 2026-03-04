# Data Quality Issues

This file tracks known data quality issues discovered during TDR analysis work. Each issue includes context sufficient to evaluate and implement workarounds at a later date.

---

## Issue 1: Arlington Datahub Assessment API Returns Incomplete Data

**Discovered:** 2026-03-03
**Affected neighborhood:** Douglas Park (and likely others)
**Severity:** High — causes a large fraction of valid residential parcels to be excluded from analysis

### Symptom

When running the Douglas Park analysis, 620 of ~850 eligible residential parcels were excluded with the reason "Building present but no floor area data available." The 1600–1700 block of S Nelson St is a representative example: these are clearly built single-family homes (property class 511, year-built records from the 1900s–1940s) that should be analyzed but are not.

### Root Cause

The pipeline estimates current GFA for single-family residential parcels from `improvementValueAmt` (assessed improvement value) divided by a neighborhood calibration rate, because the county property API does not populate `grossFloorAreaSquareFeetQty` for residential class 511 properties (this is by design). When `improvementValueAmt` is also null — because the assessment join fails — the parcel is excluded.

The assessment join fails because the assessment data downloaded from `datahub-v2.arlingtonva.us/api/RealEstate/Assessment` is structurally incomplete. The county's full assessment records live in their PROVAL system (accessible via `propertysearch.arlingtonva.us`), but the datahub API publishes only a partial snapshot.

### Evidence

- Our `assessment.json` contains 134,796 records covering 46,666 unique RPCs, but `property.json` has 57,668 unique RPCs — a gap of ~11,000 properties with no assessment data at all.
- Coverage is highly uneven by RPC district. Douglas Park (district 26) has only 30% class-511 coverage; Alcova Heights (district 23) has 93%.
- Direct confirmation: LRSN 42883 (1624 S Nelson St, RPC 26012014) appears with complete 2025 and 2026 assessment data on `propertysearch.arlingtonva.us` but is entirely absent from `assessment.json`.
- The gaps are not a simple truncation — missing and present records are interleaved throughout the same blocks (e.g., within block 26012, LRSNs 42888–42889 are present but 42880–42887 are absent).
- The issue affects at minimum districts 26, 27, 28, 32, 33, 37, and 38, all of which have <50% class-511 assessment coverage in the downloaded data.

### Current Handling

Parcels with a confirmed `propertyYearBuilt` but no `improvementValueAmt` are marked `gfa_source = "building_detected_no_gfa_data"` in `current_built.py` and excluded from available-rights and valuation calculations. They appear in the `*_excluded.geojson` output with the reason "Building present but no floor area data available." This is the correct behavior given the data gap — the analysis is limited to parcels we have reliable data for.

### Ideal Fix

Arlington County itself has the complete PROVAL data. A bulk CAMA extract (available via the county's internal systems or a data sharing agreement) would resolve this entirely. The county planning department or assessor's office would be the right contact.

### Potential Workaround (for future implementation)

**Query the datahub API by individual LRSN for missing parcels.**

The datahub endpoint `https://datahub-v2.arlingtonva.us/api/RealEstate/Assessment` may return records for individual parcels even when bulk queries omit them. This has not yet been tested.

Implementation approach:
1. After the bulk assessment download, identify all RPCs present in `property.json` but absent from `assessment.json`.
2. For each missing RPC, look up its `provalLrsnId` from `property.json`.
3. Query the assessment API with a filter on `provalLrsnId`, e.g.: `$filter=provalLrsnId eq 42883`
4. Collect any returned records and merge them into the assessment dataset before saving `assessment.json`.

The `provalLrsnId` values for the missing parcels are available in `property.json` (the field `provalLrsnId` is populated for all records). For Douglas Park, the missing parcels span LRSNs roughly in the 42530–71386 range (interleaved with present ones).

This workaround should be validated against a known-missing parcel first (e.g., LRSN 42883, RPC 26012014, 1624 S Nelson St) before running at scale.
