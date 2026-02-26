"""
Rubric-based scoring for the run-pipeline skill.

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

from tests.model_comparison.framework.scorer import BaseScorer
from tests.model_comparison.framework.types import (
    Scenario,
    ScenarioScore,
    SessionResult,
)

MIN_FINAL_TEXT_CHARS = 200

# Numbers expected in Alcova Heights final text
ALCOVA_KEY_NUMBERS = ["295", "283", "69", "216"]

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

SKIP_DOWNLOAD = "--skip-download"
SKIP_PROCESS = "--skip-process"

FOLLOWUP_ANOMALY = re.compile(r"anomaly", re.IGNORECASE)
FOLLOWUP_PARCEL = re.compile(r"parcel\s+inspector|inspect.*parcel", re.IGNORECASE)


class Scorer(BaseScorer):
    """Rubric scorer for the run-pipeline skill."""

    WEIGHTS: dict[str, float] = {
        "unix_path": 20,
        "skip_flags": 15,
        "stdout_displayed": 15,
        "summary_read": 20,
        "key_numbers": 15,
        "followup_offers": 10,
        "turn_count": 5,
    }

    MANDATORY_CRITERIA = {"unix_path", "summary_read"}

    def score_session(
        self, session: SessionResult, scenario: Scenario
    ) -> ScenarioScore:
        """Score a run-pipeline session against the rubric."""
        final_text = session.final_text
        turn_count = session.turn_count
        bash_cmds = self._bash_commands(session)
        read_paths = self._read_paths(session)
        is_happy_path = scenario.name == "happy_path"

        criteria = {}

        # ── 1. Unix-style Python path (weight 20) ──────────────────────────
        # Check unix path BEFORE windows path — /c/Users/ must not trigger
        # the Windows false-positive check (see MEMORY.md).
        all_bash_text = "\n".join(bash_cmds)
        has_unix_path = bool(UNIX_PATH_PATTERN.search(all_bash_text))
        has_windows_path = bool(WINDOWS_PATH_PATTERN.search(all_bash_text))

        if not bash_cmds:
            unix_earned = self.WEIGHTS["unix_path"]
            unix_note = "No Bash calls — path criterion N/A"
        elif has_unix_path and not has_windows_path:
            unix_earned = self.WEIGHTS["unix_path"]
            unix_note = "Unix-style /c/ path used correctly"
        elif has_windows_path:
            unix_earned = 0
            unix_note = "CRITICAL: Windows-style path detected"
        else:
            unix_earned = self.WEIGHTS["unix_path"]
            unix_note = "No Python invocation in bash (acceptable for this scenario)"
        criteria["unix_path"] = self._c("unix_path", unix_earned, unix_note)

        # ── 2. --skip flags (weight 15) ────────────────────────────────────
        has_skip_dl = any(SKIP_DOWNLOAD in cmd for cmd in bash_cmds)
        has_skip_proc = any(SKIP_PROCESS in cmd for cmd in bash_cmds)

        if not bash_cmds:
            skip_earned = self.WEIGHTS["skip_flags"]
            skip_note = "No Bash calls — skip flags N/A"
        elif has_skip_dl and has_skip_proc:
            skip_earned = self.WEIGHTS["skip_flags"]
            skip_note = "Both --skip-download and --skip-process present"
        elif has_skip_dl or has_skip_proc:
            skip_earned = self.WEIGHTS["skip_flags"] * 0.5
            skip_note = (
                f"Only one skip flag: skip-download={has_skip_dl},"
                f" skip-process={has_skip_proc}"
            )
        else:
            skip_earned = 0
            skip_note = "CRITICAL: Both skip flags absent"
        criteria["skip_flags"] = self._c("skip_flags", skip_earned, skip_note)

        # ── 3. Script stdout displayed (weight 15) ─────────────────────────
        bash_outputs = "\n".join(
            tc["output"] for tc in session.tool_calls if tc["name"] == "Bash"
        )
        if not bash_cmds:
            stdout_earned: float = 0
            stdout_note = "CRITICAL: No Bash tool call made"
        elif bash_outputs.strip() and len(final_text) > MIN_FINAL_TEXT_CHARS:
            stdout_earned = self.WEIGHTS["stdout_displayed"]
            stdout_note = "Bash called and final text is substantial"
        else:
            stdout_earned = self.WEIGHTS["stdout_displayed"] * 0.5
            stdout_note = "Bash called but output may not be shown in final text"
        criteria["stdout_displayed"] = self._c("stdout_displayed", stdout_earned, stdout_note)

        # ── 4. Summary file read and displayed (weight 20) ─────────────────
        summary_pattern = re.compile(r"_summary\.txt", re.IGNORECASE)
        read_summary = any(summary_pattern.search(p) for p in read_paths)
        summary_content_present = "295" in final_text or "Total residential" in final_text

        if not is_happy_path:
            summary_earned = self.WEIGHTS["summary_read"]
            summary_note = "Summary read N/A for this scenario"
        elif read_summary and summary_content_present:
            summary_earned = self.WEIGHTS["summary_read"]
            summary_note = "Summary file read and content present in final text"
        elif read_summary:
            summary_earned = self.WEIGHTS["summary_read"] * 0.5
            summary_note = "Summary file read but content not clearly shown in final text"
        else:
            summary_earned = 0
            summary_note = "CRITICAL: Summary file not read"
        criteria["summary_read"] = self._c("summary_read", summary_earned, summary_note)

        # ── 5. Key numbers in final text (weight 15) ───────────────────────
        if not is_happy_path:
            numbers_earned = self.WEIGHTS["key_numbers"]
            numbers_note = "Key numbers N/A for this scenario"
        else:
            found = [n for n in ALCOVA_KEY_NUMBERS if n in final_text]
            if len(found) == len(ALCOVA_KEY_NUMBERS):
                numbers_earned = self.WEIGHTS["key_numbers"]
                numbers_note = f"All key numbers found: {found}"
            elif len(found) >= 2:
                numbers_earned = self.WEIGHTS["key_numbers"] * 0.5
                numbers_note = (
                    f"Partial key numbers found: {found}"
                    f" (expected all of {ALCOVA_KEY_NUMBERS})"
                )
            else:
                numbers_earned = 0
                numbers_note = f"No key numbers found (expected {ALCOVA_KEY_NUMBERS})"
        criteria["key_numbers"] = self._c("key_numbers", numbers_earned, numbers_note)

        # ── 6. Follow-up offers (weight 10) ────────────────────────────────
        has_anomaly_offer = bool(FOLLOWUP_ANOMALY.search(final_text))
        has_parcel_offer = bool(FOLLOWUP_PARCEL.search(final_text))

        if not is_happy_path:
            followup_earned = self.WEIGHTS["followup_offers"]
            followup_note = "Follow-up offers N/A for this scenario"
        elif has_anomaly_offer and has_parcel_offer:
            followup_earned = self.WEIGHTS["followup_offers"]
            followup_note = "Both anomaly check and parcel inspector offers present"
        elif has_anomaly_offer or has_parcel_offer:
            followup_earned = self.WEIGHTS["followup_offers"] * 0.5
            followup_note = (
                f"Only one follow-up: anomaly={has_anomaly_offer},"
                f" parcel={has_parcel_offer}"
            )
        else:
            followup_earned = 0
            followup_note = "Neither follow-up offer present"
        criteria["followup_offers"] = self._c(
            "followup_offers", followup_earned, followup_note
        )

        # ── 7. Turn count ≤ 5 (weight 5) ──────────────────────────────────
        if turn_count <= 5:
            turn_earned = self.WEIGHTS["turn_count"]
            turn_note = f"Turn count: {turn_count} (≤5)"
        elif turn_count <= 10:
            turn_earned = self.WEIGHTS["turn_count"] * 0.5
            turn_note = f"Turn count: {turn_count} (5–10, degraded)"
        else:
            turn_earned = 0
            turn_note = f"Turn count: {turn_count} (>10, critical)"
        criteria["turn_count"] = self._c("turn_count", turn_earned, turn_note)

        # ── Totals ──────────────────────────────────────────────────────────
        total = round(sum(cr.earned for cr in criteria.values()), 1)
        critical_failures = [
            k for k in self.MANDATORY_CRITERIA if criteria[k].earned == 0
        ]
        passed = total >= self.PASS_THRESHOLD and not critical_failures

        return ScenarioScore(
            scenario_name=scenario.name,
            total=total,
            criteria=criteria,
            passed=passed,
            critical_failures=critical_failures,
        )
