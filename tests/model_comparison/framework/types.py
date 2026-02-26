"""
Shared data structures for the model comparison framework.

All types are dataclasses for runtime validation and IDE support.
RunResult.to_dict() produces a JSON-serializable representation.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RunStatus(Enum):
    """Outcome classification for a single CLI invocation."""

    SUCCESS = "success"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    ERROR = "error"


class Recommendation(Enum):
    """Aggregate recommendation for a model on a skill."""

    PASS = "PASS"
    CONDITIONAL = "CONDITIONAL"
    FAIL = "FAIL"


@dataclass
class Scenario:
    """A single test scenario for a skill."""

    name: str
    arguments: str
    description: str
    scored: bool = True
    max_turns: int = 4


@dataclass
class CriterionResult:
    """Result of evaluating a single scoring criterion."""

    name: str
    weight: float
    earned: float
    note: str
    is_critical: bool = False


@dataclass
class ScenarioScore:
    """Scored result for one scenario."""

    scenario_name: str
    total: float  # 0–100
    criteria: dict[str, CriterionResult]
    passed: bool
    critical_failures: list[str]


@dataclass
class SessionResult:
    """Raw output from running a skill via the CLI."""

    model: str
    skill: str
    arguments: str
    tool_calls: list[dict[str, Any]]
    final_text: str
    input_tokens: int
    output_tokens: int
    turn_count: int
    error: str | None
    status: RunStatus


@dataclass
class ScenarioResult:
    """Combined session + score for one scenario on one model."""

    scenario: Scenario
    session: SessionResult
    score: ScenarioScore | None  # None if scenario.scored is False or session errored


@dataclass
class ModelResult:
    """All scenario results for one model on one skill."""

    model: str
    skill: str
    scenario_results: list[ScenarioResult]
    aggregate_score: float
    recommendation: Recommendation
    recommendation_reason: str
    critical_failures: list[str]


@dataclass
class RunResult:
    """Complete result of a comparison run (all models, one skill)."""

    skill: str
    timestamp: str
    models: list[str]
    model_results: dict[str, ModelResult] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict (uses dataclasses.asdict with enum coercion)."""

        def _convert(obj: Any) -> Any:
            if isinstance(obj, Enum):
                return obj.value
            if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
                return {k: _convert(v) for k, v in dataclasses.asdict(obj).items()}
            if isinstance(obj, dict):
                return {k: _convert(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_convert(i) for i in obj]
            return obj

        return _convert(self)
