"""Shell tools: run_command, git_info, file_diff."""

from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid
from typing import Any, Dict, List

from .base import BaseToolExecutor, ToolDeniedError
from ...domain.entities.tool_metadata import (
    MAX_COMMAND_TIMEOUT,
    MAX_COMMAND_TIMEOUT_HARD,
    MAX_OUTPUT_LINES,
)


    # Patterns that indicate dangerous/destructive commands.
# These ALWAYS require explicit approval even in auto-approve-turn mode.
_DANGEROUS_PATTERNS = [
    "rm -rf /",
    "rm -rf /*",
    "rm -rf ~",
    "rm -rf ~/",
    "rm -rf /Library",
    "rm -rf /System",
    "rm -rf /usr",
    "rm -rf /bin",
    "rm -rf /sbin",
    "rm -rf /etc",
    "rm -rf /var",
    "rm -rf /Applications",
    "rm -rf /opt",
    "mkfs",
    "dd if=",
    ":(){:|:&};:",
    "> /dev/sd",
    "chmod -R 777 /",
    "chown -R",
    "sudo rm",
    "sudo dd",
    "sudo mkfs",
]

# System paths that should never be deleted or modified via rm/mv.
_PROTECTED_PATHS = [
    "/Library/Frameworks",
    "/Library/Python",
    "/System",
    "/usr/local/Cellar",
    "/usr/local/lib",
    "/usr/bin",
    "/usr/lib",
    "/bin",
    "/sbin",
    "/etc",
    "/var",
    "/Applications",
]


def _is_dangerous_command(command: str) -> bool:
    """Check if a command matches known dangerous patterns."""
    cmd_lower = command.lower().strip()
    for pattern in _DANGEROUS_PATTERNS:
        if pattern.lower() in cmd_lower:
            return True
    # Check for rm/mv targeting protected paths
    if any(kw in cmd_lower for kw in ("rm ", "rm\t", "mv ", "mv\t")):
        for path in _PROTECTED_PATHS:
            if path.lower() in cmd_lower:
                return True
    return False


class ShellToolExecutor(BaseToolExecutor):
    """Handles shell command execution and git operations."""

    async def run_command(self, inp: Dict[str, Any]) -> str:
        """Execute a shell command with timeout, streaming output."""
        command = inp.get("command", "")
        timeout = min(
            int(inp.get("timeout", MAX_COMMAND_TIMEOUT)),
            MAX_COMMAND_TIMEOUT_HARD,
        )
        background = inp.get("background", False)
        description = inp.get("description", "")

        if not command:
            raise ValueError("Se requiere el parametro 'command'")

        # Block dangerous commands — always require explicit approval
        if _is_dangerous_command(command):
            raise ToolDeniedError(
                f"Comando bloqueado por seguridad: modifica rutas protegidas del sistema.\n"
                f"Comando: {command}"
            )

        # Check approval
        detail = f"$ {command}\n(timeout: {timeout}s)"
        script_content = _extract_script_content(command)
        if script_content:
            detail += f"\n\n── contenido del script ──\n{script_content}"

        approved = await self._check_approval("Ejecutar comando", detail)
        if not approved:
            raise ToolDeniedError("Operacion rechazada por el usuario")

        # Background execution
        if background:
            task_id = str(uuid.uuid4())[:8]
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._validator.working_dir,
            )
            desc = description or command[:50]
            return f"Comando ejecutandose en background (pid={proc.pid}, task_id={task_id}): {desc}"

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._validator.working_dir,
            )

            stdout_lines: List[str] = []
            stderr_lines: List[str] = []
            start_time = time.time()
            last_display = ""
            _frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
            _frame_idx = [0]

            def _update_display(text: str) -> None:
                nonlocal last_display
                last_display = text
                elapsed = time.time() - start_time
                # Strip ANSI codes and Rich markup from display
                import re as _re
                clean = _re.sub(r'\033\[[0-9;]*m', '', text)
                clean = _re.sub(r'\[/?[a-z_.]+\]', '', clean)
                display = clean.strip()[:80]
                if not display:
                    display = "Ejecutando..."
                frame = _frames[_frame_idx[0] % len(_frames)]
                _frame_idx[0] += 1
                sys.stderr.write(f"\r\033[K  \033[36m{frame}\033[0m \033[2m{display} ({elapsed:.0f}s)\033[0m")
                sys.stderr.flush()

            async def _read_stream(stream, collector):
                buf = ""
                while True:
                    try:
                        chunk = await asyncio.wait_for(stream.read(4096), timeout=0.5)
                    except asyncio.TimeoutError:
                        _update_display(last_display or "Ejecutando...")
                        continue
                    if not chunk:
                        break
                    text = chunk.decode("utf-8", errors="replace")
                    buf += text
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        line = line.rstrip("\r")
                        if line:
                            collector.append(line)
                            _update_display(line)
                if buf.strip():
                    collector.append(buf.strip())
                    _update_display(buf.strip())

            try:
                await asyncio.wait_for(
                    asyncio.gather(
                        _read_stream(proc.stdout, stdout_lines),
                        _read_stream(proc.stderr, stderr_lines),
                    ),
                    timeout=timeout,
                )
                await proc.wait()
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                sys.stderr.write("\r\033[K")
                sys.stderr.flush()
                partial = "\n".join(stdout_lines[-20:] + stderr_lines[-20:])
                return f"Comando cancelado: timeout de {timeout} segundos\nUltimas lineas:\n{partial}"

            sys.stderr.write("\r\033[K")
            sys.stderr.flush()

        except Exception as exc:
            raise RuntimeError(f"Error ejecutando comando: {exc}")

        output_parts: List[str] = []
        stdout_text = "\n".join(stdout_lines)
        stderr_text = "\n".join(stderr_lines)

        if stdout_text.strip():
            output_parts.append(stdout_text)
        if stderr_text.strip():
            output_parts.append(f"[stderr]\n{stderr_text}")

        output = "\n".join(output_parts)

        lines = output.split("\n")
        if len(lines) > MAX_OUTPUT_LINES:
            output = "\n".join(lines[:MAX_OUTPUT_LINES])
            output += f"\n\n... [truncado, {len(lines)} lineas totales]"

        exit_code = proc.returncode
        if exit_code != 0:
            output += f"\n\n[exit code: {exit_code}]"

        return output if output.strip() else f"Comando completado (exit code: {exit_code})"

    async def git_info(self, inp: Dict[str, Any]) -> str:
        """Run git info commands and return output."""
        subcommand = inp.get("command", inp.get("subcommand", inp.get("type", "status")))

        allowed = {
            "status": ["git", "status", "--porcelain", "-b"],
            "log": ["git", "log", "--oneline", "-20"],
            "diff": ["git", "diff", "--stat"],
            "diff_staged": ["git", "diff", "--staged", "--stat"],
            "branch": ["git", "branch", "-a"],
            "show": ["git", "show", "--stat", "HEAD"],
            "remote": ["git", "remote", "-v"],
        }

        if subcommand in allowed:
            cmd = allowed[subcommand]
        else:
            raise ValueError(
                f"Subcomando git no permitido: {subcommand}. "
                f"Opciones: {', '.join(allowed.keys())}"
            )

        stdout, stderr, returncode = await self._run_subprocess(cmd, timeout=10)

        output = stdout.decode("utf-8", errors="replace")
        if returncode != 0:
            err = stderr.decode("utf-8", errors="replace")
            return f"git {subcommand} error:\n{err}"

        lines = output.split("\n")
        if len(lines) > MAX_OUTPUT_LINES:
            output = "\n".join(lines[:MAX_OUTPUT_LINES]) + "\n... [truncado]"

        return output if output.strip() else f"git {subcommand}: sin salida"

    async def file_diff(self, inp: Dict[str, Any]) -> str:
        """Show git diff for a file."""
        path = inp.get("path", "")
        commit = inp.get("commit", "HEAD")

        if not path:
            raise ValueError("Se requiere el parametro 'path'")

        ok, resolved = self._validator.validate_read(path)
        if not ok:
            raise ToolDeniedError(resolved)

        cmd = ["git", "diff", commit, "--", resolved]
        stdout, stderr, returncode = await self._run_subprocess(cmd, timeout=10)

        output = stdout.decode("utf-8", errors="replace")
        if not output.strip():
            return f"Sin cambios en {path} (comparando con {commit})"

        lines = output.split("\n")
        if len(lines) > MAX_OUTPUT_LINES:
            output = "\n".join(lines[:MAX_OUTPUT_LINES]) + "\n... [truncado]"

        return output


def _extract_script_content(command: str) -> str | None:
    """Extract script file content referenced in a command."""
    import shlex

    _INTERPRETERS = {"python", "python3", "ruby", "bash", "sh", "zsh", "node", "perl", "swift"}
    _SCRIPT_EXTENSIONS = {".py", ".rb", ".sh", ".js", ".pl", ".swift", ".bash", ".zsh"}

    try:
        parts = shlex.split(command)
    except ValueError:
        parts = command.split()

    if not parts:
        return None

    for i, part in enumerate(parts):
        if part.startswith("-"):
            continue
        base = os.path.basename(part)
        if base in _INTERPRETERS and i + 1 < len(parts):
            candidate = parts[i + 1]
            if not candidate.startswith("-") and os.path.isfile(candidate):
                return _read_script(candidate)
            continue
        _, ext = os.path.splitext(part)
        if ext in _SCRIPT_EXTENSIONS and os.path.isfile(part):
            return _read_script(part)

    return None


def _read_script(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        lines = content.split("\n")
        if len(lines) > 60:
            content = "\n".join(lines[:60]) + f"\n... ({len(lines)} lineas totales)"
        return content
    except OSError:
        return None
