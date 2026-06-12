#!/bin/bash

# Agent UI Utilities - Spinners, progress, and visual feedback
# Provides better UX for the CLI

# ============================================================================
# SPINNER CONFIGURATION
# ============================================================================

# Spinner frames (braille pattern - smooth animation)
SPINNER_FRAMES=("⠋" "⠙" "⠹" "⠸" "⠼" "⠴" "⠦" "⠧" "⠇" "⠏")
SPINNER_DELAY=0.08

# Alternative spinners
SPINNER_DOTS=("⣾" "⣽" "⣻" "⢿" "⡿" "⣟" "⣯" "⣷")
SPINNER_ARROWS=("←" "↖" "↑" "↗" "→" "↘" "↓" "↙")
SPINNER_SIMPLE=("-" "\\" "|" "/")

# Current spinner state
_SPINNER_PID=""
_SPINNER_MSG=""

# ============================================================================
# ANSI ESCAPE CODES
# ============================================================================

# Cursor control
CURSOR_HIDE="\033[?25l"
CURSOR_SHOW="\033[?25h"
CURSOR_UP="\033[1A"
CURSOR_DOWN="\033[1B"
CLEAR_LINE="\033[2K"
CURSOR_START="\r"

# Colors (if not already defined)
: ${BOLD:="\033[1m"}
: ${NC:="\033[0m"}
: ${RED:="\033[0;31m"}
: ${GREEN:="\033[0;32m"}
: ${YELLOW:="\033[1;33m"}
: ${BLUE:="\033[0;34m"}
: ${CYAN:="\033[0;36m"}
: ${DIM:="\033[2m"}

# ============================================================================
# SPINNER FUNCTIONS
# ============================================================================

# Start a spinner with a message
# Usage: start_spinner "Loading..."
start_spinner() {
    local msg="${1:-Procesando...}"
    _SPINNER_MSG="$msg"

    # Hide cursor
    printf "$CURSOR_HIDE"

    # Start spinner in background
    (
        local i=0
        while true; do
            local frame="${SPINNER_FRAMES[$i]}"
            printf "${CURSOR_START}${CLEAR_LINE}  ${CYAN}${frame}${NC} ${_SPINNER_MSG}"
            i=$(( (i + 1) % ${#SPINNER_FRAMES[@]} ))
            sleep $SPINNER_DELAY
        done
    ) &
    _SPINNER_PID=$!

    # Ensure cleanup on script exit
    trap "stop_spinner" EXIT
}

# Update spinner message without stopping
# Usage: update_spinner "New message..."
update_spinner() {
    _SPINNER_MSG="$1"
}

# Stop the spinner
# Usage: stop_spinner [success|error|warning] "Final message"
stop_spinner() {
    if [ -n "$_SPINNER_PID" ]; then
        kill $_SPINNER_PID 2>/dev/null
        wait $_SPINNER_PID 2>/dev/null
        _SPINNER_PID=""
    fi

    # Clear the line and show cursor
    printf "${CURSOR_START}${CLEAR_LINE}${CURSOR_SHOW}"

    # Show final status if provided
    local status="${1:-}"
    local msg="${2:-}"

    if [ -n "$status" ] && [ -n "$msg" ]; then
        case "$status" in
            success)
                echo -e "  ${GREEN}✓${NC} ${msg}"
                ;;
            error)
                echo -e "  ${RED}✗${NC} ${msg}"
                ;;
            warning)
                echo -e "  ${YELLOW}!${NC} ${msg}"
                ;;
            info)
                echo -e "  ${CYAN}ℹ${NC} ${msg}"
                ;;
        esac
    fi
}

# ============================================================================
# INLINE SPINNER (for use within Python SSE processing)
# ============================================================================

# Print a status line that can be updated (no background process)
# Usage: print_status "icon" "message" "detail"
print_status() {
    local icon="$1"
    local msg="$2"
    local detail="${3:-}"

    printf "${CURSOR_START}${CLEAR_LINE}"
    if [ -n "$detail" ]; then
        echo -e "  ${icon} ${msg} ${DIM}${detail}${NC}"
    else
        echo -e "  ${icon} ${msg}"
    fi
}

# Print a spinner frame inline (call this in a loop)
# Usage: print_spinner_frame $frame_index "message"
print_spinner_frame() {
    local frame_idx=$(( $1 % ${#SPINNER_FRAMES[@]} ))
    local frame="${SPINNER_FRAMES[$frame_idx]}"
    local msg="$2"
    printf "${CURSOR_START}${CLEAR_LINE}  ${CYAN}${frame}${NC} ${msg}"
}

# ============================================================================
# PROGRESS BAR
# ============================================================================

# Print a progress bar
# Usage: print_progress 50 100 "Downloading..."
print_progress() {
    local current=$1
    local total=$2
    local msg="${3:-}"
    local width=30

    local percent=$(( current * 100 / total ))
    local filled=$(( current * width / total ))
    local empty=$(( width - filled ))

    local bar=""
    for ((i=0; i<filled; i++)); do bar+="█"; done
    for ((i=0; i<empty; i++)); do bar+="░"; done

    printf "${CURSOR_START}${CLEAR_LINE}  ${bar} ${percent}%% ${DIM}${msg}${NC}"
}

# ============================================================================
# STATUS ICONS
# ============================================================================

icon_success="${GREEN}✓${NC}"
icon_error="${RED}✗${NC}"
icon_warning="${YELLOW}!${NC}"
icon_info="${CYAN}ℹ${NC}"
icon_pending="${DIM}○${NC}"
icon_running="${CYAN}●${NC}"
icon_tool="${BLUE}⚡${NC}"
icon_thinking="${YELLOW}◐${NC}"
icon_file="${DIM}📄${NC}"
icon_search="${DIM}🔍${NC}"
icon_edit="${DIM}✏${NC}"
icon_terminal="${DIM}⌘${NC}"

# ============================================================================
# FORMATTED OUTPUT
# ============================================================================

# Print a section header
print_header() {
    local title="$1"
    echo ""
    echo -e "${BOLD}$title${NC}"
    echo -e "${DIM}$(printf '─%.0s' {1..50})${NC}"
}

# Print a key-value pair
print_kv() {
    local key="$1"
    local value="$2"
    echo -e "  ${DIM}${key}:${NC} ${value}"
}

# Print a summary box
print_summary() {
    local files_read="${1:-0}"
    local files_written="${2:-0}"
    local tokens="${3:-0}"
    local cost="${4:-0}"
    local time="${5:-0}"

    echo ""
    echo -e "${DIM}───────────────────────────────────────────────${NC}"

    local parts=()
    [ "$files_read" -gt 0 ] && parts+=("${files_read} leídos")
    [ "$files_written" -gt 0 ] && parts+=("${files_written} modificados")

    if [ ${#parts[@]} -gt 0 ]; then
        echo -e "  ${GREEN}✓${NC} $(IFS=' | '; echo "${parts[*]}")"
    fi

    echo -e "  ${DIM}Tokens:${NC} ${tokens} ${DIM}|${NC} ${DIM}Costo:${NC} \$${cost} ${DIM}|${NC} ${DIM}Tiempo:${NC} ${time}s"
    echo -e "${DIM}───────────────────────────────────────────────${NC}"
}

# Print a tool execution line
print_tool_start() {
    local tool="$1"
    local detail="$2"

    local icon="$icon_tool"
    case "$tool" in
        read_file)   icon="${DIM}📖${NC}" ;;
        write_file)  icon="${DIM}✏️${NC}" ;;
        list_files)  icon="${DIM}📁${NC}" ;;
        search_code) icon="${DIM}🔍${NC}" ;;
        run_command) icon="${DIM}⌘${NC}" ;;
        git_info)    icon="${DIM}🔀${NC}" ;;
    esac

    echo -e "  ${icon} ${BOLD}${tool}${NC} ${DIM}${detail}${NC}"
}

print_tool_result() {
    local status="$1"  # success, error
    local preview="$2"

    if [ "$status" = "success" ]; then
        echo -e "    ${GREEN}└─${NC} ${DIM}${preview}${NC}"
    else
        echo -e "    ${RED}└─${NC} ${preview}"
    fi
}

# ============================================================================
# NOTIFICATION (macOS)
# ============================================================================

# Send a system notification (macOS)
notify() {
    local title="${1:-Turia Agent}"
    local msg="${2:-Operación completada}"

    if command -v osascript &> /dev/null; then
        osascript -e "display notification \"$msg\" with title \"$title\"" 2>/dev/null
    fi
}

# Play a sound (macOS)
play_sound() {
    local sound="${1:-default}"

    case "$sound" in
        success)
            afplay /System/Library/Sounds/Glass.aiff 2>/dev/null &
            ;;
        error)
            afplay /System/Library/Sounds/Basso.aiff 2>/dev/null &
            ;;
        *)
            afplay /System/Library/Sounds/Pop.aiff 2>/dev/null &
            ;;
    esac
}
