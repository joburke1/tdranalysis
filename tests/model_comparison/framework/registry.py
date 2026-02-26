"""
SkillRegistry: auto-discovers skill plugins from the skills/ directory.

Discovery convention:
    Each subdirectory of skills/ is a skill package if it contains:
      - skill.toml   — metadata: [skill] name, description, models
      - scenarios.py — exports SCENARIOS: list[Scenario]
      - scorer.py    — exports class Scorer(BaseScorer)

Discovery is triggered by discover(). Skills can also be registered
manually via register() for testing or one-off use.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from tests.model_comparison.framework.scorer import BaseScorer
from tests.model_comparison.framework.types import Scenario

logger = logging.getLogger(__name__)


@dataclass
class SkillConfig:
    """Metadata and components for a registered skill."""

    name: str           # e.g. "run-pipeline"
    package_path: Path  # e.g. tests/model_comparison/skills/run_pipeline/
    scenarios: list[Scenario]
    scorer: BaseScorer
    models: list[str]
    description: str


class SkillRegistry:
    """
    Discovers and loads skill plugin configurations.

    Usage:
        registry = SkillRegistry()
        configs = registry.discover()
        config = registry.get("run-pipeline")
    """

    def __init__(self, skills_dir: Path | None = None) -> None:
        """
        Args:
            skills_dir: Directory to scan for skill packages.
                        Defaults to <this file's parent parent>/skills/
        """
        if skills_dir is None:
            skills_dir = Path(__file__).parent.parent / "skills"
        self._skills_dir = skills_dir
        self._configs: dict[str, SkillConfig] = {}

    def discover(self) -> list[SkillConfig]:
        """
        Scan skills_dir and return all discovered skill configs.

        Skips directories that are missing required files or that fail to import.
        """
        if not self._skills_dir.exists():
            logger.warning("Skills directory does not exist: %s", self._skills_dir)
            return []

        for entry in sorted(self._skills_dir.iterdir()):
            if not entry.is_dir():
                continue
            if entry.name.startswith("_"):
                continue  # skip __pycache__, disabled skills prefixed with _

            toml_path = entry / "skill.toml"
            scenarios_path = entry / "scenarios.py"
            scorer_path = entry / "scorer.py"

            if not (toml_path.exists() and scenarios_path.exists() and scorer_path.exists()):
                logger.debug("Skipping %s — missing required files", entry.name)
                continue

            try:
                config = self._load_skill(entry, toml_path, scenarios_path, scorer_path)
                self._configs[config.name] = config
                logger.debug("Registered skill: %s (%s)", config.name, entry.name)
            except Exception as exc:
                logger.warning("Failed to load skill %r: %s", entry.name, exc)

        return list(self._configs.values())

    def get(self, skill_name: str) -> SkillConfig:
        """
        Get a registered skill by name.

        Raises:
            KeyError: if skill not found (call discover() first).
        """
        if skill_name not in self._configs:
            available = list(self._configs.keys())
            raise KeyError(
                f"Skill {skill_name!r} not found. Available: {available}. "
                "Did you call discover() first?"
            )
        return self._configs[skill_name]

    def register(self, config: SkillConfig) -> None:
        """Manually register a skill config (useful for tests)."""
        self._configs[config.name] = config

    def list_skills(self) -> list[str]:
        """Return names of all registered skills."""
        return list(self._configs.keys())

    @staticmethod
    def _load_skill(
        package_path: Path,
        toml_path: Path,
        scenarios_path: Path,
        scorer_path: Path,
    ) -> SkillConfig:
        """Load a single skill package from disk."""
        # Load metadata from skill.toml
        with open(toml_path, "rb") as f:
            meta = tomllib.load(f)
        skill_meta = meta.get("skill", {})
        name = skill_meta.get("name")
        description = skill_meta.get("description", "")
        models = skill_meta.get("models", ["sonnet"])

        if not name:
            raise ValueError(f"skill.toml missing [skill] name in {package_path}")

        # Import scenarios module
        scenarios_module = _import_module_from_path(
            f"_skill_scenarios_{package_path.name}", scenarios_path
        )
        scenarios: list[Scenario] = scenarios_module.SCENARIOS

        # Import scorer module and instantiate the Scorer class
        scorer_module = _import_module_from_path(
            f"_skill_scorer_{package_path.name}", scorer_path
        )
        scorer: BaseScorer = scorer_module.Scorer()

        return SkillConfig(
            name=name,
            package_path=package_path,
            scenarios=scenarios,
            scorer=scorer,
            models=models,
            description=description,
        )


def _import_module_from_path(module_name: str, path: Path):
    """Dynamically import a module from a file path."""
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot create module spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module
