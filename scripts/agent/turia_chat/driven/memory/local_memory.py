"""Local persistent memory — stores user preferences across sessions.

Memory files are stored in ~/.config/turia-agent/memory/ as markdown files.
An index (MEMORY.md) maps topics to files.

Memory types:
- user: User role, preferences, knowledge level
- feedback: How to approach work (corrections and confirmations)
- project: Ongoing work context, decisions, deadlines
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional


MEMORY_DIR = Path.home() / ".config" / "turia-agent" / "memory"
MEMORY_INDEX = MEMORY_DIR / "MEMORY.md"
MAX_MEMORY_CHARS = 3000  # Max chars to inject into system prompt


class LocalMemory:
    """Manages persistent memory files."""

    def __init__(self) -> None:
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)

    def get_all_memories(self) -> str:
        """Load all memory content for system prompt injection.

        Returns concatenated memory content, truncated to MAX_MEMORY_CHARS.
        """
        if not MEMORY_INDEX.is_file():
            return ""

        memories = []
        for md_file in sorted(MEMORY_DIR.glob("*.md")):
            if md_file.name == "MEMORY.md":
                continue
            try:
                content = md_file.read_text(encoding="utf-8", errors="replace").strip()
                if content:
                    memories.append(content)
            except OSError:
                continue

        if not memories:
            return ""

        combined = "\n\n---\n\n".join(memories)
        if len(combined) > MAX_MEMORY_CHARS:
            combined = combined[:MAX_MEMORY_CHARS] + "\n... [memoria truncada]"

        return combined

    def save_memory(self, name: str, content: str, memory_type: str = "user") -> str:
        """Save a memory to a file.

        Args:
            name: Memory topic name (used as filename slug)
            content: Memory content (markdown)
            memory_type: One of user, feedback, project

        Returns:
            Path to the saved file.
        """
        slug = name.lower().replace(" ", "_").replace("/", "_")[:50]
        filename = f"{memory_type}_{slug}.md"
        filepath = MEMORY_DIR / filename

        full_content = f"---\nname: {name}\ntype: {memory_type}\n---\n\n{content}\n"
        filepath.write_text(full_content, encoding="utf-8")

        # Update index
        self._update_index(name, filename)

        return str(filepath)

    def list_memories(self) -> List[Dict[str, str]]:
        """List all saved memories."""
        memories = []
        for md_file in sorted(MEMORY_DIR.glob("*.md")):
            if md_file.name == "MEMORY.md":
                continue
            try:
                content = md_file.read_text(encoding="utf-8", errors="replace")
                # Extract name from frontmatter
                name = md_file.stem
                for line in content.split("\n"):
                    if line.startswith("name:"):
                        name = line[5:].strip()
                        break
                memories.append({
                    "name": name,
                    "file": md_file.name,
                    "size": len(content),
                })
            except OSError:
                continue
        return memories

    def delete_memory(self, filename: str) -> bool:
        """Delete a memory file."""
        filepath = MEMORY_DIR / filename
        if filepath.is_file() and filepath.parent == MEMORY_DIR:
            filepath.unlink()
            return True
        return False

    def _update_index(self, name: str, filename: str) -> None:
        """Update MEMORY.md index."""
        lines = []
        if MEMORY_INDEX.is_file():
            lines = MEMORY_INDEX.read_text(encoding="utf-8").strip().split("\n")

        # Check if entry already exists
        entry = f"- [{name}]({filename})"
        for i, line in enumerate(lines):
            if filename in line:
                lines[i] = entry
                break
        else:
            lines.append(entry)

        # Keep index under 200 lines
        if len(lines) > 200:
            lines = lines[:200]

        MEMORY_INDEX.write_text("\n".join(lines) + "\n", encoding="utf-8")
