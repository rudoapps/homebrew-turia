"""Permission mode for tool execution."""

from enum import Enum


class PermissionMode(str, Enum):
    """Controls how tool approvals are handled."""

    ASK = "ask"        # Always ask before write/edit/run (default)
    AUTO = "auto"      # Auto-approve everything (power user)
    PLAN = "plan"      # Show what would happen but don't execute
