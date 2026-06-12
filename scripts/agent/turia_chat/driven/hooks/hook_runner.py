"""Hook runner — executes shell scripts at tool lifecycle events.

Hooks are configured in .turia/hooks.yaml or ~/.config/turia-agent/hooks.yaml:

```yaml
pre_tool_use:
  - name: "lint before write"
    match: "write_file|edit_file"
    command: "eslint --fix {path}"

post_tool_use:
  - name: "notify on run"
    match: "run_command"
    command: "echo 'Command executed: {command}'"
```

Hook exit codes:
  0 = success (continue)
  2 = block action (stderr shown to user)
  other = warning only (continue)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Hook:
    """A configured hook."""
    name: str
    event: str  # pre_tool_use, post_tool_use
    match: str = ""  # regex to match tool name
    command: str = ""  # shell command to run


@dataclass
class HookResult:
    """Result of running a hook."""
    name: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    blocked: bool = False


class HookRunner:
    """Loads and executes hooks from config files."""

    def __init__(self, project_dir: str = ".") -> None:
        self._hooks: List[Hook] = []
        self._project_dir = project_dir
        self._load_hooks()

    def _load_hooks(self) -> None:
        """Load hooks from project and user config."""
        # Project hooks (highest priority)
        project_file = Path(self._project_dir) / ".turia" / "hooks.yaml"
        if project_file.is_file():
            self._parse_hooks_file(project_file)

        # User hooks
        user_file = Path.home() / ".config" / "turia-agent" / "hooks.yaml"
        if user_file.is_file():
            self._parse_hooks_file(user_file)

    def _parse_hooks_file(self, path: Path) -> None:
        """Parse a YAML hooks file."""
        try:
            import yaml
            with open(path) as f:
                data = yaml.safe_load(f)
            if not isinstance(data, dict):
                return

            for event in ("pre_tool_use", "post_tool_use"):
                for entry in data.get(event, []):
                    if isinstance(entry, dict) and entry.get("command"):
                        self._hooks.append(Hook(
                            name=entry.get("name", entry["command"][:40]),
                            event=event,
                            match=entry.get("match", ""),
                            command=entry["command"],
                        ))
            logger.info(f"Loaded {len(self._hooks)} hooks from {path}")
        except Exception as e:
            logger.warning(f"Error loading hooks from {path}: {e}")

    def has_hooks(self, event: str) -> bool:
        """Check if there are any hooks for an event."""
        return any(h.event == event for h in self._hooks)

    def _get_matching_hooks(self, event: str, tool_name: str) -> List[Hook]:
        """Get hooks matching an event and tool name."""
        matching = []
        for hook in self._hooks:
            if hook.event != event:
                continue
            if hook.match and not re.search(hook.match, tool_name):
                continue
            matching.append(hook)
        return matching

    async def run_hooks(
        self,
        event: str,
        tool_name: str,
        tool_input: Dict[str, Any],
        tool_output: str = "",
    ) -> List[HookResult]:
        """Run all matching hooks for an event.

        Args:
            event: "pre_tool_use" or "post_tool_use"
            tool_name: Name of the tool being executed
            tool_input: Tool input parameters
            tool_output: Tool output (only for post_tool_use)

        Returns:
            List of hook results. Check .blocked for pre_tool_use hooks.
        """
        hooks = self._get_matching_hooks(event, tool_name)
        if not hooks:
            return []

        results = []
        # Build context for variable substitution
        context = {
            "tool_name": tool_name,
            "event": event,
            **{k: str(v) for k, v in tool_input.items()},
        }
        if tool_output:
            context["output"] = tool_output[:500]

        for hook in hooks:
            result = await self._execute_hook(hook, context)
            results.append(result)
            # If a pre hook blocks, stop executing further hooks
            if result.blocked:
                break

        return results

    async def _execute_hook(
        self, hook: Hook, context: Dict[str, str]
    ) -> HookResult:
        """Execute a single hook."""
        # Substitute variables in command
        cmd = hook.command
        for key, value in context.items():
            cmd = cmd.replace(f"{{{key}}}", value)

        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._project_dir,
                env={**os.environ, "TURIA_TOOL": context.get("tool_name", "")},
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=30
            )

            exit_code = proc.returncode or 0
            stdout_str = stdout.decode("utf-8", errors="replace").strip()
            stderr_str = stderr.decode("utf-8", errors="replace").strip()

            return HookResult(
                name=hook.name,
                exit_code=exit_code,
                stdout=stdout_str,
                stderr=stderr_str,
                blocked=(exit_code == 2),
            )

        except asyncio.TimeoutError:
            return HookResult(
                name=hook.name, exit_code=-1,
                stderr="Hook timeout (30s)", blocked=False,
            )
        except Exception as e:
            return HookResult(
                name=hook.name, exit_code=-1,
                stderr=str(e), blocked=False,
            )
