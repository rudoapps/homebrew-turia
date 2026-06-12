"""Path validation for tool operations — security boundary."""

from __future__ import annotations

import os
from typing import List, Optional, Tuple

from ...domain.entities.tool_metadata import (
    BLOCKED_FILE_EXTENSIONS,
    BLOCKED_FILE_NAMES,
    SENSITIVE_PATTERNS,
)


class PathValidator:
    """Validates and resolves file paths for tool operations.

    All paths are validated against the working directory and any
    additional allowed directories to prevent directory traversal attacks.
    Blocked extensions and names are rejected outright.

    Args:
        working_dir: The root directory that all paths must resolve within.
                     Defaults to os.getcwd() at construction time.
        allow_dirs: Additional directories the agent is allowed to access.
    """

    def __init__(self, working_dir: Optional[str] = None) -> None:
        self._working_dir = os.path.realpath(working_dir or os.getcwd())
        self._allow_dirs: List[str] = []

    @property
    def working_dir(self) -> str:
        """The resolved working directory."""
        return self._working_dir

    @property
    def allowed_dirs(self) -> List[str]:
        """All allowed directories (working_dir + extras)."""
        return [self._working_dir] + self._allow_dirs

    def add_allowed_dir(self, path: str) -> None:
        """Dynamically grant access to an additional directory."""
        resolved = os.path.realpath(os.path.expanduser(path))
        if resolved not in self._allow_dirs:
            self._allow_dirs.append(resolved)

    def validate_read(self, path: str) -> Tuple[bool, str]:
        """Validate a path for reading.

        Resolves the path, checks it is within the working directory,
        and verifies it is not a blocked file type.

        Args:
            path: The raw path from the tool call.

        Returns:
            A tuple of (ok, result) where result is the resolved absolute
            path on success, or an error message on failure.
        """
        resolved = self._resolve(path)

        # Must be within an allowed directory
        if not self._is_within_cwd(resolved):
            raise OutsideAllowedDirError(path, resolved, self._working_dir)

        # Check blocked extensions
        _, ext = os.path.splitext(resolved)
        if ext.lower() in BLOCKED_FILE_EXTENSIONS:
            return False, (
                f"Acceso denegado: extension '{ext}' esta bloqueada "
                f"por motivos de seguridad"
            )

        # Check blocked file names
        basename = os.path.basename(resolved)
        rel = os.path.relpath(resolved, self._working_dir)
        for blocked in BLOCKED_FILE_NAMES:
            if basename == blocked or rel.endswith(blocked):
                return False, (
                    f"Acceso denegado: el archivo '{basename}' esta "
                    f"bloqueado por motivos de seguridad"
                )

        return True, resolved

    def validate_write(self, path: str) -> Tuple[bool, str]:
        """Validate a path for writing.

        In addition to read validations, checks that the parent
        directory exists or can be created.

        Args:
            path: The raw path from the tool call.

        Returns:
            A tuple of (ok, result) where result is the resolved absolute
            path on success, or an error message on failure.
        """
        # First apply read validations
        ok, result = self.validate_read(path)
        if not ok:
            return ok, result

        resolved = result

        # Check parent directory
        parent = os.path.dirname(resolved)
        if not os.path.isdir(parent):
            # Try to determine if parent can be created
            # Walk up until we find an existing directory
            check = parent
            while check and not os.path.isdir(check):
                check = os.path.dirname(check)
            if not check or not self._is_within_cwd(check):
                return False, (
                    f"No se puede crear el directorio padre: '{parent}'"
                )

        return True, resolved

    def is_sensitive(self, path: str) -> Optional[str]:
        """Check whether a file path matches a sensitive pattern.

        Args:
            path: An already-resolved absolute path.

        Returns:
            A reason string if the file is sensitive and needs explicit
            approval, or None if the file is safe to modify.
        """
        basename = os.path.basename(path)
        rel = os.path.relpath(path, self._working_dir)

        for pattern in SENSITIVE_PATTERNS:
            if pattern in basename or pattern in rel:
                return (
                    f"'{basename}' coincide con patron sensible '{pattern}'"
                )

        return None

    # ── Internal helpers ─────────────────────────────────────────────────

    def _resolve(self, path: str) -> str:
        """Resolve a path to an absolute path relative to the working dir."""
        if os.path.isabs(path):
            return os.path.realpath(path)
        return os.path.realpath(os.path.join(self._working_dir, path))

    def _is_within_cwd(self, resolved_path: str) -> bool:
        """Check that a resolved path is within any allowed directory."""
        for allowed in [self._working_dir] + self._allow_dirs:
            try:
                common = os.path.commonpath([allowed, resolved_path])
                if common == allowed:
                    return True
            except ValueError:
                continue
        return False


class OutsideAllowedDirError(Exception):
    """Raised when a path is outside all allowed directories.

    Carries enough context for the caller to ask the user for permission
    and retry with the resolved directory added to the allow-list.
    """

    def __init__(self, raw_path: str, resolved_path: str, working_dir: str) -> None:
        self.raw_path = raw_path
        self.resolved_path = resolved_path
        self.working_dir = working_dir
        # Derive the top-level directory being requested
        # e.g. /Users/fer/other-project/src/foo.py → /Users/fer/other-project
        self.requested_dir = self._find_root_dir(resolved_path, working_dir)
        super().__init__(
            f"La ruta '{raw_path}' esta fuera del directorio de trabajo ({working_dir})"
        )

    @staticmethod
    def _find_root_dir(resolved: str, working_dir: str) -> str:
        """Find a sensible root directory to request access to.

        Walks up from the resolved path until we find a directory that
        looks like a project root (has .git) or is two levels deep from
        the common ancestor with working_dir.
        """
        # Walk up looking for a .git directory (project root)
        candidate = os.path.dirname(resolved)
        while candidate and candidate != os.path.dirname(candidate):
            if os.path.isdir(os.path.join(candidate, ".git")):
                return candidate
            candidate = os.path.dirname(candidate)

        # Fallback: use the immediate parent of the resolved path
        return os.path.dirname(resolved)
