"""ToolResult entity representing the output of a tool execution."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolResult:
    """The result of executing a tool.

    Attributes:
        id: The tool_call ID this result corresponds to.
        name: The tool function name.
        output: The string output produced by the tool.
        success: Whether the tool executed successfully.
    """

    id: str
    name: str
    output: str
    success: bool = True
