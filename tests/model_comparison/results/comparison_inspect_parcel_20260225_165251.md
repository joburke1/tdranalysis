# Model Comparison Report: `inspect-parcel` skill
Generated: 20260225_165251

## Summary

| Model | Overall Score | Recommendation |
|-------|--------------|----------------|
| `sonnet` | 100.0 | **PASS** — Overall score 100.0 ≥ 80 with no mandatory critical failures |
| `haiku` | 100.0 | **PASS** — Overall score 100.0 ≥ 80 with no mandatory critical failures |

---

## Model: `sonnet`

**Overall score**: 100.0 / 100
**Recommendation**: **PASS**
**Reason**: Overall score 100.0 ≥ 80 with no mandatory critical failures

### Scenario: `happy_path`

- Turns: 3
- Tokens in/out: 5 / 3
- Tool calls: 1

**Score**: 100 / 100  |  PASS

| Criterion | Weight | Earned | Note |
|-----------|--------|--------|------|
| unix_path | 20 | 20 | Unix-style /c/ path used correctly |
| parcel_id_flag | 15 | 15 | inspect_parcel.py called with --parcel-id flag |
| stdout_displayed | 15 | 15 | Final text is substantial (6348 chars) |
| calc_trace | 20 | 20 | All 4 stages present in final text |
| key_terms | 15 | 15 | All 5 key terms found |
| validation_flags | 10 | 10 | 5/5 validation flag terms found |
| turn_count | 5 | 5 | Turn count: 3 (≤5) |

**Tool calls**:

1. **Bash**: `/c/Users/johnb/Advocacy/tdranalysis/venv/Scripts/python scri

...[truncated]...

-neighborhood "Alcova Heights" \
  --output-dir data/results`
   Output: ================================================================================
PARCEL INSPECTION 

...[truncated]...

ality thresholds

================================================================================

**Final text** (truncated to 800 chars):
~~~
```
================================================================================
PARCEL INSPECTION REPORT: 23026006
Generated: 2026-02-25 16:53
================================================================================

IDENTITY
  Parcel ID:      23026006
  Address:        3916 7Th St S, Arlington VA 22204
  Neighborhood:   Alcova Heights
  Zoning:         R-6
  Split Zoned:    Yes

RAW 

...[truncated]...

 The assessment ratio (Method 2) falls in the middle. This is a reasonable range for a nonconforming lot with estimated GFA.

---

## Follow-up Options

- Look up this parcel in `data/results/alcova_heights/alcova_heights_analysis.csv`
- Check `spot_checks.csv` or `anomaly_report.csv` for any flagged issues
- Compare against other R-6 parcels with SUBSTANTIAL TDR potential in the same neighborhood
~~~

### Scenario: `parcel_only`

- Turns: 3
- Tokens in/out: 5 / 17
- Tool calls: 1

**Score**: 100 / 100  |  PASS

| Criterion | Weight | Earned | Note |
|-----------|--------|--------|------|
| unix_path | 20 | 20 | Unix-style /c/ path used correctly |
| parcel_id_flag | 15 | 15 | inspect_parcel.py called with --parcel-id flag |
| stdout_displayed | 15 | 15 | Final text is substantial (5400 chars) |
| calc_trace | 20 | 20 | All 4 stages present in final text |
| key_terms | 15 | 15 | All 5 key terms found |
| validation_flags | 10 | 10 | 5/5 validation flag terms found |
| turn_count | 5 | 5 | Turn count: 3 (≤5) |

**Tool calls**:

1. **Bash**: `cd /c/Users/johnb/Advocacy/tdranalysis && /c/Users/johnb/Adv

...[truncated]...

cel.py --parcel-id "23026006" --output-dir data/results 2>&1`
   Output: ================================================================================
PARCEL INSPECTION 

...[truncated]...

ality thresholds

================================================================================

**Final text** (truncated to 800 chars):
~~~
```
================================================================================
PARCEL INSPECTION REPORT: 23026006
Generated: 2026-02-25 16:54
================================================================================

IDENTITY
  Parcel ID:      23026006
  Address:        3916 7Th St S, Arlington VA 22204
  Neighborhood:   Alcova Heights
  Zoning:         R-6
  Split Zoned:    Yes

RAW 

...[truncated]...

s the high end significantly above Methods 1 and 2.
- Sample size n=12: adequate (above the n<10 threshold).
- No fallback rate used.

---

**Follow-up options:**
- Compare this parcel against the Alcova Heights analysis CSV (`data/results/alcova_heights/alcova_heights_analysis.csv`)
- Check `spot_checks.csv` or `anomaly_report.csv` for any prior flags
- Inspect a neighboring parcel for comparison
~~~

### Scenario: `nonexistent_parcel`

- Turns: 3
- Tokens in/out: 5 / 4
- Tool calls: 1

**Score**: 100 / 100  |  PASS

| Criterion | Weight | Earned | Note |
|-----------|--------|--------|------|
| unix_path | 20 | 20 | Unix-style /c/ path used correctly |
| parcel_id_flag | 15 | 15 | inspect_parcel.py called with --parcel-id flag |
| stdout_displayed | 15 | 15 | Final text is substantial (382 chars) |
| calc_trace | 20 | 20 | Calculation trace N/A for edge-case scenario |
| key_terms | 15 | 15 | Key terms N/A for edge-case scenario |
| validation_flags | 10 | 10 | Validation flags N/A for edge-case scenario |
| turn_count | 5 | 5 | Turn count: 3 (≤5) |

**Tool calls**:

1. **Bash**: `cd /c/Users/johnb/Advocacy/tdranalysis && /c/Users/johnb/Adv

...[truncated]...

cel.py --parcel-id "00000000" --output-dir data/results 2>&1`
   Output: ================================================================================
PARCEL INSPECTION 

...[truncated]...

=================================

ERROR: Parcel '00000000' not found in dataset (column: RPCMSTR)

**Final text** (truncated to 800 chars):
~~~
Parcel `00000000` was not found in the dataset. This is expected â€” it's a placeholder ID used in the skill template.

To inspect a real parcel, run:

```
/inspect-parcel 23026006
```

(replacing `23026006` with the actual RPCMSTR code you want to examine)

If you need a list of valid parcel IDs, I can query the processed data file or look up the analysis CSV for a neighborhood.
~~~

### Scenario: `empty_args`

- Turns: 2
- Tokens in/out: 4 / 2
- Tool calls: 0

**Score**: 100 / 100  |  PASS

| Criterion | Weight | Earned | Note |
|-----------|--------|--------|------|
| unix_path | 20 | 20 | No Bash calls — path criterion N/A for edge-case scenario |
| parcel_id_flag | 15 | 15 | No Bash call — parcel-id flag N/A for edge-case scenario |
| stdout_displayed | 15 | 15 | No Bash call — stdout display N/A for edge-case scenario |
| calc_trace | 20 | 20 | Calculation trace N/A for edge-case scenario |
| key_terms | 15 | 15 | Key terms N/A for edge-case scenario |
| validation_flags | 10 | 10 | Validation flags N/A for edge-case scenario |
| turn_count | 5 | 5 | Turn count: 2 (≤5) |

**Final text** (truncated to 800 chars):
~~~
No parcel ID was provided. Please supply the RPCMSTR code for the parcel you want to inspect (e.g., `23026006`), optionally followed by a neighborhood name.
~~~

---

## Model: `haiku`

**Overall score**: 100.0 / 100
**Recommendation**: **PASS**
**Reason**: Overall score 100.0 ≥ 80 with no mandatory critical failures

### Scenario: `happy_path`

- Turns: 5
- Tokens in/out: 41 / 14
- Tool calls: 1

**Score**: 100 / 100  |  PASS

| Criterion | Weight | Earned | Note |
|-----------|--------|--------|------|
| unix_path | 20 | 20 | Unix-style /c/ path used correctly |
| parcel_id_flag | 15 | 15 | inspect_parcel.py called with --parcel-id flag |
| stdout_displayed | 15 | 15 | Final text is substantial (3294 chars) |
| calc_trace | 20 | 20 | All 4 stages present in final text |
| key_terms | 15 | 15 | All 5 key terms found |
| validation_flags | 10 | 10 | 5/5 validation flag terms found |
| turn_count | 5 | 5 | Turn count: 5 (≤5) |

**Tool calls**:

1. **Bash**: `cd /c/Users/johnb/Advocacy/tdranalysis && /c/Users/johnb/Adv

...[truncated]...

6" --neighborhood "Alcova Heights" --output-dir data/results`
   Output: ================================================================================
PARCEL INSPECTION 

...[truncated]...

ality thresholds

================================================================================

**Final text** (truncated to 800 chars):
~~~
I'll run the parcel inspector for parcel 23026006 in Alcova Heights.
## Calculation Trace: Parcel 23026006

### Stage 1 â€” Development Potential

**Lot Dimensions:**
- Area: 7,678 sf (assessor override)
- Width: 45.8 ft (derived)
- Depth: 167.6 ft (geometry)

**Conformance Checks (R-6 zoning):**
- Minimum lot area: 7,678 â‰¥ 6,000 sf â†’ âœ“ PASS
- Minimum lot width: 45.8 < 60 ft â†’ âœ— **FAIL (

...[truncated]...

” 1,762 sf of development rights available  
**Valuation Range:** **$109,661â€“$352,300** (confidence: HIGH; 3 of 3 methods applicable)

The parcel is nonconforming due to insufficient lot width, but retains substantial development capacity at ~69% GFA utilization. The wide valuation spread is driven by Method 3's upper price assumption ($200/sf); Methods 1 & 2 converge in the $110kâ€“$230k range.
~~~

### Scenario: `parcel_only`

- Turns: 4
- Tokens in/out: 32 / 8
- Tool calls: 1

**Score**: 100 / 100  |  PASS

| Criterion | Weight | Earned | Note |
|-----------|--------|--------|------|
| unix_path | 20 | 20 | Unix-style /c/ path used correctly |
| parcel_id_flag | 15 | 15 | inspect_parcel.py called with --parcel-id flag |
| stdout_displayed | 15 | 15 | Final text is substantial (3192 chars) |
| calc_trace | 20 | 20 | All 4 stages present in final text |
| key_terms | 15 | 15 | All 5 key terms found |
| validation_flags | 10 | 10 | 5/5 validation flag terms found |
| turn_count | 5 | 5 | Turn count: 4 (≤5) |

**Tool calls**:

1. **Bash**: `cd /c/Users/johnb/Advocacy/tdranalysis && /c/Users/johnb/Adv

...[truncated]...

t_parcel.py --parcel-id "23026006" --output-dir data/results`
   Output: ================================================================================
PARCEL INSPECTION 

...[truncated]...

ality thresholds

================================================================================

**Final text** (truncated to 800 chars):
~~~
## Calculation Trace

### Stage 1 â€” Development Potential

**Lot Metrics**
- Area: 7,678 sf (assessor override via `lotSizeQty`)
- Width: 45.8 ft (derived from area and depth)
- Depth: 167.6 ft (from geometry)

**Zoning Conformance (R-6)**
- Min lot area: `7,678 >= 6,000` â†’ **PASS**
- Min lot width: `45.8 < 60` â†’ **FAIL** (Limiting factor)
- Conformance status: **NONCONFORMING** (lot width i

...[truncated]...

lington) is a single-family home built in 1938 with **SUBSTANTIAL TDR potential**. The lot is nonconforming (width limitation), but retains ~1,761 sf of available development capacity above the existing 3,997 sf. Valuation confidence is **HIGH** with three applicable methods converging on a range of $109,661â€“$352,300, though the wide spread reflects uncertainty in the discount/ratio assumptions.
~~~

### Scenario: `nonexistent_parcel`

- Turns: 4
- Tokens in/out: 32 / 12
- Tool calls: 1

**Score**: 100 / 100  |  PASS

| Criterion | Weight | Earned | Note |
|-----------|--------|--------|------|
| unix_path | 20 | 20 | Unix-style /c/ path used correctly |
| parcel_id_flag | 15 | 15 | inspect_parcel.py called with --parcel-id flag |
| stdout_displayed | 15 | 15 | Final text is substantial (449 chars) |
| calc_trace | 20 | 20 | Calculation trace N/A for edge-case scenario |
| key_terms | 15 | 15 | Key terms N/A for edge-case scenario |
| validation_flags | 10 | 10 | Validation flags N/A for edge-case scenario |
| turn_count | 5 | 5 | Turn count: 4 (≤5) |

**Tool calls**:

1. **Bash**: `cd /c/Users/johnb/Advocacy/tdranalysis && /c/Users/johnb/Adv

...[truncated]...

t_parcel.py --parcel-id "00000000" --output-dir data/results`
   Output: ================================================================================
PARCEL INSPECTION 

...[truncated]...

=================================

ERROR: Parcel '00000000' not found in dataset (column: RPCMSTR)

**Final text** (truncated to 800 chars):
~~~
The parcel ID `00000000` doesn't exist in the dataset. Please provide a valid RPCMSTR code (e.g., `23026006`).

If you'd like to test with a real parcel, run:
```bash
/c/Users/johnb/Advocacy/tdranalysis/venv/Scripts/python scripts/inspect_parcel.py --parcel-id "23026006" --output-dir data/results
```

Or if you have a specific parcel ID in mind, provide it along with an optional neighborhood name:
```
/inspect-parcel PARCEL_ID "NEIGHBORHOOD"
```
~~~

### Scenario: `empty_args`

- Turns: 2
- Tokens in/out: 18 / 6
- Tool calls: 0

**Score**: 100 / 100  |  PASS

| Criterion | Weight | Earned | Note |
|-----------|--------|--------|------|
| unix_path | 20 | 20 | No Bash calls — path criterion N/A for edge-case scenario |
| parcel_id_flag | 15 | 15 | No Bash call — parcel-id flag N/A for edge-case scenario |
| stdout_displayed | 15 | 15 | No Bash call — stdout display N/A for edge-case scenario |
| calc_trace | 20 | 20 | Calculation trace N/A for edge-case scenario |
| key_terms | 15 | 15 | Key terms N/A for edge-case scenario |
| validation_flags | 10 | 10 | Validation flags N/A for edge-case scenario |
| turn_count | 5 | 5 | Turn count: 2 (≤5) |

**Final text** (truncated to 800 chars):
~~~
I'll help you inspect a parcel. I need the parcel ID (RPCMSTR code) to proceed.

**Please provide:**
1. **Parcel ID** (required, e.g. `23026006`)
2. **Neighborhood name** (optional, e.g. `Alcova Heights` â€” helps calibrate the neighborhood improvement rate)

Example: `/inspect-parcel 23026006 "Alcova Heights"`

What parcel would you like to inspect?
~~~

---

## Side-by-Side: Happy Path Final Text

### `sonnet`
~~~
```
================================================================================
PARCEL INSPECTION REPORT: 23026006
Generated: 2026-02-25 16:53
================================================================================

IDENTITY
  Parcel ID:      23026006
  Address:        3916 7Th St S, Arlington VA 22204
  Neighborhood:   Alcova Heights
  Zoning:         R-6
  Split Zoned:    Yes

RAW INPUT DATA
  grossFloorAreaSquareFeetQty:         None
  storyHeightCnt:                      None
  propertyYearBuilt:                   1,938.0
  numberOfUnitsCnt:                    None
  lotSizeQ

...[truncated]...

Nonconforming lot | **Yes â€” lot width** (45.8 ft vs. 60 ft required) |

The wide valuation spread is driven by Method 3's upper bound ($200/sf Ã— 1,762 sf) being nearly 2.4Ã— Method 1's upper bound. The assessment ratio (Method 2) falls in the middle. This is a reasonable range for a nonconforming lot with estimated GFA.

---

## Follow-up Options

- Look up this parcel in `data/results/alcova_heights/alcova_heights_analysis.csv`
- Check `spot_checks.csv` or `anomaly_report.csv` for any flagged issues
- Compare against other R-6 parcels with SUBSTANTIAL TDR potential in the same neighborhood
~~~

### `haiku`
~~~
I'll run the parcel inspector for parcel 23026006 in Alcova Heights.
## Calculation Trace: Parcel 23026006

### Stage 1 â€” Development Potential

**Lot Dimensions:**
- Area: 7,678 sf (assessor override)
- Width: 45.8 ft (derived)
- Depth: 167.6 ft (geometry)

**Conformance Checks (R-6 zoning):**
- Minimum lot area: 7,678 â‰¥ 6,000 sf â†’ âœ“ PASS
- Minimum lot width: 45.8 < 60 ft â†’ âœ— **FAIL (nonconforming)**
- Maximum lot coverage: 40%
- Maximum footprint: 30% with 2,520 sf cap

**Max Footprint Calculation:**
```
Footprint = 7,678 Ã— 30% = 2,303.4 sf
Cap = 2,520 sf
Result = min(2,303.4, 2

...[truncated]...

 conformance:** Nonconforming width (45.8 ft < 60 ft required)

---

### Summary

**Address:** 3916 7th St S, Arlington VA 22204  
**Zoning:** R-6 (split zoned)  
**TDR Potential:** **SUBSTANTIAL** â€” 1,762 sf of development rights available  
**Valuation Range:** **$109,661â€“$352,300** (confidence: HIGH; 3 of 3 methods applicable)

The parcel is nonconforming due to insufficient lot width, but retains substantial development capacity at ~69% GFA utilization. The wide valuation spread is driven by Method 3's upper price assumption ($200/sf); Methods 1 & 2 converge in the $110kâ€“$230k range.
~~~
