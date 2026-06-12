"""Load skills from SKILL.md folders (Claude Code marketplace format).

Expected layout under any root:

    <root>/<skill>/SKILL.md                         # flat
    <root>/<pack>/skills/<skill>/SKILL.md           # marketplace-style

A SKILL.md file has optional YAML-like frontmatter between `---` fences,
followed by a markdown body. The body becomes the `prompt_template`.

Frontmatter is parsed as simple `key: value` pairs (first `:` is the
separator, rest of the line is the value). This avoids a hard dependency
on PyYAML and tolerates values containing `:` (common in descriptions
like `Usage: /foo:bar`). Supported keys:

  name, description, display_name, icon, category,
  allowed_tools (JSON array or comma-separated), system_prompt_addition,
  auto_apply_project_type

Hidden directories (starting with `.`) are skipped.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from ...domain.entities.skill import Skill

logger = logging.getLogger(__name__)

_KV_RE = re.compile(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$")


def load_skills_from_markdown(directory: Path, source: str) -> List[Skill]:
    """Parse every SKILL.md under `directory` into Skill objects."""
    if not directory.is_dir():
        return []

    skills: List[Skill] = []

    for skill_md in sorted(_walk_skill_files(directory)):
        if _has_hidden_parent(skill_md, directory):
            continue
        try:
            frontmatter, body = _split_frontmatter(skill_md.read_text(encoding="utf-8"))
            meta = _parse_frontmatter(frontmatter)

            skill_dir = skill_md.parent
            pack = _derive_pack(skill_dir, directory)
            name = (meta.get("name") or skill_dir.name).strip()
            description = (meta.get("description") or "").strip()

            if not name or not body.strip():
                logger.warning("Skipping %s: missing name or body", skill_md)
                continue

            skills.append(Skill(
                name=name,
                display_name=meta.get("display_name") or _humanize(name),
                description=description,
                prompt_template=_retarget_turia(body),
                source=source,
                system_prompt_addition=meta.get("system_prompt_addition"),
                allowed_tools=_parse_list(meta.get("allowed_tools")),
                icon=meta.get("icon", ""),
                category=meta.get("category") or pack or "general",
                auto_apply_project_type=meta.get("auto_apply_project_type", ""),
                path=skill_dir,
                pack=pack,
            ))
        except Exception as exc:
            logger.warning("Failed to load skill %s: %s", skill_md, exc)

    return skills


def _walk_skill_files(root: Path) -> Iterator[Path]:
    """Yield every SKILL.md under `root`, following directory symlinks."""
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        # Don't descend into hidden dirs (e.g. `.codex`, `.git`).
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        if "SKILL.md" in filenames:
            yield Path(dirpath) / "SKILL.md"


def _has_hidden_parent(path: Path, root: Path) -> bool:
    """True if any directory between `root` and `path` starts with a dot."""
    try:
        rel = path.relative_to(root)
    except ValueError:
        return False
    return any(part.startswith(".") for part in rel.parts[:-1])


def _split_frontmatter(text: str) -> Tuple[str, str]:
    """Return (frontmatter, body). Frontmatter is between leading `---` fences."""
    if not text.startswith("---"):
        return "", text
    lines = text.splitlines(keepends=True)
    for idx in range(1, len(lines)):
        if lines[idx].rstrip() == "---":
            frontmatter = "".join(lines[1:idx])
            body = "".join(lines[idx + 1:])
            return frontmatter, body.lstrip("\n")
    return "", text


def _parse_frontmatter(text: str) -> Dict[str, str]:
    """Parse simple `key: value` frontmatter. First `:` separates key from value."""
    meta: Dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        match = _KV_RE.match(line)
        if not match:
            continue
        key, value = match.group(1), match.group(2).strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        meta[key] = value
    return meta


def _parse_list(value: Optional[str]) -> Optional[List[str]]:
    """Parse `allowed_tools` from a JSON array or comma-separated string."""
    if not value:
        return None
    value = value.strip()
    if value.startswith("["):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except json.JSONDecodeError:
            pass
    return [item.strip() for item in value.split(",") if item.strip()]


def _derive_pack(skill_dir: Path, root: Path) -> str:
    """Infer pack name from the path. `<pack>/skills/<skill>/` → `<pack>`."""
    parent = skill_dir.parent
    if parent.name == "skills" and parent != root:
        return parent.parent.name
    return ""


def _humanize(slug: str) -> str:
    return " ".join(part.capitalize() for part in slug.replace("_", "-").split("-") if part)


_RETARGET = (
    (".claude/rules/", ".turia/rules/"),
    (".claude/agents/", ".turia/agents/"),
)


def _retarget_turia(body: str) -> str:
    """Rewrite `.claude/` convention dirs to `.turia/` so turia ai reads them."""
    for src, dst in _RETARGET:
        body = body.replace(src, dst)
    return body
