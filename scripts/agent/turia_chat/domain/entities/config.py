"""Configuration entities."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AuthTokens:
    """Authentication token pair returned by the auth server."""

    access_token: str
    refresh_token: str


@dataclass
class AppConfig:
    """Application configuration loaded from the config file.

    Attributes:
        api_url: Base URL for the agent API.
        access_token: Current JWT access token (may be expired).
        refresh_token: Long-lived refresh token for obtaining new access tokens.
        preferred_model: User-selected model ID, or None for auto.
        preview_mode: Whether to use preview/beta features.
        debug_mode: Whether debug logging is enabled.
    """

    api_url: str = "https://agent.rudo.es/api/v1"
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    preferred_model: Optional[str] = None
    preview_mode: bool = False
    debug_mode: bool = False

    @property
    def is_authenticated(self) -> bool:
        """Return True if we have tokens available."""
        return self.access_token is not None and self.refresh_token is not None

    @property
    def chat_endpoint(self) -> str:
        """Return the full chat SSE endpoint URL."""
        return f"{self.api_url}/agent/chat/hybrid"
