"""Rich Console singleton with a custom theme matching turia colors."""

from __future__ import annotations

from rich.console import Console
from rich.theme import Theme

# Custom theme matching the turia agent color scheme
TURIA_THEME = Theme(
    {
        "agent.name": "bold green",
        "agent.header": "bold green",
        "agent.model": "dim",
        "agent.rag": "green",
        "agent.rag_multi": "cyan",
        "agent.text": "white",
        "agent.thinking": "cyan",
        "agent.tool": "dim",
        "agent.tool_name": "bold cyan",
        "agent.delegation": "dim",
        "agent.subagent": "bold",
        "info": "cyan",
        "success": "green",
        "warning": "yellow",
        "error": "red bold",
        "cost": "dim",
        "cost.warning": "yellow",
        "cost.limit": "red bold",
        "spinner": "cyan",
        "dim": "dim",
    }
)

# Module-level singleton
_console: Console | None = None


def get_console() -> Console:
    """Return the shared Rich Console instance."""
    global _console
    if _console is None:
        _console = Console(
            theme=TURIA_THEME,
            stderr=True,  # All UI output goes to stderr (stdout is for data)
            highlight=False,
        )
    return _console
