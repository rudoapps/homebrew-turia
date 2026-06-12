"""Context handler — /context diagnostics."""

from __future__ import annotations

from typing import Optional

from ....application.services.skill_service import SkillService
from ....driven.context.project_context_builder import ProjectContextBuilder
from ...ui.console import get_console


class ContextHandler:
    """Handles context diagnostics."""

    def __init__(
        self,
        context_builder: ProjectContextBuilder,
        skill_service: Optional[SkillService] = None,
    ) -> None:
        self._context_builder = context_builder
        self._skill_service = skill_service
        self._console = get_console()

    async def handle_context(
        self,
        conversation_id: Optional[int],
        turn_count: int,
        total_cost: float,
        fetch_rag_info_fn=None,
    ) -> None:
        """Show token context diagnostics."""
        context = self._context_builder.build()
        file_tree_size = len(context.get("file_tree", ""))
        deps_size = len(context.get("dependencies", ""))
        rules_size = len(context.get("project_rules", ""))

        def est(chars: int) -> str:
            tokens = chars // 4
            return f"~{tokens // 1000}K tokens" if tokens > 1000 else f"~{tokens} tokens"

        lines = [
            "",
            "  [bold]Diagnostico de contexto[/bold]",
            "",
            f"  Conversacion:     #{conversation_id or 'nueva'}",
            f"  Turnos:           {turn_count}",
            f"  Coste acumulado:  ${total_cost:.4f}",
            "",
            "  [bold]Contexto enviado por turno:[/bold]",
            f"  System prompt:    ~10K tokens (base)",
            f"  File tree:        {est(file_tree_size)} ({file_tree_size} chars)",
            f"  Dependencias:     {est(deps_size)} ({deps_size} chars)",
            f"  Project rules:    {est(rules_size)} ({rules_size} chars)",
        ]

        if fetch_rag_info_fn:
            rag_info = await fetch_rag_info_fn()
            if rag_info and rag_info.get("has_architecture_guide"):
                lines.append("  Guia arquitectura: ~1.5K tokens (del proyecto)")

        if self._skill_service:
            project_type = context.get("project_type", "")
            auto_skill = self._skill_service.get_auto_skill_for_project(project_type)
            if auto_skill:
                skill_size = len(auto_skill.system_prompt_addition or "")
                lines.append(f"  Skill activa:     {est(skill_size)} ({auto_skill.display_name})")

        try:
            from ....driven.memory.local_memory import LocalMemory
            mem = LocalMemory().get_all_memories()
            if mem:
                lines.append(f"  Memoria usuario:  {est(len(mem))}")
        except Exception:
            pass

        lines.append("")
        self._console.print("\n".join(lines))
