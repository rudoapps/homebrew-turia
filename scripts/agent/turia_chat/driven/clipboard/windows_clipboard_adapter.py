"""Windows clipboard adapter."""

from __future__ import annotations

import subprocess
from typing import Optional

from ...application.ports.driven.clipboard_port import ClipboardPort


class WindowsClipboardAdapter(ClipboardPort):
    """Clipboard access for Windows using PowerShell."""

    def copy_text(self, text: str) -> None:
        """Copy text to the clipboard via clip.exe."""
        try:
            subprocess.run(
                ["clip.exe"],
                input=text.encode("utf-16-le"),
                capture_output=True,
                timeout=5,
            )
        except FileNotFoundError:
            raise RuntimeError("clip.exe no encontrado")
        except subprocess.TimeoutExpired:
            raise RuntimeError("Clipboard timeout")

    def get_clipboard_image(self) -> Optional[bytes]:
        """Image clipboard not supported on Windows yet."""
        return None
