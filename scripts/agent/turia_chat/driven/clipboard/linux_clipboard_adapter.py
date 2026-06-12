"""Linux clipboard adapter using xclip/xsel."""

from __future__ import annotations

import shutil
import subprocess
from typing import Optional

from ...application.ports.driven.clipboard_port import ClipboardPort


class LinuxClipboardAdapter(ClipboardPort):
    """Clipboard access for Linux using xclip or xsel."""

    def copy_text(self, text: str) -> None:
        """Copy text to the clipboard via xclip or xsel."""
        if shutil.which("xclip"):
            cmd = ["xclip", "-selection", "clipboard"]
        elif shutil.which("xsel"):
            cmd = ["xsel", "--clipboard", "--input"]
        else:
            raise RuntimeError(
                "No se encontro xclip ni xsel. "
                "Instala uno: sudo apt install xclip"
            )
        try:
            subprocess.run(
                cmd,
                input=text.encode("utf-8"),
                capture_output=True,
                timeout=5,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("Clipboard timeout")

    def get_clipboard_image(self) -> Optional[bytes]:
        """Retrieve image from clipboard via xclip."""
        if not shutil.which("xclip"):
            return None
        try:
            result = subprocess.run(
                ["xclip", "-selection", "clipboard", "-t", "image/png", "-o"],
                capture_output=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout:
                return result.stdout
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass
        return None
