"""
Orchestrator: coordinates running scenarios across models.

Responsibilities:
- Iterates models × scenarios sequentially (never parallel)
- Delegates execution to SkillRunner
- Delegates scoring to BaseScorer.score_or_error()
- Detects rate limiting and short-circuits remaining scenarios for that model
- Delegates checkpoint writing to ReportBuilder after each model completes
- Supports filtering to specific models/scenarios for selective re-runs
"""

from __future__ import annotations

import logging
from pathlib import Path

from tests.model_comparison.framework.runner import SkillRunner
from tests.model_comparison.framework.scorer import BaseScorer
from tests.model_comparison.framework.types import (
    ModelResult,
    Recommendation,
    RunResult,
    RunStatus,
    Scenario,
    ScenarioResult,
)

logger = logging.getLogger(__name__)


class Orchestrator:
    """
    Runs all scenarios for all models for one skill.

    Usage:
        runner = SkillRunner(project_root)
        orch = Orchestrator(runner, scorer, "run-pipeline", scenarios, ["sonnet", "haiku"])
        run_result = orch.run()
    """

    def __init__(
        self,
        runner: SkillRunner,
        scorer: BaseScorer,
        skill_name: str,
        scenarios: list[Scenario],
        models: list[str],
        report_builder: "ReportBuilder | None" = None,  # type: ignore[name-defined]  # noqa: F821
    ) -> None:
        self._runner = runner
        self._scorer = scorer
        self._skill_name = skill_name
        self._scenarios = scenarios
        self._models = models
        self._report_builder = report_builder

    def run(
        self,
        filter_models: list[str] | None = None,
        filter_scenarios: list[str] | None = None,
        timestamp: str | None = None,
    ) -> RunResult:
        """
        Execute the full comparison run.

        Args:
            filter_models:    If provided, only run these models.
            filter_scenarios: If provided, only run scenarios whose name is in this list.
            timestamp:        If provided, use this timestamp for the run directory name.
                              Pass from run.py so the log file can be created before the run.

        Returns:
            RunResult with all model results populated.
        """
        import datetime

        if timestamp is None:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        effective_models = filter_models or self._models
        effective_scenarios = (
            [s for s in self._scenarios if s.name in filter_scenarios]
            if filter_scenarios
            else self._scenarios
        )

        logger.info("=" * 60)
        logger.info("Skill: %s", self._skill_name)
        logger.info("Models: %s", effective_models)
        logger.info("Scenarios: %s", [s.name for s in effective_scenarios])
        logger.info("=" * 60)

        run_result = RunResult(
            skill=self._skill_name,
            timestamp=timestamp,
            models=effective_models,
        )

        for model in effective_models:
            logger.info("Model: %s", model)
            model_result = self._run_model(model, effective_scenarios, run_result)
            run_result.model_results[model] = model_result

            logger.info(
                "  >> %s AGGREGATE: %.1f/100 — %s",
                model,
                model_result.aggregate_score,
                model_result.recommendation.value,
            )

            # Write per-model checkpoint immediately so results are not lost
            # if a subsequent model run fails or times out.
            if self._report_builder is not None:
                self._report_builder.write_checkpoint(run_result, model, model_result)

        return run_result

    def _run_model(
        self,
        model: str,
        scenarios: list[Scenario],
        run_result: RunResult,
    ) -> ModelResult:
        """Run all scenarios for a single model, with rate-limit short-circuit."""
        scenario_results: list[ScenarioResult] = []
        rate_limited = False

        for scenario in scenarios:
            if rate_limited:
                # Short-circuit: skip remaining scenarios for this model.
                # Record as a skipped (unscored) result so the report is complete.
                logger.warning(
                    "  SKIP scenario %r (rate limit active for %s)", scenario.name, model
                )
                continue

            result = self._run_scenario(model, scenario)
            scenario_results.append(result)

            if result.session.status == RunStatus.RATE_LIMITED:
                logger.warning(
                    "  Rate limit detected for model %s — skipping remaining scenarios",
                    model,
                )
                rate_limited = True

        if rate_limited:
            # Model is rate-limited; no meaningful aggregate possible.
            return ModelResult(
                model=model,
                skill=self._skill_name,
                scenario_results=scenario_results,
                aggregate_score=0.0,
                recommendation=Recommendation.FAIL,
                recommendation_reason="rate_limited",
                critical_failures=["rate_limited"],
            )

        # Normal aggregation path.
        overall, rec, reason, critical_failures = self._scorer.aggregate_scores(
            scenario_results
        )
        return ModelResult(
            model=model,
            skill=self._skill_name,
            scenario_results=scenario_results,
            aggregate_score=overall,
            recommendation=rec,
            recommendation_reason=reason,
            critical_failures=critical_failures,
        )

    def _run_scenario(self, model: str, scenario: Scenario) -> ScenarioResult:
        """Run and score a single scenario."""
        logger.info(
            "  Running scenario: %r (args=%r) ...", scenario.name, scenario.arguments
        )

        session = self._runner.run(
            skill_name=self._skill_name,
            arguments=scenario.arguments,
            model=model,
            max_turns=scenario.max_turns,
        )

        logger.info(
            "  Done. Turns=%d, Tokens=%d, Status=%s, Error=%s",
            session.turn_count,
            session.input_tokens + session.output_tokens,
            session.status.value,
            session.error,
        )

        score = None
        if scenario.scored:
            score = self._scorer.score_or_error(session, scenario)
            logger.info(
                "    Score: %.1f/100  %s",
                score.total,
                "PASS" if score.passed else "FAIL",
            )
            if score.critical_failures:
                logger.info("    Critical failures: %s", score.critical_failures)

        return ScenarioResult(scenario=scenario, session=session, score=score)
