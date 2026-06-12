"""Non-REPL entry point for `turia skills ...` shell commands.

Runs a single skills subcommand (list, marketplace add/list/remove,
install, uninstall, update, installed) and exits. Shares the underlying
`MarketplaceService` and `SkillService` with the interactive CLI but
doesn't spin up the REPL or the backend chat flow.
"""

from __future__ import annotations

import asyncio
import sys
from typing import List, Optional

from ...application.services.marketplace_service import (
    MarketplaceError,
    MarketplaceService,
)
from ...application.services.skill_service import SkillService


class SkillsCliHandler:
    """Run a single `turia skills ...` invocation."""

    def __init__(
        self,
        marketplace_service: MarketplaceService,
        skill_service: SkillService,
    ) -> None:
        self._mp = marketplace_service
        self._skills = skill_service

    def run(self, argv: List[str]) -> int:
        """Entry point. argv is everything after `turia skills`."""
        if not argv:
            return self._list()
        sub = argv[0].lower()
        rest = argv[1:]

        if sub in ("list", "ls"):
            return self._list()
        if sub == "installed":
            return self._installed()
        if sub == "marketplace":
            return self._marketplace(rest)
        if sub == "install":
            return self._install(rest)
        if sub == "uninstall":
            return self._uninstall(rest)
        if sub == "update":
            return self._update(rest)
        if sub in ("help", "--help", "-h"):
            print(_USAGE)
            return 0

        print(f"Subcomando desconocido: {sub}", file=sys.stderr)
        print(_USAGE, file=sys.stderr)
        return 2

    # ── subcommands ─────────────────────────────────────────────────────

    def _list(self) -> int:
        asyncio.run(self._skills.load_skills())
        skills = self._skills.list_skills()
        if not skills:
            print("No hay skills cargadas. Usa `turia skills install <pack>@<mp>`.")
            return 0
        current_cat = None
        for s in skills:
            if s.category != current_cat:
                print(f"\n{s.category}:")
                current_cat = s.category
            prefix = f"{s.pack}:{s.name}" if s.pack else s.name
            icon = f"{s.icon} " if s.icon else ""
            print(f"  {icon}{prefix:<36} {s.description[:80]}")
        return 0

    def _installed(self) -> int:
        packs = self._mp.list_installed()
        if not packs:
            print("No hay packs instalados.")
            return 0
        print("Packs instalados:")
        for name, p in packs.items():
            print(f"  {name:<24} {p.source_path}@{p.marketplace}  ({p.commit or '—'})")
        return 0

    def _marketplace(self, rest: List[str]) -> int:
        if not rest:
            print("Uso: turia skills marketplace {add|list|remove} ...", file=sys.stderr)
            return 2
        op = rest[0].lower()
        try:
            if op == "add" and len(rest) >= 2:
                url = rest[1]
                name = rest[2] if len(rest) >= 3 else None
                resolved = self._mp.add_marketplace(url, name=name)
                print(f"Marketplace '{resolved}' añadido.")
                return 0
            if op == "list":
                mps = self._mp.list_marketplaces()
                if not mps:
                    print("No hay marketplaces configurados.")
                    return 0
                print("Marketplaces:")
                for name, m in mps.items():
                    print(f"  {name:<20} {m.url}  ({m.commit or '—'})")
                return 0
            if op == "remove" and len(rest) >= 2:
                uninstalled = self._mp.remove_marketplace(rest[1])
                print(f"Marketplace '{rest[1]}' eliminado.")
                if uninstalled:
                    print(f"Packs desinstalados: {', '.join(uninstalled)}")
                return 0
        except MarketplaceError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        print("Uso: turia skills marketplace {add <url> [name]|list|remove <name>}", file=sys.stderr)
        return 2

    def _install(self, rest: List[str]) -> int:
        if not rest:
            print("Uso: turia skills install <pack>[@<marketplace>]", file=sys.stderr)
            return 2
        try:
            pack = self._mp.install_pack(rest[0])
        except MarketplaceError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        print(f"Pack '{pack.name}' instalado desde '{pack.marketplace}'.")
        return 0

    def _uninstall(self, rest: List[str]) -> int:
        if not rest:
            print("Uso: turia skills uninstall <pack>", file=sys.stderr)
            return 2
        try:
            self._mp.uninstall_pack(rest[0])
        except MarketplaceError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        print(f"Pack '{rest[0]}' desinstalado.")
        return 0

    def _update(self, rest: List[str]) -> int:
        target = rest[0] if rest else None
        try:
            results = self._mp.update(target)
        except MarketplaceError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        if not results:
            print("Nada que actualizar.")
            return 0
        for name, old, new in results:
            suffix = " (sin cambios)" if old == new else ""
            print(f"  {name}: {old or '—'} → {new or '—'}{suffix}")
        return 0


_USAGE = """Uso: turia skills <subcomando> [args]

Subcomandos:
  list                              Listar skills cargados (por defecto)
  installed                         Ver packs instalados
  marketplace add <url> [name]      Clonar un marketplace
  marketplace list                  Ver marketplaces
  marketplace remove <name>         Eliminar marketplace (desinstala sus packs)
  install <pack>[@<marketplace>]    Instalar pack (ej. angular@rudo)
  uninstall <pack>                  Desinstalar pack
  update [<marketplace>|all]        git pull del marketplace

Ejemplos:
  turia skills marketplace add https://bitbucket.org/rudoapps/skills.git rudo
  turia skills install angular@rudo
  turia skills install python/django@rudo
  turia skills update all"""
