"""
Entry point for the model comparison test framework.

Discovers all registered skills and runs model comparisons, producing
JSON + Markdown reports in tests/model_comparison/results/<skill>/<timestamp>/.

Usage:
    # All skills, all models, all scenarios:
    python tests/model_comparison/run.py

    # One skill:
    python tests/model_comparison/run.py --skill run-pipeline

    # One model only:
    python tests/model_comparison/run.py --skill run-pipeline --model haiku

    # One scenario only:
    python tests/model_comparison/run.py --skill inspect-parcel --scenario happy_path

    # List discovered skills and exit:
    python tests/model_comparison/run.py --list

    # Skip edge-case scenarios (faster/cheaper — happy path only):
    python tests/model_comparison/run.py --fast

    # Override default timeout:
    python tests/model_comparison/run.py --timeout 900
"""

import argparse
import logging
import sys
from pathlib import Path

# Ensure project root is on the path when run directly.
PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from tests.model_comparison.framework.orchestrator import Orchestrator
from tests.model_comparison.framework.registry import SkillRegistry
from tests.model_comparison.framework.report import ReportBuilder
from tests.model_comparison.framework.runner import SkillRunner
from tests.model_comparison.framework.types import Recommendation

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

RESULTS_DIR = Path(__file__).parent / "results"

# Scenario names considered "edge cases" for --fast mode.
_FAST_MODE_SKIP = frozenset({"nonexistent_neighborhood", "nonexistent_parcel", "empty_args"})


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run model comparison tests for TDR Analysis skills.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--skill",
        metavar="NAME",
        help="Run only this skill (default: all discovered skills)",
    )
    parser.add_argument(
        "--model",
        metavar="NAME",
        help="Run only this model (default: skill's configured models)",
    )
    parser.add_argument(
        "--scenario",
        metavar="NAME",
        help="Run only this scenario name (default: all scenarios)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        dest="list_skills",
        help="List available skills and exit",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help=(
            "Skip edge-case scenarios (nonexistent_*, empty_args)."
            " Reduces invocations by ~50%%."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        metavar="SECS",
        help="Override default CLI timeout in seconds (default: 600)",
    )
    return parser.parse_args()


def _haiku_recommendation_message(skill_name: str, rec: Recommendation) -> str:
    """Return an actionable log message for the haiku model recommendation."""
    command_file = f".claude/commands/{skill_name}.md"
    if rec == Recommendation.PASS:
        return (
            f"ACTION: Haiku PASSED. "
            f"Consider adding 'model: claude-haiku-latest' frontmatter to "
            f"{command_file} (verify frontmatter support first)."
        )
    if rec == Recommendation.CONDITIONAL:
        return (
            "ACTION: Haiku CONDITIONAL. "
            "Review degraded criteria in the markdown report and tighten skill instructions."
        )
    # FAIL
    if skill_name == "inspect-parcel":
        detail = "If path or calc_trace criterion failed, Haiku is not suitable for this skill."
    else:
        detail = "If path criterion failed, Haiku is not suitable for this skill."
    return (
        f"ACTION: Haiku FAILED. "
        f"Review critical failures in the markdown report. {detail}"
    )


def main() -> None:
    args = _parse_args()

    registry = SkillRegistry()
    configs = registry.discover()

    if not configs:
        logger.error(
            "No skills discovered. Check tests/model_comparison/skills/ directory."
        )
        sys.exit(1)

    if args.list_skills:
        print("Discovered skills:")
        for cfg in configs:
            print(f"  {cfg.name!r:30s} models={cfg.models}  — {cfg.description}")
            print(f"    scenarios: {[s.name for s in cfg.scenarios]}")
        return

    # Apply --skill filter
    if args.skill:
        try:
            configs = [registry.get(args.skill)]
        except KeyError as e:
            logger.error("%s", e)
            sys.exit(1)

    # Build filter_scenarios from --scenario and/or --fast
    filter_scenarios: list[str] | None = None
    if args.scenario:
        filter_scenarios = [args.scenario]
    elif args.fast:
        # Exclude edge-case scenarios; keep the rest (including unscored ones)
        # by computing the allow-list from the first config's scenarios.
        # We apply this per-skill below.
        pass  # handled in the loop

    for cfg in configs:
        logger.info("=" * 60)
        logger.info("Skill: %s", cfg.name)
        logger.info("=" * 60)

        # Resolve filter_scenarios per skill for --fast mode
        effective_filter = filter_scenarios
        if args.fast and not args.scenario:
            effective_filter = [
                s.name for s in cfg.scenarios if s.name not in _FAST_MODE_SKIP
            ]

        filter_models = [args.model] if args.model else None

        runner = SkillRunner(project_root=PROJECT_ROOT, timeout=args.timeout)
        report_builder = ReportBuilder(results_dir=RESULTS_DIR)
        orchestrator = Orchestrator(
            runner=runner,
            scorer=cfg.scorer,
            skill_name=cfg.name,
            scenarios=cfg.scenarios,
            models=cfg.models,
            report_builder=report_builder,
        )

        run_result = orchestrator.run(
            filter_models=filter_models,
            filter_scenarios=effective_filter,
        )

        run_dir = report_builder.write(run_result)
        logger.info("Reports written to: %s", run_dir)

        # Final recommendations
        logger.info("=" * 60)
        logger.info("FINAL RECOMMENDATIONS: %s", cfg.name)
        logger.info("=" * 60)
        for model, mr in run_result.model_results.items():
            logger.info(
                "  %s: %s (score=%.1f) — %s",
                model,
                mr.recommendation.value,
                mr.aggregate_score,
                mr.recommendation_reason,
            )

        haiku_result = run_result.model_results.get("haiku")
        if haiku_result is not None:
            msg = _haiku_recommendation_message(cfg.name, haiku_result.recommendation)
            logger.info(msg)


if __name__ == "__main__":
    main()
