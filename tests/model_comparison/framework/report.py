"""
ReportBuilder: generates JSON and Markdown reports from RunResult.

Outputs:
  results/<skill>/<timestamp>/run.json       — complete serialized RunResult
  results/<skill>/<timestamp>/<model>.json   — per-model checkpoint
  results/<skill>/<timestamp>/report.md      — human-readable Markdown
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from tests.model_comparison.framework.types import ModelResult, RunResult

logger = logging.getLogger(__name__)


class ReportBuilder:
    """
    Writes run artifacts to results/<skill>/<timestamp>/.

    The results directory structure is:
        results/
            <skill>/
                <timestamp>/
                    run.json        — full run (written by write())
                    <model>.json    — per-model checkpoint (written by write_checkpoint())
                    report.md       — Markdown report (written by write())
    """

    MAX_TEXT_CHARS = 800

    def __init__(self, results_dir: Path) -> None:
        """
        Args:
            results_dir: Base results directory (e.g. tests/model_comparison/results/).
                         Reports are written to results_dir/<skill>/<timestamp>/.
        """
        self._results_dir = results_dir

    def _run_dir(self, skill: str, timestamp: str) -> Path:
        """Return (and create) the run directory for a given skill + timestamp."""
        d = self._results_dir / skill / timestamp
        d.mkdir(parents=True, exist_ok=True)
        return d

    def write(self, run_result: RunResult) -> Path:
        """
        Write all report artifacts. Returns the run directory path.

        Creates:
            results/<skill>/<timestamp>/run.json
            results/<skill>/<timestamp>/report.md
        """
        d = self._run_dir(run_result.skill, run_result.timestamp)

        json_path = d / "run.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(run_result.to_dict(), f, indent=2, default=str)
        logger.info("JSON report written: %s", json_path)

        md_path = d / "report.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(self._build_markdown(run_result))
        logger.info("Markdown report written: %s", md_path)

        return d

    def write_checkpoint(
        self, run_result: RunResult, model: str, model_result: ModelResult
    ) -> Path:
        """
        Write a per-model checkpoint JSON during the run.

        Creates:
            results/<skill>/<timestamp>/<model>.json
        """
        d = self._run_dir(run_result.skill, run_result.timestamp)
        checkpoint_path = d / f"{model}.json"

        import dataclasses
        from tests.model_comparison.framework.types import Recommendation, RunStatus
        from enum import Enum

        def _convert(obj):
            if isinstance(obj, Enum):
                return obj.value
            if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
                return {k: _convert(v) for k, v in dataclasses.asdict(obj).items()}
            if isinstance(obj, dict):
                return {k: _convert(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_convert(i) for i in obj]
            return obj

        with open(checkpoint_path, "w", encoding="utf-8") as f:
            json.dump(_convert(model_result), f, indent=2, default=str)
        logger.info("  Checkpoint written: %s", checkpoint_path)
        return checkpoint_path

    def _build_markdown(self, run_result: RunResult) -> str:
        """Build the full Markdown report string."""
        skill = run_result.skill
        timestamp = run_result.timestamp
        lines = [
            f"# Model Comparison Report: `{skill}` skill",
            f"Generated: {timestamp}",
            "",
            "## Summary",
            "",
            "| Model | Overall Score | Recommendation |",
            "|-------|--------------|----------------|",
        ]

        for model, mr in run_result.model_results.items():
            lines.append(
                f"| `{model}` | {mr.aggregate_score} | **{mr.recommendation.value}**"
                f" — {mr.recommendation_reason} |"
            )

        lines += ["", "---", ""]

        for model, mr in run_result.model_results.items():
            lines += [f"## Model: `{model}`", ""]
            lines += [
                f"**Overall score**: {mr.aggregate_score} / 100",
                f"**Recommendation**: **{mr.recommendation.value}**",
                f"**Reason**: {mr.recommendation_reason}",
                "",
            ]

            if mr.critical_failures:
                lines += [
                    f"**Critical failures**: {', '.join(mr.critical_failures)}",
                    "",
                ]

            for sr in mr.scenario_results:
                scenario_name = sr.scenario.name
                session = sr.session
                lines += [f"### Scenario: `{scenario_name}`", ""]

                if session.error:
                    lines += [f"**ERROR**: {session.error}", ""]
                    continue

                lines += [
                    f"- Turns: {session.turn_count}",
                    f"- Tokens in/out: {session.input_tokens} / {session.output_tokens}",
                    f"- Tool calls: {len(session.tool_calls)}",
                    "",
                ]

                if sr.scenario.scored and sr.score is not None:
                    score = sr.score
                    lines += [
                        f"**Score**: {score.total} / 100  |  "
                        f"{'PASS' if score.passed else 'FAIL'}",
                        "",
                        "| Criterion | Weight | Earned | Note |",
                        "|-----------|--------|--------|------|",
                    ]
                    for k, cr in score.criteria.items():
                        lines.append(
                            f"| {k} | {cr.weight} | {cr.earned} | {cr.note} |"
                        )
                    lines.append("")
                else:
                    lines += ["*Scenario not scored — human review only.*", ""]

                # Tool calls summary
                if session.tool_calls:
                    lines += ["**Tool calls**:", ""]
                    for i, tc in enumerate(session.tool_calls, 1):
                        lines += [
                            f"{i}. **{tc['name']}**: `{self._shorten(tc['input'], 120)}`",
                            f"   Output: {self._shorten(tc['output'], 200)}",
                            "",
                        ]

                # Final text — tilde fences so backtick sequences cannot close the block.
                lines += [
                    "**Final text** (truncated to 800 chars):",
                    "~~~",
                    self._shorten(session.final_text or "(none)"),
                    "~~~",
                    "",
                ]

            lines += ["---", ""]

        # Side-by-side happy path comparison
        lines += ["## Side-by-Side: Happy Path Final Text", ""]
        for model, mr in run_result.model_results.items():
            happy = next(
                (sr for sr in mr.scenario_results if sr.scenario.name == "happy_path"),
                None,
            )
            if happy:
                lines += [
                    f"### `{model}`",
                    "~~~",
                    self._shorten(happy.session.final_text or "(none)", 1200),
                    "~~~",
                    "",
                ]

        return "\n".join(lines)

    @staticmethod
    def _shorten(text: str, max_chars: int = 800) -> str:
        """
        Truncate long text for the markdown report.

        Note: the result may contain triple-backtick sequences. Callers that
        embed this output inside a markdown code block should use tilde fences
        (~~~) rather than backtick fences so the content cannot close the block
        prematurely.
        """
        if len(text) <= max_chars:
            return text
        half = max_chars // 2
        return text[:half] + "\n\n...[truncated]...\n\n" + text[-half:]
