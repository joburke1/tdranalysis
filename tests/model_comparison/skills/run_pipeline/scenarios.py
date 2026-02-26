"""
Test scenarios for the run-pipeline skill comparison.
"""

from tests.model_comparison.framework.types import Scenario

SCENARIOS: list[Scenario] = [
    Scenario(
        name="happy_path",
        arguments="Alcova Heights",
        description="Primary happy path — runs Alcova Heights neighborhood analysis",
        scored=True,
        max_turns=4,
    ),
    Scenario(
        name="nonexistent_neighborhood",
        arguments="Nonexistent Neighborhood XYZ",
        description="Error handling — neighborhood does not exist in data",
        scored=True,
        max_turns=4,
    ),
    Scenario(
        name="list_neighborhoods",
        arguments="--list",
        description="List available neighborhoods",
        scored=True,
        max_turns=4,
    ),
    Scenario(
        name="empty_args",
        arguments="",
        description="Empty args — should explain usage / show help",
        scored=True,
        max_turns=4,
    ),
    Scenario(
        name="lowercase_neighborhood",
        arguments="alcova heights",
        description="Lowercase neighborhood name — human-review only, no pass/fail",
        scored=False,
        max_turns=4,
    ),
]
