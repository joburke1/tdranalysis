"""
compare_models_inspect_parcel.py — Entry point for inspect-parcel model comparison.

Runs all inspect-parcel scenarios against both Sonnet and Haiku,
scores the results, and writes a JSON + Markdown report.

Uses the `claude` CLI (must be on PATH) with the user's existing Pro
credentials — no ANTHROPIC_API_KEY required.

Usage:
    python tests/model_comparison/compare_models_inspect_parcel.py

Guard: this file is not importable as a test module (no test_ prefix, no
pytest markers), but also has an explicit __name__ == "__main__" guard to
prevent accidental collection.
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Make sure project root is on the path when run directly.
PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from tests.model_comparison.scenarios_inspect_parcel import SCENARIOS  # noqa: E402
from tests.model_comparison.scoring_inspect_parcel import (  # noqa: E402
    aggregate_scores,
    score_session,
)
from tests.model_comparison.skill_runner import run_skill  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

HAIKU_MODEL = "haiku"
MODELS = [
    "sonnet",
    HAIKU_MODEL,
]

RESULTS_DIR = Path(__file__).parent / "results"
SKILL_NAME = "inspect-parcel"


def _shorten(text: str, max_chars: int = 800) -> str:
    """
    Truncate long text for the markdown report.

    Uses tilde-fenced blocks at call sites to avoid backtick conflicts.
    """
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    return text[:half] + "\n\n...[truncated]...\n\n" + text[-half:]


def _build_markdown_report(
    all_results: dict[str, dict[str, Any]], timestamp: str
) -> str:
    """Build a human-readable scored markdown report."""
    lines = [
        f"# Model Comparison Report: `{SKILL_NAME}` skill",
        f"Generated: {timestamp}",
        "",
        "## Summary",
        "",
        "| Model | Overall Score | Recommendation |",
        "|-------|--------------|----------------|",
    ]

    for model, data in all_results.items():
        agg = data["aggregate"]
        lines.append(
            f"| `{model}` | {agg['overall']} | **{agg['recommendation']}**"
            f" — {agg.get('reason', '')} |"
        )

    lines += ["", "---", ""]

    for model, data in all_results.items():
        lines += [f"## Model: `{model}`", ""]
        agg = data["aggregate"]
        lines += [
            f"**Overall score**: {agg['overall']} / 100",
            f"**Recommendation**: **{agg['recommendation']}**",
            f"**Reason**: {agg.get('reason', '')}",
            "",
        ]

        if agg.get("critical_failures"):
            lines += [
                f"**Critical failures**: {', '.join(agg['critical_failures'])}",
                "",
            ]

        for scenario_result in data["scenarios"]:
            scenario_name = scenario_result["scenario"]
            session = scenario_result["session"]
            scored_flag = scenario_result["scored"]

            lines += [f"### Scenario: `{scenario_name}`", ""]
            if session.get("error"):
                lines += [f"**ERROR**: {session['error']}", ""]
                continue

            lines += [
                f"- Turns: {session['turn_count']}",
                f"- Tokens in/out: {session['input_tokens']} / {session['output_tokens']}",
                f"- Tool calls: {len(session['tool_calls'])}",
                "",
            ]

            if scored_flag:
                score = scenario_result["score"]
                lines += [
                    f"**Score**: {score['total']} / 100  |  "
                    f"{'PASS' if score['passed'] else 'FAIL'}",
                    "",
                    "| Criterion | Weight | Earned | Note |",
                    "|-----------|--------|--------|------|",
                ]
                for k, v in score["criteria"].items():
                    lines.append(
                        f"| {k} | {v['weight']} | {v['earned']} | {v['note']} |"
                    )
                lines.append("")
            else:
                lines += ["*Scenario not scored — human review only.*", ""]

            # Tool calls summary
            if session["tool_calls"]:
                lines += ["**Tool calls**:", ""]
                for i, tc in enumerate(session["tool_calls"], 1):
                    lines += [
                        f"{i}. **{tc['name']}**: `{_shorten(tc['input'], 120)}`",
                        f"   Output: {_shorten(tc['output'], 200)}",
                        "",
                    ]

            lines += [
                "**Final text** (truncated to 800 chars):",
                "~~~",
                _shorten(session.get("final_text", "(none)")),
                "~~~",
                "",
            ]

        lines += ["---", ""]

    # Side-by-side happy path comparison
    lines += ["## Side-by-Side: Happy Path Final Text", ""]
    for model, data in all_results.items():
        happy = next(
            (s for s in data["scenarios"] if s["scenario"] == "happy_path"), None
        )
        if happy:
            lines += [
                f"### `{model}`",
                "~~~",
                _shorten(happy["session"].get("final_text", "(none)"), 1200),
                "~~~",
                "",
            ]

    return "\n".join(lines)


def main() -> None:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    logger.info("Starting model comparison at %s", timestamp)
    logger.info("Skill: %s", SKILL_NAME)
    logger.info("Models: %s", MODELS)
    logger.info("Scenarios: %s", [s["name"] for s in SCENARIOS])

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    all_results: dict[str, dict[str, Any]] = {}

    for model in MODELS:
        logger.info("=" * 60)
        logger.info("Model: %s", model)
        logger.info("=" * 60)
        model_scenarios = []

        for scenario in SCENARIOS:
            name = scenario["name"]
            args = scenario["arguments"]
            scored = scenario["scored"]
            logger.info("  Running scenario: %r (args=%r) ...", name, args)

            session = run_skill(
                skill_name=SKILL_NAME,
                arguments=args,
                model=model,
            )

            logger.info(
                "  Done. Turns=%d, Tokens=%d, Error=%s",
                session["turn_count"],
                session["input_tokens"] + session["output_tokens"],
                session.get("error"),
            )

            result: dict[str, Any] = {
                "scenario": name,
                "scored": scored,
                "session": session,
            }

            if scored:
                if session.get("error"):
                    result["score"] = {
                        "scenario": name,
                        "total": 0,
                        "criteria": {},
                        "passed": False,
                        "critical_failures": ["session_error"],
                    }
                else:
                    result["score"] = score_session(session, name)
                total = result["score"]["total"]
                passed = result["score"]["passed"]
                logger.info(
                    "    Score: %s/100  %s", total, "PASS" if passed else "FAIL"
                )
                if result["score"]["critical_failures"]:
                    logger.info(
                        "    Critical failures: %s",
                        result["score"]["critical_failures"],
                    )
            else:
                result["score"] = None

            model_scenarios.append(result)

        # Build aggregate (only scored scenarios).
        scored_scenarios = [s for s in model_scenarios if s["scored"]]
        aggregate = aggregate_scores(scored_scenarios)
        all_results[model] = {
            "scenarios": model_scenarios,
            "aggregate": aggregate,
        }

        logger.info(
            "  >> %s AGGREGATE: %s/100 — %s",
            model,
            aggregate["overall"],
            aggregate["recommendation"],
        )

        # Checkpoint: write per-model JSON immediately
        checkpoint_path = (
            RESULTS_DIR / f"comparison_inspect_parcel_{timestamp}_{model}.json"
        )
        with open(checkpoint_path, "w", encoding="utf-8") as f:
            json.dump(all_results[model], f, indent=2, default=str)
        logger.info("  Checkpoint written: %s", checkpoint_path)

    # Write combined JSON and Markdown reports.
    json_path = RESULTS_DIR / f"comparison_inspect_parcel_{timestamp}.json"
    md_path = RESULTS_DIR / f"comparison_inspect_parcel_{timestamp}.md"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, default=str)
    logger.info("JSON report written: %s", json_path)

    md_content = _build_markdown_report(all_results, timestamp)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    logger.info("Markdown report written: %s", md_path)

    # Final recommendations
    logger.info("=" * 60)
    logger.info("FINAL RECOMMENDATIONS")
    logger.info("=" * 60)
    for model, data in all_results.items():
        agg = data["aggregate"]
        logger.info(
            "  %s: %s (score=%s) — %s",
            model,
            agg["recommendation"],
            agg["overall"],
            agg.get("reason", ""),
        )

    haiku_agg = all_results.get(HAIKU_MODEL, {}).get("aggregate", {})
    rec = haiku_agg.get("recommendation", "FAIL")
    if rec == "PASS":
        logger.info(
            "ACTION: Haiku PASSED. "
            "Consider adding 'model: claude-haiku-latest' frontmatter to "
            ".claude/commands/inspect-parcel.md (verify frontmatter support first)."
        )
    elif rec == "CONDITIONAL":
        logger.info(
            "ACTION: Haiku CONDITIONAL. "
            "Review degraded criteria in the markdown report and tighten skill instructions."
        )
    else:
        logger.info(
            "ACTION: Haiku FAILED. "
            "Review critical failures in the markdown report. "
            "If path or calc_trace criterion failed, Haiku is not suitable for this skill."
        )


if __name__ == "__main__":
    main()
