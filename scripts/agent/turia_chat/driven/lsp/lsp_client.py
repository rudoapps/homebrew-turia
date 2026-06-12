"""Generic LSP client over stdio with Content-Length framing."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class LSPError(Exception):
    """Raised when the LSP server returns an error response."""

    def __init__(self, code: int, message: str):
        self.code = code
        super().__init__(f"LSP error {code}: {message}")


class LSPClient:
    """Async LSP client that communicates via stdin/stdout with Content-Length framing.

    Usage::

        client = LSPClient(["pyright-langserver", "--stdio"], "/path/to/project")
        capabilities = await client.start()
        symbols = await client.document_symbols("src/main.py")
        await client.stop()
    """

    def __init__(self, command: List[str], root_path: str) -> None:
        self._command = command
        self._root_path = root_path
        self._root_uri = Path(root_path).as_uri()
        self._process: Optional[asyncio.subprocess.Process] = None
        self._request_id = 0
        self._pending: Dict[int, asyncio.Future[Any]] = {}
        self._reader_task: Optional[asyncio.Task[None]] = None
        self._capabilities: Dict[str, Any] = {}
        self._open_files: set[str] = set()

    @property
    def capabilities(self) -> Dict[str, Any]:
        return self._capabilities

    async def start(self) -> Dict[str, Any]:
        """Start the LSP server and perform the initialize handshake."""
        env = {**os.environ, "NODE_OPTIONS": ""}
        self._process = await asyncio.create_subprocess_exec(
            *self._command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=self._root_path,
            env=env,
        )
        self._reader_task = asyncio.create_task(self._read_loop())

        result = await self._request("initialize", {
            "processId": os.getpid(),
            "rootUri": self._root_uri,
            "rootPath": self._root_path,
            "capabilities": {
                "textDocument": {
                    "documentSymbol": {
                        "hierarchicalDocumentSymbolSupport": True,
                        "symbolKind": {
                            "valueSet": list(range(1, 27)),
                        },
                    },
                    "definition": {"linkSupport": True},
                    "references": {},
                    "hover": {"contentFormat": ["plaintext", "markdown"]},
                },
            },
            "workspaceFolders": [
                {"uri": self._root_uri, "name": Path(self._root_path).name},
            ],
        })
        self._capabilities = result.get("capabilities", {})
        await self._notify("initialized", {})
        return self._capabilities

    async def stop(self) -> None:
        """Shutdown the LSP server gracefully."""
        if not self._process:
            return
        try:
            await asyncio.wait_for(self._request("shutdown", None), timeout=5.0)
            await self._notify("exit", None)
        except Exception:
            pass
        finally:
            if self._reader_task and not self._reader_task.done():
                self._reader_task.cancel()
            if self._process and self._process.returncode is None:
                try:
                    self._process.terminate()
                    await asyncio.wait_for(self._process.wait(), timeout=3.0)
                except (asyncio.TimeoutError, ProcessLookupError):
                    try:
                        self._process.kill()
                    except ProcessLookupError:
                        pass
            self._process = None
            # Cancel any pending futures
            for future in self._pending.values():
                if not future.done():
                    future.cancel()
            self._pending.clear()

    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    # ── LSP operations ──────────────────────────────────────────────────

    async def document_symbols(self, file_path: str) -> List[Dict[str, Any]]:
        """Get all symbols in a document."""
        uri = self._file_uri(file_path)
        await self._ensure_open(file_path)
        result = await self._request("textDocument/documentSymbol", {
            "textDocument": {"uri": uri},
        })
        return result if isinstance(result, list) else []

    async def definition(
        self, file_path: str, line: int, character: int,
    ) -> List[Dict[str, Any]]:
        """Go to definition of the symbol at a position."""
        uri = self._file_uri(file_path)
        await self._ensure_open(file_path)
        result = await self._request("textDocument/definition", {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": character},
        })
        if result is None:
            return []
        if isinstance(result, dict):
            return [result]
        return result if isinstance(result, list) else []

    async def references(
        self, file_path: str, line: int, character: int,
    ) -> List[Dict[str, Any]]:
        """Find all references to the symbol at a position."""
        uri = self._file_uri(file_path)
        await self._ensure_open(file_path)
        result = await self._request("textDocument/references", {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": character},
            "context": {"includeDeclaration": True},
        })
        return result if isinstance(result, list) else []

    async def hover(
        self, file_path: str, line: int, character: int,
    ) -> Optional[str]:
        """Get hover information (type, docs) for a symbol at a position."""
        uri = self._file_uri(file_path)
        await self._ensure_open(file_path)
        result = await self._request("textDocument/hover", {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": character},
        })
        if not result or "contents" not in result:
            return None
        return self._extract_hover_text(result["contents"])

    # ── Document management ─────────────────────────────────────────────

    async def _ensure_open(self, file_path: str) -> None:
        """Open a file in the LSP server if not already open."""
        resolved = self._resolve_path(file_path)
        if resolved in self._open_files:
            return
        uri = Path(resolved).as_uri()
        try:
            with open(resolved, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            return
        ext = os.path.splitext(resolved)[1].lower()
        lang_id = _EXT_TO_LANGUAGE_ID.get(ext, "plaintext")
        await self._notify("textDocument/didOpen", {
            "textDocument": {
                "uri": uri,
                "languageId": lang_id,
                "version": 1,
                "text": text,
            },
        })
        self._open_files.add(resolved)

    # ── JSON-RPC transport with Content-Length framing ───────────────────

    async def _request(self, method: str, params: Any) -> Any:
        """Send a JSON-RPC request and wait for the response."""
        if not self._process or not self._process.stdin:
            raise LSPError(-1, "LSP server not running")

        self._request_id += 1
        rid = self._request_id
        future: asyncio.Future[Any] = asyncio.get_event_loop().create_future()
        self._pending[rid] = future

        msg: Dict[str, Any] = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            msg["params"] = params

        await self._send(msg)
        try:
            return await asyncio.wait_for(future, timeout=30.0)
        except asyncio.TimeoutError:
            self._pending.pop(rid, None)
            raise LSPError(-1, f"Timeout waiting for {method}")

    async def _notify(self, method: str, params: Any) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        msg: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        await self._send(msg)

    async def _send(self, msg: Dict[str, Any]) -> None:
        """Write a JSON-RPC message with Content-Length header."""
        if not self._process or not self._process.stdin:
            return
        body = json.dumps(msg).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        self._process.stdin.write(header + body)
        await self._process.stdin.drain()

    async def _read_loop(self) -> None:
        """Read JSON-RPC messages from stdout in a background task."""
        assert self._process and self._process.stdout
        reader = self._process.stdout
        try:
            while True:
                # Read headers until empty line
                content_length = 0
                while True:
                    line = await reader.readline()
                    if not line:
                        return  # EOF
                    line_str = line.decode("ascii", errors="replace").strip()
                    if not line_str:
                        break
                    if line_str.lower().startswith("content-length:"):
                        content_length = int(line_str.split(":")[1].strip())

                if content_length == 0:
                    continue

                body = await reader.readexactly(content_length)
                msg = json.loads(body)

                # Handle response to a pending request
                if "id" in msg and msg["id"] in self._pending:
                    future = self._pending.pop(msg["id"])
                    if not future.done():
                        if "error" in msg:
                            err = msg["error"]
                            future.set_exception(
                                LSPError(err.get("code", -1), err.get("message", "unknown"))
                            )
                        else:
                            future.set_result(msg.get("result"))
                # Server notifications (diagnostics, etc.) are silently ignored

        except (asyncio.CancelledError, asyncio.IncompleteReadError, ConnectionError):
            pass
        except Exception as exc:
            logger.debug("LSP read loop error: %s", exc)

    # ── Helpers ─────────────────────────────────────────────────────────

    def _file_uri(self, file_path: str) -> str:
        resolved = self._resolve_path(file_path)
        return Path(resolved).as_uri()

    def _resolve_path(self, file_path: str) -> str:
        p = Path(file_path)
        if not p.is_absolute():
            p = Path(self._root_path) / p
        return str(p.resolve())

    @staticmethod
    def _extract_hover_text(contents: Any) -> str:
        """Extract readable text from hover contents (string, MarkupContent, or list)."""
        if isinstance(contents, str):
            return contents
        if isinstance(contents, dict):
            return contents.get("value", str(contents))
        if isinstance(contents, list):
            parts = []
            for item in contents:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    parts.append(item.get("value", str(item)))
            return "\n".join(parts)
        return str(contents)


# ── Language ID mapping ─────────────────────────────────────────────────

_EXT_TO_LANGUAGE_ID: Dict[str, str] = {
    ".py": "python",
    ".swift": "swift",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".java": "java",
    ".ts": "typescript",
    ".tsx": "typescriptreact",
    ".js": "javascript",
    ".jsx": "javascriptreact",
    ".dart": "dart",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".vue": "vue",
    ".svelte": "svelte",
}
