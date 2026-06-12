"""Entry point for `python3 -m turia_chat`."""

import os
import sys
import traceback


def _diag(msg: str) -> None:
    """Print a diagnostic message to stderr when --diagnose is enabled."""
    sys.stderr.write(f"[turia:diag] {msg}\n")
    sys.stderr.flush()


def main() -> int:
    diagnose = "--diagnose" in sys.argv or os.environ.get("TURIA_DIAGNOSE") == "1"
    debug = "--debug" in sys.argv or diagnose

    if diagnose:
        _diag(f"python={sys.executable}")
        _diag(f"version={sys.version.split()[0]}")
        _diag(f"platform={sys.platform}")
        _diag(f"cwd={os.getcwd()}")
        _diag("importing Container...")

    from .container import Container
    from .driving.cli.app import App

    if diagnose:
        _diag("creating Container...")
    container = Container(debug=debug)

    if diagnose:
        _diag("creating App...")
    app = App(container)

    if diagnose:
        _diag("running app...")
    return app.run()


if __name__ == "__main__":
    try:
        _rc = main()
        if os.environ.get("TURIA_DIAGNOSE") == "1" or "--diagnose" in sys.argv:
            sys.stderr.write(f"[turia:diag] main() returned {_rc}\n")
        sys.exit(_rc)
    except KeyboardInterrupt:
        sys.exit(130)
    except SystemExit:
        raise
    except BaseException:
        # Never let the CLI exit silently — print the full traceback to stderr.
        sys.stderr.write("\n[turia] Error fatal durante el arranque:\n")
        traceback.print_exc()
        sys.stderr.write(
            "\n[turia] Si esto persiste, ejecuta 'TURIA_DIAGNOSE=1 turia ai' "
            "y comparte el error.\n"
        )
        sys.exit(1)
