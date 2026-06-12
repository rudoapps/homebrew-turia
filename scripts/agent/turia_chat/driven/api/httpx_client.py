"""HTTPX-based implementation of the API client port."""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx

from ...application.ports.driven.api_client_port import ApiClientPort
from ...domain.entities.config import AuthTokens
from ...domain.entities.sse_event import SSEEvent, ErrorEvent
from .sse_parser import parse_sse_line, parse_sse_event, parse_raw_error


_HTTP_FRIENDLY_ERRORS = {
    401: "401: Sesion expirada.",
    403: "No tienes permisos para esta operacion.",
    404: "Endpoint no encontrado. Verifica la configuracion del servidor.",
    429: "Demasiadas peticiones. Espera un momento e intenta de nuevo.",
    500: "Error interno del servidor. Intenta de nuevo.",
    502: "El servidor no responde (502). Puede estar reiniciandose o sobrecargado.",
    503: "Servidor no disponible (503). Intenta de nuevo en unos segundos.",
    504: "Timeout del servidor (504). La operacion tardo demasiado.",
}

# HTTP 426 is handled specially — we extract the detail message from the response body
_UPGRADE_REQUIRED_STATUS = 426


def _friendly_http_error(status: int, body: str = "") -> str:
    """Convert HTTP status + body into a user-friendly error message."""
    friendly = _HTTP_FRIENDLY_ERRORS.get(status)
    if friendly:
        return friendly
    # Try to extract message from JSON body
    if body and not body.strip().startswith("<"):
        try:
            data = json.loads(body)
            msg = data.get("detail", data.get("error", data.get("message", "")))
            if msg:
                return f"Error {status}: {msg}"
        except (json.JSONDecodeError, AttributeError):
            pass
        return f"Error {status}: {body[:200]}"
    return f"Error {status}"


class HttpxApiClient(ApiClientPort):
    """API client using httpx for async HTTP with SSE streaming.

    Features:
      - Async streaming for real-time SSE event delivery.
      - Retry with exponential backoff (3 attempts) for transient errors.
      - Proper SSE line parsing and domain event mapping.
    """

    MAX_RETRIES = 3
    BASE_BACKOFF = 1.0  # seconds
    CONNECT_TIMEOUT = 30.0
    READ_TIMEOUT = 300.0  # 5 minutes for long-running agent turns

    def __init__(self, debug: bool = False) -> None:
        self._debug = debug

    async def send_chat(
        self,
        endpoint: str,
        access_token: str,
        payload: Dict[str, Any],
    ) -> AsyncGenerator[SSEEvent, None]:
        """Stream SSE events from the chat endpoint."""
        last_error: Optional[Exception] = None

        for attempt in range(self.MAX_RETRIES):
            try:
                async for event in self._do_stream(endpoint, access_token, payload):
                    yield event
                return  # Success — all events yielded
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
                last_error = exc
                if attempt < self.MAX_RETRIES - 1:
                    wait = self.BASE_BACKOFF * (2 ** attempt)
                    if self._debug:
                        import sys
                        print(
                            f"[DEBUG] Retry {attempt + 1}/{self.MAX_RETRIES} "
                            f"after {wait}s: {exc}",
                            file=sys.stderr,
                        )
                    await asyncio.sleep(wait)
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                # Retry on 502/503/504 (proxy/server transient errors)
                if status in (502, 503, 504) and attempt < self.MAX_RETRIES - 1:
                    last_error = exc
                    wait = self.BASE_BACKOFF * (2 ** attempt)
                    if self._debug:
                        import sys
                        print(
                            f"[DEBUG] Retry {attempt + 1}/{self.MAX_RETRIES} "
                            f"after {wait}s: HTTP {status}",
                            file=sys.stderr,
                        )
                    await asyncio.sleep(wait)
                    continue
                # Don't retry client errors (401, 403, etc.)
                yield ErrorEvent(
                    error=_friendly_http_error(status, exc.response.text[:500])
                )
                return

        # All retries exhausted
        yield ErrorEvent(
            error=f"No se pudo conectar al servidor despues de {self.MAX_RETRIES} intentos: {last_error}"
        )

    async def _do_stream(
        self,
        endpoint: str,
        access_token: str,
        payload: Dict[str, Any],
    ) -> AsyncGenerator[SSEEvent, None]:
        """Perform a single streaming request and yield SSE events."""
        timeout = httpx.Timeout(
            connect=self.CONNECT_TIMEOUT,
            read=self.READ_TIMEOUT,
            write=30.0,
            pool=30.0,
        )

        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                endpoint,
                json=payload,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                },
            ) as response:
                # Check for HTTP errors before streaming
                if response.status_code != 200:
                    status = response.status_code
                    body = ""
                    async for chunk in response.aiter_text():
                        body += chunk
                        if len(body) > 1000:
                            break
                    # For retryable errors, raise so send_chat can retry
                    if status in (502, 503, 504):
                        raise httpx.HTTPStatusError(
                            message=_friendly_http_error(status, body),
                            request=response.request,
                            response=response,
                        )
                    # For non-retryable errors, yield friendly message
                    yield ErrorEvent(
                        error=_friendly_http_error(status, body.strip())
                    )
                    return

                # Stream SSE lines
                current_event_type: Optional[str] = None
                first_line = True

                async for raw_line in response.aiter_lines():
                    line = raw_line.strip()
                    if not line:
                        # Empty line = event boundary in SSE
                        current_event_type = None
                        continue

                    field, value = parse_sse_line(line)

                    if field == "event":
                        current_event_type = value

                    elif field == "data" and current_event_type and value:
                        event = parse_sse_event(current_event_type, value)
                        if event is not None:
                            yield event

                    elif field == "raw" and first_line and value:
                        # Possibly a JSON error response without SSE framing
                        error_event = parse_raw_error(value)
                        if error_event:
                            yield error_event
                            return

                    first_line = False

    async def refresh_token(
        self,
        api_url: str,
        refresh_token: str,
    ) -> AuthTokens:
        """Exchange refresh token for new token pair."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{api_url}/users/refresh",
                json={"refresh_token": refresh_token},
            )
            if response.status_code != 200:
                raise RuntimeError(
                    _friendly_http_error(response.status_code, response.text[:500])
                )
            data = response.json()
            return AuthTokens(
                access_token=data["access_token"],
                refresh_token=data["refresh_token"],
            )

    async def get_quota(
        self,
        api_url: str,
        access_token: str,
    ) -> Dict[str, Any]:
        """Fetch user quota information."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{api_url}/agent/quota",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            response.raise_for_status()
            return response.json()

    async def get_models(
        self,
        api_url: str,
        access_token: str,
    ) -> List[Dict[str, Any]]:
        """Fetch available models."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{api_url}/agent/models",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            response.raise_for_status()
            return response.json()

    async def get_conversations(
        self,
        api_url: str,
        access_token: str,
    ) -> List[Dict[str, Any]]:
        """Fetch conversation history."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{api_url}/agent/conversations",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            response.raise_for_status()
            return response.json()

    async def get_subagents(
        self,
        api_url: str,
        access_token: str,
    ) -> Dict[str, Any]:
        """Fetch available subagents."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{api_url}/agent/subagents",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            response.raise_for_status()
            return response.json()

    async def get_messages(
        self,
        api_url: str,
        access_token: str,
        turia_version: Optional[str] = None,
        after_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Fetch active broadcast messages and version check."""
        params = {}
        if turia_version:
            params["turia_version"] = turia_version
        if after_id is not None:
            params["after_id"] = after_id
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{api_url}/agent/messages",
                headers={"Authorization": f"Bearer {access_token}"},
                params=params,
            )
            response.raise_for_status()
            return response.json()

    async def check_rag(
        self,
        api_url: str,
        access_token: str,
        git_remote_url: str,
    ) -> Dict[str, Any]:
        """Check RAG index status and linked projects."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{api_url}/rag/check",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"git_remote_url": git_remote_url},
            )
            response.raise_for_status()
            return response.json()

    async def analyze_architecture(
        self,
        api_url: str,
        access_token: str,
        project_id: int,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Send project files for architecture analysis."""
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{api_url}/rag/projects/{project_id}/analyze",
                headers={"Authorization": f"Bearer {access_token}"},
                json=payload,
            )
            response.raise_for_status()
            return response.json()

    async def get_skills(
        self,
        api_url: str,
        access_token: str,
    ) -> Dict[str, Any]:
        """Fetch available skills."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{api_url}/agent/skills",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            response.raise_for_status()
            return response.json()

    async def create_auth_session(self, api_url: str) -> str:
        """Create a CLI authentication session."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(f"{api_url}/cli-auth/session")
            response.raise_for_status()
            data = response.json()
            return data["session_id"]

    async def poll_auth_session(
        self, api_url: str, session_id: str
    ) -> Dict[str, Any]:
        """Poll an authentication session for completion."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{api_url}/cli-auth/poll",
                params={"session": session_id},
            )
            response.raise_for_status()
            return response.json()
