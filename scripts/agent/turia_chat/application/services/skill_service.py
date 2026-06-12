"""Skill service — loads, merges, and resolves skills from multiple sources."""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

from ..ports.driven.api_client_port import ApiClientPort
from .auth_service import AuthService
from ...domain.entities.skill import Skill, SkillResolution

logger = logging.getLogger(__name__)


class SkillService:
    """Manages the lifecycle of skills: load, merge, resolve.

    Skills are loaded from three sources (highest priority first):
      1. Project-local:  .turia/skills/*.yaml
      2. User-global:    ~/.config/turia-agent/skills/*.yaml
      3. Backend:        GET /agent/skills

    Duplicate names are resolved by priority — project overrides user
    overrides backend.
    """

    def __init__(
        self,
        auth_service: AuthService,
        api_client: ApiClientPort,
    ) -> None:
        self._auth_service = auth_service
        self._api_client = api_client
        self._skills: Dict[str, Skill] = {}

    async def reload(self) -> None:
        """Discard loaded skills and reload from all sources."""
        self._skills.clear()
        await self.load_skills()

    async def load_skills(self) -> None:
        """Load and merge skills from all sources."""
        from ...driven.skills.yaml_loader import load_skills_from_directory
        from ...driven.skills.markdown_loader import load_skills_from_markdown

        # 1. Backend skills (lowest priority — loaded first, overwritten later)
        backend = await self._fetch_backend_skills()
        for s in backend:
            self._register(s)

        # 2. User-global skills (YAML + SKILL.md folders)
        user_dir = Path.home() / ".config" / "turia-agent" / "skills"
        for s in load_skills_from_directory(user_dir, source="user"):
            self._register(s)
        for s in load_skills_from_markdown(user_dir, source="user"):
            self._register(s)

        # 3. Project-local skills (highest priority)
        project_dir = Path.cwd() / ".turia" / "skills"
        for s in load_skills_from_directory(project_dir, source="project"):
            self._register(s)
        for s in load_skills_from_markdown(project_dir, source="project"):
            self._register(s)

    def _register(self, skill: Skill) -> None:
        """Store a skill under both `pack:name` and bare `name` (last wins)."""
        if skill.pack:
            self._skills[f"{skill.pack}:{skill.name}"] = skill
        self._skills[skill.name] = skill

    def get_skill(self, name: str) -> Optional[Skill]:
        """Get a skill by name."""
        return self._skills.get(name)

    def list_skills(self) -> List[Skill]:
        """Return all loaded skills sorted by category then name (de-duplicated)."""
        seen: Dict[int, Skill] = {id(s): s for s in self._skills.values()}
        return sorted(seen.values(), key=lambda s: (s.category, s.pack or "", s.name))

    def get_auto_skill_for_project(self, project_type: str) -> Optional[Skill]:
        """Find the skill that auto-applies for a project type."""
        if not project_type:
            return None
        for skill in self._skills.values():
            if skill.auto_apply_project_type and (
                skill.auto_apply_project_type == project_type
                or project_type.startswith(skill.auto_apply_project_type + "/")
                or project_type.startswith(skill.auto_apply_project_type)
            ):
                return skill
        return None

    def resolve(self, name: str, args: str) -> Optional[SkillResolution]:
        """Resolve a skill invocation into an expanded prompt.

        Args:
            name: Skill slug.
            args: User-provided arguments (replaces {input} in the template).

        Returns:
            SkillResolution with the expanded prompt, or None if not found.
        """
        skill = self._skills.get(name)
        if not skill:
            return None

        template = skill.prompt_template
        if skill.path is not None:
            skill_dir = str(skill.path)
            template = template.replace("${CLAUDE_SKILL_DIR}", skill_dir)
            template = template.replace("${TURIA_SKILL_DIR}", skill_dir)

        # Use format_map with a defaultdict to handle missing placeholders
        placeholders = defaultdict(str, input=args.strip())
        try:
            expanded = template.format_map(placeholders)
        except (KeyError, ValueError):
            expanded = template.replace("{input}", args.strip())

        return SkillResolution(
            expanded_prompt=expanded,
            system_prompt_addition=skill.system_prompt_addition,
            allowed_tools=skill.allowed_tools,
        )

    async def _fetch_backend_skills(self) -> List[Skill]:
        """Fetch skills from the backend API. Returns [] on failure."""
        try:
            config = await self._auth_service.ensure_valid_token()
            data = await self._api_client.get_skills(
                api_url=config.api_url,
                access_token=config.access_token,
            )
            skills_raw = data.get("skills", [])
            return [
                Skill(
                    name=s["name"],
                    display_name=s.get("display_name", s["name"]),
                    description=s.get("description", ""),
                    prompt_template=s.get("prompt_template", "{input}"),
                    source="backend",
                    system_prompt_addition=s.get("system_prompt_addition"),
                    allowed_tools=s.get("allowed_tools"),
                    icon=s.get("icon", ""),
                    category=s.get("category", "general"),
                    auto_apply_project_type=s.get("auto_apply_project_type", ""),
                )
                for s in skills_raw
                if "name" in s
            ]
        except Exception as exc:
            logger.debug("Could not fetch backend skills: %s", exc)
            return []
