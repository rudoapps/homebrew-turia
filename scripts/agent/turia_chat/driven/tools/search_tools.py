"""Search tools: search_code, grep, list_files."""

from __future__ import annotations

import asyncio
import fnmatch
import os
import re
import shutil
from typing import Any, Dict, List

from .base import BaseToolExecutor, ToolDeniedError, MAX_SUBPROCESS_TIMEOUT, MAX_RIPGREP_COLUMNS
from ...domain.entities.tool_metadata import MAX_SEARCH_RESULTS


class SearchToolExecutor(BaseToolExecutor):
    """Handles code search and file listing operations."""

    async def search_code(self, inp: Dict[str, Any]) -> str:
        """Search for a pattern in code files."""
        query = inp.get("pattern", inp.get("query", ""))
        path = inp.get("path", inp.get("directory", "."))
        file_pattern = inp.get("file_pattern", inp.get("glob", ""))
        case_insensitive = inp.get("case_insensitive", not inp.get("case_sensitive", True))
        output_mode = inp.get("output_mode", "content")
        head_limit = int(inp.get("head_limit", 50))
        offset = int(inp.get("offset", 0))
        context_lines = inp.get("context_lines", 3)

        if not query:
            raise ValueError("Se requiere el parametro 'query' o 'pattern'")

        ok, result = self._validator.validate_read(path)
        if not ok:
            raise ToolDeniedError(result)
        resolved = result

        rg_path = shutil.which("rg")
        if rg_path:
            return await self._ripgrep_search(
                rg_path, query, resolved, file_pattern, case_insensitive,
                output_mode, head_limit, offset, context_lines,
            )
        return self._python_search(query, resolved, file_pattern, not case_insensitive)

    async def grep(self, inp: Dict[str, Any]) -> str:
        """Powerful grep with ripgrep — multiline, file type filter."""
        pattern = inp.get("pattern", "")
        if not pattern:
            raise ValueError("Se requiere el parametro 'pattern'")

        path = inp.get("path", ".")
        ok, result = self._validator.validate_read(path)
        if not ok:
            raise ToolDeniedError(result)
        resolved = result

        glob_filter = inp.get("glob", "")
        file_type = inp.get("file_type", "")
        output_mode = inp.get("output_mode", "files_with_matches")
        case_insensitive = inp.get("case_insensitive", False)
        multiline = inp.get("multiline", False)
        head_limit = int(inp.get("head_limit", 50))
        offset = int(inp.get("offset", 0))
        context_before = inp.get("context_before", 0)
        context_after = inp.get("context_after", 0)

        rg_path = shutil.which("rg")
        if not rg_path:
            return await self.search_code({"query": pattern, "path": path, "output_mode": output_mode})

        cmd = [rg_path, "--no-heading", "--no-binary", "--max-columns", str(MAX_RIPGREP_COLUMNS)]

        if case_insensitive:
            cmd.append("--ignore-case")
        if multiline:
            cmd.extend(["-U", "--multiline-dotall"])
        if glob_filter:
            cmd.extend(["--glob", glob_filter])
        if file_type:
            cmd.extend(["--type", file_type])

        if output_mode == "files_with_matches":
            cmd.extend(["--files-with-matches", "--sort", "modified"])
        elif output_mode == "count":
            cmd.append("--count")
        else:
            cmd.append("--line-number")
            if context_before:
                cmd.extend(["-B", str(context_before)])
            if context_after:
                cmd.extend(["-A", str(context_after)])

        cmd.extend([pattern, resolved])
        return await self._run_rg_and_format(cmd, resolved, head_limit, offset, pattern)

    async def list_files(self, inp: Dict[str, Any]) -> str:
        """List files in a directory with optional pattern matching."""
        path = inp.get("path", inp.get("directory", "."))
        pattern = inp.get("pattern", "")
        recursive = inp.get("recursive", True)

        ok, result = self._validator.validate_read(path)
        if not ok:
            raise ToolDeniedError(result)

        resolved = result
        if not os.path.isdir(resolved):
            raise NotADirectoryError(f"No es un directorio: {path}")

        gitignore_patterns = self._load_gitignore(resolved)
        matches: List[str] = []
        cwd = self._validator.working_dir

        if recursive:
            for root, dirs, files in os.walk(resolved):
                dirs[:] = [
                    d for d in dirs
                    if not d.startswith(".")
                    and d not in ("node_modules", "__pycache__", ".git", "venv", ".venv", "dist", "build")
                    and not self._matches_gitignore(
                        os.path.relpath(os.path.join(root, d), resolved),
                        gitignore_patterns,
                    )
                ]
                for name in files:
                    if name.startswith("."):
                        continue
                    if pattern:
                        # Strip **/ prefix — fnmatch only matches basenames
                        clean_pattern = pattern.lstrip("*").lstrip("/") if "**" in pattern else pattern
                        full = os.path.join(root, name)
                        rel = os.path.relpath(full, cwd)
                        if not fnmatch.fnmatch(name, clean_pattern) and not fnmatch.fnmatch(rel, pattern):
                            continue
                    else:
                        full = os.path.join(root, name)
                        rel = os.path.relpath(full, cwd)
                    matches.append(rel)
                    if len(matches) >= MAX_SEARCH_RESULTS:
                        break
                if len(matches) >= MAX_SEARCH_RESULTS:
                    break
        else:
            for entry in sorted(os.listdir(resolved)):
                if entry.startswith("."):
                    continue
                if pattern and not fnmatch.fnmatch(entry, pattern):
                    continue
                full = os.path.join(resolved, entry)
                rel = os.path.relpath(full, cwd)
                suffix = "/" if os.path.isdir(full) else ""
                matches.append(f"{rel}{suffix}")
                if len(matches) >= MAX_SEARCH_RESULTS:
                    break

        if not matches:
            return f"No se encontraron archivos en {path}"

        # Sort by modification time
        try:
            matches.sort(
                key=lambda m: os.path.getmtime(
                    os.path.join(cwd, m.rstrip("/"))
                ) if os.path.exists(os.path.join(cwd, m.rstrip("/"))) else 0,
                reverse=True,
            )
        except OSError:
            pass

        header = f"{len(matches)} archivos"
        if len(matches) >= MAX_SEARCH_RESULTS:
            header += f" (limitado a {MAX_SEARCH_RESULTS})"

        return f"{header}:\n" + "\n".join(matches)

    # ── Internal helpers ────────────────────────────────────────────

    async def _ripgrep_search(
        self, rg_path, query, directory, file_pattern, case_insensitive,
        output_mode, head_limit, offset, context_lines,
    ) -> str:
        """Run ripgrep with output mode support."""
        cmd = [rg_path, "--no-heading", "--no-binary", "--max-columns", str(MAX_RIPGREP_COLUMNS)]

        if case_insensitive:
            cmd.append("--ignore-case")

        if output_mode == "files_with_matches":
            cmd.extend(["--files-with-matches", "--sort", "modified"])
        elif output_mode == "count":
            cmd.append("--count")
        else:
            cmd.append("--line-number")
            if context_lines:
                cmd.extend(["-C", str(context_lines)])

        if file_pattern:
            cmd.extend(["--glob", file_pattern])

        cmd.extend([query, directory])
        return await self._run_rg_and_format(cmd, directory, head_limit, offset, query)

    async def _run_rg_and_format(
        self, cmd, directory, head_limit, offset, query
    ) -> str:
        """Execute ripgrep and format output."""
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(
                proc.communicate(), timeout=MAX_SUBPROCESS_TIMEOUT
            )
            output = stdout.decode("utf-8", errors="replace").replace("\x00", "")

            if not output.strip():
                return f'No se encontraron resultados para "{query}"'

            cwd = self._validator.working_dir
            lines = output.strip().split("\n")
            relative_lines = []
            for line in lines:
                if directory in line:
                    line = line.replace(directory, os.path.relpath(directory, cwd), 1)
                relative_lines.append(line)

            if offset > 0:
                relative_lines = relative_lines[offset:]
            if head_limit > 0:
                relative_lines = relative_lines[:head_limit]

            return "\n".join(relative_lines)

        except asyncio.TimeoutError:
            return f"Busqueda cancelada: timeout de {MAX_SUBPROCESS_TIMEOUT} segundos"
        except Exception:
            return self._python_search(query, directory, "", True)

    def _python_search(
        self, query: str, directory: str, file_pattern: str, case_sensitive: bool,
    ) -> str:
        """Pure Python fallback for code search."""
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            regex = re.compile(query, flags)
        except re.error:
            regex = re.compile(re.escape(query), flags)

        cwd = self._validator.working_dir
        matches: List[str] = []

        for root, dirs, files in os.walk(directory):
            dirs[:] = [d for d in dirs if not d.startswith(".")
                       and d not in ("node_modules", "__pycache__", ".git", "venv", ".venv")]
            for name in files:
                if name.startswith("."):
                    continue
                if file_pattern and not fnmatch.fnmatch(name, file_pattern):
                    continue
                full = os.path.join(root, name)
                rel = os.path.relpath(full, cwd)
                try:
                    with open(full, "r", encoding="utf-8", errors="ignore") as f:
                        for lineno, line in enumerate(f, 1):
                            if regex.search(line):
                                matches.append(f"{rel}:{lineno}:{line.rstrip()[:200]}")
                                if len(matches) >= MAX_SEARCH_RESULTS:
                                    break
                except (OSError, UnicodeDecodeError):
                    continue
                if len(matches) >= MAX_SEARCH_RESULTS:
                    break
            if len(matches) >= MAX_SEARCH_RESULTS:
                break

        if not matches:
            return f'No se encontraron resultados para "{query}"'

        return "\n".join(matches)
