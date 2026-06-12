"""Skill domain entity."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class Skill:
    """A named prompt template that can be invoked via /skill-name.

    Attributes:
        name: Unique slug identifier (e.g. "write-tests").
        display_name: Human-readable name (e.g. "Write Tests").
        description: Short description shown in /help.
        prompt_template: Template with {input} placeholder.
        source: Origin — "project", "user", or "backend".
        system_prompt_addition: Extra instructions appended to the system prompt.
        allowed_tools: Tool name whitelist. None means all tools allowed.
        icon: Optional emoji/icon for display.
        category: Grouping category (e.g. "testing", "devops").
        path: Filesystem root of the skill when loaded from a folder
            (SKILL.md style). Used to expand ${CLAUDE_SKILL_DIR} /
            ${TURIA_SKILL_DIR} at resolve time so skills can reference
            bundled resources.
        pack: Marketplace pack this skill belongs to (e.g. "angular").
            Enables `pack:skill` namespacing when slugs collide.
    """

    name: str
    display_name: str
    description: str
    prompt_template: str
    source: str = "backend"
    system_prompt_addition: Optional[str] = None
    allowed_tools: Optional[List[str]] = None
    icon: str = ""
    category: str = "general"
    auto_apply_project_type: str = ""
    path: Optional[Path] = None
    pack: Optional[str] = None


@dataclass
class SkillResolution:
    """Result of resolving a skill invocation."""

    expanded_prompt: str
    system_prompt_addition: Optional[str] = None
    allowed_tools: Optional[List[str]] = None
