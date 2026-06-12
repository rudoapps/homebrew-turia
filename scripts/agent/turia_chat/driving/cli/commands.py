"""Slash command registry for interactive mode."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ...application.ports.driven.api_client_port import ApiClientPort
from ...application.ports.driven.clipboard_port import ClipboardPort
from ...application.ports.driven.config_port import ConfigPort
from ...application.services.auth_service import AuthService
from ...application.services.marketplace_service import MarketplaceError, MarketplaceService
from ...application.services.skill_service import SkillService
from ...application.services.subagent_service import SubagentService
from ..ui.console import get_console


# ── Subagent shortcut mapping ───────────────────────────────────────────────

SUBAGENT_SHORTCUTS: Dict[str, str] = {
    "review": "code-review",
    "test": "test-generator",
    "explain": "explainer",
    "refactor": "refactor",
    "document": "documenter",
}


@dataclass
class CommandResult:
    """Result of executing a slash command.

    Attributes:
        handled: Whether the command was recognized and handled.
        output: Optional output message to display.
        should_continue: Whether the REPL loop should continue.
            False means exit.
        action: Optional action identifier for the caller to handle
            (e.g. "new_conversation", "change_model").
        action_data: Optional data associated with the action.
    """

    handled: bool = True
    output: str = ""
    should_continue: bool = True
    action: Optional[str] = None
    action_data: Optional[str] = None


class SlashCommandRegistry:
    """Registry and dispatcher for slash commands in interactive mode.

    Each command is a method that receives the raw argument string and
    returns a CommandResult. The registry maps command names to methods
    and handles dispatch, including aliases.

    Args:
        config_port: Configuration port for reading/writing settings.
        clipboard_port: Clipboard port for copy operations.
        auth_service: Authentication service for obtaining valid tokens.
        api_client: API client for backend calls (quota, models, etc.).
        subagent_service: Service for subagent listing and invocation.
        get_last_response: Callable that returns the last assistant response text.
        get_total_cost: Callable that returns the cumulative session cost.
        get_conversation_id: Callable that returns the current conversation ID.
    """

    def __init__(
        self,
        config_port: ConfigPort,
        clipboard_port: ClipboardPort,
        auth_service: AuthService,
        api_client: ApiClientPort,
        subagent_service: SubagentService,
        skill_service: Optional[SkillService] = None,
        marketplace_service: Optional[MarketplaceService] = None,
        get_last_response: Callable[[], str] = lambda: "",
        get_total_cost: Callable[[], float] = lambda: 0.0,
        get_conversation_id: Callable[[], Optional[int]] = lambda: None,
    ) -> None:
        self._config_port = config_port
        self._clipboard_port = clipboard_port
        self._auth_service = auth_service
        self._api_client = api_client
        self._subagent_service = subagent_service
        self._skill_service = skill_service
        self._marketplace_service = marketplace_service
        self._get_last_response = get_last_response
        self._get_total_cost = get_total_cost
        self._get_conversation_id = get_conversation_id
        self._console = get_console()

        # Command name -> handler method mapping
        self._commands: Dict[str, Callable[[str], CommandResult]] = {
            "exit": self._cmd_exit,
            "quit": self._cmd_exit,
            "q": self._cmd_exit,
            "new": self._cmd_new,
            "cost": self._cmd_cost,
            "copy": self._cmd_copy,
            "clear": self._cmd_clear,
            "help": self._cmd_help,
            "models": self._cmd_models,
            "model": self._cmd_model,
            "resume": self._cmd_resume,
            "preview": self._cmd_preview,
            "debug": self._cmd_debug,
            "undo": self._cmd_undo,
            "diff": self._cmd_diff,
            "quota": self._cmd_quota,
            "presupuesto": self._cmd_quota,
            "analyze": self._cmd_analyze,
            "analizar": self._cmd_analyze,
            "mode": self._cmd_mode,
            "modo": self._cmd_mode,
            "remember": self._cmd_remember,
            "recordar": self._cmd_remember,
            "memories": self._cmd_memories,
            "memoria": self._cmd_memories,
            "forget": self._cmd_forget,
            "olvidar": self._cmd_forget,
            "commit": self._cmd_commit,
            "review": self._cmd_review,
            "context": self._cmd_context,
            "changes": self._cmd_changes,
            "cambios": self._cmd_changes,
            # Subagent commands
            "subagents": self._cmd_subagents,
            "subagent": self._cmd_subagent,
            # Subagent shortcuts (review is /review command, use /subagent review for subagent)
            "code-review": self._cmd_subagent_shortcut,
            "test": self._cmd_subagent_shortcut,
            "explain": self._cmd_subagent_shortcut,
            "refactor": self._cmd_subagent_shortcut,
            "document": self._cmd_subagent_shortcut,
            # Skills
            "skills": self._cmd_skills,
        }

    # Expose the last-dispatched command name for shortcut resolution
    _last_cmd_name: str = ""

    def dispatch(self, input_text: str) -> Optional[CommandResult]:
        """Try to dispatch a slash command from the given input.

        Args:
            input_text: Raw user input (should start with /).

        Returns:
            A CommandResult if the input is a slash command, or None
            if it does not start with /.
        """
        stripped = input_text.strip()
        if not stripped.startswith("/"):
            return None

        parts = stripped[1:].split(maxsplit=1)
        if not parts:
            return None

        cmd_name = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        handler = self._commands.get(cmd_name)
        if handler is None:
            # Try skill dispatch before giving up
            if self._skill_service and self._skill_service.get_skill(cmd_name):
                return CommandResult(
                    handled=True,
                    action="invoke_skill",
                    action_data=f"{cmd_name}\n{args}",
                )
            return CommandResult(
                handled=True,
                output=f"Comando desconocido: /{cmd_name}. Escribe /help para ver los comandos disponibles.",
            )

        self._last_cmd_name = cmd_name
        return handler(args)

    # ── Command implementations ──────────────────────────────────────────

    def _cmd_exit(self, args: str) -> CommandResult:
        """Exit the interactive session."""
        return CommandResult(handled=True, should_continue=False)

    def _cmd_new(self, args: str) -> CommandResult:
        """Start a new conversation.

        The "new conversation" banner is rendered by the header
        (`HeaderRenderer.show_new_conversation`) when interactive.py picks
        up the `new_conversation` action — so we deliberately leave
        `output` empty to avoid printing the message twice.
        """
        return CommandResult(
            handled=True,
            action="new_conversation",
        )

    def _cmd_cost(self, args: str) -> CommandResult:
        """Show accumulated cost for this session."""
        total = self._get_total_cost()
        conv_id = self._get_conversation_id()
        lines = [f"Coste de la sesion: ${total:.4f}"]
        if conv_id is not None:
            lines.append(f"Conversacion: #{conv_id}")
        return CommandResult(handled=True, output="\n".join(lines))

    def _cmd_copy(self, args: str) -> CommandResult:
        """Copy the last assistant response to the clipboard."""
        last = self._get_last_response()
        if not last:
            return CommandResult(
                handled=True,
                output="No hay respuesta para copiar.",
            )
        try:
            self._clipboard_port.copy_text(last)
            return CommandResult(
                handled=True,
                output="Respuesta copiada al portapapeles.",
            )
        except Exception as exc:
            return CommandResult(
                handled=True,
                output=f"Error al copiar: {exc}",
            )

    def _cmd_clear(self, args: str) -> CommandResult:
        """Clear the terminal screen."""
        self._console.clear()
        return CommandResult(handled=True)

    def _cmd_help(self, args: str) -> CommandResult:
        """Show available commands."""
        help_text = (
            "Comandos disponibles:\n"
            "  /new              Nueva conversacion\n"
            "  /cost             Mostrar coste acumulado\n"
            "  /copy             Copiar ultima respuesta al portapapeles\n"
            "  /clear            Limpiar la pantalla\n"
            "  /models           Listar modelos disponibles\n"
            "  /model <id>       Cambiar modelo\n"
            "  /analyze          Analizar arquitectura del proyecto\n"
            "  /changes          Archivos modificados en esta sesion\n"
            "  /commit [msg]     Commit con mensaje auto-generado o manual\n"
            "  /review           Code review de los cambios actuales\n"
            "  /context          Diagnostico de tokens y contexto\n"
            "  /mode <modo>      Permisos: auto|ask|plan\n"
            "  /remember <texto> Guardar en memoria persistente\n"
            "  /memories         Ver memorias guardadas\n"
            "  /forget <archivo> Eliminar una memoria\n"
            "  /resume <id>      Retomar conversacion por ID\n"
            "  /undo             Deshacer ultimo cambio (stub)\n"
            "  /diff             Mostrar cambios recientes (stub)\n"
            "  /preview          Alternar modo preview\n"
            "  /debug            Alternar modo debug\n"
            "  /quota            Mostrar uso del presupuesto\n"
            "  /presupuesto      Alias de /quota\n"
            "\n"
            "Subagentes:\n"
            "  /review <msg>     Revisar codigo\n"
            "  /test <msg>       Generar tests\n"
            "  /explain <msg>    Explicar codigo\n"
            "  /refactor <msg>   Refactorizar\n"
            "  /document <msg>   Documentar\n"
            "  /subagents        Listar subagentes\n"
            "  /subagent <id> <msg>  Enviar tarea a subagente\n"
            "\n"
            "  /exit /quit /q    Salir\n"
            "\n"
            "Skills:\n"
            "  /skills           Listar skills disponibles\n"
            "  /<skill> <msg>    Invocar una skill\n"
            "\n"
            "Atajos:\n"
            "  @archivo.py       Adjuntar contenido de un archivo\n"
            "  Esc+Enter         Nueva linea (sin enviar)\n"
            "  Ctrl+D            Salir\n"
            "  Ctrl+C            Cancelar mensaje actual"
        )

        # Append loaded skills if available
        if self._skill_service:
            skills = self._skill_service.list_skills()
            if skills:
                help_text += "\n\nSkills cargadas:"
                for s in skills:
                    icon = f"{s.icon} " if s.icon else ""
                    help_text += f"\n  /{s.name:<16} {icon}{s.description}"

        return CommandResult(handled=True, output=help_text)

    def _cmd_remember(self, args: str) -> CommandResult:
        """Save a memory."""
        text = args.strip()
        if not text:
            return CommandResult(handled=True, output="  [dim]Uso: /remember <lo que quieres que recuerde>[/dim]")
        from ...driven.memory.local_memory import LocalMemory
        mem = LocalMemory()
        # Auto-detect type
        if any(w in text.lower() for w in ["no hagas", "no uses", "siempre", "nunca", "prefiero"]):
            mem_type = "feedback"
        else:
            mem_type = "user"
        name = text[:50]
        mem.save_memory(name, text, mem_type)
        return CommandResult(handled=True, output=f"  [success]\u2713[/success] Guardado en memoria ({mem_type})")

    def _cmd_memories(self, args: str) -> CommandResult:
        """List saved memories."""
        from ...driven.memory.local_memory import LocalMemory
        memories = LocalMemory().list_memories()
        if not memories:
            return CommandResult(handled=True, output="  [dim]No hay memorias guardadas.[/dim]")
        lines = ["", "  [bold]Memorias guardadas:[/bold]", ""]
        for m in memories:
            lines.append(f"  [dim]{m['file']}[/dim] — {m['name']}")
        lines.append("")
        lines.append("  [dim]Usa /forget <archivo> para eliminar[/dim]")
        return CommandResult(handled=True, output="\n".join(lines))

    def _cmd_forget(self, args: str) -> CommandResult:
        """Delete a memory."""
        filename = args.strip()
        if not filename:
            return CommandResult(handled=True, output="  [dim]Uso: /forget <nombre_archivo.md>[/dim]")
        from ...driven.memory.local_memory import LocalMemory
        if LocalMemory().delete_memory(filename):
            return CommandResult(handled=True, output=f"  [success]\u2713[/success] Memoria eliminada: {filename}")
        return CommandResult(handled=True, output=f"  [red]No encontrada: {filename}[/red]")

    def _cmd_changes(self, args: str) -> CommandResult:
        """Show files changed in this session."""
        return CommandResult(handled=True, action="show_changes")

    def _cmd_commit(self, args: str) -> CommandResult:
        """Generate commit message from diff and commit."""
        msg = args.strip()
        if msg:
            return CommandResult(handled=True, action="commit_with_message", action_data=msg)
        return CommandResult(handled=True, action="commit_auto")

    def _cmd_review(self, args: str) -> CommandResult:
        """Review current changes with AI."""
        return CommandResult(handled=True, action="review_changes")

    def _cmd_context(self, args: str) -> CommandResult:
        """Show token context diagnostics."""
        return CommandResult(handled=True, action="show_context")

    def _cmd_mode(self, args: str) -> CommandResult:
        """Change permission mode."""
        mode = args.strip().lower()
        if not mode:
            return CommandResult(handled=True, action="show_mode")
        if mode not in ("auto", "ask", "plan"):
            return CommandResult(
                handled=True,
                output="  [red]Modos disponibles: auto, ask, plan[/red]",
            )
        return CommandResult(handled=True, action="change_mode", action_data=mode)

    def _cmd_analyze(self, args: str) -> CommandResult:
        """Regenerate project architecture analysis."""
        return CommandResult(handled=True, action="analyze_architecture")

    def _cmd_models(self, args: str) -> CommandResult:
        """List available models (async fetch handled by InteractiveHandler)."""
        return CommandResult(
            handled=True,
            action="list_models",
        )

    def _cmd_model(self, args: str) -> CommandResult:
        """Change the active model or show list if no arg given."""
        model_id = args.strip()
        if not model_id:
            # No arg → show models list (same as /models)
            return CommandResult(handled=True, action="list_models")

        # "auto" → clear override
        if model_id == "auto":
            self._config_port.set_config("preferred_model", "auto")
            return CommandResult(
                handled=True,
                output="  [success]\u2713[/success] Modelo: [bold]auto[/bold] (routing automatico)",
            )

        # Otherwise validate against backend
        return CommandResult(
            handled=True,
            action="change_model",
            action_data=model_id,
        )

    def _cmd_resume(self, args: str) -> CommandResult:
        """Resume an existing conversation by ID."""
        conv_str = args.strip()
        if not conv_str:
            return CommandResult(
                handled=True,
                output="Uso: /resume <conversation_id>",
            )
        try:
            conv_id = int(conv_str)
        except ValueError:
            return CommandResult(
                handled=True,
                output=f"ID de conversacion invalido: {conv_str}",
            )
        return CommandResult(
            handled=True,
            output=f"Retomando conversacion #{conv_id}",
            action="resume_conversation",
            action_data=str(conv_id),
        )

    def _cmd_preview(self, args: str) -> CommandResult:
        """Toggle preview mode."""
        config = self._config_port.get_config()
        new_val = not config.preview_mode
        self._config_port.set_config("preview_mode", new_val)
        state = "activado" if new_val else "desactivado"
        return CommandResult(
            handled=True,
            output=f"Modo preview {state}.",
        )

    def _cmd_debug(self, args: str) -> CommandResult:
        """Toggle debug mode."""
        config = self._config_port.get_config()
        new_val = not config.debug_mode
        self._config_port.set_config("debug_mode", new_val)
        state = "activado" if new_val else "desactivado"
        return CommandResult(
            handled=True,
            output=f"Modo debug {state}.",
        )

    def _cmd_undo(self, args: str) -> CommandResult:
        """Undo last change -- stub for Phase 3."""
        return CommandResult(
            handled=True,
            output="Undo no disponible aun (Phase 3).",
        )

    def _cmd_diff(self, args: str) -> CommandResult:
        """Show recent changes -- stub for Phase 3."""
        return CommandResult(
            handled=True,
            output="Diff no disponible aun (Phase 3).",
        )

    def _cmd_quota(self, args: str) -> CommandResult:
        """Show quota/budget usage (async fetch handled by InteractiveHandler)."""
        return CommandResult(
            handled=True,
            action="fetch_quota",
        )

    def _cmd_subagents(self, args: str) -> CommandResult:
        """List available subagents (async fetch handled by InteractiveHandler)."""
        return CommandResult(
            handled=True,
            action="list_subagents",
        )

    def _cmd_subagent(self, args: str) -> CommandResult:
        """Invoke a specific subagent: /subagent <id> <message>."""
        parts = args.strip().split(maxsplit=1)
        if len(parts) < 2:
            return CommandResult(
                handled=True,
                output="Uso: /subagent <id> <mensaje>\nEjemplo: /subagent code-review src/auth.py",
            )
        subagent_id = parts[0]
        prompt = parts[1]
        return CommandResult(
            handled=True,
            action="invoke_subagent",
            action_data=f"{subagent_id}\n{prompt}",
        )

    def _cmd_skills(self, args: str) -> CommandResult:
        """Dispatch skill subcommands.

        Usage:
          /skills                              Listar skills cargadas
          /skills marketplace add <url> [name] Clonar un marketplace
          /skills marketplace list             Ver marketplaces
          /skills marketplace remove <name>    Eliminar marketplace
          /skills install <pack>[@<mp>]        Instalar pack
          /skills uninstall <pack>             Desinstalar pack
          /skills update [<mp>|all]            git pull del marketplace
          /skills installed                    Ver packs instalados
        """
        if not self._skill_service:
            return CommandResult(handled=True, output="Skills no disponibles.")

        parts = args.strip().split()
        sub = parts[0].lower() if parts else ""
        rest = parts[1:]

        if not sub or sub == "list":
            if not self._skill_service.list_skills():
                return CommandResult(handled=True, output="No hay skills cargadas. Usa /skills install <pack>@<marketplace>.")
            return CommandResult(handled=True, action="list_skills")

        if sub == "marketplace":
            return self._handle_marketplace(rest)
        if sub == "install":
            return self._handle_install(rest)
        if sub == "uninstall":
            return self._handle_uninstall(rest)
        if sub == "update":
            return self._handle_update(rest)
        if sub == "installed":
            return self._handle_installed()

        return CommandResult(
            handled=True,
            output=(
                "Subcomando desconocido. Usa uno de:\n"
                "  /skills                          listar cargadas\n"
                "  /skills marketplace add <url>    clonar marketplace\n"
                "  /skills marketplace list         ver marketplaces\n"
                "  /skills marketplace remove <n>   eliminar marketplace\n"
                "  /skills install <pack>[@<mp>]    instalar pack\n"
                "  /skills uninstall <pack>         desinstalar pack\n"
                "  /skills update [<mp>|all]        actualizar marketplace\n"
                "  /skills installed                listar packs instalados"
            ),
        )

    def _handle_marketplace(self, rest: List[str]) -> CommandResult:
        if not self._marketplace_service:
            return CommandResult(handled=True, output="Marketplace no disponible.")
        if not rest:
            return CommandResult(handled=True, output="Uso: /skills marketplace {add|list|remove} ...")
        op = rest[0].lower()
        try:
            if op == "add" and len(rest) >= 2:
                url = rest[1]
                name = rest[2] if len(rest) >= 3 else None
                resolved = self._marketplace_service.add_marketplace(url, name=name)
                return CommandResult(handled=True, output=f"Marketplace '{resolved}' añadido.")
            if op == "list":
                mps = self._marketplace_service.list_marketplaces()
                if not mps:
                    return CommandResult(handled=True, output="No hay marketplaces.")
                lines = [f"  {name}  {m.url}  ({m.commit or '—'})" for name, m in mps.items()]
                return CommandResult(handled=True, output="Marketplaces:\n" + "\n".join(lines))
            if op == "remove" and len(rest) >= 2:
                uninstalled = self._marketplace_service.remove_marketplace(rest[1])
                msg = f"Marketplace '{rest[1]}' eliminado."
                if uninstalled:
                    msg += f" Packs desinstalados: {', '.join(uninstalled)}."
                return CommandResult(handled=True, output=msg)
        except MarketplaceError as exc:
            return CommandResult(handled=True, output=f"Error: {exc}")
        return CommandResult(handled=True, output="Uso: /skills marketplace {add <url> [name]|list|remove <name>}")

    def _handle_install(self, rest: List[str]) -> CommandResult:
        if not self._marketplace_service:
            return CommandResult(handled=True, output="Marketplace no disponible.")
        if not rest:
            return CommandResult(handled=True, output="Uso: /skills install <pack>[@<marketplace>]")
        try:
            pack = self._marketplace_service.install_pack(rest[0])
        except MarketplaceError as exc:
            return CommandResult(handled=True, output=f"Error: {exc}")
        return CommandResult(
            handled=True,
            action="reload_skills",
            action_data=f"Pack '{pack.name}' instalado desde '{pack.marketplace}'.",
        )

    def _handle_uninstall(self, rest: List[str]) -> CommandResult:
        if not self._marketplace_service or not rest:
            return CommandResult(handled=True, output="Uso: /skills uninstall <pack>")
        try:
            self._marketplace_service.uninstall_pack(rest[0])
        except MarketplaceError as exc:
            return CommandResult(handled=True, output=f"Error: {exc}")
        return CommandResult(
            handled=True,
            action="reload_skills",
            action_data=f"Pack '{rest[0]}' desinstalado.",
        )

    def _handle_update(self, rest: List[str]) -> CommandResult:
        if not self._marketplace_service:
            return CommandResult(handled=True, output="Marketplace no disponible.")
        target = rest[0] if rest else None
        try:
            results = self._marketplace_service.update(target)
        except MarketplaceError as exc:
            return CommandResult(handled=True, output=f"Error: {exc}")
        if not results:
            return CommandResult(handled=True, output="Nada que actualizar.")
        lines = [
            f"  {name}: {old or '—'} → {new or '—'}" + (" (sin cambios)" if old == new else "")
            for name, old, new in results
        ]
        return CommandResult(
            handled=True,
            action="reload_skills",
            action_data="Actualizado:\n" + "\n".join(lines),
        )

    def _handle_installed(self) -> CommandResult:
        if not self._marketplace_service:
            return CommandResult(handled=True, output="Marketplace no disponible.")
        packs = self._marketplace_service.list_installed()
        if not packs:
            return CommandResult(handled=True, output="No hay packs instalados.")
        lines = [
            f"  {name:<24} {p.source_path}@{p.marketplace}  ({p.commit or '—'})"
            for name, p in packs.items()
        ]
        return CommandResult(handled=True, output="Packs instalados:\n" + "\n".join(lines))

    def _cmd_subagent_shortcut(self, args: str) -> CommandResult:
        """Handle subagent shortcut commands like /review, /test, etc."""
        cmd_name = self._last_cmd_name
        prompt = args.strip()
        if not prompt:
            return CommandResult(
                handled=True,
                output=f"Uso: /{cmd_name} <mensaje>\nEjemplo: /{cmd_name} src/auth.py",
            )
        subagent_id = SUBAGENT_SHORTCUTS.get(cmd_name, cmd_name)
        return CommandResult(
            handled=True,
            action="invoke_subagent",
            action_data=f"{subagent_id}\n{prompt}",
        )


# ── Display helpers for async results ────────────────────────────────────


def format_quota_display(data: Dict[str, Any], session_cost: float) -> str:
    """Format quota data into a rich display string.

    Args:
        data: Quota response dict from the API.
        session_cost: Current session accumulated cost.

    Returns:
        Formatted string ready to print.
    """
    lines: List[str] = [""]

    if not data.get("has_quota"):
        lines.append("  Sin limite configurado")
        cost = data.get("current_cost", 0.0)
        lines.append(f"  Coste acumulado: ${cost:.2f}")
        lines.append(f"  Coste sesion:    ${session_cost:.4f}")
        lines.append("")
        return "\n".join(lines)

    monthly_limit = float(data.get("monthly_limit", 0))
    current_cost = float(data.get("current_cost", 0))
    remaining = data.get("remaining", "?")
    usage_pct = float(data.get("usage_percent", 0) or 0)
    is_enforced = data.get("is_enforced", False)
    is_exceeded = data.get("is_exceeded", False)

    # Status indicator
    if is_exceeded:
        lines.append("  LIMITE EXCEDIDO")
    elif usage_pct >= 80:
        lines.append(f"  Cerca del limite ({usage_pct:.0f}%)")
    else:
        lines.append("  Dentro del limite")
    lines.append("")

    # Progress bar (20 unicode chars)
    bar_width = 20
    filled = int(min(100, usage_pct) / 100 * bar_width)
    empty = bar_width - filled

    if usage_pct >= 100:
        color = "red"
    elif usage_pct >= 80:
        color = "yellow"
    else:
        color = "green"

    filled_bar = "\u2588" * filled
    empty_bar = "\u2591" * empty
    lines.append(f"  [{color}]{filled_bar}[/{color}][dim]{empty_bar}[/dim] {usage_pct:.1f}%")
    lines.append("")

    # Details
    lines.append(f"  [bold]Limite mensual:[/bold]  ${monthly_limit:.2f}")
    lines.append(f"  [bold]Coste actual:[/bold]    ${current_cost:.2f}")
    lines.append(f"  [bold]Restante:[/bold]        ${remaining}")
    lines.append(f"  [bold]Coste sesion:[/bold]    ${session_cost:.4f}")
    lines.append("")

    # Enforcement
    if is_enforced:
        lines.append("  [dim]Modo:[/dim] [red]Bloqueo activo[/red]")
    else:
        lines.append("  [dim]Modo:[/dim] [yellow]Solo aviso[/yellow]")

    lines.append("")
    return "\n".join(lines)


def format_models_display(
    models: List[Dict[str, Any]],
    current_model: str,
    default_model: str,
) -> str:
    """Format models list into a rich display string.

    Args:
        models: List of model dicts from the API.
        current_model: Currently selected model ID.
        default_model: Server default model ID.

    Returns:
        Formatted string ready to print.
    """
    lines: List[str] = ["", "  [bold]Modelos disponibles:[/bold]", ""]

    if not models:
        lines.append("  [dim]No hay modelos configurados.[/dim]")
        lines.append("")
        return "\n".join(lines)

    for m in models:
        model_id = m.get("id", "")
        name = m.get("name", "")
        provider = m.get("provider", "")
        input_price = m.get("input_price", "0")
        output_price = m.get("output_price", "0")
        is_default = m.get("is_default", False)
        status = m.get("status", "unknown")
        available = m.get("available", True)
        status_message = m.get("status_message", "")

        # Indicators
        indicators: List[str] = []
        if current_model and current_model == model_id:
            indicators.append("[green]* ACTIVO[/green]")
        elif is_default:
            indicators.append("[cyan]* default[/cyan]")

        if status == "no_credits":
            indicators.append("[red]sin creditos[/red]")
        elif status == "degraded":
            indicators.append("[yellow]limitado[/yellow]")
        elif status == "error":
            indicators.append("[red]error[/red]")
        elif status == "available":
            indicators.append("[green]ok[/green]")

        indicator_str = " ".join(indicators)
        if indicator_str:
            indicator_str = f"  {indicator_str}"

        if not available:
            lines.append(f"  [dim]{model_id}[/dim]{indicator_str}")
            lines.append(f"    [dim]{name} ({provider})[/dim]")
            if status_message:
                lines.append(f"    [red]{status_message}[/red]")
        else:
            lines.append(f"  [bold]{model_id}[/bold]{indicator_str}")
            lines.append(f"    [dim]{name} ({provider})[/dim]")

        lines.append(f"    [dim]Precio: ${input_price}/1M in, ${output_price}/1M out[/dim]")
        lines.append("")

    lines.append("  [dim]Usa /model <id> para cambiar de modelo[/dim]")
    lines.append("  [dim]    /model auto para routing automatico[/dim]")
    lines.append("")
    return "\n".join(lines)


def format_skills_display(skills: list) -> str:
    """Format skills list into a rich display string.

    Args:
        skills: List of Skill domain objects.

    Returns:
        Formatted string ready to print.
    """
    lines: List[str] = ["", "  [bold]Skills disponibles:[/bold]", ""]

    if not skills:
        lines.append("  No hay skills cargadas.")
        lines.append("")
        return "\n".join(lines)

    # Group by category
    categories: Dict[str, list] = {}
    for s in skills:
        categories.setdefault(s.category, []).append(s)

    for cat, cat_skills in sorted(categories.items()):
        lines.append(f"  [dim]{cat.capitalize()}:[/dim]")
        for s in cat_skills:
            icon = f"{s.icon} " if s.icon else ""
            source_tag = f"[dim]({s.source})[/dim]" if s.source != "backend" else ""
            lines.append(f"    [cyan]/{s.name:<16}[/cyan] {icon}{s.description} {source_tag}")
        lines.append("")

    lines.append("  [dim]Uso: /<skill> <mensaje>[/dim]")
    lines.append("")
    return "\n".join(lines)


def format_subagents_display(subagents: List[Dict[str, Any]]) -> str:
    """Format subagent list into a rich display string.

    Args:
        subagents: List of subagent dicts from the API.

    Returns:
        Formatted string ready to print.
    """
    lines: List[str] = ["", "  [bold]Subagentes disponibles:[/bold]", ""]

    if not subagents:
        lines.append("  No hay subagentes disponibles.")
        lines.append("")
        return "\n".join(lines)

    for sa in subagents:
        sid = sa.get("id", "")
        desc = sa.get("description", "Sin descripcion")
        lines.append(f"  [cyan]{sid:<16}[/cyan] - {desc:.50}")

    lines.append("")
    lines.append("  [dim]Uso: /subagent <id> <mensaje>[/dim]")
    lines.append("  [dim]Ejemplo: /subagent code-review src/auth.py[/dim]")
    lines.append("")
    return "\n".join(lines)
