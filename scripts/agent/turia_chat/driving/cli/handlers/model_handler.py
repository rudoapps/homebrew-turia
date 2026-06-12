"""Model handler — /model, /models selector."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ....application.services.auth_service import AuthService
from ....application.ports.driven.api_client_port import ApiClientPort
from ....application.ports.driven.config_port import ConfigPort
from ...ui.console import get_console
from ...ui.selector import SelectOption, select_option_async


class ModelHandler:
    """Handles model listing and selection."""

    def __init__(
        self,
        auth_service: AuthService,
        api_client: ApiClientPort,
        config_port: ConfigPort,
    ) -> None:
        self._auth_service = auth_service
        self._api_client = api_client
        self._config_port = config_port
        self._console = get_console()

    async def handle_list_models(self) -> None:
        """Fetch models and show interactive selector."""
        try:
            models = await self._fetch_models()
            if models is None:
                return
            await self._show_selector(models)
        except Exception as exc:
            self._console.print(f"  [red]Error al obtener modelos: {exc}[/red]")

    async def handle_change_model(self, model_id: str) -> None:
        """Validate model and switch if valid."""
        try:
            models = await self._fetch_models()
            if models is None:
                return
            match = next((m for m in models if m.get("id") == model_id), None)
            if not match:
                available = ", ".join(m.get("id", "") for m in models if m.get("available", True))
                self._console.print(f"  [red]Modelo '{model_id}' no encontrado.[/red]")
                self._console.print(f"  [dim]Disponibles: {available}[/dim]")
                return
            if not match.get("available", True):
                self._console.print(f"  [yellow]Modelo '{model_id}' no disponible: {match.get('status_message', '')}[/yellow]")
                return
            self._apply_model(model_id, match)
        except Exception as exc:
            self._config_port.set_config("preferred_model", model_id)
            self._console.print(f"  [success]\u2713[/success] Modelo cambiado a: [bold]{model_id}[/bold]")
            self._console.print(f"  [dim](sin validar: {exc})[/dim]")

    async def _fetch_models(self) -> Optional[List[dict]]:
        """Fetch models from the API."""
        try:
            config = await self._auth_service.ensure_valid_token()
            data = await self._api_client.get_models(
                api_url=config.api_url,
                access_token=config.access_token,
            )
            return data if isinstance(data, list) else data.get("models", [])
        except Exception as exc:
            self._console.print(f"  [red]Error al obtener modelos: {exc}[/red]")
            return None

    async def _show_selector(self, models: List[dict]) -> None:
        """Show interactive model selector."""
        current = self._config_port.get_config().preferred_model or "auto"

        options = [
            SelectOption(
                value="auto", label="auto",
                description="Routing automatico del servidor",
                active=current == "auto" or current == "",
            ),
        ]
        for m in models:
            mid = m.get("id", "")
            name = m.get("name", mid)
            provider = m.get("provider", "")
            inp = m.get("input_price", "?")
            out = m.get("output_price", "?")
            available = m.get("available", True)
            is_default = m.get("is_default", False)

            right = f"${inp}/1M in  ${out}/1M out"
            if is_default:
                right += "  (default)"

            desc = f"{name} ({provider})"
            status = m.get("status", "")
            if status == "no_credits":
                desc += " - sin creditos"
            elif status == "error":
                desc += " - error"

            options.append(SelectOption(
                value=mid, label=mid, description=desc,
                right_label=right, disabled=not available,
                active=current == mid,
            ))

        self._console.print()
        chosen = await select_option_async(options, title="Selecciona modelo")

        if chosen is None:
            self._console.print("  [dim]Cancelado[/dim]")
            return

        if chosen == "auto":
            self._config_port.set_config("preferred_model", "auto")
            self._console.print(
                "  [success]\u2713[/success] Modelo: [bold]auto[/bold] [dim](routing automatico)[/dim]"
            )
        else:
            match = next((m for m in models if m.get("id") == chosen), {})
            self._apply_model(chosen, match)

    def _apply_model(self, model_id: str, model_info: dict) -> None:
        """Save model selection and show confirmation."""
        self._config_port.set_config("preferred_model", model_id)
        name = model_info.get("name", model_id)
        inp = model_info.get("input_price", "?")
        out = model_info.get("output_price", "?")
        self._console.print(
            f"  [success]\u2713[/success] Modelo: [bold]{name}[/bold] "
            f"[dim](${inp}/1M in, ${out}/1M out)[/dim]"
        )
