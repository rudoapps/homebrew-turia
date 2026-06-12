"""Interactive list selector using prompt_toolkit."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import List, Optional

from prompt_toolkit import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.layout.controls import FormattedTextControl


@dataclass
class SelectOption:
    """A single option in the selector."""

    value: str
    label: str
    description: str = ""
    right_label: str = ""
    disabled: bool = False
    active: bool = False


def _build_selector_app(options, title):
    """Build a prompt_toolkit Application for the selector."""
    cursor = 0
    for i, opt in enumerate(options):
        if opt.active and not opt.disabled:
            cursor = i
            break

    result: List[Optional[str]] = [None]

    kb = KeyBindings()

    @kb.add("up")
    @kb.add("k")
    def _up(event):
        nonlocal cursor
        start = cursor
        while True:
            cursor = (cursor - 1) % len(options)
            if not options[cursor].disabled or cursor == start:
                break

    @kb.add("down")
    @kb.add("j")
    def _down(event):
        nonlocal cursor
        start = cursor
        while True:
            cursor = (cursor + 1) % len(options)
            if not options[cursor].disabled or cursor == start:
                break

    @kb.add("enter")
    def _select(event):
        if not options[cursor].disabled:
            result[0] = options[cursor].value
        event.app.exit()

    @kb.add("escape")
    @kb.add("q")
    @kb.add("c-c")
    def _cancel(event):
        event.app.exit()

    def _get_text():
        lines = []
        if title:
            lines.append(("bold", f"  {title}\n"))
            lines.append(("", "\n"))

        for i, opt in enumerate(options):
            is_selected = i == cursor
            prefix = " \u276f " if is_selected else "   "

            if opt.disabled:
                lines.append(("ansigray", f"{prefix}{opt.label}"))
                if opt.description:
                    lines.append(("ansigray", f"  {opt.description}"))
                lines.append(("", "\n"))
                continue

            if is_selected:
                lines.append(("bold ansigreen", prefix))
                lines.append(("bold", opt.label))
            else:
                lines.append(("", prefix))
                lines.append(("", opt.label))

            if opt.right_label:
                style = "bold ansigreen" if is_selected else "ansigray"
                lines.append((style, f"  {opt.right_label}"))

            if opt.active:
                lines.append(("ansigreen", "  *"))

            lines.append(("", "\n"))

            if opt.description:
                lines.append(("ansigray", f"     {opt.description}\n"))

        lines.append(("ansigray", "\n  \u2191\u2193 mover \u00b7 enter seleccionar \u00b7 esc cancelar"))
        return lines

    control = FormattedTextControl(_get_text)
    window = Window(content=control, always_hide_cursor=True)
    layout = Layout(window)

    app: Application = Application(
        layout=layout,
        key_bindings=kb,
        full_screen=False,
        output=_create_stderr_output(),
    )

    return app, result


async def select_option_async(
    options: List[SelectOption],
    title: str = "",
) -> Optional[str]:
    """Show an interactive selector (async-safe) and return the chosen value."""
    if not options:
        return None
    app, result = _build_selector_app(options, title)
    await app.run_async()
    return result[0]


def select_option(
    options: List[SelectOption],
    title: str = "",
) -> Optional[str]:
    """Show an interactive selector (sync) and return the chosen value."""
    if not options:
        return None
    app, result = _build_selector_app(options, title)
    app.run()
    return result[0]


def _create_stderr_output():
    """Create a prompt_toolkit output that writes to stderr."""
    from prompt_toolkit.output.defaults import create_output
    return create_output(stdout=sys.stderr)
