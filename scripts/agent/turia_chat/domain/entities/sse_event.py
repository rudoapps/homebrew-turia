"""Typed SSE event entities received from the agent API stream."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .tool_call import ToolCall


class SSEEvent:
    """Base class for all SSE events."""


@dataclass(frozen=True)
class StartedEvent(SSEEvent):
    """Conversation started. Carries the server-assigned conversation_id."""

    conversation_id: int
    rag_enabled: bool = False
    rag_info: Dict[str, Any] = field(default_factory=dict)
    model: str = ""
    task_type: str = ""


@dataclass(frozen=True)
class ThinkingEvent(SSEEvent):
    """Model is thinking (may include iteration number)."""

    iteration: int = 0
    model: str = ""


@dataclass(frozen=True)
class TextEvent(SSEEvent):
    """Streaming text content from the model."""

    content: str = ""
    model: str = ""


@dataclass(frozen=True)
class ToolRequestsEvent(SSEEvent):
    """Model wants to execute one or more tools."""

    tool_calls: List[ToolCall] = field(default_factory=list)
    conversation_id: Optional[int] = None
    session_cost: float = 0.0
    session_tokens: int = 0


@dataclass(frozen=True)
class CompleteEvent(SSEEvent):
    """Conversation turn is complete. Carries cost and token data."""

    conversation_id: Optional[int] = None
    total_cost: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    session_cost: float = 0.0
    session_input_tokens: int = 0
    session_output_tokens: int = 0
    # Cost of internal LLM calls (compaction, classifier, RAG enhancer, …)
    # NOT included in `session_cost`/`total_cost`. Surface separately so the
    # CLI can show "$X main + $Y internal".
    session_internal_cost: float = 0.0
    total_internal_cost: float = 0.0
    max_iterations_reached: bool = False
    truncation_stats: Dict[str, Any] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens

    @property
    def session_tokens(self) -> int:
        return self.session_input_tokens + self.session_output_tokens


@dataclass(frozen=True)
class InternalCallEvent(SSEEvent):
    """An internal LLM call (compaction, classifier, RAG enhancer, subagent…)
    just completed. Used by the CLI to surface where time/cost is going."""

    caller: str = ""
    model_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    cost: float = 0.0

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_creation_tokens
            + self.cache_read_tokens
        )


@dataclass(frozen=True)
class ErrorEvent(SSEEvent):
    """An error occurred on the server."""

    error: str = ""


@dataclass(frozen=True)
class CostWarningEvent(SSEEvent):
    """User is approaching their cost limit."""

    usage_percent: float = 0.0
    remaining: float = 0.0
    monthly_limit: float = 0.0


@dataclass(frozen=True)
class CostLimitExceededEvent(SSEEvent):
    """User has exceeded their monthly cost limit."""

    current_cost: float = 0.0
    monthly_limit: float = 0.0


@dataclass(frozen=True)
class RateLimitedEvent(SSEEvent):
    """Request was rate-limited."""

    message: str = ""
    retry_after: int = 0
    conversation_id: Optional[int] = None


@dataclass(frozen=True)
class RagSearchEvent(SSEEvent):
    """RAG search is being performed."""

    query: str = ""
    project_type: str = ""


@dataclass(frozen=True)
class RagContextEvent(SSEEvent):
    """RAG context was found."""

    chunks: int = 0
    scope: str = "current"
    projects: str = ""
    project_type: str = ""


@dataclass(frozen=True)
class DelegationEvent(SSEEvent):
    """Task is being delegated to a subagent."""

    subagent_id: str = ""
    task: str = ""


@dataclass(frozen=True)
class ProviderFallbackEvent(SSEEvent):
    """Switching LLM providers due to an error."""

    failed_provider: str = ""
    new_provider: str = ""
    new_model: str = ""
    reason: str = ""
    message: str = ""


@dataclass(frozen=True)
class NoProvidersAvailableEvent(SSEEvent):
    """All LLM providers failed."""

    providers_tried: List[str] = field(default_factory=list)
    message: str = ""


@dataclass(frozen=True)
class RepairedEvent(SSEEvent):
    """Conversation was repaired after an interrupted session."""

    message: str = ""
