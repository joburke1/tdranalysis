"""
Test scenarios for the inspect-parcel skill comparison.

Each scenario is a dict with:
  - name: short identifier
  - arguments: substituted for $ARGUMENTS in the skill
  - description: human-readable purpose
  - scored: whether the rubric is applied (False = human-review only)
"""

from typing import TypedDict


class Scenario(TypedDict):
    name: str
    arguments: str
    description: str
    scored: bool


SCENARIOS: list[Scenario] = [
    {
        "name": "happy_path",
        "arguments": "23026006 Alcova Heights",
        "description": "Primary happy path — inspect known parcel with neighborhood calibration",
        "scored": True,
    },
    {
        "name": "parcel_only",
        "arguments": "23026006",
        "description": "Parcel without neighborhood — should use fallback rate and still produce full trace",
        "scored": True,
    },
    {
        "name": "nonexistent_parcel",
        "arguments": "00000000",
        "description": "Unknown parcel ID — should call script and report error gracefully",
        "scored": True,
    },
    {
        "name": "empty_args",
        "arguments": "",
        "description": "Empty args — should explain required parcel ID argument",
        "scored": True,
    },
]
