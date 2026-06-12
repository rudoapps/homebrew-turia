"""Build the JSON payload for the chat API endpoint."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from ...domain.entities.tool_result import ToolResult


# Mention mapping for cross-project RAG
_MENTION_MAPPING: Dict[str, str] = {
    "@back": "backend",
    "@backend": "backend",
    "@server": "backend",
    "@api": "backend",
    "@ios": "ios",
    "@android": "android",
    "@front": "web_frontend",
    "@frontend": "web_frontend",
    "@web": "web_frontend",
    "@flutter": "flutter",
    "@mobile": "ios",
}


def build_chat_payload(
    prompt: Optional[str] = None,
    conversation_id: Optional[int] = None,
    tool_results: Optional[List[ToolResult]] = None,
    project_context: Optional[Dict[str, Any]] = None,
    images: Optional[List[Dict[str, str]]] = None,
    model: Optional[str] = None,
    max_iterations: int = 15,
    git_remote_url: Optional[str] = None,
    subagent_id: Optional[str] = None,
    user_context: Optional[str] = None,
    turia_version: Optional[str] = None,
    system_prompt_addition: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the chat payload matching the backend API contract.

    This mirrors the payload builder from agent_api.sh (lines 462-588).

    Args:
        prompt: The user's message text.
        conversation_id: Existing conversation to continue.
        tool_results: Results from tool executions to send back.
        project_context: Project metadata dict.
        images: Image attachments as dicts with 'data' and 'media_type'.
        model: Preferred model ID or None for auto.
        max_iterations: Maximum agent iterations per turn.
        git_remote_url: Git remote URL for RAG context.
        subagent_id: Subagent ID if delegating.
        user_context: Additional user context (inline input).

    Returns:
        A JSON-serializable dict ready to POST to the chat endpoint.
    """
    payload: Dict[str, Any] = {"max_iterations": max_iterations}

    if prompt:
        payload["prompt"] = prompt
        # Detect @mentions for cross-project RAG
        _detect_mentions(prompt, payload)

    if conversation_id is not None:
        payload["conversation_id"] = conversation_id

    if project_context:
        payload["project_context"] = project_context

    if tool_results:
        payload["tool_results"] = [
            {
                "tool_call_id": tr.id,
                "tool_name": tr.name,
                "result": tr.output,
            }
            for tr in tool_results
        ]

    if subagent_id:
        payload["subagent_id"] = subagent_id

    if git_remote_url:
        payload["git_remote_url"] = git_remote_url

    if images:
        # Strip source_path if present (only send data + media_type)
        cleaned = []
        for img in images:
            cleaned.append({
                "data": img["data"],
                "media_type": img["media_type"],
            })
        payload["images"] = cleaned

    if model and model != "null" and model != "auto":
        payload["preferred_model"] = model

    if user_context:
        payload["user_context"] = user_context

    if turia_version:
        payload["turia_version"] = turia_version

    if system_prompt_addition:
        payload["system_prompt_addition"] = system_prompt_addition

    return payload


def _detect_mentions(prompt: str, payload: Dict[str, Any]) -> None:
    """Detect @mentions in the prompt and set target_project_type."""
    prompt_lower = prompt.lower()
    for mention, project_type in _MENTION_MAPPING.items():
        if mention in prompt_lower:
            payload["target_project_type"] = project_type
            break
