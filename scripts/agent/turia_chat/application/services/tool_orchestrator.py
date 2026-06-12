"""Tool orchestrator — classifies and executes tool calls."""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol

from ...domain.entities.tool_call import ToolCall
from ...domain.entities.tool_result import ToolResult
from ...domain.entities.tool_metadata import PARALLEL_SAFE_TOOLS
from ..ports.driven.tool_executor_port import ToolExecutorPort


class ToolProgressCallback(Protocol):
    """Protocol for receiving tool execution progress updates."""

    def on_tool_start(self, name: str, input_dict: Dict[str, Any]) -> None:
        """Called when a tool begins execution."""
        ...

    def on_tool_complete(
        self,
        name: str,
        input_dict: Dict[str, Any],
        success: bool,
        elapsed: float,
        output: str = "",
    ) -> None:
        """Called when a tool finishes execution."""
        ...

    def on_parallel_summary(
        self,
        count: int,
        elapsed: float,
        has_errors: bool,
    ) -> None:
        """Called after a batch of parallel tools completes."""
        ...

    def on_multi_file_preview(
        self,
        count: int,
        summary: str,
    ) -> None:
        """Called before executing multiple file edits."""
        ...


class ToolOrchestrator:
    """Orchestrates tool execution: classifies, schedules, and tracks results.

    Parallel-safe tools (read_file, list_files, search_code, git_info) run
    concurrently via ThreadPoolExecutor.  Sequential tools (write_file,
    edit_file, run_command) run one at a time and require user approval.

    Args:
        executor: The driven adapter that actually executes each tool.
        progress: Optional callback for UI feedback.
    """

    DENIAL_THRESHOLD = 3  # After this many denials, inject warning

    def __init__(
        self,
        executor: ToolExecutorPort,
        progress: Optional[ToolProgressCallback] = None,
        hook_runner: Optional[Any] = None,
    ) -> None:
        self._executor = executor
        self._progress = progress
        self._hook_runner = hook_runner
        self._abort_event = asyncio.Event()
        self._read_cache: Dict[str, str] = {}
        self._thread_pool = ThreadPoolExecutor(max_workers=4)
        self._denial_counts: Dict[str, int] = {}  # tool_name → consecutive denials
        self._file_changes: List[Dict[str, str]] = []  # session file change log

    @property
    def read_cache(self) -> Dict[str, str]:
        """Expose the read_file cache for inspection."""
        return self._read_cache

    @property
    def file_changes(self) -> List[Dict[str, str]]:
        """Log of all file changes in this session."""
        return self._file_changes

    @property
    def permission_mode(self):
        """Current permission mode."""
        return self._executor.permission_mode

    def set_permission_mode(self, mode) -> None:
        """Set permission mode on the executor."""
        self._executor.set_permission_mode(mode)

    def request_abort(self) -> None:
        """Signal that all pending tool execution should abort."""
        self._abort_event.set()

    def reset_abort(self) -> None:
        """Clear the abort signal for a new turn."""
        self._abort_event.clear()

    async def execute_all(
        self,
        tool_calls: List[ToolCall],
    ) -> List[ToolResult]:
        """Execute a batch of tool calls with proper scheduling.

        Parallel-safe tools run concurrently first, then sequential tools
        run one by one.  Abort is checked between each tool.

        Args:
            tool_calls: The list of ToolCall objects from the model.

        Returns:
            A list of ToolResult objects, one per tool call (same order).
        """
        self.reset_abort()

        parallel, sequential = self._classify(tool_calls)
        results: Dict[str, ToolResult] = {}

        # ── Phase 1: parallel-safe tools ─────────────────────────────
        if parallel:
            t0 = time.time()
            parallel_results = await self._run_parallel(parallel)
            elapsed = time.time() - t0
            has_errors = any(not r.success for r in parallel_results)

            for tc, result in zip(parallel, parallel_results):
                results[tc.id] = result
                # Cache successful read_file results
                if tc.name == "read_file" and result.success:
                    path = tc.input.get("path", tc.input.get("file_path", ""))
                    if path:
                        self._read_cache[path] = result.output

            if self._progress:
                self._progress.on_parallel_summary(
                    len(parallel), elapsed, has_errors
                )

        # ── Multi-file preview: show summary before sequential edits ──
        write_edits = [tc for tc in sequential if tc.name in ("write_file", "edit_file")]
        if len(write_edits) > 1 and self._progress:
            import os
            summary_lines = []
            for tc in write_edits:
                path = tc.input.get("path", tc.input.get("file_path", "?"))
                if tc.name == "edit_file":
                    old = tc.input.get("old_string", "")[:60].replace("\n", " ")
                    summary_lines.append(f"  edit {path} ({len(old)} chars)")
                else:
                    size = len(tc.input.get("content", ""))
                    summary_lines.append(f"  write {path} ({size} chars)")
            self._progress.on_multi_file_preview(
                len(write_edits), "\n".join(summary_lines)
            )

        # ── Phase 2: sequential tools ────────────────────────────────
        for tc in sequential:
            if self._abort_event.is_set():
                results[tc.id] = ToolResult(
                    id=tc.id,
                    name=tc.name,
                    output="Ejecucion abortada por el usuario.",
                    success=False,
                )
                continue

            result = await self._run_single(tc)
            results[tc.id] = result

            # Track denials
            if not result.success and "rechazada" in result.output.lower():
                self._denial_counts[tc.name] = self._denial_counts.get(tc.name, 0) + 1
                if self._denial_counts[tc.name] >= self.DENIAL_THRESHOLD:
                    result.output += (
                        f"\n\n[SISTEMA] El usuario ha rechazado {tc.name} "
                        f"{self._denial_counts[tc.name]} veces consecutivas. "
                        f"CAMBIA de estrategia: pregunta al usuario qué approach prefiere "
                        f"o propón una alternativa diferente."
                    )
            elif result.success:
                self._denial_counts.pop(tc.name, None)

            # Track file changes for /changes
            if tc.name in ("write_file", "edit_file", "move_file") and result.success:
                path = tc.input.get("path", tc.input.get("file_path", ""))
                self._file_changes.append({
                    "action": tc.name.replace("_file", ""),
                    "path": path,
                })

            # Invalidate read cache on write/edit
            if tc.name in ("write_file", "edit_file") and result.success:
                path = tc.input.get("path", tc.input.get("file_path", ""))
                self._read_cache.pop(path, None)

        # Return in original order
        return [results[tc.id] for tc in tool_calls]

    def _classify(
        self,
        tool_calls: List[ToolCall],
    ) -> tuple[List[ToolCall], List[ToolCall]]:
        """Split tool calls into parallel-safe and sequential groups."""
        parallel: List[ToolCall] = []
        sequential: List[ToolCall] = []
        for tc in tool_calls:
            if tc.name in PARALLEL_SAFE_TOOLS:
                parallel.append(tc)
            else:
                sequential.append(tc)
        return parallel, sequential

    async def _run_parallel(
        self,
        tool_calls: List[ToolCall],
    ) -> List[ToolResult]:
        """Run multiple tools concurrently."""
        tasks = [self._run_single(tc) for tc in tool_calls]
        return await asyncio.gather(*tasks)

    async def _run_single(self, tool_call: ToolCall) -> ToolResult:
        """Execute a single tool with progress tracking."""
        if self._progress:
            self._progress.on_tool_start(tool_call.name, tool_call.input)

        t0 = time.time()
        try:
            # Check read cache for read_file
            if tool_call.name == "read_file":
                path = tool_call.input.get(
                    "path", tool_call.input.get("file_path", "")
                )
                if path in self._read_cache:
                    result = ToolResult(
                        id=tool_call.id,
                        name=tool_call.name,
                        output=self._read_cache[path],
                        success=True,
                    )
                    elapsed = time.time() - t0
                    if self._progress:
                        self._progress.on_tool_complete(
                            tool_call.name, tool_call.input, True, elapsed, result.output
                        )
                    return result

            # Pre-tool hooks
            if self._hook_runner:
                pre_results = await self._hook_runner.run_hooks(
                    "pre_tool_use", tool_call.name, tool_call.input
                )
                for hr in pre_results:
                    if hr.blocked:
                        return ToolResult(
                            id=tool_call.id,
                            name=tool_call.name,
                            output=f"Bloqueado por hook '{hr.name}': {hr.stderr}",
                            success=False,
                        )

            result = await self._executor.execute(tool_call)

            # Post-tool hooks
            if self._hook_runner:
                await self._hook_runner.run_hooks(
                    "post_tool_use", tool_call.name, tool_call.input,
                    tool_output=result.output[:500] if result.output else "",
                )

        except Exception as exc:
            result = ToolResult(
                id=tool_call.id,
                name=tool_call.name,
                output=f"Error interno: {exc}",
                success=False,
            )

        elapsed = time.time() - t0
        if self._progress:
            self._progress.on_tool_complete(
                tool_call.name, tool_call.input, result.success, elapsed, result.output
            )
        return result
