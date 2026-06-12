"""Input handler — wraps prompt_toolkit for interactive user input."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys

from ..ui.console import get_console


# Maximum lines to read from an @file reference
_MAX_FILE_LINES = 200

# Pattern to match @file references (must be followed by a file-like path)
_FILE_REF_PATTERN = re.compile(r"@((?:[~/.]|[a-zA-Z])[^\s,;]+)")


def _get_history_path() -> Path:
    """Return the path to the prompt history file, creating dirs if needed."""
    config_dir = Path.home() / ".config" / "turia-agent"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "history"


def _build_key_bindings() -> KeyBindings:
    """Build key bindings for the prompt.

    Enter submits the input. Escape+Enter or Meta+Enter inserts a newline
    for multi-line editing (same behavior as Claude Code).
    """
    bindings = KeyBindings()

    @bindings.add(Keys.Enter)
    def _submit(event: object) -> None:
        """Submit input on Enter."""
        # Access buffer through the event
        event.current_buffer.validate_and_handle()  # type: ignore[attr-defined]

    @bindings.add(Keys.Escape, Keys.Enter)
    def _newline_escape(event: object) -> None:
        """Insert newline on Escape+Enter."""
        event.current_buffer.insert_text("\n")  # type: ignore[attr-defined]

    return bindings


class InputHandler:
    """Handles user input via prompt_toolkit with history and @file expansion.

    Provides a prompt_toolkit-based input session with:
      - File-based command history
      - Auto-suggestions from history
      - Custom key bindings (Enter to submit, Esc+Enter for newline)
      - @file reference expansion (reads file contents into the prompt)
    """

    def __init__(self) -> None:
        history_path = _get_history_path()
        # Completions for slash commands and @mentions
        _completions = [
            "/help", "/new", "/cost", "/copy", "/clear", "/models", "/model",
            "/resume", "/quota", "/analyze", "/mode", "/commit", "/review",
            "/context", "/remember", "/memories", "/forget", "/skills",
            "/undo", "/diff",
            "@ios", "@back", "@backend", "@android", "@flutter", "@web",
        ]
        self._session: PromptSession[str] = PromptSession(
            history=FileHistory(str(history_path)),
            auto_suggest=AutoSuggestFromHistory(),
            completer=WordCompleter(_completions, sentence=True),
            key_bindings=_build_key_bindings(),
            multiline=False,
            enable_open_in_editor=False,
        )
        self._console = get_console()

    async def read_input(self) -> Optional[str]:
        """Read user input from the prompt.

        Returns:
            The user input string with @file references expanded,
            or None on EOF (Ctrl+D).
        """
        try:
            raw = await self._session.prompt_async("\u203a ")
        except EOFError:
            return None
        except KeyboardInterrupt:
            # Ctrl+C on empty prompt — treat as cancel, return empty
            return ""

        if not raw.strip():
            return ""

        # Expand @file references
        expanded, attachments = self._expand_file_refs(raw)
        if attachments:
            for path, line_count in attachments:
                self._console.print(
                    f"  [dim]\u2192 {path} ({line_count} lineas)[/dim]"
                )

        return expanded

    def _expand_file_refs(
        self, text: str
    ) -> Tuple[str, List[Tuple[str, int]]]:
        """Expand @file references in the input text.

        Detects @path patterns, reads the referenced files (up to
        _MAX_FILE_LINES lines), and appends their contents to the prompt.

        Args:
            text: Raw user input.

        Returns:
            A tuple of (expanded_text, list of (filepath, line_count) attachments).
        """
        matches = _FILE_REF_PATTERN.findall(text)
        if not matches:
            return text, []

        attachments: List[Tuple[str, int]] = []
        file_contents_parts: List[str] = []

        for raw_path in matches:
            # Expand ~ and resolve
            expanded_path = os.path.expanduser(raw_path)
            resolved = Path(expanded_path).resolve()

            if not resolved.is_file():
                continue

            try:
                lines = resolved.read_text(encoding="utf-8", errors="replace").splitlines()
                truncated = lines[:_MAX_FILE_LINES]
                content = "\n".join(truncated)

                if len(lines) > _MAX_FILE_LINES:
                    content += f"\n... (truncado, {len(lines)} lineas totales)"

                file_contents_parts.append(
                    f"\n\n--- Contenido de {raw_path} ---\n{content}\n--- Fin de {raw_path} ---"
                )
                attachments.append((raw_path, len(truncated)))

                # Remove the @ref from the text so it reads cleanly
                text = text.replace(f"@{raw_path}", "", 1)

            except OSError:
                # Silently skip files we can't read
                continue

        if file_contents_parts:
            text = text.strip() + "".join(file_contents_parts)

        return text, attachments
