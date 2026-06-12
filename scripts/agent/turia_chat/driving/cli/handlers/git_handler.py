"""Git handler — /commit, /review, /changes."""

from __future__ import annotations

import subprocess
from typing import Callable, Coroutine, Optional

from ...ui.console import get_console


class GitHandler:
    """Handles git-related commands."""

    def __init__(self, project_root: str, send_message_fn: Callable) -> None:
        self._root = project_root
        self._send_message = send_message_fn
        self._console = get_console()

    async def handle_commit(self, message: Optional[str] = None) -> None:
        """Commit changes with auto-generated or manual message."""
        diff_result = subprocess.run(
            ["git", "diff", "--stat"],
            capture_output=True, text=True, cwd=self._root, timeout=30,
        )
        staged_result = subprocess.run(
            ["git", "diff", "--cached", "--stat"],
            capture_output=True, text=True, cwd=self._root, timeout=30,
        )

        diff_stat = diff_result.stdout.strip() + staged_result.stdout.strip()
        if not diff_stat:
            self._console.print("  [dim]No hay cambios para commitear.[/dim]")
            return

        if not message:
            diff_detail = subprocess.run(
                ["git", "diff", "--no-color"],
                capture_output=True, text=True, cwd=self._root,
            ).stdout[:3000]

            await self._send_message(
                f"Genera un mensaje de commit conciso (1-2 líneas, en inglés) para estos cambios. "
                f"Solo responde con el mensaje, nada más.\n\n```\n{diff_stat}\n\n{diff_detail}\n```"
            )
            return

        subprocess.run(["git", "add", "-A"], cwd=self._root)
        result = subprocess.run(
            ["git", "commit", "-m", message],
            capture_output=True, text=True, cwd=self._root, timeout=30,
        )
        if result.returncode == 0:
            self._console.print(f"  [success]\u2713[/success] {result.stdout.strip()}")
        else:
            self._console.print(f"  [red]{result.stderr.strip()}[/red]")

    async def handle_review(self) -> None:
        """Review current git changes with AI."""
        diff = subprocess.run(
            ["git", "diff", "--no-color"],
            capture_output=True, text=True, cwd=self._root, timeout=30,
        ).stdout

        staged = subprocess.run(
            ["git", "diff", "--cached", "--no-color"],
            capture_output=True, text=True, cwd=self._root, timeout=30,
        ).stdout

        combined = (diff + staged).strip()
        if not combined:
            self._console.print("  [dim]No hay cambios para revisar.[/dim]")
            return

        if len(combined) > 5000:
            combined = combined[:5000] + "\n... [truncado]"

        await self._send_message(
            f"Revisa estos cambios de código. Da feedback conciso sobre:\n"
            f"- Posibles bugs o errores\n"
            f"- Mejoras de calidad/legibilidad\n"
            f"- Problemas de seguridad\n"
            f"- Si respeta la arquitectura del proyecto\n\n"
            f"```diff\n{combined}\n```"
        )
