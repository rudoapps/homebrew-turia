"""Local tool executor — dispatches tool calls to specialized executors.

Each tool category has its own module:
- file_tools.py: read, write, edit, move, undo, find_and_replace
- search_tools.py: search_code, grep, list_files
- shell_tools.py: run_command, git_info, file_diff
- code_analysis_tools.py: symbols, find_definition, find_references
- web_tools.py: web_fetch
"""

from __future__ import annotations

from typing import Optional

from ...application.ports.driven.tool_executor_port import ToolExecutorPort
from ...domain.entities.tool_call import ToolCall
from ...domain.entities.tool_result import ToolResult
from ...domain.entities.permission_mode import PermissionMode
from .base import ToolDeniedError, ApprovalCallback
from .path_validator import PathValidator, OutsideAllowedDirError
from .file_backup import FileBackup
from .file_tools import FileToolExecutor
from .search_tools import SearchToolExecutor
from .shell_tools import ShellToolExecutor
from .code_analysis_tools import CodeAnalysisToolExecutor
from .web_tools import WebToolExecutor


class LocalToolExecutor(ToolExecutorPort):
    """Dispatches tool calls to specialized executors.

    Args:
        path_validator: Validates and resolves file paths.
        file_backup: Creates backups before file modifications.
        request_approval: Async callback for user approval of destructive ops.
    """

    def __init__(
        self,
        path_validator: PathValidator,
        file_backup: FileBackup,
        request_approval: Optional[ApprovalCallback] = None,
        project_type: str = "unknown",
    ) -> None:
        self._validator = path_validator
        self._backup = file_backup
        self._request_approval = request_approval

        # Create specialized executors
        args = (path_validator, file_backup, request_approval)
        self._file = FileToolExecutor(*args)
        self._search = SearchToolExecutor(*args)
        self._shell = ShellToolExecutor(*args)
        self._code = CodeAnalysisToolExecutor(*args, project_type=project_type)
        self._web = WebToolExecutor(*args)

        self._dispatch = {
            # File tools
            "read_file": self._file.read_file,
            "write_file": self._file.write_file,
            "edit_file": self._file.edit_file,
            "move_file": self._file.move_file,
            "undo_edit": self._file.undo_edit,
            "find_and_replace": self._file.find_and_replace,
            # Search tools
            "search_code": self._search.search_code,
            "grep": self._search.grep,
            "list_files": self._search.list_files,
            # Shell tools
            "run_command": self._shell.run_command,
            "git_info": self._shell.git_info,
            "file_diff": self._shell.file_diff,
            # Code analysis tools
            "symbols": self._code.symbols,
            "find_definition": self._code.find_definition,
            "find_references": self._code.find_references,
            "hover_info": self._code.hover_info,
            # Web tools
            "web_fetch": self._web.web_fetch,
        }

    @property
    def permission_mode(self) -> PermissionMode:
        return self._file.permission_mode

    def set_permission_mode(self, mode: PermissionMode) -> None:
        """Set permission mode on all executors."""
        for executor in (self._file, self._search, self._shell, self._code, self._web):
            executor.set_permission_mode(mode)

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        """Dispatch a tool call to the appropriate handler."""
        handler = self._dispatch.get(tool_call.name)
        if handler is None:
            return ToolResult(
                id=tool_call.id,
                name=tool_call.name,
                output=f"Herramienta desconocida: {tool_call.name}",
                success=False,
            )

        try:
            output = await handler(tool_call.input)
            return ToolResult(
                id=tool_call.id,
                name=tool_call.name,
                output=output,
                success=True,
            )
        except OutsideAllowedDirError as exc:
            granted = await self._request_dir_access(exc)
            if granted:
                try:
                    output = await handler(tool_call.input)
                    return ToolResult(
                        id=tool_call.id, name=tool_call.name,
                        output=output, success=True,
                    )
                except Exception as retry_exc:
                    return ToolResult(
                        id=tool_call.id, name=tool_call.name,
                        output=f"Error ejecutando {tool_call.name}: {retry_exc}",
                        success=False,
                    )
            return ToolResult(
                id=tool_call.id, name=tool_call.name,
                output=f"Acceso denegado: '{exc.requested_dir}'",
                success=False,
            )
        except ToolDeniedError as exc:
            return ToolResult(
                id=tool_call.id, name=tool_call.name,
                output=str(exc), success=False,
            )
        except Exception as exc:
            return ToolResult(
                id=tool_call.id, name=tool_call.name,
                output=f"Error ejecutando {tool_call.name}: {exc}",
                success=False,
            )

    async def _request_dir_access(self, exc: OutsideAllowedDirError) -> bool:
        """Ask user for permission to access a directory outside the project."""
        if not self._request_approval:
            return False

        approved = await self._request_approval(
            f"Acceder a {exc.requested_dir}",
            (
                f"El agente quiere acceder a '{exc.raw_path}' que esta fuera\n"
                f"del directorio de trabajo actual ({exc.working_dir}).\n\n"
                f"Se permitira acceso a: {exc.requested_dir}"
            ),
        )
        if approved:
            self._validator.add_allowed_dir(exc.requested_dir)
        return approved
