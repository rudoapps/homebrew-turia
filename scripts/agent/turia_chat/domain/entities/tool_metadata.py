"""Tool metadata constants: classification, display, and security limits."""

from __future__ import annotations

from typing import Any, Dict, Optional, Set, Tuple

# ── Tool classification ──────────────────────────────────────────────────

PARALLEL_SAFE_TOOLS: Set[str] = {"read_file", "search_code", "list_files", "git_info", "hover_info"}
"""Tools that only read state and can safely run concurrently."""

SEQUENTIAL_TOOLS: Set[str] = {"write_file", "edit_file", "run_command"}
"""Tools that mutate state and must run one at a time with user approval."""

# ── Display: icons and verbs (Spanish) ───────────────────────────────────

TOOL_ICONS: Dict[str, str] = {
    "read_file": "\u25b7",      # small triangle
    "write_file": "\u25c9",     # fisheye
    "edit_file": "\u25c9",      # fisheye
    "list_files": "\u25a1",     # white square
    "search_code": "\u25cb",    # white circle
    "run_command": "\u25b8",    # small right triangle
    "git_info": "\u25c7",       # white diamond
    "symbols": "\u25cb",        # white circle
    "find_definition": "\u25cb",# white circle
    "find_references": "\u25cb",# white circle
    "hover_info": "\u25cb",     # white circle
}

TOOL_VERBS: Dict[str, str] = {
    "read_file": "Leyendo",
    "write_file": "Escribiendo",
    "edit_file": "Editando",
    "list_files": "Listando",
    "search_code": "Buscando",
    "run_command": "Ejecutando",
    "git_info": "Git",
    "symbols": "Analizando",
    "find_definition": "Buscando definicion",
    "find_references": "Buscando referencias",
    "hover_info": "Consultando tipo",
}

# ── Security limits ──────────────────────────────────────────────────────

MAX_FILE_SIZE: int = 50_000
"""Maximum characters to return from read_file (truncate beyond this)."""

MAX_OUTPUT_LINES: int = 200
"""Maximum lines to return from command output."""

MAX_COMMAND_TIMEOUT: int = 120
"""Default timeout in seconds for run_command."""

MAX_COMMAND_TIMEOUT_HARD: int = 600
"""Absolute maximum timeout in seconds (10 minutes) for run_command."""

MAX_SEARCH_RESULTS: int = 50
"""Maximum matches to return from search_code / list_files."""

# ── Blocked files ────────────────────────────────────────────────────────

BLOCKED_FILE_EXTENSIONS: Set[str] = {
    ".pem", ".key", ".p12", ".pfx", ".jks", ".keystore",
    ".der", ".cer", ".crt", ".cert",
    ".sqlite", ".sqlite3", ".db",
}
"""File extensions that should never be read or written by tools."""

BLOCKED_FILE_NAMES: Set[str] = {
    "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa",
    ".ssh/authorized_keys", ".ssh/known_hosts",
    ".netrc", ".npmrc_auth",
}
"""Specific file names that should never be accessed."""

# ── Sensitive patterns (need approval before write) ──────────────────────

SENSITIVE_PATTERNS: list[str] = [
    ".env",
    ".env.local",
    ".env.production",
    "credentials",
    "secrets",
    "password",
    "token",
    "package.json",
    "package-lock.json",
    "Dockerfile",
    "docker-compose",
    ".yml",
    ".yaml",
    "Makefile",
    "Gemfile",
    "Pipfile",
    "requirements.txt",
    "pyproject.toml",
    "Cargo.toml",
    "go.mod",
    ".gitignore",
    ".github",
]
"""Path substrings that indicate a file needing extra approval before writes."""


# ── Helper ───────────────────────────────────────────────────────────────

def get_tool_detail(
    name: str,
    input_dict: Dict[str, Any],
) -> Tuple[str, str, str, str]:
    """Extract display information for a tool call.

    Args:
        name: The tool name (e.g. "read_file").
        input_dict: The tool input parameters.

    Returns:
        A tuple of (icon, verb, detail, action_msg) where:
          - icon: unicode character for the tool
          - verb: Spanish verb (e.g. "Leyendo")
          - detail: short description of what the tool is doing
          - action_msg: full action message for display
    """
    icon = TOOL_ICONS.get(name, "\u25cb")
    verb = TOOL_VERBS.get(name, name)

    if name == "read_file":
        path = input_dict.get("path", input_dict.get("file_path", "?"))
        detail = _short_path(path)
        action_msg = f"{verb} {detail}"

    elif name == "write_file":
        path = input_dict.get("path", input_dict.get("file_path", "?"))
        detail = _short_path(path)
        action_msg = f"{verb} {detail}"

    elif name == "edit_file":
        path = input_dict.get("path", input_dict.get("file_path", "?"))
        detail = _short_path(path)
        action_msg = f"{verb} {detail}"

    elif name == "list_files":
        path = input_dict.get("path", input_dict.get("directory", "."))
        pattern = input_dict.get("pattern", "")
        detail = _short_path(path)
        if pattern:
            detail = f"{detail} ({pattern})"
        action_msg = f"{verb} {detail}"

    elif name == "search_code":
        query = input_dict.get("pattern", input_dict.get("query", "?"))
        if len(query) > 40:
            query = query[:37] + "..."
        detail = f'"{query}"'
        action_msg = f'{verb} {detail}'

    elif name == "run_command":
        cmd = input_dict.get("command", "?")
        if len(cmd) > 60:
            cmd = cmd[:57] + "..."
        detail = cmd
        action_msg = f"{verb} `{detail}`"

    elif name == "git_info":
        sub = input_dict.get("command", input_dict.get("subcommand", "status"))
        detail = sub
        action_msg = f"{verb} {detail}"

    elif name == "symbols":
        path = input_dict.get("path", "?")
        detail = _short_path(path)
        action_msg = f"{verb} {detail}"

    elif name == "find_definition":
        symbol = input_dict.get("symbol", "?")
        detail = symbol
        action_msg = f"{verb} de `{symbol}`"

    elif name == "find_references":
        symbol = input_dict.get("symbol", "?")
        detail = symbol
        action_msg = f"{verb} de `{symbol}`"

    elif name == "hover_info":
        path = input_dict.get("path", "?")
        line = input_dict.get("line", "?")
        detail = f"{_short_path(path)}:{line}"
        action_msg = f"{verb} en {detail}"

    else:
        detail = name
        action_msg = f"{verb} {detail}"

    return icon, verb, detail, action_msg


def _short_path(path: str) -> str:
    """Shorten a path for display, keeping the last 2-3 components."""
    import os
    parts = path.replace("\\", "/").split("/")
    if len(parts) <= 3:
        return path
    return os.path.join("...", *parts[-3:])
