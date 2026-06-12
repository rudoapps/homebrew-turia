"""SSE protocol parser — converts raw SSE lines into typed domain events."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple

from ...domain.entities.sse_event import (
    SSEEvent,
    StartedEvent,
    ThinkingEvent,
    TextEvent,
    ToolRequestsEvent,
    CompleteEvent,
    ErrorEvent,
    CostWarningEvent,
    CostLimitExceededEvent,
    RateLimitedEvent,
    RagSearchEvent,
    RagContextEvent,
    DelegationEvent,
    ProviderFallbackEvent,
    NoProvidersAvailableEvent,
    RepairedEvent,
    InternalCallEvent,
)
from ...domain.entities.tool_call import ToolCall


def parse_sse_line(line: str) -> Tuple[Optional[str], Optional[str]]:
    """Parse a single SSE line into (field, value).

    SSE protocol format:
      - "event: <type>" -> ("event", "<type>")
      - "data: <json>"  -> ("data", "<json>")
      - empty line       -> (None, None) — event boundary
      - other            -> ("raw", line) — non-SSE data (possible error JSON)

    Returns:
        Tuple of (field_name, field_value), or (None, None) for blank lines.
    """
    if not line:
        return None, None

    if line.startswith("event:"):
        return "event", line[6:].strip()

    if line.startswith("data:"):
        return "data", line[5:].strip()

    # Non-SSE line — could be a raw JSON error from the server
    return "raw", line


def parse_sse_event(event_type: str, data_json: str) -> Optional[SSEEvent]:
    """Parse an SSE event type and its JSON data into a typed domain event.

    Args:
        event_type: The event type string (e.g. "started", "text", "complete").
        data_json: The raw JSON string from the data: field.

    Returns:
        A typed SSEEvent instance, or None if the event is unrecognized.
    """
    try:
        data: Dict[str, Any] = json.loads(data_json)
    except json.JSONDecodeError:
        return ErrorEvent(error=f"JSON parse error: {data_json[:100]}")

    return _build_event(event_type, data)


def parse_raw_error(raw_line: str) -> Optional[ErrorEvent]:
    """Try to parse a non-SSE line as a JSON error response.

    The server may return a JSON error body without SSE framing on HTTP errors.

    Returns:
        An ErrorEvent if the line contains an error, else None.
    """
    try:
        data = json.loads(raw_line)
    except (json.JSONDecodeError, ValueError):
        return None

    error_msg: Optional[str] = None

    if isinstance(data, list) and data:
        error_msg = data[0].get("message", str(data))
    elif isinstance(data, dict):
        detail = data.get("detail") or data.get("error") or data.get("message")
        if detail is not None:
            if isinstance(detail, list) and detail:
                error_msg = detail[0].get("message", str(detail))
            else:
                error_msg = str(detail)

    if error_msg:
        return ErrorEvent(error=error_msg)
    return None


def _build_event(event_type: str, data: Dict[str, Any]) -> Optional[SSEEvent]:
    """Map event type + parsed data to the correct domain event."""
    if event_type == "started":
        model_info = data.get("model", {})
        return StartedEvent(
            conversation_id=data.get("conversation_id", 0),
            rag_enabled=data.get("rag_enabled", False),
            rag_info=data.get("rag", {}),
            model=model_info.get("model", "") if isinstance(model_info, dict) else "",
            task_type=data.get("task_type", ""),
        )

    if event_type == "thinking":
        model_info = data.get("model", {})
        return ThinkingEvent(
            iteration=data.get("iteration", 0),
            model=model_info.get("model", "") if isinstance(model_info, dict) else "",
        )

    if event_type == "text":
        return TextEvent(
            content=data.get("content", ""),
            model=data.get("model", ""),
        )

    if event_type == "tool_requests":
        raw_calls = data.get("tool_calls", [])
        tool_calls = [
            ToolCall(
                id=tc.get("id", ""),
                name=tc.get("name", ""),
                input=tc.get("input", {}),
            )
            for tc in raw_calls
        ]
        return ToolRequestsEvent(
            tool_calls=tool_calls,
            conversation_id=data.get("conversation_id"),
            session_cost=data.get("session_cost", 0.0),
            session_tokens=(
                data.get("session_input_tokens", 0)
                + data.get("session_output_tokens", 0)
            ),
        )

    if event_type == "complete":
        return CompleteEvent(
            conversation_id=data.get("conversation_id"),
            total_cost=data.get("total_cost", 0.0),
            total_input_tokens=data.get("total_input_tokens", 0),
            total_output_tokens=data.get("total_output_tokens", 0),
            session_cost=data.get("session_cost", 0.0),
            session_input_tokens=data.get("session_input_tokens", 0),
            session_output_tokens=data.get("session_output_tokens", 0),
            session_internal_cost=data.get("session_internal_cost", 0.0),
            total_internal_cost=data.get("total_internal_cost", 0.0),
            max_iterations_reached=data.get("max_iterations_reached", False),
            truncation_stats=data.get("truncation_stats", {}),
        )

    if event_type == "internal_call":
        return InternalCallEvent(
            caller=data.get("caller", ""),
            model_id=data.get("model_id", ""),
            input_tokens=data.get("input_tokens", 0),
            output_tokens=data.get("output_tokens", 0),
            cache_creation_tokens=data.get("cache_creation_tokens", 0),
            cache_read_tokens=data.get("cache_read_tokens", 0),
            cost=data.get("cost", 0.0),
        )

    if event_type == "error":
        return ErrorEvent(error=data.get("error", "Unknown error"))

    if event_type == "cost_warning":
        return CostWarningEvent(
            usage_percent=data.get("usage_percent", 0.0),
            remaining=data.get("remaining", 0.0),
            monthly_limit=data.get("monthly_limit", 0.0),
        )

    if event_type == "cost_limit_exceeded":
        return CostLimitExceededEvent(
            current_cost=data.get("current_cost", 0.0),
            monthly_limit=data.get("monthly_limit", 0.0),
        )

    if event_type == "rate_limited":
        return RateLimitedEvent(
            message=data.get("message", ""),
            retry_after=data.get("retry_after", 0),
            conversation_id=data.get("conversation_id"),
        )

    if event_type == "rag_search":
        return RagSearchEvent(
            query=data.get("query", ""),
            project_type=data.get("project_type", ""),
        )

    if event_type == "rag_context":
        return RagContextEvent(
            chunks=data.get("chunks", 0),
            scope=data.get("scope", "current"),
            projects=data.get("projects", ""),
            project_type=data.get("project_type", ""),
        )

    if event_type == "delegation":
        return DelegationEvent(
            subagent_id=data.get("subagent_id", ""),
            task=data.get("task", ""),
        )

    if event_type == "provider_fallback":
        return ProviderFallbackEvent(
            failed_provider=data.get("failed_provider", ""),
            new_provider=data.get("new_provider", ""),
            new_model=data.get("new_model", ""),
            reason=data.get("reason", ""),
            message=data.get("message", ""),
        )

    if event_type == "no_providers_available":
        return NoProvidersAvailableEvent(
            providers_tried=data.get("providers_tried", []),
            message=data.get("message", ""),
        )

    if event_type == "repaired":
        return RepairedEvent(
            message=data.get("message", ""),
        )

    # Unrecognized event type — ignore silently
    return None
