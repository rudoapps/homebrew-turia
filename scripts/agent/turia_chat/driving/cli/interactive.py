"""Interactive REPL handler — the main loop for chat.py interactive mode."""

from __future__ import annotations

import asyncio
import subprocess
from typing import List, Optional

from ...application.ports.driven.api_client_port import ApiClientPort
from ...application.ports.driven.clipboard_port import ClipboardPort
from ...application.ports.driven.config_port import ConfigPort
from ...application.services.auth_service import AuthService
from ...application.services.chat_service import ChatService
from ...application.services.marketplace_service import MarketplaceService
from ...application.services.skill_service import SkillService
from ...application.services.subagent_service import SubagentService
from ...application.services.tool_orchestrator import ToolOrchestrator
from ...domain.entities.tool_result import ToolResult
from ...driven.context.project_context_builder import ProjectContextBuilder
from ...driven.images.image_detector import ImageDetector
from ...domain.entities.sse_event import (
    SSEEvent,
    StartedEvent,
    CompleteEvent,
    ErrorEvent,
    TextEvent,
    ToolRequestsEvent,
    ProviderFallbackEvent,
)
from ..ui.console import get_console
from ..ui.header import SessionHeader
from ..ui.renderer import SSERenderer, _make_collapse_state
from ..ui.selector import SelectOption, select_option, select_option_async
from ..ui.tool_display import ToolDisplay
from .commands import (
    SlashCommandRegistry,
    format_models_display,
    format_quota_display,
    format_skills_display,
    format_subagents_display,
)
from .input_handler import InputHandler
from .handlers.startup import StartupHandler
from .handlers.git_handler import GitHandler
from .handlers.model_handler import ModelHandler
from .handlers.context_handler import ContextHandler
from ... import __version__ as turia_version


def _detect_project_name() -> str:
    """Detect the current project name from git or cwd."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            import os
            return os.path.basename(result.stdout.strip())
    except (subprocess.SubprocessError, OSError):
        pass

    import os
    return os.path.basename(os.getcwd())


class InteractiveHandler:
    """Handles the interactive REPL chat session.

    Manages the loop of: read input -> check slash commands ->
    expand @files -> send to chat_service -> render SSE events ->
    execute tool_requests -> send results back -> repeat until complete.

    Args:
        chat_service: Service for sending messages and streaming responses.
        config_port: Configuration port for settings access.
        clipboard_port: Clipboard port for copy operations.
        auth_service: Authentication service for obtaining valid tokens.
        api_client: API client for backend calls (quota, models, etc.).
        subagent_service: Service for subagent listing and invocation.
        tool_orchestrator: Orchestrator for local tool execution.
        project_context_builder: Builder for project context metadata.
    """

    def __init__(
        self,
        chat_service: ChatService,
        config_port: ConfigPort,
        clipboard_port: ClipboardPort,
        auth_service: AuthService,
        api_client: ApiClientPort,
        subagent_service: SubagentService,
        skill_service: Optional[SkillService] = None,
        marketplace_service: Optional[MarketplaceService] = None,
        tool_orchestrator: Optional[ToolOrchestrator] = None,
        project_context_builder: Optional[ProjectContextBuilder] = None,
    ) -> None:
        self._chat_service = chat_service
        self._config_port = config_port
        self._clipboard_port = clipboard_port
        self._auth_service = auth_service
        self._api_client = api_client
        self._subagent_service = subagent_service
        self._skill_service = skill_service
        self._marketplace_service = marketplace_service
        self._tool_orchestrator = tool_orchestrator
        self._context_builder = project_context_builder or ProjectContextBuilder()
        self._collapse_state = _make_collapse_state()
        self._tool_display = ToolDisplay(collapse_state=self._collapse_state)
        self._image_detector = ImageDetector()
        self._console = get_console()

        # Session state
        self._conversation_id: Optional[int] = None
        self._total_cost: float = 0.0
        self._last_response: str = ""
        self._turn_count: int = 0
        self._project_name: str = _detect_project_name()
        self._is_first_message: bool = True
        self._last_broadcast_id: Optional[int] = None
        self._last_complete_max_iterations: bool = False
        self._fallback_model: Optional[str] = None  # Set when provider falls back

        # Specialized handlers
        self._startup = StartupHandler(auth_service, api_client, self._context_builder)
        self._git = GitHandler(str(self._context_builder._root), self._send_message)
        self._models = ModelHandler(auth_service, api_client, config_port)
        self._context_handler = ContextHandler(self._context_builder, skill_service)

        # Sub-components
        self._input_handler = InputHandler()
        self._header = SessionHeader()
        self._commands = SlashCommandRegistry(
            config_port=config_port,
            clipboard_port=clipboard_port,
            auth_service=auth_service,
            api_client=api_client,
            subagent_service=subagent_service,
            skill_service=skill_service,
            marketplace_service=marketplace_service,
            get_last_response=lambda: self._last_response,
            get_total_cost=lambda: self._total_cost,
            get_conversation_id=lambda: self._conversation_id,
        )

    def run(self) -> int:
        """Run the interactive REPL loop.

        Returns:
            Exit code: 0 for normal exit.
        """
        try:
            return asyncio.run(self._loop())
        except KeyboardInterrupt:
            self._show_exit_summary()
            return 0

    async def _loop(self) -> int:
        """Main async REPL loop."""
        # Try to resume last conversation for this project
        self._conversation_id = self._config_port.get_project_conversation()

        # Ensure auth is valid BEFORE concurrent startup (may need login UI)
        from ...application.services.auth_service import AuthenticationError, ServerUnavailableError
        try:
            await self._auth_service.ensure_valid_token()
        except ServerUnavailableError as exc:
            api_data = {"_server_down": True, "_error": str(exc)}
            rag_info = None
            # Skip to server-down handler below
            broadcast_messages = []
            self._startup.track_broadcast_ids(broadcast_messages)
            # Jump to retry loop
            while api_data.get("_server_down"):
                chosen = await select_option_async(
                    [
                        SelectOption(value="retry", label="Reintentar conexion"),
                        SelectOption(value="exit", label="Salir"),
                    ],
                    title=f"\u26a0  {api_data.get('_error', 'El servidor no esta disponible')}",
                )
                if chosen != "retry":
                    return 0
                try:
                    await self._auth_service.ensure_valid_token()
                    break
                except ServerUnavailableError as exc2:
                    api_data = {"_server_down": True, "_error": str(exc2)}
                except AuthenticationError:
                    try:
                        config = await self._startup.do_interactive_login()
                    except ServerUnavailableError as exc3:
                        api_data = {"_server_down": True, "_error": str(exc3)}
                        continue
                    if config:
                        break
                    return 0
        except AuthenticationError:
            try:
                config = await self._startup.do_interactive_login()
            except ServerUnavailableError as exc:
                self._console.print(
                    f"  [yellow]\u26a0 {exc}[/yellow]"
                )
                self._console.print(
                    "  [dim]El servidor no esta disponible. Intenta de nuevo en unos minutos.[/dim]"
                )
                return 1
            if config is None:
                return 0

        # Now auth is valid — run startup tasks sequentially but fast
        # (concurrent auth calls cause race conditions on token refresh)
        from ..ui.spinner import Spinner
        spinner = Spinner()
        spinner.start("Cargando...")

        # Load skills
        if self._skill_service:
            try:
                await self._skill_service.load_skills()
            except Exception:
                pass

        # Fetch API data and RAG concurrently (same token, no auth calls)
        async def _fetch_api():
            return await self._startup.fetch_startup_data(turia_version)

        async def _fetch_rag():
            return await self._startup.fetch_rag_info()

        api_data, rag_info = await asyncio.gather(
            _fetch_api(), _fetch_rag(),
            return_exceptions=True,
        )

        spinner.stop()

        # Handle errors from gather
        if isinstance(api_data, Exception):
            api_data = {}
        if isinstance(rag_info, Exception):
            rag_info = None

        # Server down retry loop
        while api_data.get("_server_down"):
            chosen = await select_option_async(
                [
                    SelectOption(value="retry", label="Reintentar conexion"),
                    SelectOption(value="exit", label="Salir"),
                ],
                title=f"\u26a0  {api_data.get('_error', 'El servidor no esta disponible')}",
            )
            if chosen != "retry":
                return 0
            spinner.start("Reconectando...")
            api_data = await self._startup.fetch_startup_data(turia_version)
            spinner.stop()

        broadcast_messages = api_data.get("messages", [])
        self._startup.track_broadcast_ids(broadcast_messages)
        version_check = api_data.get("version_check")

        # Block if server requires a newer version
        if version_check and version_check.get("update_required"):
            self._header.show_update_required(
                version_check.get("message", ""),
            )
            return 1

        # Detect auto-applied skill for this project type
        active_skill_name = None
        if self._skill_service:
            context = self._context_builder.build()
            project_type = context.get("project_type", "")
            auto_skill = self._skill_service.get_auto_skill_for_project(project_type)
            if auto_skill:
                active_skill_name = f"{auto_skill.icon} {auto_skill.display_name}".strip()

        # Show session header
        self._header.show(
            project_name=self._project_name,
            conversation_id=self._conversation_id,
            broadcast_messages=broadcast_messages,
            rag_info=rag_info,
            active_skill=active_skill_name,
        )

        # Offer architecture analysis if project is registered but has no guide
        if (rag_info and rag_info.get("project_id")
                and not rag_info.get("has_architecture_guide")):
            await self._startup.offer_architecture_analysis(rag_info, self._project_name)

        while True:
            try:
                user_input = await self._input_handler.read_input()
            except KeyboardInterrupt:
                self._show_exit_summary()
                return 0

            # EOF (Ctrl+D) — exit
            if user_input is None:
                self._show_exit_summary()
                return 0

            # Empty input — skip
            if not user_input.strip():
                continue

            # Check for slash commands
            cmd_result = self._commands.dispatch(user_input)
            if cmd_result is not None:
                if cmd_result.output:
                    self._console.print(f"  {cmd_result.output}")
                    self._console.print()

                if not cmd_result.should_continue:
                    self._show_exit_summary()
                    return 0

                # Handle command actions
                if cmd_result.action == "new_conversation":
                    # Save summary of current conversation as memory
                    if self._conversation_id and self._turn_count > 2:
                        self._save_conversation_summary()

                    self._conversation_id = None
                    self._is_first_message = True
                    self._fallback_model = None
                    self._config_port.clear_project_conversation()
                    self._context_builder.rebuild()
                    self._header.show_new_conversation()

                elif cmd_result.action == "resume_conversation":
                    if cmd_result.action_data:
                        self._conversation_id = int(cmd_result.action_data)
                        self._config_port.set_project_conversation(
                            self._conversation_id
                        )
                        self._header.show_resumed_conversation(
                            self._conversation_id
                        )

                elif cmd_result.action == "fetch_quota":
                    await self._handle_fetch_quota()

                elif cmd_result.action == "list_models":
                    await self._models.handle_list_models()

                elif cmd_result.action == "change_model":
                    if cmd_result.action_data:
                        await self._models.handle_change_model(cmd_result.action_data)

                elif cmd_result.action == "list_subagents":
                    await self._handle_list_subagents()

                elif cmd_result.action == "invoke_subagent":
                    if cmd_result.action_data:
                        await self._handle_invoke_subagent(
                            cmd_result.action_data
                        )

                elif cmd_result.action == "invoke_skill":
                    if cmd_result.action_data:
                        await self._handle_invoke_skill(
                            cmd_result.action_data
                        )

                elif cmd_result.action == "list_skills":
                    self._handle_list_skills()

                elif cmd_result.action == "reload_skills":
                    if cmd_result.action_data:
                        self._console.print(cmd_result.action_data)
                    if self._skill_service:
                        try:
                            await self._skill_service.reload()
                        except Exception as exc:
                            self._console.print(f"  [yellow]Skills recargadas con error: {exc}[/yellow]")

                elif cmd_result.action == "show_mode":
                    if self._tool_orchestrator:
                        mode = self._tool_orchestrator.permission_mode.value
                        self._console.print(f"  Modo actual: [bold]{mode}[/bold]")
                        self._console.print("  [dim]Usa /mode <auto|ask|plan> para cambiar[/dim]")

                elif cmd_result.action == "change_mode":
                    if self._tool_orchestrator and cmd_result.action_data:
                        from ...domain.entities.permission_mode import PermissionMode
                        mode = PermissionMode(cmd_result.action_data)
                        self._tool_orchestrator.set_permission_mode(mode)
                        icons = {"auto": "\u26a1", "ask": "\U0001f512", "plan": "\U0001f4cb"}
                        icon = icons.get(mode.value, "")
                        self._console.print(f"  {icon} Modo: [bold]{mode.value}[/bold]")

                elif cmd_result.action == "show_changes":
                    if self._tool_orchestrator:
                        changes = self._tool_orchestrator.file_changes
                        if not changes:
                            self._console.print("  [dim]No hay cambios en esta sesion.[/dim]")
                        else:
                            self._console.print()
                            self._console.print(f"  [bold]{len(changes)} archivos modificados:[/bold]")
                            icons = {"write": "\u2795", "edit": "\u270f\ufe0f ", "move": "\u27a1\ufe0f "}
                            for c in changes:
                                icon = icons.get(c["action"], "\u2022")
                                self._console.print(f"  {icon} [dim]{c['action']}[/dim] {c['path']}")
                            self._console.print()

                elif cmd_result.action == "commit_auto":
                    await self._git.handle_commit()

                elif cmd_result.action == "commit_with_message":
                    if cmd_result.action_data:
                        await self._git.handle_commit(cmd_result.action_data)

                elif cmd_result.action == "review_changes":
                    await self._git.handle_review()

                elif cmd_result.action == "show_context":
                    await self._context_handler.handle_context(
                        self._conversation_id, self._turn_count, self._total_cost,
                        fetch_rag_info_fn=self._startup.fetch_rag_info,
                    )

                elif cmd_result.action == "analyze_architecture":
                    await self._startup.run_architecture_analysis()

                continue

            # Returiar message — send to agent
            await self._send_message(user_input)

            # Check for new broadcast messages between turns
            await self._startup.check_broadcasts(turia_version)

    async def _send_message(
        self,
        prompt: str,
        system_prompt_addition: Optional[str] = None,
    ) -> None:
        """Send a message and handle the full tool execution loop.

        The loop continues sending tool_results back to the server until
        a CompleteEvent or ErrorEvent is received (no more tool requests).

        Args:
            prompt: The user's message (with @file refs already expanded).
            system_prompt_addition: Extra instructions for the system prompt (from skills).
        """
        # Reset per-turn auto-approval
        self._tool_display.reset_turn_approval()

        # Detect and encode images referenced in the prompt
        cleaned_prompt, image_attachments = self._image_detector.detect_images(prompt)
        images_payload = None
        if image_attachments:
            num = len(image_attachments)
            self._console.print(
                f"  [green]{num} imagen(es) detectada(s)[/green]"
            )
            images_payload = [
                {"data": img.data, "media_type": img.media_type}
                for img in image_attachments
            ]

        # Build full project context on every new prompt (matches bash behavior)
        project_context = self._context_builder.build()

        # Inject persistent memory on first message of session
        if self._is_first_message:
            try:
                from ...driven.memory.local_memory import LocalMemory
                memory_content = LocalMemory().get_all_memories()
                if memory_content:
                    if not system_prompt_addition:
                        system_prompt_addition = ""
                    system_prompt_addition += f"\n\n# Memoria del usuario (preferencias guardadas)\n{memory_content}"
            except Exception:
                pass

        self._is_first_message = False

        # Extract git_remote_url for RAG (top-level field, like bash client)
        git_remote_url = self._context_builder.get_git_remote_url()

        current_prompt: Optional[str] = cleaned_prompt
        current_tool_results = None

        # Loop detection: track repeated identical tool calls
        _loop_history: List[str] = []
        _LOOP_THRESHOLD = 3  # Same call N times → break the loop

        # Iteration guard: prevent runaway tool execution
        _tool_iterations = 0
        _MAX_TOOL_ITERATIONS = 15  # Max tool call rounds per user message

        while True:
            renderer = SSERenderer(collapse_state=self._collapse_state)
            # Show spinner immediately while waiting for server response
            if current_tool_results is not None:
                renderer.show_waiting_spinner("Procesando resultados...")
            else:
                renderer.show_waiting_spinner("Enviando...")
            text_chunks: List[str] = []
            pending_tool_event: Optional[ToolRequestsEvent] = None
            turn_complete = False

            try:
                # Use fallback model if primary provider failed earlier
                _model_override = self._fallback_model or None

                async for event in self._chat_service.send_message(
                    prompt=current_prompt,
                    conversation_id=self._conversation_id,
                    tool_results=current_tool_results,
                    project_context=project_context,
                    images=images_payload,
                    model=_model_override,
                    git_remote_url=git_remote_url,
                    turia_version=turia_version,
                    system_prompt_addition=system_prompt_addition,
                ):
                    # Track conversation ID
                    if isinstance(event, StartedEvent) and event.conversation_id:
                        self._conversation_id = event.conversation_id
                        self._config_port.set_project_conversation(
                            event.conversation_id
                        )

                    # Track cost from complete events
                    if isinstance(event, CompleteEvent):
                        if event.total_cost > 0:
                            self._total_cost = event.total_cost
                        elif event.session_cost > 0:
                            self._total_cost += event.session_cost
                        self._turn_count += 1
                        turn_complete = True
                        self._last_complete_max_iterations = event.max_iterations_reached

                    # Accumulate text for /copy
                    if isinstance(event, TextEvent) and event.content:
                        text_chunks.append(event.content)

                    # Track provider fallback — use fallback model for remaining turns
                    if isinstance(event, ProviderFallbackEvent) and event.new_model:
                        self._fallback_model = event.new_model

                    # Handle tool requests
                    if isinstance(event, ToolRequestsEvent) and event.tool_calls:
                        if event.conversation_id:
                            self._conversation_id = event.conversation_id
                        pending_tool_event = event
                        renderer.render(event)
                        continue

                    # Handle errors — auto-retry with fallback on credit errors
                    if isinstance(event, ErrorEvent):
                        if "credit" in event.error.lower() or "insufficient" in event.error.lower():
                            # Only auto-retry once — if we already have a fallback, don't loop
                            if not self._fallback_model:
                                renderer.finalize()
                                self._fallback_model = await self._find_openai_fallback()
                                if self._fallback_model:
                                    self._console.print(f"  [yellow]\u26a0 Sin creditos. Reintentando con {self._fallback_model}...[/yellow]")
                                    break
                            # Already retried or no fallback — show error
                        renderer.render(event)
                        turn_complete = True
                        continue

                    renderer.render(event)

            except KeyboardInterrupt:
                renderer.finalize()
                self._console.print()
                self._console.print("  [dim]Mensaje cancelado[/dim]")
                self._console.print()
                if self._tool_orchestrator:
                    self._tool_orchestrator.request_abort()
                return
            except Exception as exc:
                renderer.finalize()
                error_msg = str(exc)
                if any(s in error_msg for s in ["502", "503", "504", "conectar", "timeout", "timed out"]):
                    self._console.print()
                    self._console.print("  [yellow]\u26a0 El servidor no esta disponible. Intenta de nuevo en unos segundos.[/yellow]")
                else:
                    self._console.print()
                    self._console.print(f"  [red]Error: {error_msg}[/red]")
                self._console.print()
                return

            finally:
                renderer.finalize()

            # Accumulate text for /copy
            if text_chunks:
                self._last_response = "".join(text_chunks)

            # If we got a tool request event and have an orchestrator, execute tools
            if pending_tool_event and self._tool_orchestrator:
                self._console.print()

                # ── Iteration guard ─────────────────────────────────
                _tool_iterations += 1
                if _tool_iterations > _MAX_TOOL_ITERATIONS:
                    self._console.print(
                        f"  [yellow]\u26a0 Limite de iteraciones alcanzado ({_MAX_TOOL_ITERATIONS}). "
                        f"Finalizando turno.[/yellow]"
                    )
                    tool_results = [
                        ToolResult(
                            id=tc.id,
                            name=tc.name,
                            output=(
                                f"[SISTEMA] LIMITE DE ITERACIONES: has ejecutado {_MAX_TOOL_ITERATIONS} "
                                f"rondas de herramientas en este turno. DEBES responder al usuario ahora "
                                f"con lo que ya sabes. NO llames mas herramientas."
                            ),
                            success=False,
                        )
                        for tc in pending_tool_event.tool_calls
                    ]
                    current_prompt = None
                    current_tool_results = tool_results
                    images_payload = None
                    project_context = None
                    git_remote_url = None
                    system_prompt_addition = None
                    self._console.print()
                    continue

                # ── Loop detection ──────────────────────────────────
                import json as _json
                _call_sigs = []
                for _tc in pending_tool_event.tool_calls:
                    try:
                        _sig = f"{_tc.name}:{_json.dumps(_tc.input, sort_keys=True)}"
                    except (TypeError, ValueError):
                        _sig = f"{_tc.name}:{str(_tc.input)}"
                    _call_sigs.append(_sig)
                _batch_sig = "|".join(sorted(_call_sigs))
                _loop_history.append(_batch_sig)

                # Check 1: identical calls N times in a row
                _is_loop = False
                if len(_loop_history) >= _LOOP_THRESHOLD:
                    _recent = _loop_history[-_LOOP_THRESHOLD:]
                    if all(s == _recent[0] for s in _recent):
                        _is_loop = True

                # Check 2: same file read 5+ times (different offsets)
                if not _is_loop and len(_loop_history) >= 5:
                    _recent_5 = _loop_history[-5:]
                    _read_paths = []
                    for _sig in _recent_5:
                        if _sig.startswith("read_file:"):
                            try:
                                _inp = _json.loads(_sig[10:])
                                _read_paths.append(_inp.get("path", ""))
                            except (ValueError, TypeError):
                                pass
                    if len(_read_paths) >= 5 and len(set(_read_paths)) == 1:
                        _is_loop = True

                if _is_loop:
                        self._console.print(
                            "  [yellow]\u26a0 Bucle detectado: el agente esta repitiendo "
                            "la misma operacion. Interrumpiendo.[/yellow]"
                        )
                        # Send an error result back to force the model to change approach
                        tool_results = [
                            ToolResult(
                                id=tc.id,
                                name=tc.name,
                                output=(
                                    f"[SISTEMA] BUCLE DETECTADO: has llamado a {tc.name} "
                                    f"con los mismos parametros {_LOOP_THRESHOLD} veces consecutivas. "
                                    f"DEBES cambiar de estrategia. Si necesitas leer mas lineas de un archivo, "
                                    f"usa un offset DIFERENTE. Si el archivo no tiene mas contenido, ya lo has "
                                    f"leido completo. Responde al usuario con lo que ya sabes."
                                ),
                                success=False,
                            )
                            for tc in pending_tool_event.tool_calls
                        ]
                        current_prompt = None
                        current_tool_results = tool_results
                        images_payload = None
                        project_context = None
                        git_remote_url = None
                        system_prompt_addition = None
                        _loop_history.clear()
                        self._console.print()
                        continue

                try:
                    tool_results = await self._tool_orchestrator.execute_all(
                        pending_tool_event.tool_calls
                    )
                except KeyboardInterrupt:
                    self._console.print()
                    self._console.print("  [dim]Ejecucion de herramientas cancelada[/dim]")
                    self._console.print()
                    self._tool_orchestrator.request_abort()
                    return

                # Detect failed test/build commands — inject auto-fix hint
                _has_test_failure = False
                for _tr in tool_results:
                    if _tr.name == "run_command" and _tr.output and "exit code:" in _tr.output.lower():
                        if any(kw in _tr.output.lower() for kw in ["failed", "error", "failure", "traceback"]):
                            _has_test_failure = True
                            break

                # Loop: send tool results back
                current_prompt = None
                if _has_test_failure:
                    # Inject auto-fix instruction so LLM acts without waiting
                    current_prompt = "[SISTEMA] El comando falló. Lee el error, arregla el código y vuelve a ejecutar. NO pares a explicar."
                current_tool_results = tool_results
                images_payload = None
                project_context = None
                git_remote_url = None
                system_prompt_addition = None
                self._console.print()
                continue

            elif pending_tool_event and not self._tool_orchestrator:
                # No orchestrator — show Phase 3 stub message
                self._console.print()
                self._console.print(
                    "  [warning]Ejecucion de herramientas no disponible "
                    "(tool_orchestrator no configurado)[/warning]"
                )
                self._console.print()
                break

            # No more tool requests or turn is complete
            if turn_complete or not pending_tool_event:
                break

        # If max iterations was reached, offer to continue
        if self._last_complete_max_iterations:
            self._last_complete_max_iterations = False
            self._console.print()
            chosen = await select_option_async(
                [
                    SelectOption(value="continue", label="Continuar", description="Seguir con mas iteraciones"),
                    SelectOption(value="stop", label="Parar", description="Volver al prompt"),
                ],
                title="Se ha alcanzado el limite de iteraciones",
            )
            if chosen == "continue":
                await self._send_message("Continua con lo que estabas haciendo")
                return

        self._console.print()

    async def _handle_fetch_quota(self) -> None:
        """Fetch and display quota information from the API."""
        try:
            config = await self._auth_service.ensure_valid_token()
            data = await self._api_client.get_quota(
                api_url=config.api_url,
                access_token=config.access_token,
            )
            output = format_quota_display(data, self._total_cost)
            self._console.print(output)
        except Exception as exc:
            self._console.print(f"  [red]Error al obtener quota: {exc}[/red]")
            self._console.print()

    async def _handle_list_subagents(self) -> None:
        """Fetch and display available subagents from the API."""
        try:
            subagents = await self._subagent_service.list_subagents()
            output = format_subagents_display(subagents)
            self._console.print(output)
        except Exception as exc:
            self._console.print(
                f"  [red]Error al obtener subagentes: {exc}[/red]"
            )
            self._console.print()

    async def _handle_invoke_subagent(self, action_data: str) -> None:
        """Invoke a subagent and stream the response.

        Args:
            action_data: String in the format "subagent_id\\nprompt".
        """
        parts = action_data.split("\n", maxsplit=1)
        if len(parts) < 2:
            self._console.print("  [red]Datos de subagente invalidos.[/red]")
            return

        subagent_id = parts[0]
        prompt = parts[1]

        self._console.print()
        self._console.print(
            f"  [cyan][Subagente: {subagent_id}][/cyan]"
        )
        self._console.print()

        renderer = SSERenderer()
        text_chunks: List[str] = []

        try:
            async for event in self._subagent_service.invoke(
                subagent_id=subagent_id,
                prompt=prompt,
                conversation_id=self._conversation_id,
            ):
                if isinstance(event, StartedEvent) and event.conversation_id:
                    self._conversation_id = event.conversation_id
                    self._config_port.set_project_conversation(
                        event.conversation_id
                    )

                if isinstance(event, CompleteEvent):
                    if event.total_cost > 0:
                        self._total_cost = event.total_cost
                    elif event.session_cost > 0:
                        self._total_cost += event.session_cost
                    self._turn_count += 1

                if isinstance(event, TextEvent) and event.content:
                    text_chunks.append(event.content)

                renderer.render(event)

        except KeyboardInterrupt:
            renderer.finalize()
            self._console.print()
            self._console.print("  [dim]Subagente cancelado[/dim]")
            self._console.print()
            return
        finally:
            renderer.finalize()

        if text_chunks:
            self._last_response = "".join(text_chunks)

        self._console.print()

    async def _handle_invoke_skill(self, action_data: str) -> None:
        """Invoke a skill by name, expanding its template and sending as a message.

        Args:
            action_data: String in the format "skill_name\\nargs".
        """
        parts = action_data.split("\n", maxsplit=1)
        name = parts[0]
        args = parts[1] if len(parts) > 1 else ""

        if not self._skill_service:
            self._console.print("  [red]Skills no disponibles.[/red]")
            return

        resolution = self._skill_service.resolve(name, args)
        if not resolution:
            self._console.print(f"  [red]Skill '{name}' no encontrada.[/red]")
            return

        skill = self._skill_service.get_skill(name)
        if skill:
            icon = f"{skill.icon} " if skill.icon else ""
            self._console.print(
                f"  [cyan]{icon}{skill.display_name}[/cyan]"
            )
            self._console.print()

        # Send the expanded prompt as a returiar message
        await self._send_message(
            resolution.expanded_prompt,
            system_prompt_addition=resolution.system_prompt_addition,
        )

    def _handle_list_skills(self) -> None:
        """Display available skills."""
        if not self._skill_service:
            self._console.print("  [red]Skills no disponibles.[/red]")
            return
        skills = self._skill_service.list_skills()
        output = format_skills_display(skills)
        self._console.print(output)

    def _save_conversation_summary(self) -> None:
        """Save a summary of the current conversation as persistent memory."""
        try:
            from ...driven.memory.local_memory import LocalMemory
            import time as _time

            summary_parts = [
                f"Conversacion #{self._conversation_id}",
                f"{self._turn_count} turnos",
                f"${self._total_cost:.4f}",
            ]

            # Include file changes if available
            if self._tool_orchestrator:
                changes = self._tool_orchestrator.file_changes
                if changes:
                    files = [c["path"] for c in changes[:10]]
                    summary_parts.append(f"Archivos: {', '.join(files)}")

            # Include last response snippet
            if self._last_response:
                snippet = self._last_response[:200].replace("\n", " ")
                summary_parts.append(f"Ultimo: {snippet}")

            content = " | ".join(summary_parts)
            date = _time.strftime("%Y-%m-%d")
            LocalMemory().save_memory(
                f"conv-{self._conversation_id}-{date}",
                content,
                "project",
            )
        except Exception:
            pass  # Best-effort, don't break /new if memory fails

    async def _find_openai_fallback(self) -> Optional[str]:
        """Find an available non-Claude model from the backend."""
        try:
            config = await self._auth_service.ensure_valid_token()
            data = await self._api_client.get_models(
                api_url=config.api_url,
                access_token=config.access_token,
            )
            models = data if isinstance(data, list) else data.get("models", [])
            # Pick the first available non-Claude model (case-insensitive)
            for m in models:
                provider = (m.get("provider") or "").lower()
                if m.get("available") and "claude" not in provider:
                    return m.get("id")
        except Exception:
            pass
        return None

    def _show_exit_summary(self) -> None:
        """Display a session summary on exit."""
        self._console.print()
        parts = ["Sesion finalizada"]

        if self._turn_count > 0:
            parts.append(f"{self._turn_count} turnos")

        if self._total_cost > 0:
            parts.append(f"${self._total_cost:.4f}")

        if self._conversation_id is not None:
            parts.append(f"conversacion #{self._conversation_id}")

        summary = " \u00b7 ".join(parts)
        self._console.print(f"  [dim]{summary}[/dim]")
        self._console.print()
