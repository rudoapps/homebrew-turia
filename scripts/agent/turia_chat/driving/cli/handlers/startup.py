"""Startup handler — authentication, broadcast, RAG check, architecture offer."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ....application.services.auth_service import AuthService
from ....application.ports.driven.api_client_port import ApiClientPort
from ....driven.context.project_context_builder import ProjectContextBuilder
from ...ui.console import get_console
from ...ui.selector import SelectOption, select_option_async


class StartupHandler:
    """Handles all startup-related operations."""

    def __init__(
        self,
        auth_service: AuthService,
        api_client: ApiClientPort,
        context_builder: ProjectContextBuilder,
    ) -> None:
        self._auth_service = auth_service
        self._api_client = api_client
        self._context_builder = context_builder
        self._console = get_console()
        self._last_broadcast_id: Optional[int] = None

    async def fetch_startup_data(self, turia_version: str) -> dict:
        """Fetch broadcast messages and version check.

        Auth must be validated before calling this method.
        Returns {} on failure, or {"_server_down": True} if server unavailable.
        """
        import httpx

        try:
            config = await self._auth_service.ensure_valid_token()
        except Exception:
            # Auth already validated in _loop(), use current config as fallback
            config = self._auth_service.get_config()
            if not config.access_token:
                return {}

        try:
            return await self._api_client.get_messages(
                api_url=config.api_url,
                access_token=config.access_token,
                turia_version=turia_version,
                after_id=self._last_broadcast_id,
            )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout):
            return {"_server_down": True, "_error": "No se puede conectar al servidor."}
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (502, 503, 504):
                return {"_server_down": True, "_error": f"Servidor no disponible ({exc.response.status_code})."}
            return {}
        except Exception:
            return {}

    async def fetch_rag_info(self) -> Optional[dict]:
        """Fetch RAG project info if current directory is a git repo."""
        git_url = self._context_builder.get_git_remote_url()
        if not git_url:
            return None
        try:
            config = await self._auth_service.ensure_valid_token()
            return await self._api_client.check_rag(
                api_url=config.api_url,
                access_token=config.access_token,
                git_remote_url=git_url,
            )
        except Exception:
            return None

    async def offer_architecture_analysis(self, rag_info: dict, project_name: str) -> None:
        """Ask user if they want to analyze project architecture."""
        name = rag_info.get("project_name", project_name)

        chosen = await select_option_async(
            [
                SelectOption(value="yes", label="Si, analizar arquitectura",
                             description=f"Analiza {name} y genera una guia para mejorar las respuestas"),
                SelectOption(value="no", label="No, continuar",
                             description="Puedes hacerlo mas tarde con /analyze"),
            ],
            title="Este proyecto no tiene guia de arquitectura. Quieres generarla?",
        )

        if chosen == "yes":
            await self.run_architecture_analysis(rag_info)

    async def run_architecture_analysis(self, rag_info: Optional[dict] = None) -> None:
        """Send project files to backend for architecture analysis."""
        if not rag_info:
            rag_info = await self.fetch_rag_info()
        if not rag_info or not rag_info.get("project_id"):
            self._console.print("  [red]Proyecto no encontrado en el RAG.[/red]")
            return

        project_id = rag_info["project_id"]

        from ...ui.spinner import Spinner
        spinner = Spinner()
        spinner.start("Analizando arquitectura del proyecto...")

        context = self._context_builder.build()
        key_files_content = {}
        root = self._context_builder._root

        for kf in context.get("key_files", []):
            path = root / kf
            if path.is_file():
                try:
                    key_files_content[kf] = path.read_text(errors="replace")[:3000]
                except OSError:
                    pass

        # Collect diverse code samples (largest files per directory)
        code_extensions = {".py", ".swift", ".kt", ".ts", ".js", ".dart", ".go", ".rs", ".java"}
        skip_dirs = {"node_modules", "__pycache__", ".git", "venv", ".venv", "build", "dist",
                     "Pods", "migrations", ".build", "DerivedData"}
        candidates = []
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in code_extensions:
                continue
            rel = str(path.relative_to(root))
            if any(s in rel.split("/") for s in skip_dirs):
                continue
            try:
                size = path.stat().st_size
                if size < 100:
                    continue
                candidates.append((size, rel, path))
            except OSError:
                pass

        candidates.sort(key=lambda x: x[0], reverse=True)
        seen_dirs: set = set()
        for _, rel, path in candidates:
            if len(key_files_content) >= 20:
                break
            parent = str(path.parent.relative_to(root))
            if parent in seen_dirs:
                continue
            try:
                key_files_content[rel] = path.read_text(errors="replace")[:4000]
                seen_dirs.add(parent)
            except OSError:
                pass

        spinner.update("Generando guia de arquitectura con IA...")

        try:
            config = await self._auth_service.ensure_valid_token()
            result = await self._api_client.analyze_architecture(
                api_url=config.api_url,
                access_token=config.access_token,
                project_id=project_id,
                payload={
                    "file_tree": context.get("file_tree", ""),
                    "dependencies": context.get("dependencies", ""),
                    "key_files": key_files_content,
                    "project_type": context.get("project_type", ""),
                },
            )
            if result.get("status") == "completed":
                spinner.stop(
                    f"Guia de arquitectura generada ({result.get('guide_length', 0)} chars)",
                    "success",
                )
            else:
                spinner.stop(f"Error: {result.get('message', 'unknown')}", "error")
        except Exception as exc:
            spinner.stop(f"Error al analizar: {exc}", "error")

    async def do_interactive_login(self):
        """Run browser-based login flow."""
        import httpx
        from rich.panel import Panel
        from rich.text import Text
        from ....application.services.auth_service import AuthenticationError, ServerUnavailableError

        # Check server availability first
        try:
            config = self._auth_service.get_config()
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{config.api_url}/agent/models")
                if resp.status_code in (502, 503, 504):
                    raise ServerUnavailableError(f"Servidor no disponible ({resp.status_code}).")
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout):
            raise ServerUnavailableError("No se puede conectar al servidor.")
        except ServerUnavailableError:
            raise

        self._console.print()
        text = Text()
        text.append("\U0001f511 ", style="yellow")
        text.append("Inicio de sesion requerido", style="yellow bold")
        text.append("\n\n")
        text.append("Se abrira el navegador para iniciar sesion...", style="dim")
        panel = Panel(text, border_style="yellow", padding=(0, 1), expand=False)
        self._console.print(panel)
        self._console.print()

        try:
            with self._console.status(
                "  [dim]Esperando autenticacion en el navegador...[/dim]",
                spinner="dots",
            ):
                config = await self._auth_service.login(
                    on_url_ready=self._show_login_url
                )
            self._console.print("  [green]\u2713[/green] Sesion iniciada correctamente")
            self._console.print()
            return config
        except AuthenticationError as exc:
            self._console.print(f"  [red]\u2717 {exc}[/red]")
            self._console.print()
            return None
        except Exception as exc:
            self._console.print(f"  [red]\u2717 Error de autenticacion: {exc}[/red]")
            self._console.print()
            return None

    def _show_login_url(self, url: str, opened: bool) -> None:
        """Display the login URL so the user can open it manually if needed."""
        self._console.print()
        if opened:
            self._console.print(
                "  [dim]Si el navegador no se abrio automaticamente, "
                "abre este enlace:[/dim]"
            )
        else:
            self._console.print(
                "  [yellow]No se pudo abrir el navegador automaticamente. "
                "Abre este enlace manualmente:[/yellow]"
            )
        self._console.print(f"  [cyan]{url}[/cyan]")
        self._console.print()

    def track_broadcast_ids(self, messages: List[dict]) -> None:
        """Update last seen broadcast ID."""
        for msg in messages:
            msg_id = msg.get("id")
            if msg_id is not None:
                if self._last_broadcast_id is None or msg_id > self._last_broadcast_id:
                    self._last_broadcast_id = msg_id

    async def check_broadcasts(self, turia_version: str) -> None:
        """Check for new broadcast messages between turns."""
        try:
            config = await self._auth_service.ensure_valid_token()
            data = await self._api_client.get_messages(
                api_url=config.api_url,
                access_token=config.access_token,
                turia_version=turia_version,
                after_id=self._last_broadcast_id,
            )
            version_check = data.get("version_check")
            if version_check and version_check.get("update_required"):
                from ...ui.header import SessionHeader
                SessionHeader().show_update_required(version_check.get("message", ""))
                raise SystemExit(1)
            messages = data.get("messages", [])
            if messages:
                self.track_broadcast_ids(messages)
                from ...ui.header import SessionHeader
                SessionHeader()._render_broadcasts(messages)
                self._console.print()
        except SystemExit:
            raise
        except Exception:
            pass
