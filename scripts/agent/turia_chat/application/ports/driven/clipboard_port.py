"""Port (interface) for clipboard operations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class ClipboardPort(ABC):
    """Abstract interface for system clipboard access."""

    @abstractmethod
    def copy_text(self, text: str) -> None:
        """Copy text to the system clipboard.

        Args:
            text: The text to place on the clipboard.
        """
        ...

    @abstractmethod
    def get_clipboard_image(self) -> Optional[bytes]:
        """Retrieve image data from the system clipboard.

        Returns:
            Raw PNG image bytes if the clipboard contains an image, else None.
        """
        ...
