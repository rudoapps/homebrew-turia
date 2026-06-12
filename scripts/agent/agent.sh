#!/bin/bash

# Agent CLI module for Turia
# Provides interaction with the Agentic AI server
#
# This is the main entry point that sources all agent modules:
#   - agent_config.sh     : Configuration and dependency management
#   - agent_ui.sh         : UI utilities (colors, spinners)
#   - agent_local_tools.sh: Local tool execution
#   - agent_auth.sh       : Authentication (login, logout, token refresh)
#   - agent_api.sh        : API communication (SSE, hybrid chat)
#   - agent_chat.sh       : Chat UI (single message, interactive mode)

# ============================================================================
# DEPENDENCY CHECK
# ============================================================================

check_dependencies() {
    local missing=()

    # Python3 is required for JSON parsing, SSE streaming, etc.
    if ! command -v python3 &> /dev/null; then
        missing+=("python3")
    fi

    # curl is required for API calls
    if ! command -v curl &> /dev/null; then
        missing+=("curl")
    fi

    # jq is optional but recommended (fallback to python for JSON)
    # if ! command -v jq &> /dev/null; then
    #     missing+=("jq")
    # fi

    if [ ${#missing[@]} -gt 0 ]; then
        echo ""
        echo -e "\033[1;31m❌ Error: Dependencias faltantes\033[0m"
        echo ""
        echo "El agente requiere las siguientes herramientas que no están instaladas:"
        echo ""
        for dep in "${missing[@]}"; do
            echo -e "  • \033[1m$dep\033[0m"
        done
        echo ""
        echo "Instalación:"
        if [[ "$OSTYPE" == "darwin"* ]]; then
            echo "  brew install ${missing[*]}"
        else
            echo "  sudo apt install ${missing[*]}  # Debian/Ubuntu"
            echo "  sudo dnf install ${missing[*]}  # Fedora"
        fi
        echo ""
        return 1
    fi
    return 0
}

# Run dependency check
if ! check_dependencies; then
    return 1 2>/dev/null || exit 1
fi

# ============================================================================
# MODULE LOADING
# ============================================================================

# Get script directory
AGENT_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load all modules in dependency order
source "$AGENT_SCRIPT_DIR/agent_config.sh"      # Configuration (must be first)
source "$AGENT_SCRIPT_DIR/agent_ui.sh"          # UI utilities
source "$AGENT_SCRIPT_DIR/agent_local_tools.sh" # Local tool execution
source "$AGENT_SCRIPT_DIR/agent_auth.sh"        # Authentication
source "$AGENT_SCRIPT_DIR/agent_rag.sh"         # RAG integration
source "$AGENT_SCRIPT_DIR/agent_api.sh"         # API communication
source "$AGENT_SCRIPT_DIR/agent_subagents.sh"   # Subagent management
source "$AGENT_SCRIPT_DIR/agent_chat.sh"        # Chat UI

# ============================================================================
# HELP
# ============================================================================

# Show agent help
show_agent_help() {
    echo ""
    echo -e "${BOLD}===============================================${NC}"
    echo -e "${BOLD}           TURIA - AGENTE AI                    ${NC}"
    echo -e "${BOLD}===============================================${NC}"
    echo ""
    echo -e "${BOLD}DESCRIPCION:${NC}"
    echo "  Interactua con el servidor de agentes AI desde la linea de comandos."
    echo ""
    echo -e "${BOLD}COMANDOS:${NC}"
    echo ""
    echo -e "  ${BOLD}turia setup${NC}"
    echo "      Instala las dependencias necesarias (glow, etc.)"
    echo ""
    echo -e "  ${BOLD}turia login${NC}"
    echo "      Inicia sesion abriendo el navegador para autenticacion"
    echo ""
    echo -e "  ${BOLD}turia logout${NC}"
    echo "      Cierra la sesion actual"
    echo ""
    echo -e "  ${BOLD}turia whoami${NC}"
    echo "      Muestra el estado de autenticacion"
    echo ""
    echo -e "  ${BOLD}turia chat${NC}"
    echo "      Inicia modo interactivo (como Claude Code)"
    echo "      Comandos en modo interactivo:"
    echo "        /exit, /quit, /q  - Salir del chat"
    echo "        /new              - Nueva conversacion"
    echo "        /continue, /c     - Continuar ultima conversacion"
    echo "        /cost             - Ver costo acumulado"
    echo "        /clear            - Limpiar pantalla"
    echo "        /help             - Mostrar ayuda"
    echo ""
    echo -e "  ${BOLD}turia chat \"mensaje\"${NC}"
    echo "      Envia un mensaje unico al agente AI"
    echo ""
    echo -e "  ${BOLD}turia chat --continue${NC}"
    echo "      Continua la ultima conversacion"
    echo ""
    echo -e "  ${BOLD}turia undo${NC}"
    echo "      Lista backups disponibles de archivos modificados"
    echo ""
    echo -e "  ${BOLD}turia undo <número>${NC}"
    echo "      Restaura un archivo desde un backup"
    echo ""
    echo -e "${BOLD}EJEMPLOS:${NC}"
    echo ""
    echo "  turia setup                    # Instalar dependencias"
    echo "  turia login                    # Iniciar sesion"
    echo "  turia chat                     # Modo interactivo"
    echo "  turia chat \"Hola\"              # Mensaje unico"
    echo "  turia chat --continue          # Continuar conversacion"
    echo "  turia undo                     # Ver backups disponibles"
    echo "  turia undo 1                   # Restaurar primer backup"
    echo ""
    echo -e "${BOLD}DEPENDENCIAS:${NC}"
    echo ""
    echo "  Requeridas: python3, curl"
    echo "  Opcionales: glow (renderizado de Markdown)"
    echo ""
    echo -e "${BOLD}CONFIGURACION:${NC}"
    echo ""
    echo "  Los tokens se guardan en: ~/.config/turia-agent/config.json"
    echo "  Para cambiar la URL del servidor, edita el archivo de configuracion"
    echo "  o usa la variable de entorno AGENT_API_URL"
    echo ""
    echo -e "${BOLD}===============================================${NC}"
}

# ============================================================================
# COMMAND DISPATCHER
# ============================================================================

# Main agent command dispatcher
agent_command() {
    local subcommand="${1:-help}"
    shift 2>/dev/null || true

    case "$subcommand" in
        setup)
            # Check for --reset flag
            if [[ "$1" == "--reset" ]]; then
                rm -f "$AGENT_SETUP_DONE_FILE"
                echo -e "${YELLOW}Setup reseteado. Ejecutando instalacion...${NC}"
                echo ""
            fi
            install_agent_dependencies
            ;;
        login)
            agent_login
            ;;
        logout)
            agent_logout
            ;;
        status|whoami)
            agent_status
            ;;
        chat)
            agent_chat "$@"
            ;;
        project)
            show_project_info
            ;;
        context)
            # Mostrar contexto JSON que se enviaria al servidor
            generate_project_context | python3 -m json.tool
            ;;
        rag)
            # Verificar autenticacion antes de consultar RAG (gate propio de turia)
            if ! ensure_agent_login; then
                echo -e "${RED}Login fallido. No se puede consultar RAG.${NC}"
                return 1
            fi

            # Mostrar estado de RAG para el proyecto actual
            show_rag_status
            ;;
        conversations|conv)
            agent_conversations
            ;;
        undo)
            # Undo/restore from backups
            if [[ "$1" == "list" ]]; then
                list_file_backups
            elif [[ "$1" =~ ^[0-9]+$ ]]; then
                restore_from_backup "$1"
            else
                # Default: restore most recent backup
                list_file_backups
                echo ""
                echo -e "${BOLD}Para restaurar un backup:${NC} turia undo <número>"
                echo -e "${DIM}Ejemplo: turia undo 1${NC}"
                echo ""
            fi
            ;;
        help|--help|-h)
            show_agent_help
            ;;
        *)
            echo -e "${RED}Comando desconocido: $subcommand${NC}"
            echo -e "Usa ${YELLOW}turia agent help${NC} para ver los comandos disponibles"
            return 1
            ;;
    esac
}
