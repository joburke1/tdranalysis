# Model Feedback

This directory stores structured critique records for approved methodological feedback.
Each file represents a single approved critique of the valuation model, TDR classification
logic, or supporting economic analysis.

## Directory structure

```
model_feedback/
  README.md              # This file
  <issue_number>.md      # One file per approved feedback issue
```

## Record format

Each `.md` file is created automatically by `apply_model_feedback.yml` when the owner
comments `/approve-feedback` on a `model-feedback` issue. The format:

```markdown
# Model Feedback #<N>: <issue title>

**Issue:** #<N>
**Reporter:** @<github_username>
**Date reported:** YYYY-MM-DD
**Category:** <feedback category>
**Affected documents (self-reported):** <list>

---

## Critique

<verbatim critique from issue>

---

## Proposed Improvement

<verbatim proposed improvement from issue>

---

## Owner Note

<note from /approve-feedback command>

---

## Status

approved — implementation in progress

---

## TODO

- [ ] Update `supporting documentation/<doc>` to address critique
- [ ] If parameter change warranted: update `config/valuation_params.json`
- [ ] If code change warranted: update relevant pipeline script(s)
- [ ] Regenerate analysis for affected neighborhood(s) to validate impact
```

The `.md` format is intentional: these are narrative records, not machine-applied patches.
All changes to documentation, config, and code are implemented manually on the feature branch.

## Workflow summary

1. Stakeholder files a GitHub issue using the **Model Feedback Report** template
2. GHA triage bot (`triage_model_feedback.yml`) validates the form, identifies likely affected supporting docs, and labels the issue `triaged` + `needs-model-review`
3. Owner reviews the critique by reading the referenced supporting documentation and, if helpful, running `scripts/inspect_parcel.py` on relevant parcels
4. Owner comments `/approve-feedback note="..."` or `/reject-feedback reason="..."` on the issue
5. On approval, GHA (`apply_model_feedback.yml`) creates branch `model-feedback/issue-<N>`, writes `model_feedback/<N>.md`, and opens a PR with a TODO checklist
6. Owner implements changes on the branch:
   - Updates relevant file(s) in `supporting documentation/`
   - If warranted: updates `config/valuation_params.json` or `config/classification_params.json`
   - If warranted: updates pipeline scripts
   - Marks TODOs complete in `model_feedback/<N>.md`
7. Owner merges PR to main

## Command syntax

```
/approve-feedback note="Brief rationale for approval and implementation direction"
/reject-feedback reason="Why this critique is not accepted"
```

Commands are only processed from the project owner (`johnb`) on issues labeled `model-feedback`.

## Feedback categories

| Category | Primary supporting doc |
|----------|----------------------|
| Discount factor / valuation parameters | `Valuation of Development Rights.md` |
| TDR classification thresholds | `Valuation of Development Rights.md` |
| Development potential assumptions | `maximum development potential human.md`, `maximum development potential llm.md` |
| Demand-side analysis | `Arlington site plan process costs.md` |
| Supply-side analysis | `Valuation of Development Rights.md` |
| Other methodology critique | Review all supporting docs |

## Prerequisites

The following labels must exist in the GitHub repo for this workflow to function:

- `model-feedback` — applied by the issue template; gates triage and command workflows
- `triaged` — applied by triage bot after validation
- `needs-model-review` — applied when critique and improvement fields are valid
- `needs-more-info` — applied when required fields are missing
- `rejected` — applied by apply_model_feedback.yml on rejection
