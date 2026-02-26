"""
Rubric-based scoring for inspect-parcel skill sessions.

Rubric (per scored scenario):

| Criterion                              | Weight | Critical failure            | Degraded (0.5)            |
|----------------------------------------|--------|-----------------------------|---------------------------|
| Unix-style Python path used            | 20     | Windows-style path used     | —                         |
| --parcel-id flag in Bash command       | 15     | no Bash call (happy paths)  | wrong flag / missing      |
| Script stdout displayed                | 15     | no Bash call (happy paths)  | bash called, short output |
| Calculation trace: all 4 stages        | 20     | no stage terms at all       | 1–2 stages missing        |
| Key structural terms present           | 15     | none found                  | < half found              |
| Validation flags section               | 10     | no flag terms               | partial                   |
| Turn count ≤ 5                         | 5      | > 10 turns                  | 5–10 turns                |

Total: 100 points.

Pass threshold: ≥ 75 overall AND no critical failure on:
  - Unix-style Python path (weight 20)
  - Calculation trace (weight 20) [happy-path scenarios only]

Scenarios considered "full analysis" (all criteria apply):
  happy_path, parcel_only

Scenarios considered "edge case" (trace/key_terms/validation waived):
  nonexistent_parcel, empty_args
"""

import re
from typing import Any, TypedDict


class CriterionResult(TypedDict):
    weight: float
    earned: float
    note: str


# Criteria weights — typed as float so half-credit arithmetic (weight * 0.5) stays float.
WEIGHTS: dict[str, float] = {
    "unix_path": 20,
    "parcel_id_flag": 15,
    "stdout_displayed": 15,
    "calc_trace": 20,
    "key_terms": 15,
    "validation_flags": 10,
    "turn_count": 5,
}

# Mandatory criteria — critical failure on these → overall fail regardless of score
MANDATORY_CRITERIA = {"unix_path", "calc_trace"}

PASS_THRESHOLD = 75  # per-scenario pass bar
AGGREGATE_PASS_THRESHOLD = 80  # aggregate pass bar (haiku recommendation)
CONDITIONAL_THRESHOLD = 65  # aggregate score below PASS but at/above this → CONDITIONAL
MIN_FINAL_TEXT_CHARS = 300  # below this, stdout is not considered shown in final text

# Scenarios where all criteria apply (model must produce full trace)
FULL_ANALYSIS_SCENARIOS = {"happy_path", "parcel_only"}

WINDOWS_PATH_PATTERN = re.compile(
    r"(?:"
    r"C:\\|"  # C:\ (single backslash, as it appears in shell text)
    r"C:/Users.*?python\.exe|"  # Windows-style quoted path ending in python.exe
    r'"C:/'  # quoted Windows path
    r")",
    re.IGNORECASE,
)

UNIX_PATH_PATTERN = re.compile(
    r"/c/Users/johnb/Advocacy/tdranalysis/venv/Scripts/python"
)

# Stage presence checks — one pattern per stage; order matches the skill instructions
STAGE_PATTERNS = [
    re.compile(
        r"Stage\s*1|Development\s*Potential|max[_ ]gfa|max GFA|footprint", re.IGNORECASE
    ),
    re.compile(
        r"Stage\s*2|Current\s*Built|current[_ ]gfa|improvement\s*value|Tier\s*[123]",
        re.IGNORECASE,
    ),
    re.compile(
        r"Stage\s*3|Available\s*Rights|available[_ ]gfa|gfa[_ ]utilization|utilization",
        re.IGNORECASE,
    ),
    re.compile(
        r"Stage\s*4|Valuation|Land\s*Residual|Assessment\s*Ratio|Price\s*Per\s*SF|tdr[_ ]potential",
        re.IGNORECASE,
    ),
]

# Key structural terms — presence indicates a substantive response
KEY_TERM_PATTERNS = [
    re.compile(r"max[_ ]gfa|max GFA", re.IGNORECASE),
    re.compile(r"available[_ ]gfa|available GFA", re.IGNORECASE),
    re.compile(r"tdr[_ ]potential|TDR potential", re.IGNORECASE),
    re.compile(r"zoning|R-\d+", re.IGNORECASE),
    re.compile(r"lot\s+(area|size)|lot_area", re.IGNORECASE),
]

# Validation flag terms — the skill explicitly requires surfacing these
VALIDATION_FLAG_PATTERNS = [
    re.compile(r"Tier\s*[123]|GFA\s*(source|tier)", re.IGNORECASE),
    re.compile(r"fallback\s*rate|fallback", re.IGNORECASE),
    re.compile(r"sample\s*size|n\s*=\s*\d+", re.IGNORECASE),
    re.compile(r"spread|high\s*/\s*low|valuation.*spread", re.IGNORECASE),
    re.compile(r"nonconform|conformance", re.IGNORECASE),
]


def _c(key: str, earned: float, note: str) -> CriterionResult:
    """Build a criterion result dict for the given scoring key."""
    return {"weight": WEIGHTS[key], "earned": earned, "note": note}


def _bash_commands(session: dict[str, Any]) -> list[str]:
    """Return inputs of all Bash tool calls in the session."""
    return [tc["input"] for tc in session["tool_calls"] if tc["name"] == "Bash"]


def score_session(session: dict[str, Any], scenario_name: str) -> dict[str, Any]:
    """
    Score a session dict against the inspect-parcel rubric.

    Returns:
        {
            "scenario": str,
            "total": float,          # 0–100
            "criteria": dict,        # criterion -> {"weight", "earned", "note"}
            "passed": bool,
            "critical_failures": list[str],
        }
    """
    final_text = session.get("final_text", "")
    turn_count = session.get("turn_count", 0)
    bash_cmds = _bash_commands(session)
    all_bash_text = "\n".join(bash_cmds)
    is_full_analysis = scenario_name in FULL_ANALYSIS_SCENARIOS

    criteria: dict[str, CriterionResult] = {}

    # ── 1. Unix-style Python path (weight 20) ──────────────────────────────
    has_unix_path = bool(UNIX_PATH_PATTERN.search(all_bash_text))
    has_windows_path = bool(WINDOWS_PATH_PATTERN.search(all_bash_text))

    if not bash_cmds:
        if is_full_analysis:
            unix_earned: float = 0
            unix_note = "CRITICAL: No Bash calls made — path not verified"
        else:
            unix_earned = WEIGHTS["unix_path"]
            unix_note = "No Bash calls — path criterion N/A for edge-case scenario"
    elif has_unix_path:
        unix_earned = WEIGHTS["unix_path"]
        unix_note = "Unix-style /c/ path used correctly"
    elif has_windows_path:
        unix_earned = 0
        unix_note = "CRITICAL: Windows-style path detected"
    else:
        # Bash called but no python invocation found (unusual)
        unix_earned = WEIGHTS["unix_path"] * 0.5
        unix_note = "Bash called but /c/Users path not found in commands"
    criteria["unix_path"] = _c("unix_path", unix_earned, unix_note)

    # ── 2. --parcel-id flag in Bash command (weight 15) ────────────────────
    has_inspect_script = any("inspect_parcel" in cmd for cmd in bash_cmds)
    has_parcel_id_flag = any("--parcel-id" in cmd for cmd in bash_cmds)

    if not bash_cmds:
        if is_full_analysis:
            flag_earned: float = 0
            flag_note = "CRITICAL: No Bash call — inspect_parcel.py never invoked"
        else:
            flag_earned = WEIGHTS["parcel_id_flag"]
            flag_note = "No Bash call — parcel-id flag N/A for edge-case scenario"
    elif has_inspect_script and has_parcel_id_flag:
        flag_earned = WEIGHTS["parcel_id_flag"]
        flag_note = "inspect_parcel.py called with --parcel-id flag"
    elif has_inspect_script:
        flag_earned = WEIGHTS["parcel_id_flag"] * 0.5
        flag_note = "inspect_parcel.py called but --parcel-id flag not found"
    else:
        flag_earned = 0
        flag_note = "inspect_parcel.py not found in any Bash command"
    criteria["parcel_id_flag"] = _c("parcel_id_flag", flag_earned, flag_note)

    # ── 3. Script stdout displayed (weight 15) ─────────────────────────────
    if not bash_cmds:
        if is_full_analysis:
            stdout_earned: float = 0
            stdout_note = "CRITICAL: No Bash call made"
        else:
            stdout_earned = WEIGHTS["stdout_displayed"]
            stdout_note = "No Bash call — stdout display N/A for edge-case scenario"
    elif len(final_text) > MIN_FINAL_TEXT_CHARS:
        stdout_earned = WEIGHTS["stdout_displayed"]
        stdout_note = f"Final text is substantial ({len(final_text)} chars)"
    else:
        stdout_earned = WEIGHTS["stdout_displayed"] * 0.5
        stdout_note = f"Final text may be too short ({len(final_text)} chars < {MIN_FINAL_TEXT_CHARS})"
    criteria["stdout_displayed"] = _c("stdout_displayed", stdout_earned, stdout_note)

    # ── 4. Calculation trace: all 4 stages (weight 20) ─────────────────────
    if not is_full_analysis:
        trace_earned = WEIGHTS["calc_trace"]
        trace_note = "Calculation trace N/A for edge-case scenario"
    else:
        stages_found = [
            i + 1 for i, pat in enumerate(STAGE_PATTERNS) if pat.search(final_text)
        ]
        if len(stages_found) == 4:
            trace_earned = WEIGHTS["calc_trace"]
            trace_note = "All 4 stages present in final text"
        elif len(stages_found) >= 2:
            trace_earned = WEIGHTS["calc_trace"] * 0.5
            trace_note = f"Only {len(stages_found)}/4 stages found: {stages_found}"
        else:
            trace_earned = 0
            trace_note = f"CRITICAL: Only {len(stages_found)}/4 stage terms found: {stages_found}"
    criteria["calc_trace"] = _c("calc_trace", trace_earned, trace_note)

    # ── 5. Key structural terms (weight 15) ────────────────────────────────
    if not is_full_analysis:
        terms_earned = WEIGHTS["key_terms"]
        terms_note = "Key terms N/A for edge-case scenario"
    else:
        found_terms = [
            i for i, pat in enumerate(KEY_TERM_PATTERNS) if pat.search(final_text)
        ]
        if len(found_terms) >= len(KEY_TERM_PATTERNS):
            terms_earned = WEIGHTS["key_terms"]
            terms_note = f"All {len(KEY_TERM_PATTERNS)} key terms found"
        elif len(found_terms) >= len(KEY_TERM_PATTERNS) // 2 + 1:
            terms_earned = WEIGHTS["key_terms"] * 0.5
            terms_note = (
                f"Partial key terms: {len(found_terms)}/{len(KEY_TERM_PATTERNS)} found"
            )
        else:
            terms_earned = 0
            terms_note = (
                f"Too few key terms: {len(found_terms)}/{len(KEY_TERM_PATTERNS)} found"
            )
    criteria["key_terms"] = _c("key_terms", terms_earned, terms_note)

    # ── 6. Validation flags section (weight 10) ────────────────────────────
    if not is_full_analysis:
        val_earned = WEIGHTS["validation_flags"]
        val_note = "Validation flags N/A for edge-case scenario"
    else:
        found_flags = [
            i
            for i, pat in enumerate(VALIDATION_FLAG_PATTERNS)
            if pat.search(final_text)
        ]
        if len(found_flags) >= 2:
            val_earned = WEIGHTS["validation_flags"]
            val_note = f"{len(found_flags)}/{len(VALIDATION_FLAG_PATTERNS)} validation flag terms found"
        elif len(found_flags) == 1:
            val_earned = WEIGHTS["validation_flags"] * 0.5
            val_note = f"Only {len(found_flags)}/{len(VALIDATION_FLAG_PATTERNS)} validation flag terms found"
        else:
            val_earned = 0
            val_note = "No validation flag terms found in final text"
    criteria["validation_flags"] = _c("validation_flags", val_earned, val_note)

    # ── 7. Turn count ≤ 5 (weight 5) ──────────────────────────────────────
    if turn_count <= 5:
        turn_earned = WEIGHTS["turn_count"]
        turn_note = f"Turn count: {turn_count} (≤5)"
    elif turn_count <= 10:
        turn_earned = WEIGHTS["turn_count"] * 0.5
        turn_note = f"Turn count: {turn_count} (5–10, degraded)"
    else:
        turn_earned = 0
        turn_note = f"Turn count: {turn_count} (>10, critical)"
    criteria["turn_count"] = _c("turn_count", turn_earned, turn_note)

    # ── Totals ─────────────────────────────────────────────────────────────
    total = sum(v["earned"] for v in criteria.values())

    critical_failures = [k for k in MANDATORY_CRITERIA if criteria[k]["earned"] == 0]

    passed = total >= PASS_THRESHOLD and not critical_failures

    return {
        "scenario": scenario_name,
        "total": round(total, 1),
        "criteria": criteria,
        "passed": passed,
        "critical_failures": critical_failures,
    }


def aggregate_scores(scored_scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Aggregate scores across all scored scenarios.

    Precondition: all items in scored_scenarios have scored==True (caller filters).
    Returns overall score (mean), any critical failures, and a recommendation string.
    """
    if not scored_scenarios:
        return {
            "overall": 0,
            "recommendation": "FAIL",
            "details": "No scored scenarios",
        }

    total_scores = [s["score"]["total"] for s in scored_scenarios]
    overall = round(sum(total_scores) / len(total_scores), 1)

    all_critical: list[str] = []
    for s in scored_scenarios:
        all_critical.extend(s["score"]["critical_failures"])

    mandatory_critical = [c for c in all_critical if c in MANDATORY_CRITERIA]

    if mandatory_critical:
        recommendation = "FAIL"
        reason = f"Critical failures on mandatory criteria: {mandatory_critical}"
    elif overall >= AGGREGATE_PASS_THRESHOLD:
        recommendation = "PASS"
        reason = (
            f"Overall score {overall} ≥ {AGGREGATE_PASS_THRESHOLD}"
            " with no mandatory critical failures"
        )
    elif overall >= CONDITIONAL_THRESHOLD:
        recommendation = "CONDITIONAL"
        reason = (
            f"Overall score {overall} is {CONDITIONAL_THRESHOLD}–"
            f"{AGGREGATE_PASS_THRESHOLD - 1}; review degraded criteria"
        )
    else:
        recommendation = "FAIL"
        reason = f"Overall score {overall} < {CONDITIONAL_THRESHOLD}"

    return {
        "overall": overall,
        "recommendation": recommendation,
        "reason": reason,
        "scenario_scores": [
            {
                "scenario": s["scenario"],
                "total": s["score"]["total"],
                "passed": s["score"]["passed"],
            }
            for s in scored_scenarios
        ],
        "critical_failures": all_critical,
    }
