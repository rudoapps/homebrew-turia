"""Import tests — verify all modules can be imported without errors.

Run: python3 scripts/agent/tests/test_imports.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

MODULES = [
    # Domain
    "turia_chat.domain.entities.tool_call",
    "turia_chat.domain.entities.tool_result",
    "turia_chat.domain.entities.skill",
    "turia_chat.domain.entities.sse_event",
    "turia_chat.domain.entities.config",
    "turia_chat.domain.entities.permission_mode",

    # Application
    "turia_chat.application.ports.driven.api_client_port",
    "turia_chat.application.ports.driven.tool_executor_port",
    "turia_chat.application.ports.driven.config_port",
    "turia_chat.application.services.auth_service",
    "turia_chat.application.services.chat_service",
    "turia_chat.application.services.skill_service",
    "turia_chat.application.services.tool_orchestrator",

    # Driven - Tools
    "turia_chat.driven.tools.base",
    "turia_chat.driven.tools.file_tools",
    "turia_chat.driven.tools.search_tools",
    "turia_chat.driven.tools.shell_tools",
    "turia_chat.driven.tools.code_analysis_tools",
    "turia_chat.driven.tools.web_tools",
    "turia_chat.driven.tools.local_executor",
    "turia_chat.driven.tools.path_validator",
    "turia_chat.driven.tools.file_backup",

    # Driven - Other
    "turia_chat.driven.hooks.hook_runner",
    "turia_chat.driven.memory.local_memory",
    "turia_chat.driven.notifications.os_notify",
    "turia_chat.driven.context.project_context_builder",
    "turia_chat.driven.api.httpx_client",
    "turia_chat.driven.api.payload_builder",

    # Driving - CLI
    "turia_chat.driving.cli.commands",
    "turia_chat.driving.cli.input_handler",
    "turia_chat.driving.cli.handlers.startup",
    "turia_chat.driving.cli.handlers.git_handler",
    "turia_chat.driving.cli.handlers.model_handler",
    "turia_chat.driving.cli.handlers.context_handler",

    # Driving - UI
    "turia_chat.driving.ui.console",
    "turia_chat.driving.ui.header",
    "turia_chat.driving.ui.renderer",
    "turia_chat.driving.ui.selector",
    "turia_chat.driving.ui.spinner",
    "turia_chat.driving.ui.markdown",
    "turia_chat.driving.ui.tool_display",
]


def test_imports():
    """Test that all modules can be imported."""
    passed = 0
    failed = 0
    errors = []

    for module_path in MODULES:
        try:
            __import__(module_path)
            print(f"  \033[32m✓\033[0m {module_path}")
            passed += 1
        except Exception as e:
            print(f"  \033[31m✗\033[0m {module_path} — {e}")
            failed += 1
            errors.append(f"{module_path}: {e}")

    print()
    print(f"  Results: {passed} passed, {failed} failed, {len(MODULES)} total")

    if errors:
        print()
        print("  Failures:")
        for e in errors:
            print(f"    - {e}")

    return failed == 0


if __name__ == "__main__":
    print()
    print("  Running import tests...")
    print()
    ok = test_imports()
    sys.exit(0 if ok else 1)
