"""Composition root — wires all dependencies together."""

from __future__ import annotations

from .application.ports.driven.api_client_port import ApiClientPort
from .application.ports.driven.clipboard_port import ClipboardPort
from .application.ports.driven.config_port import ConfigPort
from .application.ports.driven.tool_executor_port import ToolExecutorPort
from .application.services.auth_service import AuthService
from .application.services.chat_service import ChatService
from .application.services.marketplace_service import MarketplaceService
from .application.services.skill_service import SkillService
from .application.services.subagent_service import SubagentService
from .application.services.tool_orchestrator import ToolOrchestrator
from .driven.api.httpx_client import HttpxApiClient
from .driven.config.json_config_adapter import JsonConfigAdapter
from .driven.context.project_context_builder import ProjectContextBuilder
from .driven.tools.file_backup import FileBackup
from .driven.tools.local_executor import LocalToolExecutor
from .driven.tools.path_validator import PathValidator
from .driving.ui.tool_display import ToolDisplay


class Container:
    """Dependency injection container.

    Creates and wires all layers following the dependency rule:
      domain <- application <- driven (infrastructure)
                            <- driving (CLI/UI)

    All driven adapters are created here and injected into application services.
    The driving layer receives services from this container.
    """

    def __init__(self, debug: bool = False) -> None:
        self._debug = debug

        # ── Driven adapters (infrastructure) ────────────────────────────
        self._config_adapter = JsonConfigAdapter()
        self._project_context_builder = ProjectContextBuilder()
        self._api_client = HttpxApiClient(debug=debug)
        self._clipboard_adapter = self._create_clipboard_adapter()

        # ── Tool execution infrastructure ───────────────────────────────
        self._path_validator = PathValidator()
        self._file_backup = FileBackup()
        self._tool_display = ToolDisplay()

        # Detect project type for LSP server selection
        project_type = self._project_context_builder.detect_project_type()

        # The approval callback bridges the driven executor to the UI layer
        self._tool_executor = LocalToolExecutor(
            path_validator=self._path_validator,
            file_backup=self._file_backup,
            request_approval=self._tool_display.show_approval_prompt,
            project_type=project_type,
        )

        # ── Application services ────────────────────────────────────────
        self._auth_service = AuthService(
            config_port=self._config_adapter,
            api_client=self._api_client,
        )
        self._chat_service = ChatService(
            auth_service=self._auth_service,
            api_client=self._api_client,
            config_port=self._config_adapter,
            debug=debug,
        )
        self._tool_orchestrator = ToolOrchestrator(
            executor=self._tool_executor,
            progress=self._tool_display,
        )
        self._subagent_service = SubagentService(
            auth_service=self._auth_service,
            api_client=self._api_client,
            chat_service=self._chat_service,
        )
        self._skill_service = SkillService(
            auth_service=self._auth_service,
            api_client=self._api_client,
        )
        self._marketplace_service = MarketplaceService()

    @staticmethod
    def _create_clipboard_adapter() -> ClipboardPort:
        """Create the appropriate clipboard adapter for the current platform."""
        import platform
        system = platform.system()
        if system == "Darwin":
            from .driven.clipboard.macos_clipboard_adapter import MacOSClipboardAdapter
            return MacOSClipboardAdapter()
        elif system == "Linux":
            from .driven.clipboard.linux_clipboard_adapter import LinuxClipboardAdapter
            return LinuxClipboardAdapter()
        else:
            from .driven.clipboard.windows_clipboard_adapter import WindowsClipboardAdapter
            return WindowsClipboardAdapter()

    # ── Public accessors for the driving layer ──────────────────────────

    @property
    def config_port(self) -> ConfigPort:
        return self._config_adapter

    @property
    def clipboard_port(self) -> ClipboardPort:
        return self._clipboard_adapter

    @property
    def api_client(self) -> ApiClientPort:
        return self._api_client

    @property
    def auth_service(self) -> AuthService:
        return self._auth_service

    @property
    def chat_service(self) -> ChatService:
        return self._chat_service

    @property
    def subagent_service(self) -> SubagentService:
        return self._subagent_service

    @property
    def skill_service(self) -> SkillService:
        return self._skill_service

    @property
    def marketplace_service(self) -> MarketplaceService:
        return self._marketplace_service

    @property
    def tool_orchestrator(self) -> ToolOrchestrator:
        return self._tool_orchestrator

    @property
    def tool_executor(self) -> ToolExecutorPort:
        return self._tool_executor

    @property
    def path_validator(self) -> PathValidator:
        return self._path_validator

    @property
    def file_backup(self) -> FileBackup:
        return self._file_backup

    @property
    def project_context_builder(self) -> ProjectContextBuilder:
        return self._project_context_builder

    @property
    def tool_display(self) -> ToolDisplay:
        return self._tool_display
