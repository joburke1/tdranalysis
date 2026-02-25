"""
Rubric-based scoring for run-pipeline skill sessions.

Rubric (per scored scenario):

| Criterion                          | Weight | Critical failure        | Degraded (0.5)       |
|------------------------------------|--------|------------------------|----------------------|
| Unix-style Python path used        | 20     | Windows-style path used | —                   |
| --skip flags present               | 15     | both flags absent       | one flag missing     |
| Script stdout displayed            | 15     | no Bash call at all     | bash called, not shown |
| Summary file read and displayed    | 20     | not read                | read but not shown   |
| Key numbers in final text          | 15     | no numbers              | partial numbers      |
| Follow-up offers present           | 10     | not offered             | only one of two      |
| Turn count ≤ 5                     | 5      | > 10 turns              | 5–10 turns           |

Total: 100 points.

Pass threshold: ≥ 75 overall AND no critical failure on:
  - Unix-style Python path (weight 20)
  - Summary file read (weight 20)

Key numbers expected in happy-path final text:
  295, 283, 69 (from $69M), 216 (from $216M)
"""

import re
from typing import Any

# Criteria weights
WEIGHTS = {
    "unix_path": 20,
    "skip_flags": 15,
    "stdout_displayed": 15,
    "summary_read": 20,
    "key_numbers": 15,
    "followup_offers": 10,
    "turn_count": 5,
}

# Mandatory criteria — critical failure on these → overall fail regardless of score
MANDATORY_CRITERIA = {"unix_path", "summary_read"}

PASS_THRESHOLD = 75          # per-scenario pass bar
AGGREGATE_PASS_THRESHOLD = 80  # aggregate pass bar (haiku recommendation)

# Numbers expected in Alcova Heights final text
ALCOVA_KEY_NUMBERS = ["295", "283", "69", "216"]

WINDOWS_PATH_PATTERN = re.compile(
    r"(?:"
    r"C:\\\\|"           # C:\\ (escaped backslash in strings)
    r"C:\\|"             # C:\
    r"C:/Users.*?python\.exe|"  # Windows-style quoted path ending in python.exe
    r'"C:/'              # quoted Windows path
    r")",
    re.IGNORECASE,
)

UNIX_PATH_PATTERN = re.compile(r"/c/Users/johnb/Advocacy/tdranalysis/venv/Scripts/python")

SKIP_DOWNLOAD = "--skip-download"
SKIP_PROCESS = "--skip-process"

FOLLOWUP_ANOMALY = re.compile(r"anomaly", re.IGNORECASE)
FOLLOWUP_PARCEL = re.compile(r"parcel\s+inspector|inspect.*parcel", re.IGNORECASE)


def _bash_commands(session: dict[str, Any]) -> list[str]:
    return [tc["input"] for tc in session["tool_calls"] if tc["name"] == "Bash"]


def _read_paths(session: dict[str, Any]) -> list[str]:
    return [tc["input"] for tc in session["tool_calls"] if tc["name"] == "Read"]


def _all_bash_outputs(session: dict[str, Any]) -> str:
    return "\n".join(tc["output"] for tc in session["tool_calls"] if tc["name"] == "Bash")


def score_session(session: dict[str, Any], scenario_name: str) -> dict[str, Any]:
    """
    Score a session dict against the rubric.

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
    read_paths = _read_paths(session)
    bash_outputs = _all_bash_outputs(session)
    is_happy_path = scenario_name == "happy_path"

    criteria: dict[str, dict] = {}

    # ── 1. Unix-style Python path (weight 20) ──────────────────────────────
    # Check all bash commands for path usage
    all_bash_text = "\n".join(bash_cmds)
    has_unix_path = bool(UNIX_PATH_PATTERN.search(all_bash_text))
    has_windows_path = bool(WINDOWS_PATH_PATTERN.search(all_bash_text))

    if not bash_cmds:
        # No bash call at all — path criterion N/A for non-happy-path scenarios
        # but for happy path this is a critical failure handled in stdout_displayed
        unix_earned = WEIGHTS["unix_path"]  # give benefit of doubt if no bash needed
        unix_note = "No Bash calls — path criterion N/A"
    elif has_unix_path and not has_windows_path:
        unix_earned = WEIGHTS["unix_path"]
        unix_note = "Unix-style /c/ path used correctly"
    elif has_windows_path:
        unix_earned = 0
        unix_note = "CRITICAL: Windows-style path detected"
    else:
        # Bash called but no python invocation (e.g. list command)
        unix_earned = WEIGHTS["unix_path"]
        unix_note = "No Python invocation in bash (acceptable for this scenario)"
    criteria["unix_path"] = {"weight": WEIGHTS["unix_path"], "earned": unix_earned, "note": unix_note}

    # ── 2. --skip flags (weight 15) ────────────────────────────────────────
    has_skip_dl = any(SKIP_DOWNLOAD in cmd for cmd in bash_cmds)
    has_skip_proc = any(SKIP_PROCESS in cmd for cmd in bash_cmds)

    if not bash_cmds:
        skip_earned = WEIGHTS["skip_flags"]
        skip_note = "No Bash calls — skip flags N/A"
    elif has_skip_dl and has_skip_proc:
        skip_earned = WEIGHTS["skip_flags"]
        skip_note = "Both --skip-download and --skip-process present"
    elif has_skip_dl or has_skip_proc:
        skip_earned = WEIGHTS["skip_flags"] * 0.5
        skip_note = f"Only one skip flag: skip-download={has_skip_dl}, skip-process={has_skip_proc}"
    else:
        skip_earned = 0
        skip_note = "CRITICAL: Both skip flags absent"
    criteria["skip_flags"] = {"weight": WEIGHTS["skip_flags"], "earned": skip_earned, "note": skip_note}

    # ── 3. Script stdout displayed (weight 15) ─────────────────────────────
    # Check that model made a bash call and that stdout appears in final text
    if not bash_cmds:
        stdout_earned = 0
        stdout_note = "CRITICAL: No Bash tool call made"
    elif bash_outputs.strip() and len(final_text) > 200:
        stdout_earned = WEIGHTS["stdout_displayed"]
        stdout_note = "Bash called and final text is substantial"
    else:
        stdout_earned = WEIGHTS["stdout_displayed"] * 0.5
        stdout_note = "Bash called but output may not be shown in final text"
    criteria["stdout_displayed"] = {"weight": WEIGHTS["stdout_displayed"], "earned": stdout_earned, "note": stdout_note}

    # ── 4. Summary file read and displayed (weight 20) ────────────────────
    # Only apply strictly on happy path; for other scenarios relax
    summary_pattern = re.compile(r"_summary\.txt", re.IGNORECASE)
    read_summary = any(summary_pattern.search(p) for p in read_paths)
    # Also check if the model embedded summary content in final text
    summary_content_present = "295" in final_text or "Total residential" in final_text

    if not is_happy_path:
        # Not applicable for non-happy-path scenarios
        summary_earned = WEIGHTS["summary_read"]
        summary_note = "Summary read N/A for this scenario"
    elif read_summary and summary_content_present:
        summary_earned = WEIGHTS["summary_read"]
        summary_note = "Summary file read and content present in final text"
    elif read_summary:
        summary_earned = WEIGHTS["summary_read"] * 0.5
        summary_note = "Summary file read but content not clearly shown in final text"
    else:
        summary_earned = 0
        summary_note = "CRITICAL: Summary file not read"
    criteria["summary_read"] = {"weight": WEIGHTS["summary_read"], "earned": summary_earned, "note": summary_note}

    # ── 5. Key numbers in final text (weight 15) ──────────────────────────
    if not is_happy_path:
        numbers_earned = WEIGHTS["key_numbers"]
        numbers_note = "Key numbers N/A for this scenario"
    else:
        found = [n for n in ALCOVA_KEY_NUMBERS if n in final_text]
        if len(found) == len(ALCOVA_KEY_NUMBERS):
            numbers_earned = WEIGHTS["key_numbers"]
            numbers_note = f"All key numbers found: {found}"
        elif len(found) >= 2:
            numbers_earned = WEIGHTS["key_numbers"] * 0.5
            numbers_note = f"Partial key numbers found: {found} (expected all of {ALCOVA_KEY_NUMBERS})"
        else:
            numbers_earned = 0
            numbers_note = f"No key numbers found (expected {ALCOVA_KEY_NUMBERS})"
    criteria["key_numbers"] = {"weight": WEIGHTS["key_numbers"], "earned": numbers_earned, "note": numbers_note}

    # ── 6. Follow-up offers (weight 10) ───────────────────────────────────
    has_anomaly_offer = bool(FOLLOWUP_ANOMALY.search(final_text))
    has_parcel_offer = bool(FOLLOWUP_PARCEL.search(final_text))

    if not is_happy_path:
        followup_earned = WEIGHTS["followup_offers"]
        followup_note = "Follow-up offers N/A for this scenario"
    elif has_anomaly_offer and has_parcel_offer:
        followup_earned = WEIGHTS["followup_offers"]
        followup_note = "Both anomaly check and parcel inspector offers present"
    elif has_anomaly_offer or has_parcel_offer:
        followup_earned = WEIGHTS["followup_offers"] * 0.5
        followup_note = f"Only one follow-up: anomaly={has_anomaly_offer}, parcel={has_parcel_offer}"
    else:
        followup_earned = 0
        followup_note = "Neither follow-up offer present"
    criteria["followup_offers"] = {"weight": WEIGHTS["followup_offers"], "earned": followup_earned, "note": followup_note}

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
    criteria["turn_count"] = {"weight": WEIGHTS["turn_count"], "earned": turn_earned, "note": turn_note}

    # ── Totals ─────────────────────────────────────────────────────────────
    total = sum(v["earned"] for v in criteria.values())

    critical_failures = [
        k for k in MANDATORY_CRITERIA if criteria[k]["earned"] == 0
    ]

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
        return {"overall": 0, "recommendation": "FAIL", "details": "No scored scenarios"}

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
        reason = f"Overall score {overall} ≥ {AGGREGATE_PASS_THRESHOLD} with no mandatory critical failures"
    elif overall >= 65:
        recommendation = "CONDITIONAL"
        reason = f"Overall score {overall} is 65–79; review degraded criteria"
    else:
        recommendation = "FAIL"
        reason = f"Overall score {overall} < 65"

    return {
        "overall": overall,
        "recommendation": recommendation,
        "reason": reason,
        "scenario_scores": [
            {"scenario": s["scenario"], "total": s["score"]["total"], "passed": s["score"]["passed"]}
            for s in scored_scenarios
        ],
        "critical_failures": all_critical,
    }
