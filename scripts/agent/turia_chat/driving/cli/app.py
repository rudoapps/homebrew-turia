"""Main CLI application — parses arguments and dispatches to handlers."""

from __future__ import annotations

import asyncio
import sys
from typing import List, Optional

from .single import SingleMessageHandler
from ...container import Container


class App:
    """Top-level CLI application.

    Supports:
      - `chat.py "message"`              — single-shot message mode
      - `chat.py --conversation ID "msg"` — continue a specific conversation
      - `chat.py`                         — interactive REPL mode
      - `chat.py --new "message"`         — force new conversation
      - `chat.py --debug "message"`       — enable debug mode
    """

    def __init__(self, container: Container) -> None:
        self._container = container

    def run(self, argv: Optional[List[str]] = None) -> int:
        """Parse arguments and run the appropriate handler.

        Args:
            argv: Command-line arguments (defaults to sys.argv[1:]).

        Returns:
            Exit code.
        """
        if argv is None:
            argv = sys.argv[1:]

        if argv and argv[0] == "--skills":
            return self._run_skills(argv[1:])

        args = self._parse_args(argv)

        if args.prompt:
            return self._run_single(args)
        else:
            return self._run_interactive()

    def _run_skills(self, argv: List[str]) -> int:
        """Run a single `turia skills ...` subcommand."""
        from .skills_cli import SkillsCliHandler

        handler = SkillsCliHandler(
            marketplace_service=self._container.marketplace_service,
            skill_service=self._container.skill_service,
        )
        return handler.run(argv)

    def _run_interactive(self) -> int:
        """Run interactive REPL mode."""
        from .interactive import InteractiveHandler

        handler = InteractiveHandler(
            chat_service=self._container.chat_service,
            config_port=self._container.config_port,
            clipboard_port=self._container.clipboard_port,
            auth_service=self._container.auth_service,
            api_client=self._container.api_client,
            subagent_service=self._container.subagent_service,
            skill_service=self._container.skill_service,
            marketplace_service=self._container.marketplace_service,
            tool_orchestrator=self._container.tool_orchestrator,
            project_context_builder=self._container.project_context_builder,
        )
        return handler.run()

    def _run_single(self, args: _ParsedArgs) -> int:
        """Run single-message mode."""
        handler = SingleMessageHandler(
            chat_service=self._container.chat_service,
            config_port=self._container.config_port,
        )

        conversation_id = args.conversation_id
        if conversation_id is None and not args.new_conversation:
            # Try to resume the project's last conversation
            conversation_id = self._container.config_port.get_project_conversation()

        return asyncio.run(
            handler.run(prompt=args.prompt, conversation_id=conversation_id)
        )

    @staticmethod
    def _parse_args(argv: List[str]) -> _ParsedArgs:
        """Parse command-line arguments without external dependencies.

        Supports:
          --conversation ID  : specify conversation ID
          --new              : force new conversation
          --debug            : enable debug output
          Remaining args joined as the prompt.
        """
        args = _ParsedArgs()
        i = 0

        while i < len(argv):
            arg = argv[i]

            if arg in ("--conversation", "-c") and i + 1 < len(argv):
                try:
                    args.conversation_id = int(argv[i + 1])
                except ValueError:
                    print(
                        f"Error: --conversation requiere un ID numerico, recibido: {argv[i + 1]}",
                        file=sys.stderr,
                    )
                    sys.exit(1)
                i += 2
                continue

            if arg in ("--new", "-n"):
                args.new_conversation = True
                i += 1
                continue

            if arg == "--debug":
                args.debug = True
                i += 1
                continue

            if arg == "--help":
                _print_help()
                sys.exit(0)

            # Everything else is part of the prompt
            args.prompt_parts.append(arg)
            i += 1

        if args.prompt_parts:
            args.prompt = " ".join(args.prompt_parts)

        return args


class _ParsedArgs:
    """Simple container for parsed CLI arguments."""

    def __init__(self) -> None:
        self.prompt: Optional[str] = None
        self.prompt_parts: List[str] = []
        self.conversation_id: Optional[int] = None
        self.new_conversation: bool = False
        self.debug: bool = False


def _print_help() -> None:
    """Print usage information."""
    print(
        """Turia Chat - CLI para el agente de IA

Uso:
  chat.py "mensaje"                    Enviar un mensaje al agente
  chat.py --conversation ID "mensaje"  Continuar una conversacion existente
  chat.py --new "mensaje"              Forzar nueva conversacion
  chat.py --debug "mensaje"            Habilitar modo debug
  chat.py                              Modo interactivo (REPL)

Opciones:
  --conversation, -c ID   ID de conversacion a continuar
  --new, -n               Iniciar nueva conversacion
  --debug                 Mostrar informacion de depuracion
  --help                  Mostrar esta ayuda""",
        file=sys.stderr,
    )
