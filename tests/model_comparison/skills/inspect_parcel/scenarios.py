"""
Test scenarios for the inspect-parcel skill comparison.
"""

from tests.model_comparison.framework.types import Scenario

SCENARIOS: list[Scenario] = [
    Scenario(
        name="happy_path",
        arguments="23026006 Alcova Heights",
        description="Primary happy path — inspect known parcel with neighborhood calibration",
        scored=True,
        max_turns=4,
    ),
    Scenario(
        name="parcel_only",
        arguments="23026006",
        description="Parcel without neighborhood — should use fallback rate and produce full trace",
        scored=True,
        max_turns=4,
    ),
    Scenario(
        name="nonexistent_parcel",
        arguments="00000000",
        description="Unknown parcel ID — should call script and report error gracefully",
        scored=True,
        max_turns=4,
    ),
    Scenario(
        name="empty_args",
        arguments="",
        description="Empty args — should explain required parcel ID argument",
        scored=True,
        max_turns=4,
    ),
]
