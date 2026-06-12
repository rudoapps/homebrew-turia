"""Persistent registry of installed marketplaces and packs.

Stored as `~/.config/turia-agent/installed.json`. Tracks:

  {
    "marketplaces": {
      "<name>": {"url": "...", "commit": "<sha>"}
    },
    "packs": {
      "<pack>": {"marketplace": "<name>", "source_path": "anturiar", "commit": "<sha>"}
    }
  }
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class MarketplaceEntry:
    url: str
    commit: str = ""


@dataclass
class PackEntry:
    marketplace: str
    source_path: str
    commit: str = ""


@dataclass
class Registry:
    """In-memory view of the installed state, backed by a JSON file."""

    path: Path
    marketplaces: Dict[str, MarketplaceEntry] = field(default_factory=dict)
    packs: Dict[str, PackEntry] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "Registry":
        reg = cls(path=path)
        if not path.is_file():
            return reg
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not read %s: %s", path, exc)
            return reg
        for name, raw in (data.get("marketplaces") or {}).items():
            reg.marketplaces[name] = MarketplaceEntry(
                url=str(raw.get("url", "")),
                commit=str(raw.get("commit", "")),
            )
        for pack, raw in (data.get("packs") or {}).items():
            reg.packs[pack] = PackEntry(
                marketplace=str(raw.get("marketplace", "")),
                source_path=str(raw.get("source_path", "")),
                commit=str(raw.get("commit", "")),
            )
        return reg

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "marketplaces": {
                name: {"url": m.url, "commit": m.commit}
                for name, m in self.marketplaces.items()
            },
            "packs": {
                name: {
                    "marketplace": p.marketplace,
                    "source_path": p.source_path,
                    "commit": p.commit,
                }
                for name, p in self.packs.items()
            },
        }
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    def packs_from(self, marketplace: str) -> Dict[str, PackEntry]:
        return {
            name: pack
            for name, pack in self.packs.items()
            if pack.marketplace == marketplace
        }
