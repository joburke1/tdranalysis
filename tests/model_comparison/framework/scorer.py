"""
BaseScorer: abstract base class for skill-specific rubric scorers.

Each skill implements score_session() with its own criteria.
This base class provides:
- aggregate_scores(): mean across scenarios, recommendation derivation (not overridable)
- _c(): criterion result builder
- _bash_commands(), _read_paths(), _all_bash_text(): shared session inspection helpers
- Weight validation in __init__
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from tests.model_comparison.framework.types import (
    CriterionResult,
    ModelResult,
    Recommendation,
    RunStatus,
    Scenario,
    ScenarioResult,
    ScenarioScore,
    SessionResult,
)


class BaseScorer(ABC):
    """
    Abstract base class for skill-specific rubric scorers.

    Subclasses must define:
      WEIGHTS: dict[str, float]   — criterion name → weight; must sum to 100
      MANDATORY_CRITERIA: set[str] — criteria that cause FAIL if earned == 0

    Subclasses must implement:
      score_session(session, scenario) → ScenarioScore
    """

    WEIGHTS: dict[str, float]
    MANDATORY_CRITERIA: set[str]

    PASS_THRESHOLD: float = 75.0
    AGGREGATE_PASS_THRESHOLD: float = 80.0
    CONDITIONAL_THRESHOLD: float = 65.0

    def __init__(self) -> None:
        total = sum(self.WEIGHTS.values())
        if abs(total - 100) > 0.01:
            raise ValueError(
                f"{type(self).__name__}.WEIGHTS sum to {total}, expected 100"
            )
        unknown = self.MANDATORY_CRITERIA - self.WEIGHTS.keys()
        if unknown:
            raise ValueError(
                f"{type(self).__name__}.MANDATORY_CRITERIA references unknown keys: {unknown}"
            )

    @abstractmethod
    def score_session(
        self, session: SessionResult, scenario: Scenario
    ) -> ScenarioScore:
        """
        Score a single session against the skill-specific rubric.

        Args:
            session:  The parsed CLI output.
            scenario: The scenario that was run (for conditional logic).

        Returns:
            ScenarioScore with total (0–100), per-criterion breakdown, pass/fail.
        """
        ...

    def aggregate_scores(
        self, scenario_results: list[ScenarioResult]
    ) -> tuple[float, Recommendation, str, list[str]]:
        """
        Aggregate scores across all scored scenarios.

        This method is final — do not override. All skills use the same
        mean-based aggregation and threshold logic.

        Returns:
            (overall_score, recommendation, reason, all_critical_failures)
        """
        scored = [
            sr for sr in scenario_results if sr.scenario.scored and sr.score is not None
        ]
        if not scored:
            return 0.0, Recommendation.FAIL, "No scored scenarios", []

        totals = [sr.score.total for sr in scored]  # type: ignore[union-attr]
        overall = round(sum(totals) / len(totals), 1)

        all_critical: list[str] = []
        for sr in scored:
            all_critical.extend(sr.score.critical_failures)  # type: ignore[union-attr]

        mandatory_critical = [c for c in all_critical if c in self.MANDATORY_CRITERIA]

        if mandatory_critical:
            rec = Recommendation.FAIL
            reason = f"Critical failures on mandatory criteria: {mandatory_critical}"
        elif overall >= self.AGGREGATE_PASS_THRESHOLD:
            rec = Recommendation.PASS
            reason = (
                f"Overall score {overall} ≥ {self.AGGREGATE_PASS_THRESHOLD}"
                " with no mandatory critical failures"
            )
        elif overall >= self.CONDITIONAL_THRESHOLD:
            rec = Recommendation.CONDITIONAL
            reason = (
                f"Overall score {overall} is {self.CONDITIONAL_THRESHOLD}–"
                f"{self.AGGREGATE_PASS_THRESHOLD - 1}; review degraded criteria"
            )
        else:
            rec = Recommendation.FAIL
            reason = f"Overall score {overall} < {self.CONDITIONAL_THRESHOLD}"

        return overall, rec, reason, all_critical

    # ── Shared helpers ────────────────────────────────────────────────────────

    def _c(self, name: str, earned: float, note: str) -> CriterionResult:
        """Build a CriterionResult for a criterion defined in self.WEIGHTS."""
        weight = self.WEIGHTS[name]
        is_critical = name in self.MANDATORY_CRITERIA and earned == 0
        return CriterionResult(
            name=name,
            weight=weight,
            earned=earned,
            note=note,
            is_critical=is_critical,
        )

    @staticmethod
    def _bash_commands(session: SessionResult) -> list[str]:
        """Return inputs of all Bash tool calls in the session."""
        return [tc["input"] for tc in session.tool_calls if tc["name"] == "Bash"]

    @staticmethod
    def _read_paths(session: SessionResult) -> list[str]:
        """Return inputs of all Read tool calls in the session."""
        return [tc["input"] for tc in session.tool_calls if tc["name"] == "Read"]

    @staticmethod
    def _all_bash_text(session: SessionResult) -> str:
        """Join all Bash command inputs into a single string for pattern matching."""
        return "\n".join(
            tc["input"] for tc in session.tool_calls if tc["name"] == "Bash"
        )

    def _make_error_score(self, scenario_name: str) -> ScenarioScore:
        """
        Return a zero score for a session that errored before scoring could occur.
        All criteria score 0; critical_failures includes 'session_error'.
        """
        criteria = {
            name: CriterionResult(
                name=name, weight=weight, earned=0.0, note="session error", is_critical=False
            )
            for name, weight in self.WEIGHTS.items()
        }
        return ScenarioScore(
            scenario_name=scenario_name,
            total=0.0,
            criteria=criteria,
            passed=False,
            critical_failures=["session_error"],
        )

    def score_or_error(
        self, session: SessionResult, scenario: Scenario
    ) -> ScenarioScore:
        """
        Score a session, returning a zero error score if the session failed.

        This is the entry point used by the Orchestrator — it handles
        ERROR/TIMEOUT/RATE_LIMITED sessions without crashing.
        """
        if session.status in (RunStatus.ERROR, RunStatus.TIMEOUT):
            return self._make_error_score(scenario.name)
        # RATE_LIMITED is handled upstream by the Orchestrator (short-circuit),
        # but guard here just in case.
        if session.status == RunStatus.RATE_LIMITED:
            return self._make_error_score(scenario.name)
        return self.score_session(session, scenario)
