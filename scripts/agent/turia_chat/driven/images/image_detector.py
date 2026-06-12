"""Detect image file paths in text and encode them as base64 attachments."""

from __future__ import annotations

import base64
import os
import re
import subprocess
import sys
from typing import List, Optional, Tuple

from ...domain.entities.message import ImageAttachment

# Supported image extensions and their MIME types.
_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
}

_IMAGE_EXT_RE = r"\.(png|jpg|jpeg|gif|webp|bmp|svg)"

# Patterns that match image file paths embedded in free text.
# Group 0 captures the full path (with possible leading ~, ./, or ../).
_PATH_PATTERNS: List[re.Pattern[str]] = [
    # Absolute or home-relative: /foo/bar.png, ~/Desktop/shot.jpg
    re.compile(
        r"(?:^|\s)(~?(?:/[^\s]+)+" + _IMAGE_EXT_RE + r")(?=\s|$)",
        re.IGNORECASE,
    ),
    # Dot-relative: ./img.png, ../assets/logo.webp
    re.compile(
        r"(?:^|\s)(\.\.?/[^\s]+" + _IMAGE_EXT_RE + r")(?=\s|$)",
        re.IGNORECASE,
    ),
]


class ImageDetector:
    """Scan text for image file paths, read and base64-encode them.

    This mirrors the ``detect_and_encode_images`` / ``remove_image_paths_from_text``
    helpers from ``agent_config.sh``.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect_images(self, text: str) -> Tuple[str, List[ImageAttachment]]:
        """Find image paths in *text*, encode the files, and strip the paths.

        Args:
            text: The raw user input that may contain image file paths.

        Returns:
            A tuple of ``(cleaned_text, attachments)`` where *cleaned_text*
            has the image paths removed and *attachments* is a (possibly
            empty) list of :class:`ImageAttachment` instances.
        """
        paths_found: List[str] = []

        for pattern in _PATH_PATTERNS:
            for match in pattern.finditer(text):
                # Group 1 is the full path (without leading whitespace).
                paths_found.append(match.group(1))

        attachments: List[ImageAttachment] = []
        for raw_path in paths_found:
            attachment = self._encode_path(raw_path)
            if attachment is not None:
                attachments.append(attachment)

        cleaned = self._strip_paths(text, paths_found)
        return cleaned, attachments

    def check_clipboard_image(self) -> Optional[ImageAttachment]:
        """Return an :class:`ImageAttachment` from the macOS clipboard, or ``None``.

        On non-macOS platforms this always returns ``None``.
        """
        if sys.platform != "darwin":
            return None

        if not self._clipboard_has_image():
            return None

        data = self._clipboard_image_bytes()
        if data is None:
            return None

        encoded = base64.b64encode(data).decode("utf-8")
        return ImageAttachment(data=encoded, media_type="image/png")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _encode_path(raw_path: str) -> Optional[ImageAttachment]:
        """Read a single image file and return an attachment, or ``None``."""
        expanded = os.path.expanduser(raw_path)

        # Resolve relative paths against cwd.
        if not os.path.isabs(expanded):
            expanded = os.path.abspath(expanded)

        if not os.path.isfile(expanded):
            print(
                f"  [warning] Image file not found, skipping: {raw_path}",
                file=sys.stderr,
            )
            return None

        ext = os.path.splitext(expanded)[1].lower()
        media_type = _MEDIA_TYPES.get(ext, "image/png")

        try:
            with open(expanded, "rb") as fh:
                data = base64.b64encode(fh.read()).decode("utf-8")
        except OSError as exc:
            print(
                f"  [warning] Could not read image {raw_path}: {exc}",
                file=sys.stderr,
            )
            return None

        return ImageAttachment(data=data, media_type=media_type)

    @staticmethod
    def _strip_paths(text: str, paths: List[str]) -> str:
        """Remove the literal *paths* from *text* and tidy whitespace."""
        for path in paths:
            text = text.replace(path, " ")

        # Collapse multiple spaces.
        return " ".join(text.split())

    # ------------------------------------------------------------------
    # Clipboard helpers (macOS)
    # ------------------------------------------------------------------

    @staticmethod
    def _clipboard_has_image() -> bool:
        """Check whether the macOS clipboard contains image data."""
        try:
            result = subprocess.run(
                ["osascript", "-e", "clipboard info"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return False
            return any(
                token in result.stdout
                for token in ("TIFF", "PNG", "JPEG", "GIF")
            )
        except (subprocess.SubprocessError, OSError):
            return False

    @staticmethod
    def _clipboard_image_bytes() -> Optional[bytes]:
        """Retrieve clipboard image data as PNG bytes."""
        # Prefer pngpaste if installed.
        try:
            result = subprocess.run(
                ["pngpaste", "-"],
                capture_output=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout:
                return result.stdout
        except FileNotFoundError:
            pass

        # Fallback: osascript to get PNG data.
        script = 'set imgData to the clipboard as «class PNGf»\nreturn imgData'
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout:
                return result.stdout
        except (subprocess.SubprocessError, OSError):
            pass

        return None
