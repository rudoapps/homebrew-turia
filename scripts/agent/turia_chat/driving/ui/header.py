"""Session header display for interactive mode."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from rich.panel import Panel
from rich.text import Text

from .console import get_console


def _is_homebrew_install() -> bool:
    """Check if turia was installed via Homebrew or Linuxbrew."""
    import os
    path = os.path.abspath(__file__).lower()
    return any(k in path for k in ("/homebrew/", "/linuxbrew/", "/cellar/"))


def _get_upgrade_command() -> str:
    """Return the appropriate upgrade command for the install method."""
    if _is_homebrew_install():
        return "brew update && brew upgrade turia"
    return "pip install --upgrade git+https://github.com/rudoapps/homebrew-turia.git"


# Style mapping for broadcast message types
_MESSAGE_STYLES: Dict[str, str] = {
    "info": "cyan",
    "warning": "yellow",
    "success": "green",
    "error": "red bold",
}

_MESSAGE_ICONS: Dict[str, str] = {
    "info": "\u2139\ufe0f ",     # ℹ️
    "warning": "\u26a0\ufe0f ",  # ⚠️
    "success": "\u2705 ",        # ✅
    "error": "\u274c ",          # ❌
}

_PANEL_BORDER_STYLES: Dict[str, str] = {
    "info": "cyan",
    "warning": "yellow",
    "success": "green",
    "error": "red",
}


class SessionHeader:
    """Renders the interactive session header banner.

    Shows project name, conversation info, and available shortcuts
    using the Rich console with turia theme styling.
    """

    def __init__(self) -> None:
        self._console = get_console()

    def show(
        self,
        project_name: str,
        conversation_id: Optional[int] = None,
        broadcast_messages: Optional[List[Dict[str, Any]]] = None,
        rag_info: Optional[Dict[str, Any]] = None,
        active_skill: Optional[str] = None,
    ) -> None:
        """Display the session header banner."""
        _SEP = "\u2500" * 70
        self._console.print(f"  [dim]{_SEP}[/dim]")

        # Project line
        parts = [f"[agent.header]{project_name}[/agent.header]"]

        if conversation_id is not None:
            parts.append(f"[dim]conversacion #{conversation_id}[/dim]")

        # RAG status indicator
        if rag_info and rag_info.get("has_index"):
            chunks = rag_info.get("total_chunks", 0)
            indexed_at = rag_info.get("last_indexed_at", "")
            date_str = f" {indexed_at[:10]}" if indexed_at else ""
            parts.append(f"[agent.rag]RAG:{chunks} chunks{date_str}[/agent.rag]")
        elif rag_info and rag_info.get("status") == "pending":
            parts.append("[dim]RAG: pendiente[/dim]")

        line = " \u00b7 ".join(parts)
        self._console.print(f"  {line}")

        # Linked projects line with last indexed date
        linked = rag_info.get("linked_projects", []) if rag_info else []
        if linked:
            mentions = []
            for lp in linked:
                name = lp.get("name", "")
                mention = lp.get("mention", "")
                status = lp.get("status", "")
                indexed_at = lp.get("last_indexed_at", "")
                date_str = ""
                if indexed_at:
                    date_str = f" {indexed_at[:10]}"
                if status == "ready":
                    mentions.append(f"[agent.rag]{mention}[/agent.rag] [dim]{name}{date_str}[/dim]")
                else:
                    mentions.append(f"[dim]{mention} {name} (no indexado)[/dim]")
            sep = " \u00b7 "
            self._console.print(f"  [dim]Proyectos:[/dim] {sep.join(mentions)}")

        # Active skill line
        if active_skill:
            self._console.print(f"  [dim]Skill:[/dim] [cyan]{active_skill}[/cyan]")

        # Shortcuts line
        self._console.print(
            "  [dim]/new nueva conversacion \u00b7 /help comandos[/dim]"
        )

        self._console.print(f"  [dim]{_SEP}[/dim]")

        # Broadcast messages (after header, before prompt)
        if broadcast_messages:
            self._render_broadcasts(broadcast_messages)

        self._console.print()

    def _render_broadcasts(self, messages: List[Dict[str, Any]]) -> None:
        """Render broadcast messages grouped in a styled panel."""
        lines = Text()
        for i, msg in enumerate(messages):
            msg_type = msg.get("message_type", "info")
            text = msg.get("message", "")
            style = _MESSAGE_STYLES.get(msg_type, "cyan")
            icon = _MESSAGE_ICONS.get(msg_type, "\u2139\ufe0f ")
            if i > 0:
                lines.append("\n")
            lines.append(f"{icon} ", style=style)
            lines.append(text, style=style)

        # Use the most severe message type for the panel border
        severity_order = ["error", "warning", "success", "info"]
        types = [m.get("message_type", "info") for m in messages]
        border_type = next((t for t in severity_order if t in types), "info")
        border_style = _PANEL_BORDER_STYLES.get(border_type, "cyan")

        panel = Panel(
            lines,
            border_style=border_style,
            padding=(0, 1),
            width=74,
        )
        self._console.print(panel)

    def show_update_required(self, message: str) -> None:
        """Display a blocking update-required banner and exit message."""
        self._console.print()
        text = Text()
        text.append("\u26a0\ufe0f  ", style="yellow bold")
        text.append("Actualizacion requerida", style="yellow bold")
        text.append("\n\n")
        text.append(message, style="white")
        text.append("\n\n")
        text.append(_get_upgrade_command(), style="cyan bold")

        panel = Panel(
            text,
            border_style="yellow",
            padding=(1, 2),
            width=74,
        )
        self._console.print(panel)
        self._console.print()

    def show_new_conversation(self) -> None:
        """Display a brief banner when starting a new conversation."""
        self._console.print()
        self._console.print("  [success]\u2713[/success] Nueva conversacion iniciada")
        self._console.print()

    def show_resumed_conversation(self, conversation_id: int) -> None:
        """Display a brief banner when resuming an existing conversation.

        Args:
            conversation_id: The conversation ID being resumed.
        """
        self._console.print()
        self._console.print(
            f"  [info]\u2139[/info] Retomando conversacion #{conversation_id}"
        )
        self._console.print()
