"""
Test scenarios for the run-pipeline skill comparison.

Each scenario is a dict with:
  - name: short identifier
  - arguments: substituted for $ARGUMENTS in the skill
  - description: human-readable purpose
  - scored: whether the rubric is applied (False = human-review only)
"""

SCENARIOS: list[dict] = [
    {
        "name": "happy_path",
        "arguments": "Alcova Heights",
        "description": "Primary happy path — runs Alcova Heights neighborhood analysis",
        "scored": True,
    },
    {
        "name": "nonexistent_neighborhood",
        "arguments": "Nonexistent Neighborhood XYZ",
        "description": "Error handling — neighborhood does not exist in data",
        "scored": True,
    },
    {
        "name": "list_neighborhoods",
        "arguments": "--list",
        "description": "List available neighborhoods",
        "scored": True,
    },
    {
        "name": "empty_args",
        "arguments": "",
        "description": "Empty args — should explain usage / show help",
        "scored": True,
    },
    {
        "name": "lowercase_neighborhood",
        "arguments": "alcova heights",
        "description": "Lowercase neighborhood name — human-review only, no pass/fail",
        "scored": False,
    },
]
