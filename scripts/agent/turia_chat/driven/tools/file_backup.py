"""File backup system for safe write/edit operations."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class BackupInfo:
    """Information about a single file backup.

    Attributes:
        backup_id: Unique identifier (timestamp-based).
        original_path: The absolute path of the original file.
        backup_path: The absolute path to the backup copy.
        timestamp: Unix timestamp when the backup was created.
        size: File size in bytes.
    """

    backup_id: str
    original_path: str
    backup_path: str
    timestamp: float
    size: int


class FileBackup:
    """Creates and manages file backups before modifications.

    Backups are stored in a temporary directory with a metadata index
    so they can be listed and restored.

    Args:
        backup_dir: Directory to store backups.  Defaults to a temp dir
                    under the system temp path.
    """

    def __init__(self, backup_dir: Optional[str] = None) -> None:
        if backup_dir is None:
            backup_dir = os.path.join(
                tempfile.gettempdir(), "turia_chat_backups"
            )
        self._backup_dir = backup_dir
        self._index_path = os.path.join(self._backup_dir, "index.json")
        os.makedirs(self._backup_dir, exist_ok=True)

    def create_backup(self, path: str) -> Optional[str]:
        """Create a backup of a file before modification.

        Args:
            path: Absolute path to the file to back up.

        Returns:
            The backup file path, or None if the source file does not exist.
        """
        if not os.path.isfile(path):
            return None

        ts = time.time()
        backup_id = f"{int(ts * 1000)}"
        basename = os.path.basename(path)
        backup_name = f"{backup_id}_{basename}"
        backup_path = os.path.join(self._backup_dir, backup_name)

        shutil.copy2(path, backup_path)

        # Update index
        index = self._load_index()
        index.append({
            "backup_id": backup_id,
            "original_path": path,
            "backup_path": backup_path,
            "timestamp": ts,
            "size": os.path.getsize(path),
        })

        # Keep only last 50 backups
        if len(index) > 50:
            old = index[:-50]
            index = index[-50:]
            for entry in old:
                try:
                    os.remove(entry["backup_path"])
                except OSError:
                    pass

        self._save_index(index)
        return backup_path

    def list_backups(self) -> List[BackupInfo]:
        """List recent backups, most recent first.

        Returns:
            List of BackupInfo objects ordered by timestamp descending.
        """
        index = self._load_index()
        result = []
        for entry in reversed(index):
            result.append(BackupInfo(
                backup_id=entry["backup_id"],
                original_path=entry["original_path"],
                backup_path=entry["backup_path"],
                timestamp=entry["timestamp"],
                size=entry.get("size", 0),
            ))
        return result

    def restore_backup(self, backup_id: str) -> bool:
        """Restore a file from a backup.

        Args:
            backup_id: The ID of the backup to restore.

        Returns:
            True if the restore succeeded, False otherwise.
        """
        index = self._load_index()
        for entry in index:
            if entry["backup_id"] == backup_id:
                backup_path = entry["backup_path"]
                original_path = entry["original_path"]
                if os.path.isfile(backup_path):
                    # Ensure parent directory exists
                    os.makedirs(os.path.dirname(original_path), exist_ok=True)
                    shutil.copy2(backup_path, original_path)
                    return True
                return False
        return False

    # ── Internal helpers ─────────────────────────────────────────────────

    def _load_index(self) -> list:
        """Load the backup index from disk."""
        if not os.path.isfile(self._index_path):
            return []
        try:
            with open(self._index_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []

    def _save_index(self, index: list) -> None:
        """Save the backup index to disk."""
        with open(self._index_path, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)
