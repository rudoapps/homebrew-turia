"""Subagent service — lists and invokes specialised subagents."""

from __future__ import annotations

from typing import Any, AsyncGenerator, Dict, List, Optional

from ..ports.driven.api_client_port import ApiClientPort
from .auth_service import AuthService, AuthenticationError
from .chat_service import ChatService
from ...domain.entities.sse_event import SSEEvent, ErrorEvent


class SubagentService:
    """Manages subagent discovery and invocation.

    Responsibilities:
      - Fetch the list of available subagents from the backend.
      - Invoke a subagent by delegating through the chat service with a
        subagent_id parameter.
    """

    def __init__(
        self,
        auth_service: AuthService,
        api_client: ApiClientPort,
        chat_service: ChatService,
    ) -> None:
        self._auth = auth_service
        self._api_client = api_client
        self._chat_service = chat_service

    async def list_subagents(self) -> List[Dict[str, Any]]:
        """Fetch the list of available subagents.

        Returns:
            List of subagent dicts with at least 'id' and 'description' keys.

        Raises:
            AuthenticationError: If authentication fails.
            Exception: On network or API errors.
        """
        config = await self._auth.ensure_valid_token()
        data = await self._api_client.get_subagents(
            api_url=config.api_url,
            access_token=config.access_token,
        )
        return data.get("subagents", [])

    async def invoke(
        self,
        subagent_id: str,
        prompt: str,
        conversation_id: Optional[int] = None,
    ) -> AsyncGenerator[SSEEvent, None]:
        """Invoke a subagent and stream the response.

        Delegates to chat_service.send_message with the subagent_id
        parameter so the backend routes to the correct subagent.

        Args:
            subagent_id: Identifier of the subagent to invoke.
            prompt: The user's prompt/task for the subagent.
            conversation_id: Existing conversation to continue, or None.

        Yields:
            SSEEvent instances as they stream back from the server.
        """
        async for event in self._chat_service.send_message(
            prompt=prompt,
            conversation_id=conversation_id,
            subagent_id=subagent_id,
            max_iterations=15,
        ):
            yield event
