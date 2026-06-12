"""Git wrapper for cloning and updating skill marketplaces.

Supports `x-token-auth` URL injection for private Bitbucket repos. The
public surface is three functions so other code doesn't need to shell out
to git directly.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger(__name__)


class GitError(RuntimeError):
    """Raised when a git operation fails."""


def clone(url: str, dest: Path, token: Optional[str] = None) -> None:
    """Clone `url` into `dest`. Injects `x-token-auth:<token>` if provided."""
    if dest.exists():
        raise GitError(f"destination already exists: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    target_url = _inject_token(url, token) if token else url
    _run(["git", "clone", "--depth", "1", target_url, str(dest)])


def pull(repo: Path) -> None:
    """Fast-forward `repo` to its remote HEAD."""
    if not (repo / ".git").exists():
        raise GitError(f"not a git repo: {repo}")
    _run(["git", "-C", str(repo), "fetch", "--depth", "1", "origin"])
    _run(["git", "-C", str(repo), "reset", "--hard", "FETCH_HEAD"])


def current_commit(repo: Path) -> str:
    """Return the short SHA of HEAD, or an empty string if unreadable."""
    if not (repo / ".git").exists():
        return ""
    try:
        out = subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
        )
        return out.strip()
    except (subprocess.SubprocessError, OSError):
        return ""


def remove(repo: Path) -> None:
    """Delete a cloned repo. Safe no-op if the directory is absent."""
    if repo.exists():
        shutil.rmtree(repo)


def _inject_token(url: str, token: str) -> str:
    """Insert `x-token-auth:<token>@` into the URL's netloc."""
    parsed = urlparse(url)
    if "@" in parsed.netloc:
        return url
    new_netloc = f"x-token-auth:{token}@{parsed.netloc}"
    return urlunparse(parsed._replace(netloc=new_netloc))


def _run(cmd: list) -> None:
    """Run a command, raising GitError on failure."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise GitError(f"git invocation failed: {exc}") from exc
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise GitError(stderr or f"git failed: {' '.join(cmd)}")
