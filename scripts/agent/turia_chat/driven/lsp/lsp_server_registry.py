"""Registry mapping project types to LSP server commands with auto-install."""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LSPServerConfig:
    """Configuration for an LSP server."""
    command: List[str]
    pip_package: Optional[str] = None  # pip package name (installed in venv)
    fallback: Optional[List[str]] = None
    fallback_pip_package: Optional[str] = None


_LSP_SERVERS: Dict[str, LSPServerConfig] = {
    "python": LSPServerConfig(
        command=["pyright", "--langserver", "--stdio"],
        pip_package="pyright",
        fallback=["pylsp"],
        fallback_pip_package="python-lsp-server",
    ),
    "python/django": LSPServerConfig(
        command=["pyright", "--langserver", "--stdio"],
        pip_package="pyright",
    ),
    "python/fastapi": LSPServerConfig(
        command=["pyright", "--langserver", "--stdio"],
        pip_package="pyright",
    ),
    "swift": LSPServerConfig(
        command=["sourcekit-lsp"],
        # Comes with Xcode — no pip install
    ),
    "ios": LSPServerConfig(
        command=["sourcekit-lsp"],
    ),
    "kotlin": LSPServerConfig(
        command=["kotlin-language-server"],
    ),
    "android": LSPServerConfig(
        command=["kotlin-language-server"],
    ),
    "node": LSPServerConfig(
        command=["typescript-language-server", "--stdio"],
    ),
    "node/react": LSPServerConfig(
        command=["typescript-language-server", "--stdio"],
    ),
    "node/next": LSPServerConfig(
        command=["typescript-language-server", "--stdio"],
    ),
    "node/vue": LSPServerConfig(
        command=["typescript-language-server", "--stdio"],
    ),
    "node/express": LSPServerConfig(
        command=["typescript-language-server", "--stdio"],
    ),
    "dart": LSPServerConfig(
        command=["dart", "language-server", "--protocol=lsp"],
    ),
    "flutter": LSPServerConfig(
        command=["dart", "language-server", "--protocol=lsp"],
    ),
    "go": LSPServerConfig(
        command=["gopls"],
    ),
    "rust": LSPServerConfig(
        command=["rust-analyzer"],
    ),
}


def _which(binary: str) -> Optional[str]:
    """Find a binary in PATH or in the current Python's venv bin."""
    found = shutil.which(binary)
    if found:
        return found
    # Also check the venv bin directory (pyright installed via venv pip)
    import sys
    venv_bin = os.path.join(os.path.dirname(sys.executable), binary)
    if os.path.isfile(venv_bin) and os.access(venv_bin, os.X_OK):
        return venv_bin
    return None


def detect_lsp_command(project_type: str) -> Optional[List[str]]:
    """Return the LSP server command for a project type, or None if unavailable."""
    config = _LSP_SERVERS.get(project_type)
    if not config:
        return None

    resolved = _which(config.command[0])
    if resolved:
        cmd = list(config.command)
        cmd[0] = resolved  # Use full path
        return cmd

    if config.fallback:
        resolved = _which(config.fallback[0])
        if resolved:
            cmd = list(config.fallback)
            cmd[0] = resolved
            return cmd

    return None


def get_pip_package(project_type: str) -> Optional[str]:
    """Get the pip package name for the LSP server, or None if already installed or no pip package."""
    config = _LSP_SERVERS.get(project_type)
    if not config:
        return None

    # Already available (check venv bin too)
    if _which(config.command[0]):
        return None
    if config.fallback and _which(config.fallback[0]):
        return None

    return config.pip_package or config.fallback_pip_package


def get_install_info(project_type: str) -> Optional[str]:
    """Get human-readable install instruction."""
    pkg = get_pip_package(project_type)
    if pkg:
        return f"pip install {pkg}"
    return None
