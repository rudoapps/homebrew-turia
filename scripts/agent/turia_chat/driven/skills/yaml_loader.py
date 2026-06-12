"""Load skills from local YAML files."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List

from ...domain.entities.skill import Skill

logger = logging.getLogger(__name__)

_REQUIRED_FIELDS = ("name", "display_name", "description", "prompt_template")


def load_skills_from_directory(directory: Path, source: str) -> List[Skill]:
    """Parse all .yaml/.yml files in a directory into Skill objects.

    Args:
        directory: Path to scan for skill YAML files.
        source: Origin label ("project" or "user").

    Returns:
        List of valid Skill objects. Invalid files are skipped with a warning.
    """
    if not directory.is_dir():
        return []

    try:
        import yaml
    except ImportError:
        logger.debug("PyYAML not installed — local skills disabled")
        return []

    skills: List[Skill] = []

    for path in sorted(directory.glob("*.y*ml")):
        if path.suffix not in (".yaml", ".yml"):
            continue
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                continue

            # Validate required fields
            missing = [f for f in _REQUIRED_FIELDS if not raw.get(f)]
            if missing:
                logger.warning("Skill %s missing fields: %s", path.name, missing)
                continue

            skills.append(Skill(
                name=str(raw["name"]),
                display_name=str(raw["display_name"]),
                description=str(raw["description"]),
                prompt_template=str(raw["prompt_template"]),
                source=source,
                system_prompt_addition=raw.get("system_prompt_addition"),
                allowed_tools=raw.get("allowed_tools"),
                icon=str(raw.get("icon", "")),
                category=str(raw.get("category", "general")),
            ))
        except Exception as exc:
            logger.warning("Failed to load skill %s: %s", path.name, exc)

    return skills
