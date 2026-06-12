"""File operation tools: read, write, edit, move, undo, find_and_replace."""

from __future__ import annotations

import fnmatch
import json
import os
import re
from typing import Any, Dict, List, Optional

from .base import BaseToolExecutor, ToolDeniedError, MAX_CONTENT_PREVIEW
from ...domain.entities.tool_metadata import MAX_FILE_SIZE

# Marker used to embed file metadata in the detail string so the UI layer
# can extract old/new content for the editor diff and Rich panel rendering
# without changing the ApprovalCallback signature.
_FILE_META_MARKER = "\x00__FILE_META__\x00"


class FileToolExecutor(BaseToolExecutor):
    """Handles file read/write/edit operations."""

    async def read_file(self, inp: Dict[str, Any]) -> str:
        """Read a file with line numbers. Supports offset/limit."""
        path = inp.get("path", inp.get("file_path", ""))
        if not path:
            raise ValueError("Se requiere el parametro 'path'")

        ok, result = self._validator.validate_read(path)
        if not ok:
            raise ToolDeniedError(result)

        resolved = result
        if not os.path.isfile(resolved):
            raise FileNotFoundError(f"Archivo no encontrado: {path}")

        with open(resolved, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        lines = content.split("\n")
        total_lines = len(lines)

        offset = inp.get("offset") or inp.get("start_line")
        limit = inp.get("limit")
        end_line = inp.get("end_line")

        if offset is not None or limit is not None or end_line is not None:
            s = max(1, int(offset or 1))
            if limit is not None:
                e = min(total_lines, s + int(limit) - 1)
            elif end_line is not None:
                e = min(total_lines, int(end_line))
            else:
                e = total_lines
            lines = lines[s - 1:e]
            start_num = s
        else:
            start_num = 1

        numbered = [f"{i:>6}\t{line}" for i, line in enumerate(lines, start=start_num)]
        output = "\n".join(numbered)

        if len(output) > MAX_FILE_SIZE:
            output = output[:MAX_FILE_SIZE]
            output += f"\n\n... [truncado, archivo tiene {total_lines} lineas]"

        return output

    async def write_file(self, inp: Dict[str, Any]) -> str:
        """Write content to a file, creating directories as needed."""
        path = inp.get("path", inp.get("file_path", ""))
        content = inp.get("content", "")
        if not path:
            raise ValueError("Se requiere el parametro 'path'")

        ok, result = self._validator.validate_write(path)
        if not ok:
            raise ToolDeniedError(result)

        resolved = result
        is_new = not os.path.isfile(resolved)

        if is_new:
            preview = content[:MAX_CONTENT_PREVIEW]
            if len(content) > MAX_CONTENT_PREVIEW:
                preview += "\n..."
            title = f"Crear {os.path.relpath(resolved, self._validator.working_dir)}"
            detail = f"Nuevo archivo ({len(content)} caracteres):\n{preview}"
            # Embed metadata for UI (new file — no old content)
            meta = _encode_file_meta(
                filename=os.path.relpath(resolved, self._validator.working_dir),
                old_content="",
                new_content=content,
            )
            detail = meta + detail
        else:
            rel = os.path.relpath(resolved, self._validator.working_dir)
            title = f"Escribir {rel}"
            with open(resolved, "r", encoding="utf-8", errors="replace") as rf:
                current_content = rf.read()
            detail = _build_write_diff(current_content, content)
            sensitive = self._validator.is_sensitive(resolved)
            if sensitive:
                detail = f"[SENSIBLE: {sensitive}]\n{detail}"
            # Embed metadata for UI
            meta = _encode_file_meta(
                filename=rel,
                old_content=current_content,
                new_content=content,
            )
            detail = meta + detail

        approved = await self._check_approval(title, detail)
        if not approved:
            raise ToolDeniedError("Operacion rechazada por el usuario")

        if not is_new:
            self._backup.create_backup(resolved)

        parent = os.path.dirname(resolved)
        if parent:
            os.makedirs(parent, exist_ok=True)

        with open(resolved, "w", encoding="utf-8") as f:
            f.write(content)

        rel = os.path.relpath(resolved, self._validator.working_dir)
        lines_count = content.count("\n") + 1
        return f"Archivo {'creado' if is_new else 'escrito'}: {rel} ({lines_count} lineas)"

    async def edit_file(self, inp: Dict[str, Any]) -> str:
        """Apply old_string -> new_string replacement."""
        path = inp.get("path", inp.get("file_path", ""))
        old_string = inp.get("old_string", "")
        new_string = inp.get("new_string", "")
        replace_all = inp.get("replace_all", False)

        if not path:
            raise ValueError("Se requiere el parametro 'path'")
        if not old_string:
            raise ValueError("Se requiere el parametro 'old_string'")

        ok, result = self._validator.validate_write(path)
        if not ok:
            raise ToolDeniedError(result)

        resolved = result
        if not os.path.isfile(resolved):
            raise FileNotFoundError(f"Archivo no encontrado: {path}")

        with open(resolved, "r", encoding="utf-8", errors="replace") as f:
            current = f.read()

        count = current.count(old_string)
        if count == 0:
            match_result = _fuzzy_find_and_replace(current, old_string, new_string)
            if match_result is not None:
                new_content = match_result
                count = 1
            else:
                raise ValueError(
                    f"old_string no encontrado en {path}. "
                    f"Verifica que el texto coincida exactamente."
                )
        else:
            if replace_all:
                new_content = current.replace(old_string, new_string)
            else:
                new_content = current.replace(old_string, new_string, 1)

        old_lines = old_string.count("\n") + 1
        new_lines = new_string.count("\n") + 1
        added = max(0, new_lines - old_lines)
        removed = max(0, old_lines - new_lines)

        rel = os.path.relpath(resolved, self._validator.working_dir)
        title = f"Editar {rel}  +{added}/-{removed} lineas"
        detail = _build_diff_detail(old_string, new_string)

        sensitive = self._validator.is_sensitive(resolved)
        if sensitive:
            detail = f"[SENSIBLE: {sensitive}]\n{detail}"

        # Embed metadata for UI (old/new content for editor diff)
        meta = _encode_file_meta(
            filename=rel,
            old_content=current,
            new_content=new_content,
        )
        detail = meta + detail

        approved = await self._check_approval(title, detail)
        if not approved:
            raise ToolDeniedError("Operacion rechazada por el usuario")

        self._backup.create_backup(resolved)

        with open(resolved, "w", encoding="utf-8") as f:
            f.write(new_content)

        # Post-edit context: return ~20 lines around the change so the agent
        # doesn't have to re-read the file. Avoids the "edit → re-read → edit
        # → re-read" loop seen on bulk-edit sessions (conv 219, 2026-04-11
        # had 9 reads of smtp/adapter.py because each edit forced a fresh
        # read). For replace_all we show context around the FIRST match;
        # the agent can grep for the rest if needed.
        context_block = _build_post_edit_context(
            new_content=new_content,
            new_string=new_string,
            context_lines=10,
        )

        message = (
            f"Archivo editado: {rel} "
            f"(+{added}/-{removed} lineas, {count} coincidencia(s))"
        )
        if context_block:
            message += f"\n\nContexto post-edit ({rel}):\n{context_block}"
        return message

    async def move_file(self, inp: Dict[str, Any]) -> str:
        """Move or rename a file/directory."""
        import shutil

        source = inp.get("source", "")
        destination = inp.get("destination", "")

        if not source or not destination:
            raise ValueError("Se requieren 'source' y 'destination'")

        ok, resolved_src = self._validator.validate_read(source)
        if not ok:
            raise ToolDeniedError(resolved_src)
        ok, resolved_dst = self._validator.validate_write(destination)
        if not ok:
            raise ToolDeniedError(resolved_dst)

        if not os.path.exists(resolved_src):
            raise FileNotFoundError(f"No encontrado: {source}")

        approved = await self._check_approval(
            "Mover archivo", f"{source} → {destination}"
        )
        if not approved:
            raise ToolDeniedError("Operacion rechazada por el usuario")

        parent = os.path.dirname(resolved_dst)
        if parent:
            os.makedirs(parent, exist_ok=True)

        shutil.move(resolved_src, resolved_dst)
        return f"Movido: {source} → {destination}"

    async def undo_edit(self, inp: Dict[str, Any]) -> str:
        """Undo the last edit by restoring from backup."""
        path = inp.get("path", "")
        if not path:
            raise ValueError("Se requiere el parametro 'path'")

        ok, resolved = self._validator.validate_write(path)
        if not ok:
            raise ToolDeniedError(resolved)

        index = self._backup._load_index()
        matching = [e for e in index if e["original_path"] == resolved]
        if not matching:
            return f"No hay backup disponible para {path}"

        latest = max(matching, key=lambda e: e["timestamp"])
        restored = self._backup.restore_backup(latest["backup_id"])
        if restored:
            rel = os.path.relpath(resolved, self._validator.working_dir)
            return f"Restaurado: {rel} (backup aplicado)"
        return f"Error al restaurar backup para {path}"

    async def find_and_replace(self, inp: Dict[str, Any]) -> str:
        """Search and replace across multiple files."""
        search = inp.get("search", "")
        replace = inp.get("replace", "")
        file_pattern = inp.get("file_pattern", "")
        is_regex = inp.get("is_regex", False)

        if not search:
            raise ValueError("Se requiere el parametro 'search'")

        if is_regex:
            try:
                pattern = re.compile(search)
            except re.error as e:
                raise ValueError(f"Regex invalida: {e}")
        else:
            pattern = re.compile(re.escape(search))

        cwd = self._validator.working_dir
        changed_files = []

        for root, dirs, files in os.walk(cwd):
            dirs[:] = [d for d in dirs if not d.startswith(".")
                       and d not in ("node_modules", "__pycache__", "venv", ".venv", "build", "dist")]
            for name in files:
                if name.startswith("."):
                    continue
                if file_pattern and not fnmatch.fnmatch(name, file_pattern):
                    continue
                full = os.path.join(root, name)
                try:
                    with open(full, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                except (OSError, UnicodeDecodeError):
                    continue

                matches = list(pattern.finditer(content))
                if not matches:
                    continue

                if is_regex:
                    new_content = pattern.sub(replace, content)
                else:
                    new_content = content.replace(search, replace)

                self._backup.create_backup(full)
                with open(full, "w", encoding="utf-8") as f:
                    f.write(new_content)

                rel = os.path.relpath(full, cwd)
                changed_files.append(f"{rel} ({len(matches)} reemplazos)")

        if not changed_files:
            return f'No se encontraron coincidencias para "{search}"'

        return f"{len(changed_files)} archivos modificados:\n" + "\n".join(changed_files)


# ── Helper functions ────────────────────────────────────────────────


def _fuzzy_find_and_replace(
    content: str, old_string: str, new_string: str
) -> Optional[str]:
    """Try to find old_string with normalized whitespace."""

    def normalize_indent(text: str) -> str:
        return "\n".join(line.expandtabs(4) for line in text.split("\n"))

    norm_content = normalize_indent(content)
    norm_old = normalize_indent(old_string)

    if norm_content.count(norm_old) == 1:
        pos = norm_content.find(norm_old)
        norm_before = norm_content[:pos]
        start_line = norm_before.count("\n")
        old_line_count = old_string.count("\n") + 1

        content_lines = content.split("\n")
        original_old = "\n".join(content_lines[start_line:start_line + old_line_count])
        return content.replace(original_old, new_string, 1)

    def strip_trailing(text: str) -> str:
        return "\n".join(line.rstrip() for line in text.split("\n"))

    stripped_content = strip_trailing(content)
    stripped_old = strip_trailing(old_string)

    if stripped_content.count(stripped_old) == 1:
        pos = stripped_content.find(stripped_old)
        before = stripped_content[:pos]
        start_line = before.count("\n")
        old_line_count = old_string.count("\n") + 1
        content_lines = content.split("\n")
        original_old = "\n".join(content_lines[start_line:start_line + old_line_count])
        return content.replace(original_old, new_string, 1)

    return None


def _encode_file_meta(filename: str, old_content: str, new_content: str) -> str:
    """Encode file metadata as a hidden prefix in the detail string.

    The UI layer (ToolDisplay) will strip this prefix before rendering
    and use the metadata for the editor diff ('e' key) and pager ('d' key).
    """
    meta = json.dumps({
        "filename": filename,
        "old_content": old_content,
        "new_content": new_content,
    }, ensure_ascii=False)
    return f"{_FILE_META_MARKER}{meta}{_FILE_META_MARKER}"


def _build_diff_detail(old: str, new: str) -> str:
    """Build a compact diff display for edit approval."""
    parts: List[str] = []
    for line in old.split("\n"):
        parts.append(f"  - {line}")
    for line in new.split("\n"):
        parts.append(f"  + {line}")
    if len(parts) > 30:
        parts = parts[:30]
        parts.append("  ... (truncado)")
    return "\n".join(parts)


def _build_post_edit_context(
    new_content: str,
    new_string: str,
    context_lines: int = 10,
    max_total_lines: int = 60,
) -> str:
    """Return ~context_lines of post-edit content around the inserted region.

    Lets the agent verify the edit and chain follow-up edits without re-reading
    the file. Returns line-numbered output (matching read_file format) so the
    agent can reference exact line numbers.
    """
    if not new_content or not new_string:
        return ""

    pos = new_content.find(new_string)
    if pos == -1:
        # new_string was empty after a deletion, or a fuzzy replace was used.
        # Skip context — caller will fall back to grep/read.
        return ""

    # Convert byte offset to (start_line, end_line) of the new_string.
    prefix = new_content[:pos]
    start_line = prefix.count("\n") + 1  # 1-indexed
    new_string_line_count = max(1, new_string.count("\n") + (1 if new_string else 0))
    end_line = start_line + new_string_line_count - 1

    all_lines = new_content.split("\n")
    total_lines = len(all_lines)

    window_start = max(1, start_line - context_lines)
    window_end = min(total_lines, end_line + context_lines)

    # Bound the total slice in case the edit itself is huge
    if window_end - window_start + 1 > max_total_lines:
        window_end = window_start + max_total_lines - 1

    width = len(str(window_end))
    out_lines: List[str] = []
    for ln in range(window_start, window_end + 1):
        marker = ">" if start_line <= ln <= end_line else " "
        out_lines.append(f"{ln:>{width}} {marker} {all_lines[ln - 1]}")

    header = (
        f"  (lineas {window_start}-{window_end} de {total_lines}, "
        f"'>' marca las lineas modificadas)"
    )
    return header + "\n" + "\n".join(out_lines)


def _build_write_diff(current: str, new: str) -> str:
    """Build a unified-style diff for write_file approval."""
    import difflib

    current_lines = current.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)

    diff = list(difflib.unified_diff(
        current_lines, new_lines, fromfile="actual", tofile="nuevo", lineterm="",
    ))

    if not diff:
        return "Sin cambios (contenido identico)"

    parts: List[str] = []
    for line in diff:
        line = line.rstrip("\n")
        if line.startswith("---") or line.startswith("+++"):
            continue
        elif line.startswith("@@"):
            parts.append(f"  {line}")
        elif line.startswith("-"):
            parts.append(f"  - {line[1:]}")
        elif line.startswith("+"):
            parts.append(f"  + {line[1:]}")
        else:
            parts.append(f"    {line[1:]}" if line.startswith(" ") else f"    {line}")

    if len(parts) > 40:
        parts = parts[:40]
        parts.append("  ... (truncado)")

    return "\n".join(parts)
