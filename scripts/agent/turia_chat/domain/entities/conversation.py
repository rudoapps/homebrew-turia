"""Conversation entity tracking a full chat session."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .message import Message


@dataclass
class Conversation:
    """A conversation session with the agent.

    Attributes:
        id: Server-assigned conversation ID (None until started event).
        messages: Ordered list of messages in this conversation.
        total_cost: Cumulative cost in USD across all turns.
        total_tokens: Cumulative token count across all turns.
        session_cost: Cost for the current session/turn.
        session_tokens: Token count for the current session/turn.
        model: The model being used for this conversation.
        rag_enabled: Whether RAG is active for this conversation.
        max_iterations_reached: Whether the server hit the iteration limit.
    """

    id: Optional[int] = None
    messages: List[Message] = field(default_factory=list)
    total_cost: float = 0.0
    total_tokens: int = 0
    session_cost: float = 0.0
    session_tokens: int = 0
    model: Optional[str] = None
    rag_enabled: bool = False
    max_iterations_reached: bool = False

    def add_message(self, message: Message) -> None:
        """Append a message to the conversation."""
        self.messages.append(message)

    def update_from_complete(
        self,
        total_cost: float,
        total_tokens: int,
        session_cost: float,
        session_tokens: int,
        max_iterations_reached: bool = False,
    ) -> None:
        """Update conversation stats from a complete event."""
        self.total_cost = total_cost
        self.total_tokens = total_tokens
        self.session_cost = session_cost
        self.session_tokens = session_tokens
        self.max_iterations_reached = max_iterations_reached
