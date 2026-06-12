"""ToolCall entity representing a tool the model wants to execute."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class ToolCall:
    """A tool invocation requested by the model.

    Attributes:
        id: Unique identifier for this tool call.
        name: The tool function name (e.g. "read_file", "execute_command").
        input: The arguments/parameters for the tool.
    """

    id: str
    name: str
    input: Dict[str, Any]
