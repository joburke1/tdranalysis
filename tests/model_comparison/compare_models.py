"""
compare_models.py — Entry point for model comparison test.

Runs all run-pipeline scenarios against both Sonnet and Haiku,
scores the results, and writes a JSON + Markdown report.

Usage:
    ANTHROPIC_API_KEY=sk-... python tests/model_comparison/compare_models.py

Guard: this file is not importable as a test module (no test_ prefix, no
pytest markers), but also has an explicit __name__ == "__main__" guard to
prevent accidental collection.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Make sure project root is on the path when run directly
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tests.model_comparison.scenarios_run_pipeline import SCENARIOS
from tests.model_comparison.scoring import aggregate_scores, score_session
from tests.model_comparison.skill_runner import run_skill

MODELS = [
    "claude-sonnet-latest",
    "claude-haiku-latest",
]

RESULTS_DIR = Path(__file__).parent / "results"
SKILL_NAME = "run-pipeline"


def _shorten(text: str, max_chars: int = 800) -> str:
    """Truncate long text for the markdown report."""
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    return text[:half] + "\n\n...[truncated]...\n\n" + text[-half:]


def _build_markdown_report(all_results: dict[str, dict[str, Any]], timestamp: str) -> str:
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
            f"| `{model}` | {agg['overall']} | **{agg['recommendation']}** — {agg.get('reason', '')} |"
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

            # Final text
            lines += [
                "**Final text** (truncated to 800 chars):",
                "```",
                _shorten(session.get("final_text", "(none)")),
                "```",
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
                "```",
                _shorten(happy["session"].get("final_text", "(none)"), 1200),
                "```",
                "",
            ]

    return "\n".join(lines)


def main() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY environment variable not set.")
        sys.exit(1)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"Starting model comparison at {timestamp}")
    print(f"Skill: {SKILL_NAME}")
    print(f"Models: {MODELS}")
    print(f"Scenarios: {[s['name'] for s in SCENARIOS]}")
    print()

    all_results: dict[str, dict[str, Any]] = {}

    for model in MODELS:
        print(f"\n{'='*60}")
        print(f"Model: {model}")
        print(f"{'='*60}")
        model_scenarios = []

        for scenario in SCENARIOS:
            name = scenario["name"]
            args = scenario["arguments"]
            scored = scenario["scored"]
            print(f"  Running scenario: {name!r} (args={args!r}) ...", end=" ", flush=True)

            session = run_skill(
                skill_name=SKILL_NAME,
                arguments=args,
                model=model,
                api_key=api_key,
            )

            print(
                f"done. Turns={session['turn_count']}, "
                f"Tokens={session['input_tokens']+session['output_tokens']}, "
                f"Error={session.get('error')}"
            )

            result = {
                "scenario": name,
                "scored": scored,
                "session": session,
            }

            if scored:
                result["score"] = score_session(session, name)
                total = result["score"]["total"]
                passed = result["score"]["passed"]
                print(f"    Score: {total}/100  {'PASS' if passed else 'FAIL'}")
                if result["score"]["critical_failures"]:
                    print(f"    Critical failures: {result['score']['critical_failures']}")
            else:
                result["score"] = None

            model_scenarios.append(result)

        # Build aggregate (only scored scenarios)
        scored_scenarios = [s for s in model_scenarios if s["scored"]]
        aggregate = aggregate_scores(scored_scenarios)
        all_results[model] = {
            "scenarios": model_scenarios,
            "aggregate": aggregate,
        }

        print(f"\n  >> {model} AGGREGATE: {aggregate['overall']}/100 — {aggregate['recommendation']}")

    # Write JSON
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = RESULTS_DIR / f"comparison_{timestamp}.json"
    md_path = RESULTS_DIR / f"comparison_{timestamp}.md"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\nJSON report written: {json_path}")

    md_content = _build_markdown_report(all_results, timestamp)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    print(f"Markdown report written: {md_path}")

    # Print final recommendations
    print("\n" + "=" * 60)
    print("FINAL RECOMMENDATIONS")
    print("=" * 60)
    for model, data in all_results.items():
        agg = data["aggregate"]
        print(f"  {model}: {agg['recommendation']} (score={agg['overall']}) — {agg.get('reason', '')}")

    haiku_model = next((m for m in MODELS if "haiku" in m), None)
    haiku_agg = all_results.get(haiku_model or "", {}).get("aggregate", {})
    rec = haiku_agg.get("recommendation", "FAIL")
    print()
    if rec == "PASS":
        print(
            f"ACTION: Haiku PASSED ({haiku_model}). "
            "Consider adding 'model: claude-haiku-latest' frontmatter to "
            ".claude/commands/run-pipeline.md (verify frontmatter support first)."
        )
    elif rec == "CONDITIONAL":
        print(
            "ACTION: Haiku CONDITIONAL. "
            "Review degraded criteria in the markdown report and tighten skill instructions."
        )
    else:
        print(
            "ACTION: Haiku FAILED. "
            "Review critical failures in the markdown report. "
            "If path criterion failed, Haiku is not suitable for this skill."
        )


if __name__ == "__main__":
    main()
