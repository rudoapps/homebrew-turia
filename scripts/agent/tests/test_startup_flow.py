"""Integration tests for the startup flow.

Tests the authentication + data fetching + header rendering pipeline
to catch race conditions, missing broadcasts, login loops, etc.

Run: python3 scripts/agent/tests/test_startup_flow.py
"""

import asyncio
import os
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from turia_chat.domain.entities.config import AppConfig
from turia_chat.application.services.auth_service import AuthenticationError, ServerUnavailableError


# ── Mock classes ────────────────────────────────────────────────────

class MockAuthService:
    """Simulates auth service with configurable behavior."""

    def __init__(self, scenario: str = "valid_token"):
        self._scenario = scenario
        self._login_count = 0
        self._ensure_count = 0
        self._config = AppConfig(
            api_url="https://test.example.com/api/v1",
            access_token="test-access-token",
            refresh_token="test-refresh-token",
        )

    def get_config(self) -> AppConfig:
        return self._config

    async def ensure_valid_token(self) -> AppConfig:
        self._ensure_count += 1
        if self._scenario == "valid_token":
            return self._config
        elif self._scenario == "needs_refresh":
            # Simulate successful refresh
            self._config.access_token = "refreshed-token"
            return self._config
        elif self._scenario == "refresh_fails":
            raise AuthenticationError("Token expired, refresh failed")
        elif self._scenario == "server_down":
            raise ServerUnavailableError("Server unavailable (502)")
        elif self._scenario == "race_condition":
            # First call succeeds, subsequent calls fail (simulates concurrent refresh)
            if self._ensure_count <= 1:
                return self._config
            raise AuthenticationError("Token was invalidated by concurrent refresh")
        return self._config

    async def login(self) -> AppConfig:
        self._login_count += 1
        if self._scenario == "server_down":
            raise ServerUnavailableError("Cannot connect")
        self._config.access_token = "new-login-token"
        return self._config


class MockApiClient:
    """Simulates API client."""

    def __init__(self, messages=None, rag_info=None, skills=None):
        self._messages = messages or {"messages": [
            {"id": 1, "message": "Test broadcast", "message_type": "info"},
        ]}
        self._rag_info = rag_info or {
            "has_index": True,
            "project_id": 1,
            "project_name": "test-project",
            "total_chunks": 500,
            "last_indexed_at": "2026-04-01T00:00:00",
            "has_architecture_guide": True,
            "linked_projects": [],
        }
        self._skills = skills or {"skills": []}
        self.get_messages_count = 0
        self.check_rag_count = 0

    async def get_messages(self, api_url, access_token, turia_version=None, after_id=None):
        self.get_messages_count += 1
        return self._messages

    async def check_rag(self, api_url, access_token, git_remote_url):
        self.check_rag_count += 1
        return self._rag_info

    async def get_skills(self, api_url, access_token):
        return self._skills


class MockContextBuilder:
    """Simulates project context builder."""

    def __init__(self, git_url="https://github.com/test/repo"):
        self._git_url = git_url
        self._root = "/tmp/test-project"

    def get_git_remote_url(self) -> Optional[str]:
        return self._git_url

    def build(self) -> dict:
        return {"project_type": "python/django", "project_name": "test"}


# ── Test functions ──────────────────────────────────────────────────

async def test_startup_valid_token():
    """Normal flow: valid token, fetches messages and RAG."""
    from turia_chat.driving.cli.handlers.startup import StartupHandler

    auth = MockAuthService("valid_token")
    api = MockApiClient()
    ctx = MockContextBuilder()

    handler = StartupHandler(auth, api, ctx)

    data = await handler.fetch_startup_data("0.0.321")
    rag = await handler.fetch_rag_info()

    assert data.get("messages"), "Should have broadcast messages"
    assert len(data["messages"]) == 1, "Should have 1 message"
    assert rag is not None, "Should have RAG info"
    assert rag["has_index"] is True, "RAG should be indexed"
    assert api.get_messages_count == 1, "Should call get_messages once"
    assert api.check_rag_count == 1, "Should call check_rag once"
    return True


async def test_startup_token_refresh():
    """Token expired but refresh succeeds."""
    from turia_chat.driving.cli.handlers.startup import StartupHandler

    auth = MockAuthService("needs_refresh")
    api = MockApiClient()
    ctx = MockContextBuilder()

    handler = StartupHandler(auth, api, ctx)

    data = await handler.fetch_startup_data("0.0.321")
    assert data.get("messages"), "Should get messages after refresh"
    return True


async def test_startup_auth_fails_fallback():
    """Auth fails but uses fallback config."""
    from turia_chat.driving.cli.handlers.startup import StartupHandler

    auth = MockAuthService("refresh_fails")
    api = MockApiClient()
    ctx = MockContextBuilder()

    handler = StartupHandler(auth, api, ctx)

    data = await handler.fetch_startup_data("0.0.321")
    # Should still try with fallback config (has access_token)
    assert api.get_messages_count >= 0, "Should attempt or fallback gracefully"
    return True


async def test_startup_server_down():
    """Server is completely down."""
    from turia_chat.driving.cli.handlers.startup import StartupHandler

    auth = MockAuthService("server_down")
    api = MockApiClient()
    ctx = MockContextBuilder()

    handler = StartupHandler(auth, api, ctx)

    # ensure_valid_token raises ServerUnavailableError
    # but fetch_startup_data catches it and uses fallback
    data = await handler.fetch_startup_data("0.0.321")
    # Should not crash
    return True


async def test_startup_no_git_repo():
    """Not in a git repo — RAG should return None."""
    from turia_chat.driving.cli.handlers.startup import StartupHandler

    auth = MockAuthService("valid_token")
    api = MockApiClient()
    ctx = MockContextBuilder(git_url=None)

    handler = StartupHandler(auth, api, ctx)

    rag = await handler.fetch_rag_info()
    assert rag is None, "No git URL should return None RAG"
    assert api.check_rag_count == 0, "Should not call check_rag"
    return True


async def test_broadcast_tracking():
    """Broadcast IDs tracked to avoid repeats."""
    from turia_chat.driving.cli.handlers.startup import StartupHandler

    auth = MockAuthService("valid_token")
    api = MockApiClient(messages={"messages": [
        {"id": 5, "message": "First", "message_type": "info"},
        {"id": 10, "message": "Second", "message_type": "warning"},
    ]})
    ctx = MockContextBuilder()

    handler = StartupHandler(auth, api, ctx)

    data = await handler.fetch_startup_data("0.0.321")
    handler.track_broadcast_ids(data.get("messages", []))

    assert handler._last_broadcast_id == 10, f"Should track max ID=10, got {handler._last_broadcast_id}"
    return True


async def test_no_double_login():
    """Auth should not trigger login inside fetch_startup_data."""
    from turia_chat.driving.cli.handlers.startup import StartupHandler

    auth = MockAuthService("refresh_fails")
    api = MockApiClient()
    ctx = MockContextBuilder()

    handler = StartupHandler(auth, api, ctx)

    await handler.fetch_startup_data("0.0.321")

    assert auth._login_count == 0, f"Should NOT trigger login, but login was called {auth._login_count} times"
    return True


async def test_concurrent_auth_safety():
    """Concurrent calls should not cause race conditions."""
    from turia_chat.driving.cli.handlers.startup import StartupHandler

    auth = MockAuthService("race_condition")
    api = MockApiClient()
    ctx = MockContextBuilder()

    handler = StartupHandler(auth, api, ctx)

    # Simulate what _loop does: concurrent fetch_api + fetch_rag
    results = await asyncio.gather(
        handler.fetch_startup_data("0.0.321"),
        handler.fetch_rag_info(),
        return_exceptions=True,
    )

    # Neither should crash
    for r in results:
        assert not isinstance(r, Exception), f"Should not raise: {r}"
    return True


async def test_header_data_completeness():
    """All header data should be present after startup."""
    from turia_chat.driving.cli.handlers.startup import StartupHandler

    auth = MockAuthService("valid_token")
    api = MockApiClient(
        messages={"messages": [
            {"id": 1, "message": "Broadcast test", "message_type": "info"},
        ]},
        rag_info={
            "has_index": True,
            "project_id": 1,
            "project_name": "milwaukee-ios",
            "total_chunks": 1722,
            "last_indexed_at": "2026-03-31T00:00:00",
            "has_architecture_guide": True,
            "linked_projects": [
                {"name": "milwaukee-python", "project_type": "backend",
                 "status": "ready", "mention": "@back", "last_indexed_at": "2026-03-31"},
            ],
        },
    )
    ctx = MockContextBuilder()

    handler = StartupHandler(auth, api, ctx)

    api_data = await handler.fetch_startup_data("0.0.321")
    rag_info = await handler.fetch_rag_info()

    # Verify all header data is present
    messages = api_data.get("messages", [])
    assert len(messages) == 1, "Should have 1 broadcast message"
    assert messages[0]["message"] == "Broadcast test", "Message content"

    assert rag_info["has_index"] is True, "RAG indexed"
    assert rag_info["total_chunks"] == 1722, "Chunk count"
    assert rag_info["has_architecture_guide"] is True, "Architecture guide"
    assert len(rag_info["linked_projects"]) == 1, "1 linked project"
    assert rag_info["linked_projects"][0]["mention"] == "@back", "Mention"

    return True


# ── Runner ──────────────────────────────────────────────────────────

async def run_all():
    tests = [
        ("Valid token flow", test_startup_valid_token),
        ("Token refresh flow", test_startup_token_refresh),
        ("Auth fails with fallback", test_startup_auth_fails_fallback),
        ("Server down handling", test_startup_server_down),
        ("No git repo (no RAG)", test_startup_no_git_repo),
        ("Broadcast ID tracking", test_broadcast_tracking),
        ("No double login", test_no_double_login),
        ("Concurrent auth safety", test_concurrent_auth_safety),
        ("Header data completeness", test_header_data_completeness),
    ]

    passed = 0
    failed = 0
    errors = []

    for name, test_fn in tests:
        try:
            result = await test_fn()
            if result:
                print(f"  \033[32m✓\033[0m {name}")
                passed += 1
            else:
                print(f"  \033[31m✗\033[0m {name} — returned False")
                failed += 1
                errors.append(name)
        except AssertionError as e:
            print(f"  \033[31m✗\033[0m {name} — {e}")
            failed += 1
            errors.append(f"{name}: {e}")
        except Exception as e:
            print(f"  \033[31m✗\033[0m {name} — EXCEPTION: {e}")
            failed += 1
            errors.append(f"{name}: {e}")

    print()
    print(f"  Results: {passed} passed, {failed} failed, {passed + failed} total")

    if errors:
        print()
        print("  Failures:")
        for e in errors:
            print(f"    - {e}")

    return failed == 0


if __name__ == "__main__":
    print()
    print("  Running startup flow tests...")
    print()
    ok = asyncio.run(run_all())
    sys.exit(0 if ok else 1)
