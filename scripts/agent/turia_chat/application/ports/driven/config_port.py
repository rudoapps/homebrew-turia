"""Port (interface) for configuration storage."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from ....domain.entities.config import AppConfig


class ConfigPort(ABC):
    """Abstract interface for reading and writing application configuration."""

    @abstractmethod
    def get_config(self) -> AppConfig:
        """Load and return the current application configuration.

        Returns:
            An AppConfig instance populated from persistent storage.
        """
        ...

    @abstractmethod
    def set_config(self, key: str, value: Any) -> None:
        """Persist a single configuration value.

        Args:
            key: The configuration key (e.g. "access_token", "preferred_model").
            value: The value to store. Use None to clear.
        """
        ...

    @abstractmethod
    def get_project_conversation(self) -> Optional[int]:
        """Get the last conversation ID for the current project.

        Uses the git remote URL (or cwd) to identify the project.
        Returns None if no conversation exists or the TTL has expired.
        """
        ...

    @abstractmethod
    def set_project_conversation(self, conversation_id: int) -> None:
        """Save the conversation ID for the current project.

        Args:
            conversation_id: The server-assigned conversation ID.
        """
        ...

    @abstractmethod
    def clear_project_conversation(self) -> None:
        """Remove the stored conversation for the current project."""
        ...
