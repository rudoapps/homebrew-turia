"""Markdown rendering wrapper using rich.Markdown."""

from __future__ import annotations

from rich.markdown import Markdown
from rich.padding import Padding

from .console import get_console


def render_markdown(text: str) -> None:
    """Render markdown text to the console with left padding.

    Uses Rich's built-in Markdown renderer which handles:
      - Code blocks with syntax highlighting
      - Bold, italic, inline code
      - Headers
      - Lists (bullet and numbered)
      - Tables
      - Horizontal rules
      - Links

    Args:
        text: Markdown-formatted text to render.
    """
    if not text.strip():
        return

    console = get_console()
    md = Markdown(text, code_theme="monokai")
    # Add 2-space left padding and limit width to prevent resize issues
    padded = Padding(md, (0, 0, 0, 2))
    console.print(padded, width=min(console.width, 100))


def render_streaming_text(text: str) -> None:
    """Render plain text during streaming (before final markdown render).

    During streaming we receive text incrementally and cannot wait for
    the full markdown to be available. This renders text with basic
    formatting and 2-space indentation.

    Args:
        text: Raw text content to display.
    """
    if not text:
        return

    console = get_console()
    # Indent each line with 2 spaces to match turia style
    indented = "  " + text.replace("\n", "\n  ")
    console.print(indented, end="", highlight=False)
