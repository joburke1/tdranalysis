# Corrections

This directory contains version-controlled correction records approved by the project owner.
Each file represents a single approved data quality fix for one parcel.

## Directory structure

```
corrections/
  <neighborhood_slug>/
    <issue_number>.json    # One file per approved correction
  .last_map_update         # Date of last map regeneration (YYYY-MM-DD)
  README.md                # This file
```

## JSON schema

```json
{
  "issue_number": 42,
  "parcel_id": "23026006",
  "neighborhood": "alcova_heights",
  "spot_check_result": "excluded",
  "spot_check_notes": "Building confirmed present — GFA not available from property API",
  "reporter": "github_username",
  "reported_date": "2026-03-05",
  "approved_by": "johnb",
  "approved_date": "2026-03-05"
}
```

### `spot_check_result` values

| Value | Meaning |
|-------|---------|
| `excluded` | Parcel should be excluded from TDR analysis |
| `confirmed` | Parcel is correctly included; current classification confirmed |
| `reviewed` | Parcel reviewed; no pipeline change needed |

## Applying corrections

After merging one or more correction PRs, run:

```bash
# Apply all pending corrections
/c/Users/johnb/Advocacy/tdranalysis/venv/Scripts/python scripts/apply_corrections.py

# Apply corrections for one neighborhood only
/c/Users/johnb/Advocacy/tdranalysis/venv/Scripts/python scripts/apply_corrections.py \
  --neighborhood alcova_heights

# Preview without writing (dry run)
/c/Users/johnb/Advocacy/tdranalysis/venv/Scripts/python scripts/apply_corrections.py \
  --dry-run
```

The script upserts rows into `data/results/<neighborhood>/spot_checks.csv`. Re-run the
pipeline for the affected neighborhood(s) to see the changes reflected in output.

## Workflow summary

1. Stakeholder files a GitHub issue using the Data Quality Report template
2. GHA triage bot validates the form and labels it `needs-human-review`
3. Owner validates locally with `inspect_parcel.py` and Claude Code
4. Owner comments `/approve spot_check=excluded note="..."` on the issue
5. GHA creates a correction PR with the JSON file
6. Owner merges the PR in VS Code
7. Owner runs `apply_corrections.py` and re-runs the pipeline
8. Owner runs `generate_map.py` and commits updated `map.html`
9. GitHub Pages deploys automatically

See `.vscode/tasks.json` for one-click VS Code tasks for each step.
