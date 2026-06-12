"""Single-message handler — sends one prompt and renders the streamed response."""

from __future__ import annotations

from typing import Optional

from ...application.services.chat_service import ChatService
from ...application.ports.driven.config_port import ConfigPort
from ...domain.entities.sse_event import StartedEvent
from ..ui.renderer import SSERenderer


class SingleMessageHandler:
    """Handles the single-shot message flow: send prompt, render stream, exit.

    This is the handler for `chat.py "hello"` mode.
    """

    def __init__(
        self,
        chat_service: ChatService,
        config_port: ConfigPort,
    ) -> None:
        self._chat_service = chat_service
        self._config_port = config_port

    async def run(
        self,
        prompt: str,
        conversation_id: Optional[int] = None,
    ) -> int:
        """Send a single message and render the streamed response.

        Args:
            prompt: The user's message.
            conversation_id: Optional conversation to continue.

        Returns:
            Exit code: 0 for success, 1 for error.
        """
        renderer = SSERenderer()

        try:
            async for event in self._chat_service.send_message(
                prompt=prompt,
                conversation_id=conversation_id,
            ):
                # Track conversation ID for project persistence
                if isinstance(event, StartedEvent) and event.conversation_id:
                    self._config_port.set_project_conversation(
                        event.conversation_id
                    )

                renderer.render(event)

        except KeyboardInterrupt:
            renderer.finalize()
            return 130  # Standard SIGINT exit code

        finally:
            renderer.finalize()

        return 0
