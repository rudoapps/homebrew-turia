#!/bin/bash

# Agent Chat Module
# Handles chat UI, interactive mode, and conversations

# ============================================================================
# COST / NUMBER FORMATTING HELPERS
# ============================================================================

# Format cost value with appropriate decimal places
# Usage: format_cost "0.001234"
format_cost() {
    local cost="${1:-0}"
    echo "$cost" | awk '{
        if ($1 >= 0.01) printf "%.2f\n", $1
        else if ($1 >= 0.001) printf "%.4f\n", $1
        else { s = sprintf("%.6f", $1); gsub(/0+$/, "", s); gsub(/\.$/, "", s); print s }
    }'
}

# ============================================================================
# ERROR FORMATTING
# ============================================================================

# Display formatted error with cause and solutions
# Usage: show_formatted_error "title" "cause" "solution1" "solution2" ...
show_formatted_error() {
    local title="$1"
    local cause="$2"
    shift 2
    local solutions=("$@")

    echo ""
    echo -e "${RED}┌─${NC} ${RED}✗ Error${NC} ${RED}─────────────────────────────────────────${NC}"
    echo -e "${RED}│${NC}"
    echo -e "${RED}│${NC}  ${BOLD}${title}${NC}"

    if [ -n "$cause" ]; then
        echo -e "${RED}│${NC}"
        echo -e "${RED}│${NC}  ${DIM}Causa:${NC} ${cause}"
    fi

    if [ ${#solutions[@]} -gt 0 ]; then
        echo -e "${RED}│${NC}"
        echo -e "${RED}│${NC}  ${YELLOW}💡 Soluciones:${NC}"
        for solution in "${solutions[@]}"; do
            echo -e "${RED}│${NC}     ${DIM}•${NC} ${solution}"
        done
    fi

    echo -e "${RED}│${NC}"
    echo -e "${RED}└─────────────────────────────────────────────────${NC}"
    echo ""
}

# ============================================================================
# MULTI-LINE INPUT
# ============================================================================

# Read multi-line input with readline support for keyboard shortcuts
# Supports:
# - Ctrl+A: Go to start of line
# - Ctrl+E: Go to end of line
# - Ctrl+W: Delete word backward
# - Ctrl+K: Delete to end of line
# - Ctrl+U: Delete to start of line
# - Arrow keys: Move cursor / navigate history
# - Single line: press Enter to submit
# - Multi-line: type \ at end of line to continue, or Enter twice to submit
read_multiline_input() {
    local lines=()
    local line=""

    # Show prompt
    echo -ne "${CYAN}›${NC} " >&2

    # Read first line with readline support
    if ! IFS= read -e -r line; then
        echo ""
        return
    fi

    # Empty first line - return empty
    if [ -z "$line" ]; then
        echo ""
        return
    fi

    # Check for backslash continuation on first line
    if [[ "$line" == *"\\" ]]; then
        line="${line%\\}"
        lines+=("$line")
        # Explicit multi-line mode with backslash
        while true; do
            echo -ne "${DIM}  ...${NC} " >&2
            if ! IFS= read -e -r line; then
                break
            fi
            if [ -z "$line" ]; then
                break
            fi
            if [[ "$line" == *"\\" ]]; then
                line="${line%\\}"
                lines+=("$line")
                continue
            fi
            lines+=("$line")
            break
        done
    else
        lines+=("$line")

        # Paste detection: check if more data is available on stdin immediately.
        # Pasted text arrives all at once, so data is buffered.
        # Typed text won't have anything in the buffer after Enter.
        local extra_lines
        extra_lines=$(python3 -c "
import sys, select
lines = []
while select.select([sys.stdin], [], [], 0.05)[0]:
    line = sys.stdin.readline()
    if not line:
        break
    lines.append(line.rstrip('\n').replace('\x1b[200~','').replace('\x1b[201~',''))
for l in lines:
    print(l)
" 2>/dev/null)
        if [ -n "$extra_lines" ]; then
            while IFS= read -r line; do
                lines+=("$line")
            done <<< "$extra_lines"
        fi

        # If we captured multiple lines (paste detected), show them
        if [ ${#lines[@]} -gt 1 ]; then
            local paste_count=$((${#lines[@]} - 1))
            echo -e "${DIM}  ... (+${paste_count} líneas pegadas)${NC}" >&2
        fi
    fi

    # Join lines with newlines
    local result=""
    local first=true
    for l in "${lines[@]}"; do
        if [ "$first" = true ]; then
            result="$l"
            first=false
        else
            result="$result"$'\n'"$l"
        fi
    done

    echo "$result"
}

# ============================================================================
# TYPING INDICATOR (Spinner)
# ============================================================================

# PID del proceso de spinner (global para poder matarlo)
TYPING_INDICATOR_PID=""

# Mostrar indicador de typing (spinner animado)
# Ejecutar en background: show_typing_indicator &
show_typing_indicator() {
    local message="${1:-Pensando...}"
    local frames=("⠋" "⠙" "⠹" "⠸" "⠼" "⠴" "⠦" "⠧" "⠇" "⠏")
    local i=0
    local start_time=$(date +%s)

    # Ocultar cursor
    printf "\033[?25l" >&2

    while true; do
        local elapsed=$(($(date +%s) - start_time))
        printf "\r\033[2K  \033[0;36m${frames[$i]}\033[0m %s \033[2m(%ds)\033[0m" "$message" "$elapsed" >&2
        i=$(( (i + 1) % 10 ))
        sleep 0.08
    done
}

# Detener indicador de typing
stop_typing_indicator() {
    if [ -n "$TYPING_INDICATOR_PID" ]; then
        kill "$TYPING_INDICATOR_PID" 2>/dev/null
        wait "$TYPING_INDICATOR_PID" 2>/dev/null
        TYPING_INDICATOR_PID=""
    fi
    # Limpiar línea y mostrar cursor
    printf "\r\033[2K\033[?25h" >&2
}

# Asegurar que el spinner se detenga y cursor se restaure al salir (Ctrl+C, etc.)
cleanup_on_exit() {
    stop_typing_indicator
    # Always ensure cursor is visible
    printf "\033[?25h" >&2
}
trap 'cleanup_on_exit' EXIT INT TERM

# ============================================================================
# INTERACTIVE SELECTOR
# ============================================================================

# Interactive option selector with arrow keys
# Usage: selected=$(interactive_select "Pregunta?" "Opción 1" "Opción 2" "Opción 3")
# Returns: the selected option text
interactive_select() {
    local prompt="$1"
    shift
    local options=("$@")

    python3 - "$prompt" "${options[@]}" << 'PYEOF'
import sys
import tty
import termios

# Colors
BOLD = "\033[1m"
DIM = "\033[2m"
NC = "\033[0m"
CYAN = "\033[0;36m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"

# Cursor control
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"
CLEAR_LINE = "\033[2K"
MOVE_UP = "\033[A"

# Use /dev/tty for keyboard input (stdin may be redirected)
import select
try:
    tty_file = open('/dev/tty', 'r')
    # Drain any buffered input (leftover enter key, etc.)
    fd = tty_file.fileno()
    old = termios.tcgetattr(fd)
    tty.setraw(fd)
    while select.select([tty_file], [], [], 0)[0]:
        tty_file.read(1)
    termios.tcsetattr(fd, termios.TCSADRAIN, old)
except OSError:
    # Fallback: no TTY available, return first option
    print(sys.argv[2] if len(sys.argv) > 2 else "")
    sys.exit(0)

_original_settings = termios.tcgetattr(tty_file.fileno())

import signal, atexit

def _restore_terminal():
    try:
        termios.tcsetattr(tty_file.fileno(), termios.TCSADRAIN, _original_settings)
        sys.stderr.write(SHOW_CURSOR)
        sys.stderr.flush()
    except:
        pass

atexit.register(_restore_terminal)
signal.signal(signal.SIGTERM, lambda *_: (_restore_terminal(), sys.exit(1)))

def get_key():
    """Read a single keypress. Terminal must already be in raw mode."""
    ch = tty_file.read(1)
    if ch == '\x1b':  # Escape sequence
        ch2 = tty_file.read(1)
        if ch2 == '[':
            ch3 = tty_file.read(1)
            if ch3 == 'A': return 'up'
            if ch3 == 'B': return 'down'
        return 'esc'
    if ch in ('\r', '\n'): return 'enter'
    if ch == '\x03': return 'ctrl-c'  # Ctrl+C
    return ch

def render(prompt, options, selected_idx, first_render=False):
    """Render the selector."""
    # Move up to clear previous render (except first time)
    if not first_render:
        # Move up: 1 for prompt + number of options
        for _ in range(len(options) + 1):
            sys.stderr.write(f"{MOVE_UP}{CLEAR_LINE}")

    # Print prompt
    sys.stderr.write(f"{BOLD}{prompt}{NC}\n")

    # Print options
    for i, opt in enumerate(options):
        if i == selected_idx:
            sys.stderr.write(f"  {GREEN}❯{NC} {BOLD}{opt}{NC}\n")
        else:
            sys.stderr.write(f"    {DIM}{opt}{NC}\n")

    sys.stderr.flush()

# Get arguments
prompt = sys.argv[1]
options = sys.argv[2:]

if not options:
    print("")
    sys.exit(1)

selected_idx = 0

# Hide cursor
sys.stderr.write(HIDE_CURSOR)
sys.stderr.flush()

try:
    # Set raw mode ONCE for the entire selection loop
    tty.setraw(tty_file.fileno())

    render(prompt, options, selected_idx, first_render=True)

    while True:
        key = get_key()

        if key == 'up':
            selected_idx = (selected_idx - 1) % len(options)
            render(prompt, options, selected_idx)
        elif key == 'down':
            selected_idx = (selected_idx + 1) % len(options)
            render(prompt, options, selected_idx)
        elif key == 'enter':
            break
        elif key in ('esc', 'ctrl-c', 'q'):
            selected_idx = -1
            break

finally:
    # Restore terminal settings ONCE at the end
    termios.tcsetattr(tty_file.fileno(), termios.TCSADRAIN, _original_settings)
    sys.stderr.write(SHOW_CURSOR)
    sys.stderr.flush()
    tty_file.close()

# Output selected option
if selected_idx >= 0 and selected_idx < len(options):
    print(options[selected_idx])
else:
    print("")
PYEOF
}

# ============================================================================
# RESPONSE DISPLAY
# ============================================================================

# Display response with markdown rendering
display_response() {
    local text_response="$1"
    local model_name="${2:-}"

    echo ""
    # Response header with model info
    if [ -n "$model_name" ]; then
        echo -e "${DIM}╭─${NC} ${BOLD}Agent${NC} ${DIM}($model_name) ────────────────────────────────────────────╮${NC}"
    else
        echo -e "${DIM}╭─${NC} ${BOLD}Agent${NC} ${DIM}─────────────────────────────────────────────────────────╮${NC}"
    fi
    echo ""

    # Render markdown with glow if available
    if command -v glow &> /dev/null; then
        echo "$text_response" | glow -s dark -w 80 -
    else
        # Simple markdown to ANSI conversion
        echo "$text_response" | python3 -c "
import sys
import re

text = sys.stdin.read()

# Bold: **text** or __text__
text = re.sub(r'\*\*(.+?)\*\*', '\033[1m\\1\033[0m', text)
text = re.sub(r'__(.+?)__', '\033[1m\\1\033[0m', text)

# Inline code: \`code\`
text = re.sub(r'\`([^\`]+)\`', '\033[36m\\1\033[0m', text)

# Headers
text = re.sub(r'^### (.+)$', '\033[1;35m\\1\033[0m', text, flags=re.MULTILINE)
text = re.sub(r'^## (.+)$', '\033[1;34m\\1\033[0m', text, flags=re.MULTILINE)
text = re.sub(r'^# (.+)$', '\033[1;33m\\1\033[0m', text, flags=re.MULTILINE)

# Bullet points
text = re.sub(r'^(\s*)[-*] ', r'\\1• ', text, flags=re.MULTILINE)

# Numbered lists
text = re.sub(r'^(\s*)(\d+)\. ', r'\\1\033[33m\\2.\033[0m ', text, flags=re.MULTILINE)

print(text)
"
    fi
}

# Display summary after response
display_summary() {
    local tokens="$1"
    local cost="$2"
    local elapsed="$3"
    local tools_count="$4"
    local conv_id="$5"

    echo ""

    # Build summary line with separators
    local summary_parts=""

    # Tools indicator
    if [ "$tools_count" -gt 0 ] 2>/dev/null; then
        summary_parts="${GREEN}✓${NC} ${tools_count} tools"
    fi

    # Stats
    [ -n "$tokens" ] && [ "$tokens" != "0" ] && summary_parts="$summary_parts · ${tokens} tokens"
    if [ -n "$cost" ]; then
        local cost_fmt=$(format_cost "$cost")
        summary_parts="$summary_parts · \$$cost_fmt"
    fi
    [ -n "$elapsed" ] && [ "$elapsed" != "0" ] && summary_parts="$summary_parts · ${elapsed}s"

    # Remove leading separator if no tools
    summary_parts="${summary_parts# · }"

    # Display in box
    echo -e "${DIM}┌──────────────────────────────────────────────────────────────┐${NC}"
    echo -e "${DIM}│${NC}  $summary_parts"
    echo -e "${DIM}└──────────────────────────────────────────────────────────────┘${NC}"
}

# ============================================================================
# SINGLE MESSAGE CHAT
# ============================================================================

# Agent chat - single message mode
agent_chat_single() {
    local prompt="$1"

    show_project_info
    echo ""

    # Mostrar indicador de typing inmediatamente
    show_typing_indicator "Pensando..." &
    TYPING_INDICATOR_PID=$!
    disown $TYPING_INDICATOR_PID 2>/dev/null  # Evitar mensaje "Killed" al terminar
    # Exportar PID para que send_chat_hybrid pueda detenerlo
    export TURIA_TYPING_PID=$TYPING_INDICATOR_PID

    local response run_status
    # Temporarily disable errexit to capture non-zero return codes
    set +e
    response=$(run_hybrid_chat "$prompt" "")
    run_status=$?
    set -e

    # Asegurar que el typing indicator esté detenido
    stop_typing_indicator
    unset TURIA_TYPING_PID

    # Handle auth errors - try refresh first, then prompt for login
    if [ $run_status -eq 2 ]; then
        if handle_auth_error; then
            echo -e "${BOLD}Reintentando...${NC}"
            set +e
            response=$(run_hybrid_chat "$prompt" "")
            run_status=$?
            set -e
        else
            return 1
        fi
    fi

    # Check for other errors
    local error=$(json_get_error "$response")

    if [ -n "$error" ] && [ "$error" != "None" ]; then
        echo -e "${RED}Error: $error${NC}"
        return 1
    fi

    # Check if conversation was repaired (interrupted session)
    if json_is_true "$response" "repaired"; then
        echo ""
        echo -e "  ${YELLOW}⚠️  La conversacion estaba interrumpida y fue recuperada.${NC}"
        echo -e "  ${DIM}Puedes continuar escribiendo tu siguiente mensaje.${NC}"
        echo ""
        return 0
    fi

    # Extract response data
    local text_response=$(json_get "$response" "response")
    last_response="$text_response"  # Store for /copy command
    local conv_id=$(json_get "$response" "conversation_id")
    local cost=$(json_get_num "$response" "total_cost")
    local elapsed=$(json_get_num "$response" "elapsed_time")
    local tokens=$(json_get_num "$response" "total_tokens")
    local tools_count=$(json_get_num "$response" "tools_count")
    local total_elapsed=$(json_get_num "$response" "total_elapsed")
    local text_streamed=$(json_get "$response" "text_streamed")

    # Use total_elapsed if available (includes tool execution time)
    [ -n "$total_elapsed" ] && [ "$total_elapsed" != "0" ] && elapsed="$total_elapsed"

    # Display response (skip if already streamed)
    # Note: Python json outputs lowercase "true"
    if [ "$text_streamed" != "True" ] && [ "$text_streamed" != "true" ]; then
        display_response "$text_response"
    fi
    display_summary "$tokens" "$cost" "$elapsed" "$tools_count" "$conv_id"
}

# ============================================================================
# INTERACTIVE MODE
# ============================================================================

# Interactive chat mode
agent_chat_interactive() {
    local conversation_id=""
    local total_cost=0
    local last_response=""  # Store last response for /copy command

    # Export terminal width for subprocesses (subshells lose tty access)
    export COLUMNS=$(stty size < /dev/tty 2>/dev/null | awk '{print $2}' || tput cols 2>/dev/null || echo 80)

    # Try to recover last conversation for this project
    local saved_conv_id=$(get_project_conversation)

    echo ""

    # Header line: 📁 folder · ↩ #conv · /new nueva · /help comandos
    local project_name=$(basename "$PWD")
    local header_line="📁 ${BOLD}$project_name${NC}"
    if [ -n "$saved_conv_id" ]; then
        conversation_id="$saved_conv_id"
        header_line="$header_line ${DIM}·${NC} ${DIM}↩${NC} #$conversation_id"
    fi
    header_line="$header_line ${DIM}·${NC} ${WHITE}/new${NC} ${DIM}nueva${NC} ${DIM}·${NC} ${WHITE}/help${NC} ${DIM}comandos${NC}"
    echo -e "$header_line"

    # Build status bar
    local status_parts=""

    # RAG status
    local rag_git_url=$(get_rag_git_url 2>/dev/null)
    if [ -n "$rag_git_url" ]; then
        local rag_response=$(check_rag_index 2>/dev/null)
        local rag_status=$(json_get "$rag_response" "status")
        case "$rag_status" in
            "ready")
                status_parts="${GREEN}●${NC} RAG"
                ;;
            "pending")
                status_parts="${YELLOW}○${NC} RAG ${DIM}pendiente${NC}"
                ;;
            "indexing")
                status_parts="${CYAN}◐${NC} RAG ${DIM}indexando${NC}"
                ;;
            *)
                status_parts="${DIM}○ RAG${NC}"
                ;;
        esac
    else
        status_parts="${DIM}○ RAG${NC}"
    fi

    # Quota/Presupuesto status
    local quota_str=$(get_quota_status_inline)
    if [ -n "$quota_str" ]; then
        status_parts="$status_parts  │  $quota_str"
    fi

    echo -e "${DIM}───────────────────────────────────────────────────────────────${NC}"
    echo -e " $status_parts"
    echo -e "${DIM}───────────────────────────────────────────────────────────────${NC}"

    while true; do
        # Refresh terminal width on each iteration (handles resizes)
        export COLUMNS=$(stty size < /dev/tty 2>/dev/null | awk '{print $2}' || echo "${COLUMNS:-80}")

        # Read multi-line input
        local user_input
        user_input=$(read_multiline_input)

        # Handle empty input
        if [ -z "$user_input" ]; then
            continue
        fi

        # Check for clipboard image (only on macOS for now)
        if [[ "$OSTYPE" == "darwin"* ]] && has_clipboard_image; then
            echo ""
            echo -e "${CYAN}📋 Imagen detectada en el clipboard${NC}"
            echo -n -e "${DIM}¿Incluir en el mensaje? (s/n): ${NC}"
            local include_clipboard
            read -n 1 include_clipboard < /dev/tty 2>/dev/null
            echo ""

            if [[ "$include_clipboard" =~ ^[sS]$ ]]; then
                echo -e "${DIM}Incluyendo imagen del clipboard...${NC}"
                # Note: La imagen se enviará automáticamente por el código existente de detect_and_encode_images
                # Solo agregamos un placeholder en el texto para indicarlo
                user_input="$user_input

[Imagen del clipboard incluida]"
                echo -e "${GREEN}✓${NC} Imagen del clipboard agregada"
                echo ""
            else
                echo -e "${DIM}Imagen ignorada${NC}"
                echo ""
            fi
        fi

        # Handle special commands
        case "$user_input" in
            /exit|/quit|/q)
                echo ""
                echo -e "${YELLOW}Saliendo del chat...${NC}"
                if [ -n "$conversation_id" ]; then
                    echo -e "Conversacion ID: ${BOLD}$conversation_id${NC}"
                fi
                # Format cost with appropriate precision (use Python for locale-independent formatting)
                local exit_cost_fmt=$(python3 -c "
cost = float('${total_cost:-0}')
if cost >= 0.01:
    fmt = f'{cost:.2f}'
elif cost >= 0.001:
    fmt = f'{cost:.4f}'
else:
    fmt = f'{cost:.6f}'.rstrip('0').rstrip('.')
print(fmt)
" 2>/dev/null || echo "$total_cost")
                echo -e "Costo total de la sesion: ${BOLD}\$${exit_cost_fmt}${NC}"
                echo -e "${GREEN}Hasta luego!${NC}"
                echo ""
                return 0
                ;;
            /new)
                conversation_id=""
                clear_project_conversation
                echo -e "${YELLOW}Nueva conversacion iniciada.${NC}"
                echo ""
                continue
                ;;
            /cost)
                local cost_cmd_fmt=$(python3 -c "
cost = float('${total_cost:-0}')
if cost >= 0.01:
    fmt = f'{cost:.2f}'
elif cost >= 0.001:
    fmt = f'{cost:.4f}'
else:
    fmt = f'{cost:.6f}'.rstrip('0').rstrip('.')
print(fmt)
" 2>/dev/null || echo "$total_cost")
                echo -e "Costo acumulado: ${BOLD}\$${cost_cmd_fmt}${NC}"
                if [ -n "$conversation_id" ]; then
                    echo -e "Conversacion actual: ${BOLD}$conversation_id${NC}"
                fi
                echo ""
                continue
                ;;
            /copy)
                # Copy last response to clipboard
                if [ -z "$last_response" ]; then
                    echo -e "${YELLOW}No hay respuesta para copiar${NC}"
                    echo -e "${DIM}Primero haz una pregunta al agente${NC}"
                    echo ""
                else
                    if [[ "$OSTYPE" == "darwin"* ]]; then
                        # macOS
                        echo "$last_response" | pbcopy
                        local char_count=${#last_response}
                        echo -e "${GREEN}✓${NC} Respuesta copiada al clipboard ${DIM}($char_count caracteres)${NC}"
                    elif command -v xclip &> /dev/null; then
                        # Linux con xclip
                        echo "$last_response" | xclip -selection clipboard
                        local char_count=${#last_response}
                        echo -e "${GREEN}✓${NC} Respuesta copiada al clipboard ${DIM}($char_count caracteres)${NC}"
                    else
                        echo -e "${YELLOW}Clipboard no soportado en este sistema${NC}"
                        echo -e "${DIM}Instala xclip: sudo apt-get install xclip${NC}"
                    fi
                    echo ""
                fi
                continue
                ;;
            /clear)
                clear
                echo -e "${BOLD}TURIA AGENT - Chat Interactivo${NC}"
                echo -e "${BOLD}───────────────────────────────────────────────────────────────${NC}"
                echo ""
                continue
                ;;
            /undo)
                # Show backups and restore most recent
                list_file_backups
                echo -e "${DIM}Usa /undo <n> para restaurar un backup específico${NC}"
                echo ""
                continue
                ;;
            /undo\ *)
                local undo_num="${user_input#/undo }"
                if [[ "$undo_num" =~ ^[0-9]+$ ]]; then
                    restore_from_backup "$undo_num"
                else
                    echo -e "${RED}Uso: /undo <número>${NC}"
                fi
                echo ""
                continue
                ;;
            /diff)
                # Show diff of all files modified in session (using backups)
                if [ ! -d "$AGENT_UNDO_DIR" ]; then
                    echo -e "${DIM}No hay cambios en esta sesión${NC}"
                    echo ""
                    continue
                fi
                local has_diffs=false
                local seen_files=""
                for meta in $(ls -t "$AGENT_UNDO_DIR"/*.meta 2>/dev/null); do
                    local orig=$(python3 -c "import json; print(json.load(open('$meta'))['original_path'])" 2>/dev/null)
                    # Skip if already shown this file (show only oldest backup vs current)
                    if [[ "$seen_files" == *"|$orig|"* ]]; then
                        continue
                    fi
                    seen_files="${seen_files}|$orig|"
                    local bak="${meta%.meta}.bak"
                    if [ -f "$orig" ] && [ -f "$bak" ]; then
                        local diff_output=$(diff -u "$bak" "$orig" 2>/dev/null)
                        if [ -n "$diff_output" ]; then
                            has_diffs=true
                            local added=$(echo "$diff_output" | grep -c "^+" || true)
                            local removed=$(echo "$diff_output" | grep -c "^-" || true)
                            echo -e "  ${BOLD}$(basename "$orig")${NC} ${GREEN}+$added${NC} ${RED}-$removed${NC}"
                            echo "$diff_output" | tail -n +4 | head -30 | while IFS= read -r line; do
                                if [[ "$line" == +* ]]; then
                                    echo -e "  ${GREEN}$line${NC}"
                                elif [[ "$line" == -* ]]; then
                                    echo -e "  ${RED}$line${NC}"
                                else
                                    echo -e "  ${DIM}$line${NC}"
                                fi
                            done
                            echo ""
                        fi
                    fi
                done
                if [ "$has_diffs" = false ]; then
                    echo -e "${DIM}No hay cambios en esta sesión${NC}"
                fi
                echo ""
                continue
                ;;
            /help)
                echo ""
                echo -e "${BOLD}Comandos disponibles:${NC}"
                echo -e "  ${YELLOW}/exit${NC}, ${YELLOW}/quit${NC}, ${YELLOW}/q${NC}  - Salir del chat"
                echo -e "  ${YELLOW}/new${NC}               - Iniciar nueva conversacion"
                echo -e "  ${YELLOW}/resume <id>${NC}       - Retomar conversacion por ID"
                echo -e "  ${YELLOW}/cost${NC}              - Ver costo acumulado de la sesion"
                echo -e "  ${YELLOW}/presupuesto${NC}       - Ver limite y uso mensual"
                echo -e "  ${YELLOW}/copy${NC}              - Copiar ultima respuesta al clipboard"
                echo -e "  ${YELLOW}/undo${NC}              - Ver/restaurar backups de archivos"
                echo -e "  ${YELLOW}/diff${NC}              - Ver cambios del agente en esta sesion"
                echo -e "  ${YELLOW}/clear${NC}             - Limpiar pantalla"
                echo -e "  ${YELLOW}/help${NC}              - Mostrar esta ayuda"
                echo -e "  ${YELLOW}/debug${NC}             - Activar/desactivar modo debug"
                echo -e "  ${YELLOW}/preview [on|off]${NC}  - Activar/desactivar preview de cambios"
                echo ""
                echo -e "${BOLD}Modelos:${NC}"
                echo -e "  ${YELLOW}/models${NC}            - Ver modelos disponibles"
                echo -e "  ${YELLOW}/model <id>${NC}        - Cambiar modelo (ej: /model sonnet)"
                echo -e "  ${YELLOW}/model auto${NC}        - Usar routing automatico"
                echo ""
                echo -e "${BOLD}Subagentes:${NC}"
                echo -e "  ${YELLOW}/subagents${NC}         - Listar subagentes disponibles"
                echo -e "  ${YELLOW}/subagent <id> <msg>${NC} - Invocar un subagente especifico"
                echo ""
                echo -e "${BOLD}Atajos de subagentes:${NC}"
                echo -e "  ${YELLOW}/review <archivo>${NC}   - Revisar codigo (code-review)"
                echo -e "  ${YELLOW}/test <archivo>${NC}     - Generar tests (test-generator)"
                echo -e "  ${YELLOW}/explain <archivo>${NC}  - Explicar codigo (explainer)"
                echo -e "  ${YELLOW}/refactor <archivo>${NC} - Sugerir refactorizaciones (refactor)"
                echo -e "  ${YELLOW}/document <archivo>${NC} - Generar documentacion (documenter)"
                echo -e "  ${YELLOW}/debug <error>${NC}      - Ayudar a debuggear (debugger)"
                echo ""
                echo -e "${BOLD}Referencias a archivos:${NC}"
                echo -e "  - Usa ${YELLOW}@archivo.swift${NC} para adjuntar un archivo al mensaje"
                echo -e "    ${DIM}refactoriza @HealthContainer.swift${NC}"
                echo ""
                echo -e "${BOLD}Entrada multi-linea:${NC}"
                echo -e "  - Escribe \\ al final de una linea para continuar"
                echo -e "  - Al pegar texto, presiona Enter dos veces para enviar"
                echo ""
                echo -e "${BOLD}Imagenes:${NC}"
                echo -e "  - Incluye rutas de imagenes en tu mensaje:"
                echo -e "    ${DIM}Que ves en ~/Desktop/screenshot.png?${NC}"
                echo ""
                continue
                ;;
            /quota|/presupuesto)
                fetch_and_show_quota
                continue
                ;;
            /models)
                show_available_models
                continue
                ;;
            /model)
                # Show current model
                local current=$(get_agent_config "preferred_model")
                if [ -n "$current" ] && [ "$current" != "null" ]; then
                    echo -e "Modelo actual: ${BOLD}$current${NC}"
                else
                    echo -e "Modelo actual: ${DIM}auto (routing automatico)${NC}"
                fi
                echo -e "${DIM}Usa /models para ver opciones disponibles${NC}"
                echo ""
                continue
                ;;
            /model\ *)
                # Change model
                local new_model="${user_input#/model }"
                if [ "$new_model" = "auto" ] || [ "$new_model" = "default" ]; then
                    set_agent_config "preferred_model" "null"
                    echo -e "${GREEN}✓${NC} Modelo: ${BOLD}auto${NC} (routing automatico)"
                    echo -e "${DIM}El sistema elegira el modelo segun el tipo de tarea${NC}"
                else
                    set_agent_config "preferred_model" "$new_model"
                    echo -e "${GREEN}✓${NC} Modelo cambiado a: ${BOLD}$new_model${NC}"
                    echo -e "${DIM}Todas las siguientes peticiones usaran este modelo${NC}"
                fi
                echo ""
                continue
                ;;
            /resume\ *)
                local resume_id="${user_input#/resume }"
                if [[ "$resume_id" =~ ^[0-9]+$ ]]; then
                    conversation_id="$resume_id"
                    echo -e "${GREEN}Conversacion #$conversation_id retomada.${NC}"
                    echo -e "${DIM}Escribe tu mensaje para continuar.${NC}"
                else
                    echo -e "${RED}ID de conversacion invalido: $resume_id${NC}"
                    echo -e "Uso: ${YELLOW}/resume 123${NC}"
                fi
                echo ""
                continue
                ;;
            /subagents)
                show_available_subagents
                continue
                ;;
            /review\ *)
                # Code review subagent shortcut
                local review_msg="${user_input#/review }"
                if [ -z "$review_msg" ] || [ "$review_msg" = "/review" ]; then
                    echo -e "${RED}Uso: /review <archivo o mensaje>${NC}"
                    echo -e "Ejemplo: ${DIM}/review src/auth.py${NC}"
                    echo ""
                    continue
                fi
                local new_conv_id
                new_conv_id=$(invoke_subagent_in_chat "code-review" "$review_msg" "$conversation_id")
                if [ -z "$conversation_id" ] && [ -n "$new_conv_id" ] && [ "$new_conv_id" != "None" ]; then
                    conversation_id="$new_conv_id"
                fi
                echo ""
                continue
                ;;
            /test\ *)
                # Test generator subagent shortcut
                local test_msg="${user_input#/test }"
                if [ -z "$test_msg" ] || [ "$test_msg" = "/test" ]; then
                    echo -e "${RED}Uso: /test <archivo o mensaje>${NC}"
                    echo -e "Ejemplo: ${DIM}/test src/utils.py${NC}"
                    echo ""
                    continue
                fi
                local new_conv_id
                new_conv_id=$(invoke_subagent_in_chat "test-generator" "$test_msg" "$conversation_id")
                if [ -z "$conversation_id" ] && [ -n "$new_conv_id" ] && [ "$new_conv_id" != "None" ]; then
                    conversation_id="$new_conv_id"
                fi
                echo ""
                continue
                ;;
            /explain\ *)
                # Code explainer subagent shortcut
                local explain_msg="${user_input#/explain }"
                if [ -z "$explain_msg" ] || [ "$explain_msg" = "/explain" ]; then
                    echo -e "${RED}Uso: /explain <archivo o mensaje>${NC}"
                    echo -e "Ejemplo: ${DIM}/explain src/database.py${NC}"
                    echo ""
                    continue
                fi
                local new_conv_id
                new_conv_id=$(invoke_subagent_in_chat "explainer" "$explain_msg" "$conversation_id")
                if [ -z "$conversation_id" ] && [ -n "$new_conv_id" ] && [ "$new_conv_id" != "None" ]; then
                    conversation_id="$new_conv_id"
                fi
                echo ""
                continue
                ;;
            /refactor\ *)
                # Refactor assistant subagent shortcut
                local refactor_msg="${user_input#/refactor }"
                if [ -z "$refactor_msg" ] || [ "$refactor_msg" = "/refactor" ]; then
                    echo -e "${RED}Uso: /refactor <archivo o mensaje>${NC}"
                    echo -e "Ejemplo: ${DIM}/refactor src/legacy.py${NC}"
                    echo ""
                    continue
                fi
                local new_conv_id
                new_conv_id=$(invoke_subagent_in_chat "refactor" "$refactor_msg" "$conversation_id")
                if [ -z "$conversation_id" ] && [ -n "$new_conv_id" ] && [ "$new_conv_id" != "None" ]; then
                    conversation_id="$new_conv_id"
                fi
                echo ""
                continue
                ;;
            /document\ *)
                # Documenter subagent shortcut
                local doc_msg="${user_input#/document }"
                if [ -z "$doc_msg" ] || [ "$doc_msg" = "/document" ]; then
                    echo -e "${RED}Uso: /document <archivo o mensaje>${NC}"
                    echo -e "Ejemplo: ${DIM}/document src/api.py${NC}"
                    echo ""
                    continue
                fi
                local new_conv_id
                new_conv_id=$(invoke_subagent_in_chat "documenter" "$doc_msg" "$conversation_id")
                if [ -z "$conversation_id" ] && [ -n "$new_conv_id" ] && [ "$new_conv_id" != "None" ]; then
                    conversation_id="$new_conv_id"
                fi
                echo ""
                continue
                ;;
            /preview*)
                # Toggle preview mode for file changes
                local preview_arg="${user_input#/preview}"
                preview_arg="${preview_arg# }"  # Remove leading space

                if [ -z "$preview_arg" ] || [ "$preview_arg" = "toggle" ]; then
                    # Toggle preview mode
                    local current_preview=$(get_agent_config "preview_mode")
                    if [ "$current_preview" = "false" ]; then
                        set_agent_config "preview_mode" "true"
                        echo -e "${GREEN}✓ Preview mode activado${NC}"
                        echo -e "${DIM}Verás una vista previa antes de que el agente modifique archivos${NC}"
                    else
                        set_agent_config "preview_mode" "false"
                        echo -e "${YELLOW}Preview mode desactivado${NC}"
                        echo -e "${DIM}Los cambios se aplicarán sin confirmación (no recomendado)${NC}"
                    fi
                elif [ "$preview_arg" = "on" ]; then
                    set_agent_config "preview_mode" "true"
                    echo -e "${GREEN}✓ Preview mode activado${NC}"
                elif [ "$preview_arg" = "off" ]; then
                    set_agent_config "preview_mode" "false"
                    echo -e "${YELLOW}Preview mode desactivado${NC}"
                else
                    echo -e "${RED}Uso: /preview [on|off]${NC}"
                    echo -e "Ejemplo: ${DIM}/preview on${NC}"
                fi
                echo ""
                continue
                ;;
            /debug*)
                # Handle both /debug (toggle) and /debug <msg> (subagent)
                local debug_arg="${user_input#/debug}"
                debug_arg="${debug_arg# }"  # Remove leading space

                if [ -z "$debug_arg" ]; then
                    # Just "/debug" - toggle debug mode
                    local current_debug=$(get_agent_config "debug_mode")
                    if [ "$current_debug" = "true" ]; then
                        set_agent_config "debug_mode" "false"
                        echo -e "${YELLOW}Debug mode desactivado${NC}"
                    else
                        set_agent_config "debug_mode" "true"
                        echo -e "${GREEN}Debug mode activado${NC}"
                        echo -e "${DIM}Verás información de diagnóstico en las peticiones${NC}"
                    fi
                    echo ""
                else
                    # "/debug <message>" - invoke debugger subagent
                    local new_conv_id
                    new_conv_id=$(invoke_subagent_in_chat "debugger" "$debug_arg" "$conversation_id")
                    if [ -z "$conversation_id" ] && [ -n "$new_conv_id" ] && [ "$new_conv_id" != "None" ]; then
                        conversation_id="$new_conv_id"
                    fi
                    echo ""
                fi
                continue
                ;;
            /subagent\ *)
                # Extract subagent_id and prompt from: /subagent <id> <mensaje>
                local rest="${user_input#/subagent }"
                local subagent_id="${rest%% *}"
                local subagent_prompt="${rest#* }"

                # Check if only ID was provided without message
                if [ "$subagent_id" = "$subagent_prompt" ] || [ -z "$subagent_prompt" ]; then
                    echo -e "${RED}Uso: /subagent <id> <mensaje>${NC}"
                    echo -e "Ejemplo: ${DIM}/subagent code-review src/auth.py${NC}"
                    echo -e "Usa ${YELLOW}/subagents${NC} para ver los subagentes disponibles"
                    echo ""
                    continue
                fi

                # Invoke subagent and capture new conversation_id if created
                local new_conv_id
                new_conv_id=$(invoke_subagent_in_chat "$subagent_id" "$subagent_prompt" "$conversation_id")

                # Update conversation_id if a new one was created
                if [ -z "$conversation_id" ] && [ -n "$new_conv_id" ] && [ "$new_conv_id" != "None" ]; then
                    conversation_id="$new_conv_id"
                fi
                echo ""
                continue
                ;;
            /*)
                echo -e "${RED}Comando desconocido: $user_input${NC}"
                echo -e "Escribe ${YELLOW}/help${NC} para ver los comandos disponibles."
                echo ""
                continue
                ;;
        esac

        # Expand @file references: attach file contents to the prompt
        local expanded_input="$user_input"
        local file_attachments=""
        # Match @path patterns (not @mentions which would be just a word)
        while [[ "$expanded_input" =~ @([a-zA-Z0-9_./-]+\.[a-zA-Z0-9]+) ]]; do
            local ref="${BASH_REMATCH[1]}"
            local resolved=""
            # Try as-is, then relative to PWD
            if [ -f "$ref" ]; then
                resolved="$ref"
            elif [ -f "$PWD/$ref" ]; then
                resolved="$PWD/$ref"
            else
                # Try fuzzy find in project
                resolved=$(find . -maxdepth 5 -name "$(basename "$ref")" -type f 2>/dev/null | head -1)
            fi
            if [ -n "$resolved" ] && [ -f "$resolved" ]; then
                local content=$(head -200 "$resolved")
                local linecount=$(wc -l < "$resolved" | tr -d ' ')
                file_attachments="${file_attachments}

--- ${resolved} (${linecount} líneas) ---
${content}"
                if [ "$linecount" -gt 200 ]; then
                    file_attachments="${file_attachments}
... (truncado, ${linecount} líneas total)"
                fi
                echo -e "  ${DIM}📎 $(basename "$resolved")${NC}" >&2
            else
                echo -e "  ${YELLOW}⚠ No se encontró: $ref${NC}" >&2
            fi
            # Remove the @ref from the match to avoid infinite loop
            expanded_input="${expanded_input/@${ref}/}"
        done
        if [ -n "$file_attachments" ]; then
            user_input="${user_input}

[Archivos adjuntos por el usuario:]${file_attachments}"
        fi

        # Send message with continuation loop
        local current_prompt="$user_input"
        local continue_iterations=true

        # Mostrar indicador de typing inmediatamente
        show_typing_indicator "Pensando..." &
        TYPING_INDICATOR_PID=$!
        disown $TYPING_INDICATOR_PID 2>/dev/null  # Evitar mensaje "Killed" al terminar
        # Exportar PID para que send_chat_hybrid pueda detenerlo
        export TURIA_TYPING_PID=$TYPING_INDICATOR_PID

        while [ "$continue_iterations" = true ]; do
            echo ""

            # Use hybrid mode - tools execute locally
            local response run_status
            # Temporarily disable errexit to capture non-zero return codes
            set +e
            response=$(run_hybrid_chat "$current_prompt" "$conversation_id")
            run_status=$?

            # Asegurar que el typing indicator esté detenido después de cada llamada
            # Keep errexit disabled - kill/wait can fail if process already dead
            stop_typing_indicator
            unset TURIA_TYPING_PID
            set -e

            # Check for empty or invalid response
            if [ -z "$response" ] || [ "$response" = "{}" ]; then
                show_formatted_error \
                    "No se recibió respuesta del servidor" \
                    "La conexión terminó inesperadamente" \
                    "Verifica tu conexión a internet" \
                    "Verifica que el servidor esté activo" \
                    "Intenta de nuevo en unos momentos"
                break
            fi

            # Handle auth errors - try refresh first, then prompt for login
            if [ $run_status -eq 2 ]; then
                if handle_auth_error; then
                    set +e
                    response=$(run_hybrid_chat "$current_prompt" "$conversation_id")
                    run_status=$?
                    set -e
                else
                    break
                fi
            fi

            # Check for rate limit (not an error - just wait)
            if json_is_true "$response" "rate_limited"; then
                local rate_msg=$(json_get "$response" "rate_limit_message" "Rate limit alcanzado")
                # Update conversation_id if provided
                local rate_conv_id=$(json_get "$response" "conversation_id")
                if [ -n "$rate_conv_id" ] && [ "$rate_conv_id" != "None" ] && [ "$rate_conv_id" != "null" ]; then
                    conversation_id="$rate_conv_id"
                    save_project_conversation "$conversation_id"
                fi
                echo ""
                echo -e "${YELLOW}⚠️  $rate_msg${NC}"
                echo -e "${DIM}Conversacion: #$conversation_id${NC}"
                echo -e "${DIM}Espera unos segundos y escribe otro mensaje para continuar.${NC}"
                echo -e "${DIM}(Si sales, usa /resume $conversation_id para retomar)${NC}"
                echo ""
                break  # Exit inner loop but stay in interactive mode
            fi

            # Check for errors
            local error=$(json_get "$response" "error")

            if [ -n "$error" ] && [ "$error" != "None" ]; then
                # Provide contextual error messages based on error type
                if [[ "$error" == *"inesperadamente"* ]] || [[ "$error" == *"timeout"* ]]; then
                    show_formatted_error \
                        "Timeout o conexión interrumpida" \
                        "$error" \
                        "Intenta con un mensaje más corto" \
                        "Verifica tu conexión a internet" \
                        "Espera unos momentos y reintenta"
                elif [[ "$error" == *"Connection"* ]] || [[ "$error" == *"connection"* ]]; then
                    show_formatted_error \
                        "Error de conexión" \
                        "$error" \
                        "Verifica tu conexión a internet" \
                        "Verifica que el servidor esté activo: https://agent.rudo.es" \
                        "Intenta de nuevo en unos momentos"
                elif [[ "$error" == *"Not Found"* ]] || [[ "$error" == *"404"* ]]; then
                    show_formatted_error \
                        "Servidor no disponible" \
                        "$error" \
                        "El servidor puede estar en mantenimiento" \
                        "Contacta al administrador" \
                        "Intenta de nuevo más tarde"
                else
                    show_formatted_error "$error" "" "Intenta de nuevo" "Si el problema persiste, contacta soporte"
                fi
                break
            fi

            # Check if operation was aborted by user (ESC key)
            if json_is_true "$response" "aborted"; then
                local completed_tools=$(json_get_num "$response" "completed_tools")
                local total_tools=$(json_get_num "$response" "total_tools")
                local abort_conv_id=$(json_get "$response" "conversation_id")

                # Update conversation ID if available
                if [ -n "$abort_conv_id" ] && [ "$abort_conv_id" != "None" ] && [ "$abort_conv_id" != "null" ]; then
                    conversation_id="$abort_conv_id"
                    save_project_conversation "$conversation_id"
                fi

                echo ""
                echo -e "${YELLOW}⚡ Operación cancelada${NC} ${DIM}($completed_tools/$total_tools herramientas ejecutadas)${NC}"
                echo -e "${DIM}La conversación #$conversation_id sigue activa.${NC}"
                echo -e "${DIM}Escribe otro mensaje para continuar o dar nuevas instrucciones.${NC}"
                echo ""
                break  # Exit inner loop but stay in interactive mode
            fi

            # Extract response data - disable errexit to prevent crashes on missing fields
            set +e
            local text_response=$(json_get "$response" "response" 2>/dev/null || echo "")
            last_response="$text_response"  # Store for /copy command
            local new_conv_id=$(json_get "$response" "conversation_id" 2>/dev/null || echo "")
            local msg_cost=$(json_get_num "$response" "total_cost" 2>/dev/null || echo "0")
            local session_cost=$(json_get_num "$response" "session_cost" 2>/dev/null || echo "0")
            # Internal cost (compaction, classifier, RAG enhancer, …) — NOT
            # included in session_cost/total_cost. Surfaced so the user sees
            # the FULL spend (cuadra con la consola de Anthropic).
            local session_internal_cost=$(json_get_num "$response" "session_internal_cost" 2>/dev/null || echo "0")
            local total_internal_cost=$(json_get_num "$response" "total_internal_cost" 2>/dev/null || echo "0")
            local msg_elapsed=$(json_get_num "$response" "elapsed_time" 2>/dev/null || echo "0")
            local msg_tokens=$(json_get_num "$response" "total_tokens" 2>/dev/null || echo "0")
            local session_tokens=$(json_get_num "$response" "session_tokens" 2>/dev/null || echo "0")
            local msg_tools=$(json_get_num "$response" "tools_count" 2>/dev/null || echo "0")
            local max_iter_reached=$(json_get "$response" "max_iterations_reached" 2>/dev/null || echo "")
            local total_elapsed=$(json_get_num "$response" "total_elapsed" 2>/dev/null || echo "0")
            local text_streamed=$(json_get "$response" "text_streamed" 2>/dev/null || echo "")
            set -e

            # Update conversation ID if this is a new conversation
            if [ -z "$conversation_id" ] && [ -n "$new_conv_id" ] && [ "$new_conv_id" != "None" ] && [ "$new_conv_id" != "null" ]; then
                conversation_id="$new_conv_id"
                # Save for future sessions
                save_project_conversation "$conversation_id"
            fi

            # Update total cost (protect against empty values)
            set +e
            [ -z "$msg_cost" ] && msg_cost=0
            total_cost=$(echo "${total_cost:-0} ${msg_cost:-0}" | awk '{printf "%.6f", $1 + $2}')
            set -e

            # Display response (or notice if empty)
            # Skip if text was already streamed to the terminal
            # Note: Python json outputs lowercase "true", bash comparison is case-sensitive
            if [ "$text_streamed" = "True" ] || [ "$text_streamed" = "true" ]; then
                : # Text was already shown during streaming
            elif [ -z "$text_response" ] || [ "$text_response" = "None" ]; then
                echo ""
                echo -e "${YELLOW}Agent:${NC}"
                echo ""
                echo -e "${DIM}(El agente ejecutó herramientas pero no generó respuesta de texto)${NC}"
                echo -e "${DIM}Escribe otro mensaje para continuar o pedir explicación.${NC}"
            else
                # Disable errexit for display_response (glow or python could fail)
                set +e
                display_response "$text_response"
                set -e
            fi

            # Display compact summary - single line
            set +e
            local summary_parts=""

            # Duration
            if [ -n "$total_elapsed" ] && [ "$total_elapsed" != "0" ]; then
                if [ "${total_elapsed:-0}" -ge 60 ] 2>/dev/null; then
                    local m=$((total_elapsed / 60))
                    local s=$((total_elapsed % 60))
                    summary_parts="${m}m${s}s"
                else
                    summary_parts="${total_elapsed}s"
                fi
            fi

            # Cost and tokens
            if [ -n "$session_tokens" ] && [ "$session_tokens" != "0" ]; then
                [ -z "$session_cost" ] && session_cost=0
                local session_cost_fmt=$(format_cost "${session_cost:-0}")
                [ -n "$summary_parts" ] && summary_parts="$summary_parts · "
                summary_parts="${summary_parts}\$${session_cost_fmt}"
                # Append "(+$X internal)" if internal traffic was tracked.
                # awk comparison is locale-safe for floats.
                local has_internal=$(awk -v v="${session_internal_cost:-0}" 'BEGIN { print (v+0 > 0) ? "1" : "0" }')
                if [ "$has_internal" = "1" ]; then
                    local internal_fmt=$(format_cost "${session_internal_cost:-0}")
                    summary_parts="${summary_parts} (+\$${internal_fmt} internal)"
                fi
                summary_parts="${summary_parts} · ${session_tokens} tokens"
            fi

            # Tools count
            local tools_count=${msg_tools:-0}
            if [ "$tools_count" != "0" ] && [ "$tools_count" != "" ]; then
                [ -n "$summary_parts" ] && summary_parts="$summary_parts · "
                summary_parts="${summary_parts}${tools_count} tools"
            fi

            echo ""
            echo -e "  ${DIM}${summary_parts}${NC}"
            echo ""
            set -e

            # Show compact status bar
            set +e
            local status_parts=""
            local rag_git_url=$(get_rag_git_url 2>/dev/null || echo "")
            if [ -n "$rag_git_url" ]; then
                local rag_response=$(check_rag_index 2>/dev/null || echo "{}")
                local rag_status=$(json_get "$rag_response" "status" 2>/dev/null || echo "")
                case "$rag_status" in
                    "ready") status_parts="${GREEN}●${NC} RAG" ;;
                    "pending") status_parts="${YELLOW}○${NC} RAG" ;;
                    "indexing") status_parts="${CYAN}◐${NC} RAG" ;;
                esac
            fi
            local quota_str=$(get_quota_status_inline 2>/dev/null || echo "")
            if [ -n "$quota_str" ]; then
                [ -n "$status_parts" ] && status_parts="$status_parts  "
                status_parts="$status_parts$quota_str"
            fi
            set -e
            if [ -n "$status_parts" ]; then
                echo -e "  ${DIM}${status_parts}${NC}"
            fi

            # Check if max iterations was reached (server-side)
            if [ "$max_iter_reached" = "True" ] || [ "$max_iter_reached" = "true" ]; then
                echo -e "${YELLOW}───────────────────────────────────────────────────────────────${NC}"
                echo -e "${YELLOW}El agente ha alcanzado el limite de iteraciones del servidor.${NC}"
                echo ""
                local continue_choice=$(interactive_select "¿Qué deseas hacer?" "Continuar" "Detener")

                if [ "$continue_choice" = "Continuar" ]; then
                    current_prompt="continua"
                    echo ""
                else
                    continue_iterations=false
                fi
            else
                continue_iterations=false
            fi

            # Check if max tool iterations was reached (client-side safety limit)
            if json_is_true "$response" "max_tool_iterations_reached"; then
                echo -e "${YELLOW}───────────────────────────────────────────────────────────────${NC}"
                echo -e "${YELLOW}El agente ha ejecutado muchas herramientas (20+ en esta sesión).${NC}"
                echo -e "${DIM}Esto es un limite de seguridad para evitar bucles infinitos.${NC}"
                echo ""
                local tool_choice=$(interactive_select "¿Qué deseas hacer?" "Continuar" "Detener")

                if [ "$tool_choice" = "Continuar" ]; then
                    current_prompt="continua con la tarea"
                    continue_iterations=true
                    echo ""
                fi
            fi
        done

        # Disable errexit before going back to read input - prevents exit on EOF or read errors
        set +e

        # Visual separator and hint that user can continue
        echo -e "${DIM}───────────────────────────────────────────────────────────────${NC}"
        echo ""
    done
}

# ============================================================================
# MAIN CHAT ENTRY
# ============================================================================

# Agent chat - main entry point
agent_chat() {
    # Session-scoped auto-approve directory (per-tool flags, cleaned up on exit)
    export TURIA_AUTO_APPROVE_DIR="/tmp/turia_auto_approve_$$"
    rm -rf "$TURIA_AUTO_APPROVE_DIR"
    mkdir -p "$TURIA_AUTO_APPROVE_DIR"
    trap 'rm -rf "$TURIA_AUTO_APPROVE_DIR"' EXIT

    init_agent_config

    # Check dependencies on first run
    if ! ensure_agent_dependencies; then
        return 1
    fi

    # Verify authentication and token validity (with auto-refresh)
    if is_agent_authenticated; then
        if ! ensure_valid_token_with_refresh; then
            echo -e "${YELLOW}Tu sesion ha expirado y no se pudo renovar.${NC}"
            echo ""
            set_agent_config "access_token" "null"
            set_agent_config "refresh_token" "null"
        fi
    fi

    # If not authenticated (or refresh failed), trigger login
    if ! is_agent_authenticated; then
        echo -e "${YELLOW}No hay sesion activa. Iniciando login...${NC}"
        echo ""
        if ! agent_login; then
            echo -e "${RED}No se pudo iniciar sesion.${NC}"
            return 1
        fi
        echo ""
    fi

    local prompt="${1:-}"

    # If no prompt provided, enter interactive mode
    if [ -z "$prompt" ]; then
        agent_chat_interactive
        return $?
    fi

    # Single message mode
    agent_chat_single "$prompt"
}

# ============================================================================
# CONVERSATIONS
# ============================================================================

# List conversations
agent_conversations() {
    init_agent_config

    # Verify authentication and token validity (with auto-refresh)
    if is_agent_authenticated; then
        if ! ensure_valid_token_with_refresh; then
            echo -e "${YELLOW}Tu sesion ha expirado y no se pudo renovar.${NC}"
            echo ""
            set_agent_config "access_token" "null"
            set_agent_config "refresh_token" "null"
        fi
    fi

    # If not authenticated (or refresh failed), trigger login
    if ! is_agent_authenticated; then
        echo -e "${YELLOW}No hay sesion activa. Iniciando login...${NC}"
        echo ""
        if ! agent_login; then
            echo -e "${RED}No se pudo iniciar sesion.${NC}"
            return 1
        fi
        echo ""
    fi

    local api_url=$(get_agent_config "api_url")
    local access_token=$(get_agent_config "access_token")

    echo -e "${BOLD}-----------------------------------------------${NC}"
    echo -e "${BOLD}Conversaciones${NC}"
    echo -e "${BOLD}-----------------------------------------------${NC}"

    local response=$(curl -s "$api_url/agent/conversations" \
        -H "Authorization: Bearer $access_token")

    # Check for errors
    local error=$(json_get_error "$response")

    if [ -n "$error" ] && [ "$error" != "None" ]; then
        # Check if it's an auth error
        if [[ "$error" == *"Not authenticated"* ]] || [[ "$error" == *"token"* ]] || \
           [[ "$error" == *"expired"* ]] || [[ "$error" == *"authentication"* ]]; then
            if handle_auth_error; then
                # Retry the request
                access_token=$(get_agent_config "access_token")
                response=$(curl -s "$api_url/agent/conversations" \
                    -H "Authorization: Bearer $access_token")
                error=$(json_get_error "$response")
                if [ -n "$error" ] && [ "$error" != "None" ]; then
                    echo -e "${RED}Error: $error${NC}"
                    return 1
                fi
            else
                return 1
            fi
        else
            echo -e "${RED}Error: $error${NC}"
            return 1
        fi
    fi

    # Display conversations
    python3 -c "
import sys
import json

data = json.load(sys.stdin)
conversations = data.get('conversations', [])

if not conversations:
    print('No hay conversaciones.')
else:
    for conv in conversations:
        status = 'activa' if conv.get('is_active', False) else 'archivada'
        print(f\"ID: {conv['id']} | {conv['title'][:50]}... | Costo: \${conv['total_cost']:.6f} | {status}\")
" <<< "$response"
}
