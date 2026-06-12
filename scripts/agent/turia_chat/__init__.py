"""Turia Chat - Clean Architecture CLI for the Turia Agent API."""

import os as _os


def _read_version() -> str:
    """Read version from VERSION file or package metadata."""
    # 1. Try VERSION file (Homebrew / development)
    _here = _os.path.dirname(_os.path.abspath(__file__))
    for _rel in (
        _os.path.join(_here, "..", "..", "..", "VERSION"),
        _os.path.join(_here, "..", "..", "..", "..", "VERSION"),
    ):
        _path = _os.path.normpath(_rel)
        if _os.path.isfile(_path):
            with open(_path) as _f:
                return _f.read().strip()

    # 2. Try package metadata (pip install)
    try:
        from importlib.metadata import version
        return version("turia")
    except Exception:
        pass

    return "dev"


__version__ = _read_version()
