"""Marketplace service — add/install/update/uninstall skill packs.

Directory layout under `~/.config/turia-agent/`:

    marketplaces/<name>/        cloned git repo
    skills/<pack>/              symlink → marketplaces/<name>/<source-path>
    installed.json              registry
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from ...driven.skills import fetcher
from ...driven.skills.registry import (
    MarketplaceEntry,
    PackEntry,
    Registry,
)

logger = logging.getLogger(__name__)


@dataclass
class InstalledPack:
    name: str
    marketplace: str
    source_path: str
    skills_path: Path
    commit: str


class MarketplaceError(RuntimeError):
    """Raised for user-visible marketplace operation failures."""


class MarketplaceService:
    """Add marketplaces and install/update/uninstall their skill packs."""

    def __init__(self, root: Optional[Path] = None) -> None:
        self._root = root or (Path.home() / ".config" / "turia-agent")
        self._marketplaces_dir = self._root / "marketplaces"
        self._skills_dir = self._root / "skills"
        self._registry_path = self._root / "installed.json"
        self._registry = Registry.load(self._registry_path)

    # ── Marketplaces ────────────────────────────────────────────────────

    def add_marketplace(
        self,
        url: str,
        name: Optional[str] = None,
        token: Optional[str] = None,
    ) -> str:
        """Clone a marketplace. Returns the resolved name."""
        name = name or _name_from_url(url)
        if not name:
            raise MarketplaceError(f"could not derive a name from URL: {url}")
        if name in self._registry.marketplaces:
            raise MarketplaceError(f"marketplace '{name}' already exists")

        dest = self._marketplaces_dir / name
        try:
            fetcher.clone(url, dest, token=token)
        except fetcher.GitError as exc:
            raise MarketplaceError(f"clone failed: {exc}") from exc

        self._registry.marketplaces[name] = MarketplaceEntry(
            url=url,
            commit=fetcher.current_commit(dest),
        )
        self._registry.save()
        return name

    def list_marketplaces(self) -> Dict[str, MarketplaceEntry]:
        return dict(self._registry.marketplaces)

    def remove_marketplace(self, name: str) -> List[str]:
        """Remove a marketplace and all packs installed from it.

        Returns the list of packs that were uninstalled.
        """
        if name not in self._registry.marketplaces:
            raise MarketplaceError(f"unknown marketplace: {name}")
        uninstalled: List[str] = []
        for pack_name in list(self._registry.packs_from(name).keys()):
            self._remove_pack_link(pack_name)
            uninstalled.append(pack_name)
            self._registry.packs.pop(pack_name, None)
        fetcher.remove(self._marketplaces_dir / name)
        self._registry.marketplaces.pop(name, None)
        self._registry.save()
        return uninstalled

    # ── Packs ───────────────────────────────────────────────────────────

    def install_pack(
        self,
        spec: str,
        marketplace: Optional[str] = None,
    ) -> InstalledPack:
        """Install `<source-path>[@<marketplace>]` as a pack."""
        source_path, mp_name = _parse_spec(spec, marketplace)
        mp_name = mp_name or self._single_marketplace()
        if mp_name not in self._registry.marketplaces:
            raise MarketplaceError(f"unknown marketplace: {mp_name}")

        mp_dir = self._marketplaces_dir / mp_name
        pack_dir = (mp_dir / source_path).resolve()
        if not pack_dir.is_dir():
            raise MarketplaceError(
                f"pack not found in marketplace: {source_path} (looked in {mp_dir})"
            )
        if not (pack_dir / "skills").is_dir():
            raise MarketplaceError(
                f"pack '{source_path}' has no skills/ directory"
            )

        pack_name = _flatten(source_path)
        if pack_name in self._registry.packs:
            raise MarketplaceError(f"pack '{pack_name}' already installed")

        link_path = self._skills_dir / pack_name
        self._skills_dir.mkdir(parents=True, exist_ok=True)
        if link_path.exists() or link_path.is_symlink():
            raise MarketplaceError(f"path exists and would be overwritten: {link_path}")
        link_path.symlink_to(pack_dir, target_is_directory=True)

        commit = fetcher.current_commit(mp_dir)
        self._registry.packs[pack_name] = PackEntry(
            marketplace=mp_name,
            source_path=source_path,
            commit=commit,
        )
        self._registry.save()

        return InstalledPack(
            name=pack_name,
            marketplace=mp_name,
            source_path=source_path,
            skills_path=link_path,
            commit=commit,
        )

    def uninstall_pack(self, pack_name: str) -> None:
        if pack_name not in self._registry.packs:
            raise MarketplaceError(f"pack not installed: {pack_name}")
        self._remove_pack_link(pack_name)
        self._registry.packs.pop(pack_name, None)
        self._registry.save()

    def update(self, target: Optional[str] = None) -> List[Tuple[str, str, str]]:
        """Pull one or all marketplaces. Returns [(marketplace, old_commit, new_commit)]."""
        if target and target != "all":
            names = [target]
            if target not in self._registry.marketplaces:
                raise MarketplaceError(f"unknown marketplace: {target}")
        else:
            names = list(self._registry.marketplaces.keys())

        results: List[Tuple[str, str, str]] = []
        for name in names:
            mp_dir = self._marketplaces_dir / name
            old_commit = self._registry.marketplaces[name].commit
            try:
                fetcher.pull(mp_dir)
            except fetcher.GitError as exc:
                raise MarketplaceError(f"pull failed for {name}: {exc}") from exc
            new_commit = fetcher.current_commit(mp_dir)
            self._registry.marketplaces[name].commit = new_commit
            for pack in self._registry.packs_from(name).values():
                pack.commit = new_commit
            results.append((name, old_commit, new_commit))
        self._registry.save()
        return results

    def list_installed(self) -> Dict[str, PackEntry]:
        return dict(self._registry.packs)

    # ── internals ───────────────────────────────────────────────────────

    def _single_marketplace(self) -> str:
        names = list(self._registry.marketplaces.keys())
        if len(names) == 1:
            return names[0]
        if not names:
            raise MarketplaceError("no marketplaces configured — run `/skills marketplace add <url>`")
        raise MarketplaceError(
            f"multiple marketplaces ({', '.join(names)}) — specify `<pack>@<marketplace>`"
        )

    def _remove_pack_link(self, pack_name: str) -> None:
        link = self._skills_dir / pack_name
        if link.is_symlink() or link.exists():
            if link.is_symlink():
                link.unlink()
            else:
                import shutil
                shutil.rmtree(link)


# ── helpers ─────────────────────────────────────────────────────────────


def _name_from_url(url: str) -> str:
    parsed = urlparse(url)
    last = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    if last.endswith(".git"):
        last = last[:-4]
    return last


def _parse_spec(
    spec: str, explicit_marketplace: Optional[str]
) -> Tuple[str, Optional[str]]:
    """Parse `<pack>` or `<pack>@<marketplace>`. Explicit arg wins."""
    if "@" in spec:
        source_path, _, mp_name = spec.partition("@")
    else:
        source_path, mp_name = spec, None
    return source_path.strip("/"), explicit_marketplace or mp_name or None


def _flatten(source_path: str) -> str:
    """`python/django` → `python-django`."""
    return source_path.replace("/", "-").strip("-")
