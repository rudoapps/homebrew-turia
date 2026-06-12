"""JSON file-based configuration adapter."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

from ...application.ports.driven.config_port import ConfigPort
from ...domain.entities.config import AppConfig


class JsonConfigAdapter(ConfigPort):
    """Reads and writes configuration from JSON files in ~/.config/turia-agent/.

    Mirrors the behavior of agent_config.sh:
      - Config: ~/.config/turia-agent/config.json
      - Conversations: ~/.config/turia-agent/conversations.json
      - File-mtime caching for reads to avoid redundant disk I/O.
      - Per-project conversation tracking using git remote URL.
    """

    DEFAULT_API_URL = "https://agent.rudo.es/api/v1"
    CONVERSATION_TTL = 86400  # 24 hours default

    def __init__(self) -> None:
        self._config_dir = Path.home() / ".config" / "turia-agent"
        self._config_file = self._config_dir / "config.json"
        self._conversations_file = self._config_dir / "conversations.json"

        # Mtime cache for config reads
        self._cached_config: Optional[dict] = None
        self._cached_mtime: Optional[float] = None

        # Project ID cache
        self._project_id_cache: Optional[str] = None
        self._project_dir_cache: Optional[str] = None

        # Ensure config directory exists
        self._config_dir.mkdir(parents=True, exist_ok=True)
        if not self._config_file.exists():
            self._write_json(self._config_file, {
                "api_url": os.environ.get("AGENT_API_URL", self.DEFAULT_API_URL),
                "access_token": None,
                "refresh_token": None,
            })

    def get_config(self) -> AppConfig:
        """Load config from disk (with mtime caching)."""
        raw = self._read_config_cached()
        return AppConfig(
            api_url=raw.get("api_url", self.DEFAULT_API_URL),
            access_token=raw.get("access_token"),
            refresh_token=raw.get("refresh_token"),
            preferred_model=raw.get("preferred_model"),
            preview_mode=raw.get("preview_mode", False),
            debug_mode=raw.get("debug_mode", False),
        )

    def set_config(self, key: str, value: Any) -> None:
        """Write a single key to the config file."""
        raw = self._read_config_forced()
        raw[key] = value
        self._write_json(self._config_file, raw)
        # Invalidate cache
        self._cached_config = None
        self._cached_mtime = None

    def get_project_conversation(self) -> Optional[int]:
        """Get the last conversation ID for the current project."""
        if not self._conversations_file.exists():
            return None

        project_id = self._get_project_id()
        ttl = int(os.environ.get("TURIA_CONVERSATION_TTL", str(self.CONVERSATION_TTL)))

        try:
            data = json.loads(self._conversations_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

        entry = data.get(project_id)
        if not entry:
            return None

        conv_id = entry.get("conversation_id")
        updated_at = entry.get("updated_at", 0)

        if conv_id is not None and (time.time() - updated_at) < ttl:
            return int(conv_id)

        return None

    def set_project_conversation(self, conversation_id: int) -> None:
        """Save conversation ID for the current project."""
        project_id = self._get_project_id()

        if self._conversations_file.exists():
            try:
                data = json.loads(
                    self._conversations_file.read_text(encoding="utf-8")
                )
            except (json.JSONDecodeError, OSError):
                data = {}
        else:
            data = {}

        data[project_id] = {
            "conversation_id": conversation_id,
            "updated_at": int(time.time()),
        }
        self._write_json(self._conversations_file, data)

    def clear_project_conversation(self) -> None:
        """Remove stored conversation for the current project."""
        if not self._conversations_file.exists():
            return

        project_id = self._get_project_id()

        try:
            data = json.loads(self._conversations_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return

        data.pop(project_id, None)
        self._write_json(self._conversations_file, data)

    # ── Private helpers ─────────────────────────────────────────────────

    def _read_config_cached(self) -> dict:
        """Read config file with mtime-based caching."""
        if not self._config_file.exists():
            return {}

        try:
            current_mtime = self._config_file.stat().st_mtime
        except OSError:
            return {}

        if (
            self._cached_config is not None
            and self._cached_mtime == current_mtime
        ):
            return self._cached_config

        raw = self._read_config_forced()
        self._cached_config = raw
        self._cached_mtime = current_mtime
        return raw

    def _read_config_forced(self) -> dict:
        """Read config file without caching."""
        try:
            return json.loads(self._config_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _get_project_id(self) -> str:
        """Get project identifier from git remote URL or cwd.

        Mirrors get_project_id() from agent_config.sh.
        """
        current_dir = os.getcwd()

        if self._project_dir_cache == current_dir and self._project_id_cache:
            return self._project_id_cache

        # Try to get git remote URL
        try:
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                git_url = result.stdout.strip()
                # Normalize: remove .git suffix and user@ prefix, replace : with /
                normalized = re.sub(r"\.git$", "", git_url)
                normalized = re.sub(r".*@", "", normalized)
                normalized = normalized.replace(":", "/")
                self._project_id_cache = normalized
                self._project_dir_cache = current_dir
                return normalized
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass

        # Fallback to current directory
        self._project_id_cache = current_dir
        self._project_dir_cache = current_dir
        return current_dir

    @staticmethod
    def _write_json(path: Path, data: dict) -> None:
        """Atomically write JSON to a file using a temp file + rename."""
        tmp_path = path.with_suffix(".tmp")
        try:
            tmp_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            tmp_path.replace(path)
        except OSError:
            # Cleanup temp file on failure
            tmp_path.unlink(missing_ok=True)
            raise
