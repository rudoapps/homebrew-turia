"""OS-native notifications for long-running operations."""

from __future__ import annotations

import platform
import subprocess
import logging

logger = logging.getLogger(__name__)


def send_notification(title: str, message: str) -> None:
    """Send an OS-native notification.

    Works on macOS (osascript) and Linux (notify-send).
    Silently fails if neither is available.
    """
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.Popen(
                [
                    "osascript", "-e",
                    f'display notification "{message}" with title "{title}" sound name "Glass"',
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif system == "Linux":
            subprocess.Popen(
                ["notify-send", "--app-name=turia", title, message],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    except (FileNotFoundError, OSError) as e:
        logger.debug(f"Notification failed: {e}")
