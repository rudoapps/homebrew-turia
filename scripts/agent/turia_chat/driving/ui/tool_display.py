"""Tool execution display — renders tool progress and approval prompts."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, Optional, Tuple

from rich.panel import Panel
from rich.text import Text

from ...domain.entities.tool_metadata import get_tool_detail
from .console import get_console
from .spinner import Spinner

# Approval choices
_ALLOW = "allow"
_ALLOW_ALWAYS = "allow_always"
_REJECT = "reject"

# Re-use the marker from file_tools to extract embedded metadata
_FILE_META_MARKER = "\x00__FILE_META__\x00"

# Maximum diff lines shown inline before truncation
_MAX_INLINE_DIFF_LINES = 20
# Maximum lines of new content shown for write_file (new file)
_MAX_NEW_FILE_PREVIEW_LINES = 5


class ToolDisplay:
    """Renders tool execution progress to the terminal.

    Provides visual feedback for tool starts, completions, parallel
    summaries, approval prompts, and diff displays.
    """

    def __init__(self, collapse_state: Optional[Dict[str, Any]] = None) -> None:
        self._console = get_console()
        self._spinner = Spinner()
        self._auto_approve_turn: bool = False
        self._collapse: Optional[Dict[str, Any]] = collapse_state

    def show_tool_start(self, name: str, input_dict: Dict[str, Any]) -> None:
        """Show that a tool is about to start executing.

        Args:
            name: Tool name (e.g. "read_file").
            input_dict: The tool input parameters.
        """
        icon, verb, detail, action_msg = get_tool_detail(name, input_dict)
        self._spinner.start(f"{icon} {action_msg}")

    def show_tool_complete(
        self,
        name: str,
        input_dict: Dict[str, Any],
        success: bool,
        elapsed: float,
        output: str = "",
    ) -> None:
        """Show that a tool has finished executing.

        Args:
            name: Tool name.
            input_dict: The tool input parameters.
            success: Whether the tool succeeded.
            elapsed: Time taken in seconds.
            output: The tool's output text (for summary extraction).
        """
        icon, verb, detail, action_msg = get_tool_detail(name, input_dict)
        elapsed_str = f"{elapsed:.1f}s" if elapsed >= 0.1 else "<0.1s"

        self._spinner.stop()

        # For single-tool case, add elapsed and detail to collapse summary
        if self._collapse and self._collapse["is_collapsible"]:
            # Build a richer single-tool summary: "read_file config/settings.py"
            if detail:
                self._collapse["collapse_tool_summary"] = f"{name} {detail}"
            # Elapsed will be appended by show_parallel_summary for multi-tool;
            # for single tool, store it now (may be overwritten by parallel_summary)
            self._collapse["_last_elapsed"] = elapsed_str

        if success:
            self._collapse_print(
                f"  [success]\u2713[/success] [agent.tool]{action_msg}[/agent.tool] "
                f"[dim]({elapsed_str})[/dim]"
            )
        else:
            # Mark errors so we don't collapse them
            if self._collapse:
                self._collapse["has_errors"] = True
            self._collapse_print(
                f"  [error]\u2717[/error] [agent.tool]{action_msg}[/agent.tool] "
                f"[dim]({elapsed_str})[/dim]"
            )

        # Show summary for run_command results
        if name == "run_command" and output:
            summary = _extract_command_summary(output)
            if summary:
                self._collapse_print(f"  [dim]  {summary}[/dim]")

        # Show compact edit details for edit_file / write_file so the
        # user can see WHAT changed even in auto-approve mode.
        if name in ("edit_file", "write_file") and output and success:
            edit_summary = _extract_edit_summary(output)
            if edit_summary:
                for line in edit_summary:
                    self._collapse_print(f"  [dim]  {line}[/dim]")

    def show_parallel_summary(
        self,
        count: int,
        elapsed: float,
        has_errors: bool,
    ) -> None:
        """Show a summary after a batch of parallel tools completes.

        Args:
            count: Number of tools that ran in parallel.
            elapsed: Total time for the parallel batch.
            has_errors: Whether any tool in the batch failed.
        """
        self._spinner.stop()
        elapsed_str = f"{elapsed:.1f}s"

        # Update collapse summary with elapsed time
        if self._collapse:
            self._collapse["collapse_tool_summary"] += f" \u00b7 {elapsed_str}"
            if has_errors:
                self._collapse["has_errors"] = True

        if has_errors:
            self._collapse_print(
                f"  [warning]\u25cb[/warning] [agent.tool]{count} herramientas "
                f"en paralelo[/agent.tool] [dim]({elapsed_str}, con errores)[/dim]"
            )
        else:
            self._collapse_print(
                f"  [success]\u2713[/success] [agent.tool]{count} herramientas "
                f"en paralelo[/agent.tool] [dim]({elapsed_str})[/dim]"
            )

    async def show_approval_prompt(
        self,
        tool_name: str,
        detail: str,
    ) -> bool:
        """Show an interactive approval prompt for a write/edit/run operation.

        Displays the operation detail and a selector for the user to choose
        between allow, allow always, or reject.

        Args:
            tool_name: The tool requesting approval.
            detail: Description of what the tool wants to do.

        Returns:
            True if the user approved, False otherwise.
        """
        self._spinner.stop()

        # Approval prompts must NOT be collapsed — user needs to see the diff
        if self._collapse:
            self._collapse["is_collapsible"] = False

        # Auto-approve if user selected "Permitir todo el turno"
        if self._auto_approve_turn:
            self._console.print(
                f"  [dim](auto-aprobado este turno)[/dim]"
            )
            return True

        # Extract embedded file metadata if present
        file_meta = _extract_file_meta(detail)
        if file_meta:
            detail = _strip_file_meta(detail)

        self._console.print()

        # Render diff as a Rich Panel if we have file metadata. The mere
        # presence of file_meta proves this is a file operation (edit/write)
        # — don't check tool_name because it's actually the title string
        # ("Escribir foo.py"), not the tool name ("write_file").
        if file_meta:
            self._render_diff_panel(tool_name, detail, file_meta)
        else:
            # Fallback: flat rendering for non-file tools (run_command, etc.)
            self._render_flat_detail(detail)

        self._console.print()

        # Interactive selector (with 'd' and 'e' support when file_meta exists)
        result = self._show_selector(tool_name, file_meta=file_meta, raw_detail=detail)

        if result == _ALLOW_ALWAYS:
            self._auto_approve_turn = True
            return True

        return result == _ALLOW

    def _render_diff_panel(
        self,
        tool_name: str,
        detail: str,
        file_meta: Dict[str, str],
    ) -> None:
        """Render a Rich Panel with diff lines using background colors.

        - Added lines:   dark green background
        - Removed lines: dark red background
        - Context lines: dim (no background)

        For new files, shows the first lines with green background and
        syntax highlighting via Rich Syntax.
        """
        filename = file_meta.get("filename", "")
        old_content = file_meta.get("old_content", "")
        new_content = file_meta.get("new_content", "")

        is_new_file = not old_content

        if is_new_file:
            # New file — use Syntax with full highlighting
            from rich.syntax import Syntax

            ext = os.path.splitext(filename)[1].lstrip(".")
            lang = _detect_language(ext)
            new_lines = new_content.split("\n")
            total = len(new_lines)
            title = f" crear {filename} ({total} lineas) "

            max_preview = _MAX_INLINE_DIFF_LINES
            preview = "\n".join(new_lines[:max_preview])

            try:
                syntax = Syntax(
                    preview, lang,
                    line_numbers=True, theme="monokai", word_wrap=True,
                )
                if total > max_preview:
                    from rich.console import Group
                    hint = Text(
                        f"\n  ... +{total - max_preview} lineas mas"
                        f"  (pulsa 'd' para ver todo)",
                        style="dim",
                    )
                    body = Group(syntax, hint)
                else:
                    body = syntax
            except Exception:
                body = Text(preview)
        else:
            # Edit/rewrite — diff with background colors
            diff_lines = _compute_diff_lines(old_content, new_content)
            added = sum(1 for t, _ in diff_lines if t == "+")
            removed = sum(1 for t, _ in diff_lines if t == "-")
            title = f" edit {filename} (+{added}/-{removed}) "

            body = Text()
            truncated = len(diff_lines) > _MAX_INLINE_DIFF_LINES
            visible = (
                diff_lines[:_MAX_INLINE_DIFF_LINES] if truncated else diff_lines
            )

            width = len(str(len(visible)))
            for i, (typ, text) in enumerate(visible, 1):
                num = f" {i:>{width}}  "
                if typ == "-":
                    body.append(num, style="dim on #3a1a1a")
                    body.append(f"- {text}", style="on #3a1a1a")
                    body.append("\n")
                elif typ == "+":
                    body.append(num, style="dim on #1a3a1a")
                    body.append(f"+ {text}", style="on #1a3a1a")
                    body.append("\n")
                else:
                    body.append(num, style="dim")
                    body.append(f"  {text}\n", style="dim")

            if truncated:
                remaining = len(diff_lines) - _MAX_INLINE_DIFF_LINES
                body.append(
                    f"\n  ... {remaining} lineas mas"
                    f"  (pulsa 'd' para ver todo)\n",
                    style="dim",
                )

        panel = Panel(
            body,
            title=title,
            title_align="left",
            border_style="dim",
            padding=(0, 1),
        )
        self._console.print(panel)

    def _render_flat_detail(self, detail: str) -> None:
        """Render detail as flat colored lines (original behavior).

        Script blocks (── contenido del script ──) are rendered inside a
        Rich Panel with syntax highlighting for better readability.
        """
        lines = detail.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i]
            if line.startswith("── contenido del script"):
                # Collect all script lines until end of detail
                script_lines = []
                i += 1
                while i < len(lines):
                    script_lines.append(lines[i])
                    i += 1

                # Detect language from content (simple heuristic)
                script_text = "\n".join(script_lines)
                lang = "python"
                if script_text.lstrip().startswith(("#!/bin/bash", "#!/bin/sh", "set -")):
                    lang = "bash"
                elif script_text.lstrip().startswith(("{", "[")):
                    lang = "json"

                try:
                    from rich.syntax import Syntax
                    # Show with line numbers inside a panel
                    total_lines = len(script_lines)
                    max_preview = 30
                    preview = "\n".join(script_lines[:max_preview])
                    syntax = Syntax(
                        preview,
                        lang,
                        line_numbers=True,
                        theme="monokai",
                        word_wrap=True,
                    )
                    title = f" contenido ({total_lines} lineas) "
                    if total_lines > max_preview:
                        title += f"— mostrando {max_preview} "
                    code_panel = Panel(
                        syntax,
                        title=title,
                        title_align="left",
                        border_style="dim",
                        padding=(0, 1),
                    )
                    self._console.print(code_panel)
                    if total_lines > max_preview:
                        self._console.print(
                            f"  [dim]... +{total_lines - max_preview} "
                            f"lineas mas (pulsa 'd' para ver todo)[/dim]"
                        )
                except ImportError:
                    # Fallback if Syntax not available
                    for sl in script_lines:
                        self._console.print(f"  [yellow]{sl}[/yellow]")
            elif line.startswith("  - "):
                self._console.print(f"  [red]{line}[/red]")
                i += 1
            elif line.startswith("  + "):
                self._console.print(f"  [green]{line}[/green]")
                i += 1
            elif line.lstrip().startswith("@@"):
                self._console.print(f"  [cyan]{line}[/cyan]")
                i += 1
            else:
                self._console.print(f"  [dim]{line}[/dim]")
                i += 1

    def reset_turn_approval(self) -> None:
        """Reset auto-approval at the start of a new turn."""
        self._auto_approve_turn = False

    def _show_selector(
        self,
        tool_name: str,
        file_meta: Optional[Dict[str, str]] = None,
        raw_detail: str = "",
    ) -> str:
        """Show an interactive selector using keyboard arrows.

        Args:
            tool_name: The tool requesting approval.
            file_meta: Optional file metadata for diff/editor actions.
            raw_detail: The raw diff detail string (for pager).

        Returns:
            One of _ALLOW, _ALLOW_ALWAYS, or _REJECT.
        """
        options = [
            (_ALLOW, "Permitir", "green", "solo esta accion"),
            (_ALLOW_ALWAYS, "Permitir todo", "cyan", "resto del turno sin preguntar"),
            (_REJECT, "Rechazar", "red", "cancelar esta accion"),
        ]

        # Add diff/editor options when file metadata is available
        has_file_options = file_meta is not None
        if has_file_options:
            options.append(("diff", "Diff (d)", "yellow", "ver diff completo"))
            options.append(("editor", "Editor (e)", "yellow", "abrir en editor"))

        selected = 0

        # Hide cursor
        sys.stderr.write("\033[?25l")
        sys.stderr.flush()

        try:
            import tty
            import termios

            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            tty.setraw(fd)

            try:
                while True:
                    # Render selector line with descriptions inline
                    line_parts = []
                    for i, (_, label, color, desc) in enumerate(options):
                        if i == selected:
                            line_parts.append(
                                f"\033[1m\u276f {label}\033[0m \033[2m({desc})\033[0m"
                            )
                        else:
                            line_parts.append(f"\033[2m  {label}\033[0m")

                    selector_line = "  " + "   ".join(line_parts)
                    sys.stderr.write(f"\r\033[K{selector_line}")
                    sys.stderr.flush()

                    # Read key
                    ch = sys.stdin.read(1)
                    if ch == "\r" or ch == "\n":
                        value = options[selected][0]
                        if value == "diff" and has_file_options:
                            # Restore terminal, open pager, then loop back
                            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                            sys.stderr.write("\r\033[K\033[?25h")
                            sys.stderr.flush()
                            self._open_pager(raw_detail, file_meta)
                            tty.setraw(fd)
                            sys.stderr.write("\033[?25l")
                            sys.stderr.flush()
                            continue
                        elif value == "editor" and has_file_options:
                            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                            sys.stderr.write("\r\033[K\033[?25h")
                            sys.stderr.flush()
                            self._open_editor_diff(file_meta)
                            tty.setraw(fd)
                            sys.stderr.write("\033[?25l")
                            sys.stderr.flush()
                            continue
                        break
                    elif ch == "\x1b":
                        seq = sys.stdin.read(2)
                        if seq == "[D":  # Left arrow
                            selected = max(0, selected - 1)
                        elif seq == "[C":  # Right arrow
                            selected = min(len(options) - 1, selected + 1)
                    elif ch == "d" and has_file_options:
                        # Direct shortcut: open pager
                        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                        sys.stderr.write("\r\033[K\033[?25h")
                        sys.stderr.flush()
                        self._open_pager(raw_detail, file_meta)
                        tty.setraw(fd)
                        sys.stderr.write("\033[?25l")
                        sys.stderr.flush()
                        continue
                    elif ch == "e" and has_file_options:
                        # Direct shortcut: open editor diff
                        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                        sys.stderr.write("\r\033[K\033[?25h")
                        sys.stderr.flush()
                        self._open_editor_diff(file_meta)
                        tty.setraw(fd)
                        sys.stderr.write("\033[?25l")
                        sys.stderr.flush()
                        continue
                    elif ch == "q" or ch == "\x03":  # q or Ctrl+C
                        selected = 2  # Reject
                        break
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

        except (ImportError, OSError, ValueError):
            # Fallback to simple input if terminal control unavailable
            sys.stderr.write("\033[?25h")
            sys.stderr.flush()
            return self._show_simple_prompt()

        # Clear line and show result
        sys.stderr.write(f"\r\033[K\033[?25h")
        sys.stderr.flush()

        choice_value, choice_label, choice_color, _desc = options[selected]
        self._console.print(f"  [{choice_color}]{choice_label}[/{choice_color}]")

        return choice_value

    def _open_pager(self, raw_detail: str, file_meta: Dict[str, str]) -> None:
        """Open the full diff in a pager (delta > bat > $PAGER > less)."""
        filename = file_meta.get("filename", "file")
        old_content = file_meta.get("old_content", "")
        new_content = file_meta.get("new_content", "")

        # Generate a unified diff for the pager
        import difflib

        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)
        diff_text = "".join(difflib.unified_diff(
            old_lines, new_lines,
            fromfile=f"a/{filename}", tofile=f"b/{filename}",
        ))

        if not diff_text:
            diff_text = raw_detail  # Fallback to the raw detail

        # Write diff to temp file
        try:
            tmp = tempfile.NamedTemporaryFile(
                mode="w", suffix=".diff", prefix="turia-diff-",
                delete=False, encoding="utf-8",
            )
            tmp.write(diff_text)
            tmp.close()

            # Try pagers in order of preference
            pager_cmd = _find_pager()
            if pager_cmd:
                try:
                    subprocess.run(pager_cmd + [tmp.name], check=False)
                except (OSError, subprocess.SubprocessError):
                    self._console.print(
                        "  [warning]No se pudo abrir el pager[/warning]"
                    )
            else:
                self._console.print(
                    "  [warning]No se encontro pager (delta, bat, less)[/warning]"
                )
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

    def _open_editor_diff(self, file_meta: Dict[str, str]) -> None:
        """Open old/new content in an editor's diff view."""
        filename = file_meta.get("filename", "file")
        old_content = file_meta.get("old_content", "")
        new_content = file_meta.get("new_content", "")

        ext = os.path.splitext(filename)[1] or ".txt"
        before_path = None
        after_path = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=f"-before{ext}", prefix="turia-diff-",
                delete=False, encoding="utf-8",
            ) as f:
                f.write(old_content)
                before_path = f.name

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=f"-after{ext}", prefix="turia-diff-",
                delete=False, encoding="utf-8",
            ) as f:
                f.write(new_content)
                after_path = f.name

            editor_cmd = _find_diff_editor(before_path, after_path)
            if editor_cmd:
                try:
                    subprocess.run(editor_cmd, check=False)
                except (OSError, subprocess.SubprocessError):
                    self._console.print(
                        "  [warning]No se pudo abrir el editor[/warning]"
                    )
            else:
                self._console.print(
                    "  [warning]No se encontro editor diff "
                    "(code, cursor, opendiff, vimdiff)[/warning]"
                )
        finally:
            for p in (before_path, after_path):
                if p:
                    try:
                        os.unlink(p)
                    except OSError:
                        pass

    def _show_simple_prompt(self) -> str:
        """Fallback simple text prompt."""
        self._console.print(
            "  [bold]Permitir (s), Siempre (a), Rechazar (n):[/bold] ",
            end="",
        )
        sys.stderr.flush()
        try:
            response = input().strip().lower()
            if response in ("a", "always", "siempre", "todo"):
                return _ALLOW_ALWAYS
            elif response in ("s", "si", "y", "yes"):
                return _ALLOW
            return _REJECT
        except (EOFError, KeyboardInterrupt):
            self._console.print("  [dim]Cancelado[/dim]")
            return _REJECT

    def show_diff(
        self,
        old_content: str,
        new_content: str,
        filename: str,
    ) -> None:
        """Display a colored diff between old and new content.

        Args:
            old_content: The original file content (or snippet).
            new_content: The modified content (or snippet).
            filename: The filename for the header.
        """
        self._spinner.stop()

        old_lines = old_content.split("\n")
        new_lines = new_content.split("\n")

        added = max(0, len(new_lines) - len(old_lines))
        removed = max(0, len(old_lines) - len(new_lines))

        self._console.print(
            f"  [bold]\u25c9 Update({filename})[/bold]  "
            f"[green]+{added}[/green]/[red]-{removed}[/red] lineas"
        )

        for line in old_lines:
            self._console.print(f"    [red]{line}[/red]")
        for line in new_lines:
            self._console.print(f"    [green]{line}[/green]")

    def _collapse_print(self, *args: Any, **kwargs: Any) -> None:
        """Print via Rich console and increment the collapse line counter."""
        self._console.print(*args, **kwargs)
        if self._collapse:
            self._collapse["lines_since_collapse_point"] += 1

    # ── Protocol aliases for ToolProgressCallback ────────────────────────

    def on_tool_start(self, name: str, input_dict: Dict[str, Any]) -> None:
        """Alias for show_tool_start (ToolProgressCallback protocol)."""
        self.show_tool_start(name, input_dict)

    def on_tool_complete(
        self,
        name: str,
        input_dict: Dict[str, Any],
        success: bool,
        elapsed: float,
        output: str = "",
    ) -> None:
        """Alias for show_tool_complete (ToolProgressCallback protocol)."""
        self.show_tool_complete(name, input_dict, success, elapsed, output)

        # OS notification for long commands (>30s)
        if name == "run_command" and elapsed > 30:
            try:
                from ...driven.notifications.os_notify import send_notification
                status = "completado" if success else "fallido"
                cmd = input_dict.get("command", "")[:50]
                send_notification(
                    f"turia - Comando {status}",
                    f"{cmd} ({elapsed:.0f}s)",
                )
            except Exception:
                pass

    def on_parallel_summary(
        self,
        count: int,
        elapsed: float,
        has_errors: bool,
    ) -> None:
        """Alias for show_parallel_summary (ToolProgressCallback protocol)."""
        self.show_parallel_summary(count, elapsed, has_errors)

    def on_multi_file_preview(self, count: int, summary: str) -> None:
        """Show preview of multiple file edits before execution."""
        self._console.print()
        self._console.print(f"  [bold cyan]\u2139 {count} archivos a modificar:[/bold cyan]")
        for line in summary.strip().split("\n"):
            self._console.print(f"  [dim]{line.strip()}[/dim]")


def _detect_language(ext: str) -> str:
    """Map file extension to Rich Syntax language identifier."""
    return {
        "py": "python", "js": "javascript", "ts": "typescript",
        "tsx": "tsx", "jsx": "jsx", "rb": "ruby", "go": "go",
        "rs": "rust", "java": "java", "kt": "kotlin",
        "swift": "swift", "sh": "bash", "yml": "yaml",
        "yaml": "yaml", "json": "json", "toml": "toml",
        "md": "markdown", "sql": "sql", "html": "html",
        "css": "css", "xml": "xml",
    }.get(ext, "text")


def _extract_file_meta(detail: str) -> Optional[Dict[str, str]]:
    """Extract embedded file metadata from the detail string.

    Returns a dict with 'filename', 'old_content', 'new_content' or None.
    """
    if _FILE_META_MARKER not in detail:
        return None
    try:
        start = detail.index(_FILE_META_MARKER) + len(_FILE_META_MARKER)
        end = detail.index(_FILE_META_MARKER, start)
        return json.loads(detail[start:end])
    except (ValueError, json.JSONDecodeError):
        return None


def _strip_file_meta(detail: str) -> str:
    """Remove the embedded file metadata prefix from the detail string."""
    if _FILE_META_MARKER not in detail:
        return detail
    try:
        end = detail.index(_FILE_META_MARKER, detail.index(_FILE_META_MARKER) + 1)
        return detail[end + len(_FILE_META_MARKER):]
    except ValueError:
        return detail


def _compute_diff_lines(old_content: str, new_content: str) -> list:
    """Compute diff lines as (type, text) tuples.

    type is one of '+', '-', or ' ' (context).
    """
    import difflib

    old_lines = old_content.splitlines(keepends=False)
    new_lines = new_content.splitlines(keepends=False)

    result = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
        None, old_lines, new_lines
    ).get_opcodes():
        if tag == "equal":
            # Show up to 2 context lines around changes
            lines = old_lines[i1:i2]
            if len(lines) > 4 and result:
                # Show 2 lines of context at start and end, skip middle
                for line in lines[:2]:
                    result.append((" ", line))
                result.append((" ", "..."))
                for line in lines[-2:]:
                    result.append((" ", line))
            else:
                for line in lines:
                    result.append((" ", line))
        elif tag == "replace":
            for line in old_lines[i1:i2]:
                result.append(("-", line))
            for line in new_lines[j1:j2]:
                result.append(("+", line))
        elif tag == "delete":
            for line in old_lines[i1:i2]:
                result.append(("-", line))
        elif tag == "insert":
            for line in new_lines[j1:j2]:
                result.append(("+", line))

    return result


def _find_pager() -> Optional[list]:
    """Find the best available pager command. Returns a list of args."""
    for cmd in ("delta", "bat", "batcat"):
        if shutil.which(cmd):
            return [cmd]
    # Try $PAGER
    pager_env = os.environ.get("PAGER")
    if pager_env and shutil.which(pager_env.split()[0]):
        return pager_env.split()
    # Fallback
    if shutil.which("less"):
        return ["less", "-R"]
    return None


def _find_diff_editor(
    before_path: str, after_path: str
) -> Optional[list]:
    """Find the best available diff editor and return the command list."""
    # VS Code
    if shutil.which("code"):
        return ["code", "--wait", "--diff", before_path, after_path]
    # Cursor
    if shutil.which("cursor"):
        return ["cursor", "--wait", "--diff", before_path, after_path]
    # macOS FileMerge
    if shutil.which("opendiff"):
        return ["opendiff", before_path, after_path]
    # vimdiff
    if shutil.which("vimdiff"):
        return ["vimdiff", before_path, after_path]
    return None


def _extract_edit_summary(output: str) -> list[str]:
    """Extract a compact summary of an edit_file / write_file result.

    For edit_file (which now includes post-edit context lines marked with
    '>'), returns those modified lines so the user sees WHAT changed at a
    glance — even in auto-approve mode where the diff dialog was skipped.

    For write_file, returns the first 3 lines of the new file content.

    Returns:
        A list of display lines (max ~5), or [] if nothing useful.
    """
    lines = output.split("\n")

    # edit_file with post-edit context — look for '>' marked lines
    modified = [
        l.strip()
        for l in lines
        if len(l) > 3 and l.lstrip()[:1].isdigit() and ">" in l
    ]
    if modified:
        # Show up to 5 modified lines
        result = modified[:5]
        remaining = len(modified) - 5
        if remaining > 0:
            result.append(f"... (+{remaining} lineas modificadas)")
        return result

    # write_file — show first 3 content lines (skip the "Archivo creado" header)
    content_lines = [l for l in lines[1:] if l.strip()]
    if content_lines:
        preview = content_lines[:3]
        if len(content_lines) > 3:
            preview.append("...")
        return preview

    return []


def _extract_command_summary(output: str) -> str:
    """Extract a one-line summary from command output.

    Platform-agnostic: shows the last meaningful line of output
    and the exit code if non-zero.
    """
    import re

    lines = output.strip().split("\n")
    if not lines:
        return ""

    # Check for exit code
    exit_code = None
    last_line = lines[-1].strip()
    m = re.search(r"\[exit code: (\d+)\]", last_line)
    if m:
        exit_code = int(m.group(1))
        lines = lines[:-1]  # remove exit code line

    # Find last non-empty, non-bracket line
    summary_line = ""
    for line in reversed(lines):
        line = line.strip()
        if line and not line.startswith("["):
            summary_line = line[:80]
            break

    if exit_code is not None and exit_code != 0:
        if summary_line:
            return f"{summary_line} (exit {exit_code})"
        return f"exit code {exit_code}"

    if summary_line:
        return summary_line

    return ""
