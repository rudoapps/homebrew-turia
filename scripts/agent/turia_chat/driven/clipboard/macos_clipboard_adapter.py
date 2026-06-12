"""macOS clipboard adapter using pbcopy and osascript."""

from __future__ import annotations

import subprocess
from typing import Optional

from ...application.ports.driven.clipboard_port import ClipboardPort


class MacOSClipboardAdapter(ClipboardPort):
    """Clipboard access for macOS using system utilities.

    - Text copy: pbcopy
    - Image detection: osascript (clipboard info)
    - Image retrieval: pngpaste (preferred) or osascript fallback
    """

    def copy_text(self, text: str) -> None:
        """Copy text to the macOS clipboard via pbcopy."""
        try:
            proc = subprocess.run(
                ["pbcopy"],
                input=text.encode("utf-8"),
                capture_output=True,
                timeout=5,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"pbcopy failed: {proc.stderr.decode()}")
        except FileNotFoundError:
            raise RuntimeError("pbcopy not found — not running on macOS?")
        except subprocess.TimeoutExpired:
            raise RuntimeError("pbcopy timed out")

    def get_clipboard_image(self) -> Optional[bytes]:
        """Retrieve image data from the clipboard as PNG bytes.

        Returns None if the clipboard doesn't contain an image.
        """
        if not self._has_clipboard_image():
            return None

        # Try pngpaste first (faster, cleaner output)
        png_data = self._try_pngpaste()
        if png_data:
            return png_data

        # Fallback to osascript
        return self._try_osascript()

    def _has_clipboard_image(self) -> bool:
        """Check if the clipboard contains image data."""
        try:
            result = subprocess.run(
                ["osascript", "-e", "clipboard info"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                info = result.stdout
                return any(fmt in info for fmt in ("TIFF", "PNG", "JPEG", "GIF"))
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass
        return False

    def _try_pngpaste(self) -> Optional[bytes]:
        """Try to get clipboard image via pngpaste."""
        try:
            result = subprocess.run(
                ["pngpaste", "-"],
                capture_output=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout:
                return result.stdout
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass
        return None

    def _try_osascript(self) -> Optional[bytes]:
        """Try to get clipboard image via osascript as PNG."""
        script = 'set imgData to the clipboard as <<class PNGf>>\nreturn imgData'
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout:
                return result.stdout
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass
        return None
