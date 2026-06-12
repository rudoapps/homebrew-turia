"""Port (interface) for executing tool calls locally."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ....domain.entities.tool_call import ToolCall
from ....domain.entities.tool_result import ToolResult


class ToolExecutorPort(ABC):
    """Abstract interface for local tool execution.

    Implementations receive a ToolCall from the model and execute it
    on the local machine (read files, write files, run commands, etc.),
    returning a ToolResult to send back to the server.
    """

    @abstractmethod
    async def execute(self, tool_call: ToolCall) -> ToolResult:
        """Execute a single tool call and return its result.

        Args:
            tool_call: The tool invocation requested by the model.

        Returns:
            A ToolResult with the output (or error) of the execution.
        """
        ...
