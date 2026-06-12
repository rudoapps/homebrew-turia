"""Code analysis tools: symbols, find_definition, find_references, hover_info.

Uses LSP (Language Server Protocol) when a server is available for the
project's language.  Falls back to regex-based analysis otherwise.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional

from .base import BaseToolExecutor, ToolDeniedError
from ..lsp.lsp_client import LSPClient, LSPError
from ..lsp.lsp_server_registry import detect_lsp_command

logger = logging.getLogger(__name__)

# ── LSP SymbolKind → human label ────────────────────────────────────────

_SYMBOL_KIND: Dict[int, str] = {
    1: "file", 2: "module", 3: "namespace", 4: "package",
    5: "class", 6: "method", 7: "property", 8: "field",
    9: "constructor", 10: "enum", 11: "interface", 12: "function",
    13: "variable", 14: "constant", 15: "string", 16: "number",
    17: "boolean", 18: "array", 19: "object", 20: "key",
    21: "null", 22: "enum member", 23: "struct", 24: "event",
    25: "operator", 26: "type parameter",
}

# ── Regex patterns (fallback) ───────────────────────────────────────────

SYMBOL_PATTERNS = {
    ".py": [
        (r'^(class\s+\w+)', "class"),
        (r'^(\s*def\s+\w+)', "function"),
        (r'^(\s*async\s+def\s+\w+)', "async function"),
    ],
    ".swift": [
        (r'^(\s*(?:class|struct|enum|protocol|actor)\s+\w+)', "type"),
        (r'^(\s*(?:func|init)\s+\w+)', "function"),
        (r'^(\s*(?:var|let)\s+\w+)', "property"),
        (r'^(\s*extension\s+\w+)', "extension"),
    ],
    ".kt": [
        (r'^(\s*(?:class|object|interface|data class|sealed class|enum class)\s+\w+)', "type"),
        (r'^(\s*(?:fun|suspend fun)\s+\w+)', "function"),
        (r'^(\s*(?:val|var)\s+\w+)', "property"),
    ],
    ".ts": [
        (r'^(\s*(?:class|interface|type|enum)\s+\w+)', "type"),
        (r'^(\s*(?:function|async function)\s+\w+)', "function"),
        (r'^(\s*(?:export\s+)?(?:const|let|var)\s+\w+)', "variable"),
    ],
    ".js": [
        (r'^(\s*class\s+\w+)', "class"),
        (r'^(\s*(?:function|async function)\s+\w+)', "function"),
        (r'^(\s*(?:const|let|var)\s+\w+\s*=\s*(?:function|\(|async))', "function"),
    ],
    ".dart": [
        (r'^(\s*(?:class|mixin|extension|enum)\s+\w+)', "type"),
        (r'^(\s*\w+\s+\w+\s*\()', "function"),
    ],
    ".go": [
        (r'^(type\s+\w+\s+(?:struct|interface))', "type"),
        (r'^(func\s+(?:\(\w+\s+\*?\w+\)\s+)?\w+)', "function"),
    ],
}


class CodeAnalysisToolExecutor(BaseToolExecutor):
    """Handles code intelligence via LSP with regex fallback."""

    def __init__(self, *args: Any, project_type: str = "unknown", **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._project_type = project_type
        self._lsp: Optional[LSPClient] = None
        self._lsp_available: Optional[bool] = None  # None = not yet checked
        self._lsp_command: Optional[List[str]] = None

    async def _get_lsp(self) -> Optional[LSPClient]:
        """Lazily start the LSP client on first use."""
        if self._lsp_available is False:
            return None
        if self._lsp and self._lsp.is_running():
            return self._lsp

        # First attempt — detect and start
        if self._lsp_available is None:
            self._lsp_command = detect_lsp_command(self._project_type)
            if not self._lsp_command:
                self._lsp_available = False
                return None
            try:
                self._lsp = LSPClient(self._lsp_command, self._validator.working_dir)
                await self._lsp.start()
                self._lsp_available = True
                logger.info("LSP server started: %s", self._lsp_command)
                return self._lsp
            except Exception as exc:
                logger.debug("Failed to start LSP server %s: %s", self._lsp_command, exc)
                self._lsp_available = False
                self._lsp = None
                return None

        return None

    async def shutdown_lsp(self) -> None:
        """Stop the LSP server if running. Called during cleanup."""
        if self._lsp:
            await self._lsp.stop()
            self._lsp = None

    # ── symbols ─────────────────────────────────────────────────────────

    async def symbols(self, inp: Dict[str, Any]) -> str:
        """Extract symbol definitions from a file."""
        path = inp.get("path", "")
        if not path:
            raise ValueError("Se requiere el parametro 'path'")

        ok, resolved = self._validator.validate_read(path)
        if not ok:
            raise ToolDeniedError(resolved)
        if not os.path.isfile(resolved):
            raise FileNotFoundError(f"Archivo no encontrado: {path}")

        # Try LSP first
        lsp = await self._get_lsp()
        if lsp:
            try:
                raw_symbols = await lsp.document_symbols(resolved)
                if raw_symbols:
                    return self._format_lsp_symbols(raw_symbols, path)
            except LSPError as exc:
                logger.debug("LSP symbols failed, falling back to regex: %s", exc)

        # Regex fallback
        return self._regex_symbols(resolved, path)

    # ── find_definition ─────────────────────────────────────────────────

    async def find_definition(self, inp: Dict[str, Any]) -> str:
        """Find where a symbol is defined in the project."""
        symbol = inp.get("symbol", "")
        file_pattern = inp.get("file_pattern", "")
        if not symbol:
            raise ValueError("Se requiere el parametro 'symbol'")

        # Try LSP: find the symbol via grep, then ask LSP for its definition
        lsp = await self._get_lsp()
        if lsp:
            try:
                position = await self._find_symbol_position(symbol, file_pattern)
                if position:
                    file_path, line, char = position
                    locations = await lsp.definition(file_path, line, char)
                    if locations:
                        return self._format_locations(locations, "Definicion")
            except LSPError as exc:
                logger.debug("LSP definition failed, falling back to regex: %s", exc)

        # Regex fallback
        return await self._regex_find_definition(symbol, file_pattern)

    # ── find_references ─────────────────────────────────────────────────

    async def find_references(self, inp: Dict[str, Any]) -> str:
        """Find all references to a symbol in the project."""
        symbol = inp.get("symbol", "")
        file_pattern = inp.get("file_pattern", "")
        if not symbol:
            raise ValueError("Se requiere el parametro 'symbol'")

        # Try LSP
        lsp = await self._get_lsp()
        if lsp:
            try:
                position = await self._find_symbol_position(symbol, file_pattern)
                if position:
                    file_path, line, char = position
                    refs = await lsp.references(file_path, line, char)
                    if refs:
                        return self._format_locations(refs[:50], "Referencia")
            except LSPError as exc:
                logger.debug("LSP references failed, falling back to regex: %s", exc)

        # Regex fallback
        return await self._regex_find_references(symbol, file_pattern)

    # ── hover_info (LSP only) ───────────────────────────────────────────

    async def hover_info(self, inp: Dict[str, Any]) -> str:
        """Get type/documentation info for a symbol at a file position."""
        path = inp.get("path", "")
        line = inp.get("line")
        character = inp.get("character")

        if not path:
            raise ValueError("Se requiere el parametro 'path'")
        if line is None or character is None:
            raise ValueError("Se requieren los parametros 'line' y 'character'")

        ok, resolved = self._validator.validate_read(path)
        if not ok:
            raise ToolDeniedError(resolved)

        lsp = await self._get_lsp()
        if not lsp:
            return (
                "hover_info requiere un servidor LSP. "
                "Instala uno para este lenguaje (ej: pyright, sourcekit-lsp). "
                "Usa read_file para ver el codigo directamente."
            )

        try:
            info = await lsp.hover(resolved, int(line), int(character))
            if info:
                return info
            return f"Sin informacion de tipo disponible en {path}:{line}:{character}"
        except LSPError as exc:
            return f"Error obteniendo hover info: {exc}"

    # ── LSP formatting helpers ──────────────────────────────────────────

    def _format_lsp_symbols(
        self, symbols: List[Dict[str, Any]], path: str, indent: int = 0,
    ) -> str:
        """Format LSP DocumentSymbol[] into a readable string."""
        lines: List[str] = []
        for sym in symbols:
            kind_num = sym.get("kind", 0)
            kind = _SYMBOL_KIND.get(kind_num, f"kind-{kind_num}")
            name = sym.get("name", "?")
            range_info = sym.get("selectionRange") or sym.get("range", {})
            start_line = range_info.get("start", {}).get("line", 0) + 1
            prefix = "  " * indent
            lines.append(f"{start_line:>5} {prefix}[{kind}] {name}")
            # Recurse into children
            children = sym.get("children", [])
            if children:
                lines.append(self._format_lsp_symbols(children, path, indent + 1))

        if not indent:
            header = f"{len(lines)} simbolos en {path} (LSP):\n"
            return header + "\n".join(lines)
        return "\n".join(lines)

    def _format_locations(
        self, locations: List[Dict[str, Any]], label: str,
    ) -> str:
        """Format LSP Location[] into a readable string."""
        lines: List[str] = []
        root = self._validator.working_dir
        for loc in locations:
            # Handle Location vs LocationLink
            uri = loc.get("uri") or loc.get("targetUri", "")
            range_info = loc.get("range") or loc.get("targetSelectionRange", {})
            start = range_info.get("start", {})
            line_num = start.get("line", 0) + 1
            col = start.get("character", 0) + 1

            # Convert URI to relative path
            file_path = uri
            if uri.startswith("file://"):
                file_path = uri[7:]  # strip file://
            if file_path.startswith(root):
                file_path = os.path.relpath(file_path, root)

            lines.append(f"  {file_path}:{line_num}:{col}")

        count = len(lines)
        return f"{count} {label.lower()}(s) encontrada(s) (LSP):\n" + "\n".join(lines)

    # ── Symbol position resolution ──────────────────────────────────────

    async def _find_symbol_position(
        self, symbol: str, file_pattern: str = "",
    ) -> Optional[tuple]:
        """Find the first occurrence of a symbol via grep, returning (file, line, col).

        This is needed because LSP definition/references require a file position,
        but the user provides a symbol name.
        """
        from .search_tools import SearchToolExecutor
        search = SearchToolExecutor(self._validator, self._backup, self._request_approval)
        search.set_permission_mode(self._permission_mode)

        result = await search.grep({
            "pattern": rf'\b{re.escape(symbol)}\b',
            "output_mode": "content",
            "glob": file_pattern or None,
            "head_limit": 5,
        })

        # Parse first grep match: "path:line:content"
        for line in result.splitlines():
            if not line.strip() or line.startswith("--"):
                continue
            # Format: path:line_num:col:content or path:line_num:content
            parts = line.split(":", 3)
            if len(parts) >= 3:
                try:
                    file_path = parts[0]
                    line_num = int(parts[1]) - 1  # LSP uses 0-based lines
                    # Find the column of the symbol in the line content
                    content = parts[2] if len(parts) == 3 else parts[3]
                    col = content.find(symbol)
                    if col < 0:
                        col = 0
                    ok, resolved = self._validator.validate_read(file_path)
                    if ok:
                        return (resolved, line_num, col)
                except (ValueError, IndexError):
                    continue

        return None

    # ── Regex fallback implementations ──────────────────────────────────

    def _regex_symbols(self, resolved: str, path: str) -> str:
        """Extract symbols using regex patterns."""
        with open(resolved, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        ext = os.path.splitext(resolved)[1].lower()
        file_patterns = SYMBOL_PATTERNS.get(ext, SYMBOL_PATTERNS.get(".py", []))

        symbols: List[str] = []
        for i, line in enumerate(lines, 1):
            for regex, kind in file_patterns:
                m = re.match(regex, line)
                if m:
                    symbols.append(f"{i:>5} [{kind}] {m.group(1).strip()}")
                    break

        if not symbols:
            return f"No se encontraron simbolos en {path}"

        return f"{len(symbols)} simbolos en {path}:\n" + "\n".join(symbols)

    async def _regex_find_definition(self, symbol: str, file_pattern: str) -> str:
        """Regex-based find definition."""
        def_patterns = [
            rf'^\s*(?:class|struct|enum|protocol|interface|actor|type)\s+{re.escape(symbol)}\b',
            rf'^\s*(?:def|func|fun|function|suspend fun|async def)\s+{re.escape(symbol)}\b',
            rf'^\s*(?:val|var|let|const)\s+{re.escape(symbol)}\b',
            rf'^\s*extension\s+{re.escape(symbol)}\b',
            rf'^\s*data\s+class\s+{re.escape(symbol)}\b',
        ]
        combined = "|".join(f"({p})" for p in def_patterns)

        from .search_tools import SearchToolExecutor
        search = SearchToolExecutor(self._validator, self._backup, self._request_approval)
        search.set_permission_mode(self._permission_mode)
        return await search.grep({
            "pattern": combined,
            "output_mode": "content",
            "glob": file_pattern or None,
            "head_limit": 20,
            "context_after": 3,
        })

    async def _regex_find_references(self, symbol: str, file_pattern: str) -> str:
        """Regex-based find references."""
        from .search_tools import SearchToolExecutor
        search = SearchToolExecutor(self._validator, self._backup, self._request_approval)
        search.set_permission_mode(self._permission_mode)
        return await search.grep({
            "pattern": rf'\b{re.escape(symbol)}\b',
            "output_mode": "content",
            "glob": file_pattern or None,
            "head_limit": 50,
        })
