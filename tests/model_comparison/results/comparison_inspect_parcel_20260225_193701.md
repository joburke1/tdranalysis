# Model Comparison Report: `inspect-parcel` skill
Generated: 20260225_193701

## Summary

| Model | Overall Score | Recommendation |
|-------|--------------|----------------|
| `sonnet` | 95.0 | **FAIL** — Critical failures on mandatory criteria: ['unix_path'] |
| `haiku` | 0.0 | **FAIL** — Overall score 0.0 < 65 |

---

## Model: `sonnet`

**Overall score**: 95.0 / 100
**Recommendation**: **FAIL**
**Reason**: Critical failures on mandatory criteria: ['unix_path']

**Critical failures**: unix_path

### Scenario: `happy_path`

- Turns: 3
- Tokens in/out: 5 / 3
- Tool calls: 1

**Score**: 100 / 100  |  PASS

| Criterion | Weight | Earned | Note |
|-----------|--------|--------|------|
| unix_path | 20 | 20 | Unix-style /c/ path used correctly |
| parcel_id_flag | 15 | 15 | inspect_parcel.py called with --parcel-id flag |
| stdout_displayed | 15 | 15 | Final text is substantial (6281 chars) |
| calc_trace | 20 | 20 | All 4 stages present in final text |
| key_terms | 15 | 15 | All 5 key terms found |
| validation_flags | 10 | 10 | 5/5 validation flag terms found |
| turn_count | 5 | 5 | Turn count: 3 (≤5) |

**Tool calls**:

1. **Bash**: `/c/Users/johnb/Advocacy/tdranalysis/venv/Scripts/python scri

...[truncated]...

neighborhood "Alcova Heights" --output-dir data/results 2>&1`
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
Generated: 2026-02-25 19:37
================================================================================

IDENTITY
  Parcel ID:      23026006
  Address:        3916 7Th St S, Arlington VA 22204
  Neighborhood:   Alcova Heights
  Zoning:         R-6
  Split Zoned:    Yes

RAW 

...[truncated]...

ot width 45.8 ft < 60 ft required. Max footprint constrained to lot coverage limit (30% of area), not width-based setbacks. |

---

**Follow-up options:**
- Compare against the Alcova Heights CSV: `data/results/alcova_heights/alcova_heights_analysis.csv`
- Check if it appears in `spot_checks.csv` or `anomaly_report.csv`
- Run with `--json` for structured data if you need to feed results downstream
~~~

### Scenario: `parcel_only`

- Turns: 3
- Tokens in/out: 5 / 3
- Tool calls: 1

**Score**: 80 / 100  |  FAIL

| Criterion | Weight | Earned | Note |
|-----------|--------|--------|------|
| unix_path | 20 | 0 | CRITICAL: Windows-style path detected |
| parcel_id_flag | 15 | 15 | inspect_parcel.py called with --parcel-id flag |
| stdout_displayed | 15 | 15 | Final text is substantial (6641 chars) |
| calc_trace | 20 | 20 | All 4 stages present in final text |
| key_terms | 15 | 15 | All 5 key terms found |
| validation_flags | 10 | 10 | 5/5 validation flag terms found |
| turn_count | 5 | 5 | Turn count: 3 (≤5) |

**Tool calls**:

1. **Bash**: `cd "C:/Users/johnb/Advocacy/tdranalysis" && /c/Users/johnb/A

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
Generated: 2026-02-25 19:38
================================================================================

IDENTITY
  Parcel ID:      23026006
  Address:        3916 7Th St S, Arlington VA 22204
  Neighborhood:   Alcova Heights
  Zoning:         R-6
  Split Zoned:    Yes

RAW 

...[truncated]...

nd significantly above Methods 1 and 2. The $100–$200/sf range spans a large uncertainty band; the more defensible range from Methods 1 & 2 is roughly $109k–$229k.

---

**Follow-up options:**
- Look up this parcel in `data/results/alcova_heights/alcova_heights_analysis.csv`
- Check `spot_checks.csv` or `anomaly_report.csv` for any flags
- Compare against other nonconforming lots in Alcova Heights
~~~

### Scenario: `nonexistent_parcel`

- Turns: 3
- Tokens in/out: 5 / 18
- Tool calls: 1

**Score**: 100 / 100  |  PASS

| Criterion | Weight | Earned | Note |
|-----------|--------|--------|------|
| unix_path | 20 | 20 | Unix-style /c/ path used correctly |
| parcel_id_flag | 15 | 15 | inspect_parcel.py called with --parcel-id flag |
| stdout_displayed | 15 | 15 | Final text is substantial (423 chars) |
| calc_trace | 20 | 20 | Calculation trace N/A for edge-case scenario |
| key_terms | 15 | 15 | Key terms N/A for edge-case scenario |
| validation_flags | 10 | 10 | Validation flags N/A for edge-case scenario |
| turn_count | 5 | 5 | Turn count: 3 (≤5) |

**Tool calls**:

1. **Bash**: `/c/Users/johnb/Advocacy/tdranalysis/venv/Scripts/python scri

...[truncated]...

cel.py --parcel-id "00000000" --output-dir data/results 2>&1`
   Output: ================================================================================
PARCEL INSPECTION 

...[truncated]...

=================================

ERROR: Parcel '00000000' not found in dataset (column: RPCMSTR)

**Final text** (truncated to 800 chars):
~~~
Parcel `00000000` was not found in the dataset — it appears to be a placeholder ID rather than a real parcel.

To inspect a real parcel, use:

```
/inspect-parcel 23026006
```

Replace `23026006` with the actual RPCMSTR code you want to examine. You can find valid parcel IDs in:
- `data/results/alcova_heights/alcova_heights_analysis.csv` (analyzed parcels)
- `data/processed/parcels_enriched.gpkg` (all processed parcels)
~~~

### Scenario: `empty_args`

- Turns: 2
- Tokens in/out: 4 / 16
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
No parcel ID was provided. Please provide the RPCMSTR code for the parcel you want to inspect (e.g., `23026006`), optionally followed by a neighborhood name.
~~~

---

## Model: `haiku`

**Overall score**: 0.0 / 100
**Recommendation**: **FAIL**
**Reason**: Overall score 0.0 < 65

**Critical failures**: session_error, session_error, session_error, session_error

### Scenario: `happy_path`

**ERROR**: claude CLI exited with code 1 (partial output): 

### Scenario: `parcel_only`

**ERROR**: claude CLI exited with code 1 (partial output): 

### Scenario: `nonexistent_parcel`

**ERROR**: claude CLI exited with code 1 (partial output): 

### Scenario: `empty_args`

**ERROR**: claude CLI exited with code 1 (partial output): 

---

## Side-by-Side: Happy Path Final Text

### `sonnet`
~~~
```
================================================================================
PARCEL INSPECTION REPORT: 23026006
Generated: 2026-02-25 19:37
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

 Sample size | OK (n=12 >= 10) |
| Valuation spread | **High/low = 3.21x** — exceeds 2.5x threshold. Wide uncertainty driven by Method 3 (price/sf $100–$200 range). |
| Nonconforming lot | **Yes** — lot width 45.8 ft < 60 ft required. Max footprint constrained to lot coverage limit (30% of area), not width-based setbacks. |

---

**Follow-up options:**
- Compare against the Alcova Heights CSV: `data/results/alcova_heights/alcova_heights_analysis.csv`
- Check if it appears in `spot_checks.csv` or `anomaly_report.csv`
- Run with `--json` for structured data if you need to feed results downstream
~~~

### `haiku`
~~~
You've hit your limit · resets 8pm (America/New_York)
~~~
