"""Port (interface) for the agent API client."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Dict, List, Optional

from ....domain.entities.sse_event import SSEEvent
from ....domain.entities.config import AuthTokens


class ApiClientPort(ABC):
    """Abstract interface for communicating with the agent API.

    Implementations handle HTTP transport, SSE parsing, and retry logic.
    """

    @abstractmethod
    async def send_chat(
        self,
        endpoint: str,
        access_token: str,
        payload: Dict[str, Any],
    ) -> AsyncGenerator[SSEEvent, None]:
        """Send a chat request and yield SSE events as they stream in.

        Args:
            endpoint: Full URL of the chat SSE endpoint.
            access_token: Bearer token for authorization.
            payload: JSON-serializable chat payload.

        Yields:
            Typed SSEEvent instances as they arrive from the server.

        Raises:
            ConnectionError: If the server cannot be reached after retries.
            AuthenticationError: If the server returns 401.
        """
        yield  # pragma: no cover — abstract generator
        return  # type: ignore[misc]

    @abstractmethod
    async def refresh_token(
        self,
        api_url: str,
        refresh_token: str,
    ) -> AuthTokens:
        """Exchange a refresh token for new access + refresh tokens.

        Args:
            api_url: Base API URL.
            refresh_token: The current refresh token.

        Returns:
            New AuthTokens pair.

        Raises:
            AuthenticationError: If the refresh token is invalid/expired.
        """
        ...

    @abstractmethod
    async def get_quota(
        self,
        api_url: str,
        access_token: str,
    ) -> Dict[str, Any]:
        """Fetch the user's current quota/usage information.

        Returns:
            Dict with quota details (monthly_limit, current_cost, etc.).
        """
        ...

    @abstractmethod
    async def get_models(
        self,
        api_url: str,
        access_token: str,
    ) -> List[Dict[str, Any]]:
        """Fetch available models.

        Returns:
            List of model information dicts.
        """
        ...

    @abstractmethod
    async def get_conversations(
        self,
        api_url: str,
        access_token: str,
    ) -> List[Dict[str, Any]]:
        """Fetch the user's conversation history.

        Returns:
            List of conversation summary dicts.
        """
        ...

    @abstractmethod
    async def get_subagents(
        self,
        api_url: str,
        access_token: str,
    ) -> Dict[str, Any]:
        """Fetch available subagents.

        Returns:
            Dict with a 'subagents' key containing a list of subagent dicts.
        """
        ...

    @abstractmethod
    async def get_messages(
        self,
        api_url: str,
        access_token: str,
        turia_version: Optional[str] = None,
        after_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Fetch active broadcast messages and version check for the current user.

        Args:
            after_id: If provided, only return messages with id > after_id.

        Returns:
            Dict with 'messages' list and optional 'version_check'.
        """
        ...

    @abstractmethod
    async def check_rag(
        self,
        api_url: str,
        access_token: str,
        git_remote_url: str,
    ) -> Dict[str, Any]:
        """Check RAG index status and linked projects for a git repo.

        Returns:
            Dict with has_index, status, project_name, linked_projects, etc.
        """
        ...

    @abstractmethod
    async def analyze_architecture(
        self,
        api_url: str,
        access_token: str,
        project_id: int,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Send project files to backend for architecture analysis."""
        ...

    @abstractmethod
    async def get_skills(
        self,
        api_url: str,
        access_token: str,
    ) -> Dict[str, Any]:
        """Fetch available skills from the backend.

        Returns:
            Dict with a 'skills' key containing a list of skill dicts.
        """
        ...

    @abstractmethod
    async def create_auth_session(self, api_url: str) -> str:
        """Create a CLI authentication session.

        Returns:
            The session_id to use for browser login and polling.
        """
        ...

    @abstractmethod
    async def poll_auth_session(
        self, api_url: str, session_id: str
    ) -> Dict[str, Any]:
        """Poll an authentication session for completion.

        Returns:
            Dict with 'status' and, when completed, 'access_token',
            'refresh_token', and 'user_email'.
        """
        ...
