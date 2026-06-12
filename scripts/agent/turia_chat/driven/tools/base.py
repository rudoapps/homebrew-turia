"""Base class for tool executors with shared utilities."""

from __future__ import annotations

import asyncio
import os
import fnmatch
from typing import Any, Awaitable, Callable, Dict, List, Optional

from .path_validator import PathValidator, OutsideAllowedDirError
from .file_backup import FileBackup
from ...domain.entities.permission_mode import PermissionMode

# Type alias for the approval callback
ApprovalCallback = Callable[[str, str], Awaitable[bool]]

# Constants
MAX_SUBPROCESS_TIMEOUT = 15
MAX_RIPGREP_COLUMNS = 500
MAX_CONTENT_PREVIEW = 500
MAX_WEB_CONTENT = 15000


class ToolDeniedError(Exception):
    """Raised when a tool operation is denied (security or user rejection)."""


class BaseToolExecutor:
    """Shared utilities for tool executors."""

    def __init__(
        self,
        validator: PathValidator,
        backup: FileBackup,
        request_approval: Optional[ApprovalCallback] = None,
    ) -> None:
        self._validator = validator
        self._backup = backup
        self._request_approval = request_approval
        self._permission_mode = PermissionMode.ASK

    def set_permission_mode(self, mode: PermissionMode) -> None:
        self._permission_mode = mode

    @property
    def permission_mode(self) -> PermissionMode:
        return self._permission_mode

    async def _check_approval(self, title: str, detail: str) -> bool:
        """Check approval based on current permission mode."""
        if self._permission_mode == PermissionMode.AUTO:
            return True
        if self._permission_mode == PermissionMode.PLAN:
            raise ToolDeniedError(f"[PLAN] {title}\n{detail}")
        if self._request_approval:
            return await self._request_approval(title, detail)
        return True

    async def _run_subprocess(
        self,
        cmd: List[str],
        cwd: Optional[str] = None,
        timeout: int = MAX_SUBPROCESS_TIMEOUT,
    ) -> tuple:
        """Run a subprocess with timeout. Returns (stdout, stderr, returncode)."""
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd or self._validator.working_dir,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            return b"", b"timeout", -1

        return stdout, stderr, proc.returncode

    @staticmethod
    def _load_gitignore(directory: str) -> List[str]:
        """Load .gitignore patterns from a directory."""
        gitignore_path = os.path.join(directory, ".gitignore")
        if not os.path.isfile(gitignore_path):
            return []
        try:
            with open(gitignore_path, "r", encoding="utf-8") as f:
                return [
                    line.strip()
                    for line in f
                    if line.strip() and not line.startswith("#")
                ]
        except OSError:
            return []

    @staticmethod
    def _matches_gitignore(rel_path: str, patterns: List[str]) -> bool:
        """Check if a relative path matches any gitignore pattern."""
        for pattern in patterns:
            if fnmatch.fnmatch(rel_path, pattern):
                return True
            if fnmatch.fnmatch(os.path.basename(rel_path), pattern):
                return True
        return False
