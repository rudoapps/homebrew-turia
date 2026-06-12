#!/usr/bin/env python3
"""Turia Chat — entry point.

Usage:
  python3 chat.py "hello"
  python3 chat.py --conversation 42 "continue this"
  python3 chat.py --new "start fresh"
  python3 chat.py --debug "debug mode"
"""

from __future__ import annotations

import sys


def main() -> int:
    """Create the DI container, build the app, and run it."""
    # Check for --debug flag early so we can pass it to the container
    debug = "--debug" in sys.argv

    from turia_chat.container import Container
    from turia_chat.driving.cli.app import App

    container = Container(debug=debug)
    app = App(container=container)
    return app.run()


if __name__ == "__main__":
    sys.exit(main())
