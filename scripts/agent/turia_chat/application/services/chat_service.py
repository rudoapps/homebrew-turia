"""Chat service — orchestrates sending messages and streaming responses."""

from __future__ import annotations

from typing import Any, AsyncGenerator, Dict, List, Optional

from ..ports.driven.api_client_port import ApiClientPort
from ..ports.driven.config_port import ConfigPort
from .auth_service import AuthService, AuthenticationError
from ...domain.entities.sse_event import SSEEvent, ErrorEvent
from ...domain.entities.tool_result import ToolResult


class ChatService:
    """Orchestrates the chat flow: auth -> payload -> stream -> events.

    This is the primary use case for Phase 1. It:
      1. Validates authentication (refreshing tokens if needed).
      2. Builds the chat payload via the payload builder.
      3. Streams SSE events from the API.
      4. Yields typed domain events to the caller.
      5. Handles 401 by refreshing and retrying once.
    """

    def __init__(
        self,
        auth_service: AuthService,
        api_client: ApiClientPort,
        config_port: ConfigPort,
        debug: bool = False,
    ) -> None:
        self._auth = auth_service
        self._api_client = api_client
        self._config_port = config_port
        self._debug = debug

    async def send_message(
        self,
        prompt: str,
        conversation_id: Optional[int] = None,
        tool_results: Optional[List[ToolResult]] = None,
        project_context: Optional[Dict[str, Any]] = None,
        images: Optional[List[Dict[str, str]]] = None,
        model: Optional[str] = None,
        max_iterations: int = 15,
        subagent_id: Optional[str] = None,
        git_remote_url: Optional[str] = None,
        turia_version: Optional[str] = None,
        system_prompt_addition: Optional[str] = None,
    ) -> AsyncGenerator[SSEEvent, None]:
        """Send a message and yield SSE events as they stream back.

        Args:
            prompt: The user's message text.
            conversation_id: Existing conversation to continue, or None for new.
            tool_results: Results from previous tool executions.
            project_context: Project context dict (git info, file tree, etc.).
            images: List of image dicts with 'data' and 'media_type' keys.
            model: Override model ID, or None for default/auto.
            max_iterations: Maximum agent iterations.
            subagent_id: Subagent ID for delegating to a specific subagent.

        Yields:
            SSEEvent instances as they arrive from the server.
        """
        # Step 1: Ensure valid auth
        try:
            config = await self._auth.ensure_valid_token()
        except AuthenticationError as exc:
            yield ErrorEvent(error=str(exc))
            return

        # Step 2: Build payload
        from ...driven.api.payload_builder import build_chat_payload

        effective_model = model or config.preferred_model
        payload = build_chat_payload(
            prompt=prompt,
            conversation_id=conversation_id,
            tool_results=tool_results,
            project_context=project_context,
            images=images,
            model=effective_model,
            max_iterations=max_iterations,
            subagent_id=subagent_id,
            git_remote_url=git_remote_url,
            turia_version=turia_version,
            system_prompt_addition=system_prompt_addition,
        )

        # Debug: log payload
        if self._debug:
            import json
            import sys
            print(
                f"[DEBUG] Endpoint: {config.chat_endpoint}",
                file=sys.stderr,
            )
            # Redact large fields for readability
            debug_payload = dict(payload)
            if "project_context" in debug_payload and debug_payload["project_context"]:
                ctx = debug_payload["project_context"]
                debug_payload["project_context"] = {
                    k: (v[:80] + "..." if isinstance(v, str) and len(v) > 80 else v)
                    for k, v in ctx.items()
                }
            if "tool_results" in debug_payload:
                for tr in debug_payload.get("tool_results", []):
                    if isinstance(tr.get("result"), str) and len(tr["result"]) > 200:
                        tr["result"] = tr["result"][:200] + "..."
            print(
                f"[DEBUG] Payload: {json.dumps(debug_payload, ensure_ascii=False, indent=2)}",
                file=sys.stderr,
            )

        # Step 3: Stream with 401 retry
        retried_auth = False
        async for event in self._stream_with_auth_retry(
            config=config,
            payload=payload,
            retried=retried_auth,
        ):
            yield event

    async def _stream_with_auth_retry(
        self,
        config: Any,
        payload: Dict[str, Any],
        retried: bool,
    ) -> AsyncGenerator[SSEEvent, None]:
        """Stream SSE events, retrying once on 401."""
        try:
            async for event in self._api_client.send_chat(
                endpoint=config.chat_endpoint,
                access_token=config.access_token,
                payload=payload,
            ):
                # Check if we got an auth error event
                if isinstance(event, ErrorEvent) and "401" in event.error and not retried:
                    # Try refreshing and retry
                    try:
                        config = await self._auth.refresh()
                        async for retry_event in self._api_client.send_chat(
                            endpoint=config.chat_endpoint,
                            access_token=config.access_token,
                            payload=payload,
                        ):
                            yield retry_event
                        return
                    except AuthenticationError as exc:
                        yield ErrorEvent(error=str(exc))
                        return
                yield event
        except Exception as exc:
            yield ErrorEvent(error=f"Error de conexion: {exc}")
