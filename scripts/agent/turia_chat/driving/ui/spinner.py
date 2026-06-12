"""Spinner with elapsed time display."""

from __future__ import annotations

import sys
import threading
import time
from typing import Optional

from .console import get_console

# Braille spinner frames
_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


class Spinner:
    """A spinner that shows elapsed time, matching the bash turia agent UX.

    Uses a background thread to update the spinner animation and elapsed
    time counter on stderr, without interfering with Rich console output.
    """

    def __init__(self) -> None:
        self._running = False
        self._message = ""
        self._thread: Optional[threading.Thread] = None
        self._start_time: float = 0.0
        self._frame: int = 0
        self._console = get_console()

    @property
    def is_running(self) -> bool:
        """Return True if the spinner is currently visible."""
        return self._running

    def start(self, message: str = "Procesando...") -> None:
        """Start the spinner with the given message."""
        self.stop()
        self._message = message
        self._running = True
        self._start_time = time.time()
        self._frame = 0
        sys.stderr.write("\033[?25l")  # Hide cursor
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def _spin(self) -> None:
        """Background thread: animate spinner with elapsed time."""
        while self._running:
            frame = _FRAMES[self._frame % len(_FRAMES)]
            elapsed = time.time() - self._start_time
            line = f"\r\033[K  \033[36m{frame}\033[0m {self._message} \033[2m({elapsed:.1f}s)\033[0m"
            sys.stderr.write(line)
            sys.stderr.flush()
            self._frame += 1
            time.sleep(0.08)

    def update(self, message: str) -> None:
        """Update the spinner message."""
        self._message = message

    def stop(self, final_message: Optional[str] = None, status: str = "success") -> None:
        """Stop the spinner and optionally display a final status line.

        Args:
            final_message: Optional message to show after stopping.
            status: One of "success", "error", "info" — controls the icon.
        """
        if not self._running and self._thread is None:
            if final_message:
                self._show_final(final_message, status, 0.0)
            return

        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=0.3)
            self._thread = None

        # Clear spinner line and restore cursor
        try:
            sys.stderr.write("\r\033[K\033[?25h")
            sys.stderr.flush()
        except OSError:
            pass

        if final_message:
            elapsed = time.time() - self._start_time if self._start_time else 0.0
            self._show_final(final_message, status, elapsed)

    def _show_final(self, message: str, status: str, elapsed: float) -> None:
        """Print a final status line after stopping."""
        icons = {
            "success": "[success]\u2713[/success]",
            "error": "[error]\u2717[/error]",
            "info": "[info]\u2139[/info]",
        }
        icon = icons.get(status, icons["info"])
        elapsed_str = f" [dim]({elapsed:.1f}s)[/dim]" if elapsed > 0.5 else ""
        self._console.print(f"  {icon} {message}{elapsed_str}")
