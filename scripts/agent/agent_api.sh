#!/bin/bash

# Agent API Module
# Handles communication with the server (SSE, hybrid chat)

# ============================================================================
# HTTP RETRY LOGIC (with exponential backoff)
# ============================================================================

# Execute curl with retry logic and exponential backoff
# Usage: curl_with_retry <max_retries> <curl_args...>
# Example: curl_with_retry 3 -s "$endpoint" -H "Authorization: Bearer $token"
curl_with_retry() {
    local max_retries="${1:-3}"
    shift
    local curl_args=("$@")

    local attempt=1
    local backoff=1

    while [ $attempt -le $max_retries ]; do
        # Execute curl and capture HTTP code + response
        local http_code
        local response
        local curl_output=$(mktemp)

        # Run curl with -w to get HTTP code, -o to save response
        http_code=$(curl -w "%{http_code}" -o "$curl_output" "${curl_args[@]}" 2>/dev/null)
        local curl_exit=$?
        response=$(cat "$curl_output")
        rm -f "$curl_output"

        # Success cases: curl succeeded AND (HTTP 2xx or 4xx)
        # We don't retry on 4xx because those are client errors (auth, validation, etc.)
        if [ $curl_exit -eq 0 ]; then
            # Check HTTP code
            if [[ "$http_code" =~ ^[24] ]]; then
                # Success (2xx) or client error (4xx) - return response
                echo "$response"
                return 0
            elif [[ "$http_code" =~ ^5 ]]; then
                # Check if 500 is actually an auth error (server closes connection on expired token)
                local resp_lower=$(echo "$response" | tr '[:upper:]' '[:lower:]')
                if [[ "$resp_lower" == *"not authorized"* ]] || [[ "$resp_lower" == *"connection already closed"* ]] || \
                   [[ "$resp_lower" == *"not authenticated"* ]]; then
                    echo "$response"
                    return 0  # Return as 4xx so caller handles auth
                fi
                # Server error (5xx) - retry
                if [ $attempt -lt $max_retries ]; then
                    echo -e "  ${YELLOW}⚠${NC} ${DIM}Error del servidor (${http_code}), reintentando en ${backoff}s...${NC}" >&2
                    sleep $backoff
                    backoff=$((backoff * 2))
                    attempt=$((attempt + 1))
                    continue
                else
                    # Max retries reached
                    echo "$response"
                    return 1
                fi
            fi
        else
            # curl failed (network error, timeout, DNS, etc.)
            if [ $attempt -lt $max_retries ]; then
                echo -e "  ${YELLOW}⚠${NC} ${DIM}Error de conexión, reintentando en ${backoff}s...${NC}" >&2
                sleep $backoff
                backoff=$((backoff * 2))
                attempt=$((attempt + 1))
                continue
            else
                # Max retries reached - return empty (network failure)
                echo ""
                return 1
            fi
        fi
    done

    # Fallback (should not reach here)
    echo "$response"
    return 1
}

# ============================================================================
# QUOTA API
# ============================================================================

# Get quota status as formatted string (for status bar)
get_quota_status_inline() {
    local api_url=$(get_agent_config "api_url")
    local access_token=$(get_agent_config "access_token")
    local endpoint="$api_url/agent/quota"

    local response=$(curl_with_retry 3 -s "$endpoint" \
        -H "Authorization: Bearer $access_token" \
        -H "Content-Type: application/json")

    # Check for errors silently
    local error=$(json_get_error "$response")
    if [ -n "$error" ] && [ "$error" != "None" ] && [ "$error" != "" ]; then
        return 0  # Silently ignore errors
    fi

    # Parse and return formatted quota string
    # Use temp file to avoid heredoc quote escaping issues
    local tmp_response=$(mktemp)
    echo "$response" > "$tmp_response"
    python3 - "$tmp_response" <<'PYEOF' 2>/dev/null
import json
import sys

BOLD = "\033[1m"
DIM = "\033[2m"
NC = "\033[0m"
RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"

tmp_file = sys.argv[1]
with open(tmp_file) as f:
    response = f.read()
try:
    data = json.loads(response)
except:
    sys.exit(0)

if not data.get("has_quota"):
    cost = float(data.get('current_cost', 0))
    print(f"💰 Presupuesto: {GREEN}∞{NC} {DIM}(${cost:.2f} usado){NC}")
else:
    usage_pct = data.get("usage_percent", 0) or 0
    monthly_limit = float(data.get("monthly_limit", 0) or 0)
    current_cost = float(data.get("current_cost", 0) or 0)
    is_exceeded = data.get("is_exceeded", False)

    # Progress bar (20 chars)
    bar_width = 20
    filled = int(min(100, usage_pct) / 100 * bar_width)
    empty = bar_width - filled

    if is_exceeded:
        bar_color = RED
    elif usage_pct >= 80:
        bar_color = YELLOW
    else:
        bar_color = GREEN

    bar = f"{bar_color}{'█' * filled}{NC}{DIM}{'░' * empty}{NC}"
    print(f"💰 Presupuesto: {bar} {usage_pct:.0f}% {DIM}(${current_cost:.2f}/${monthly_limit:.2f}){NC}")
PYEOF
    rm -f "$tmp_response"
}

# Show inline quota status (legacy, calls get_quota_status_inline)
show_quota_inline() {
    local status=$(get_quota_status_inline)
    if [ -n "$status" ]; then
        echo -e "  $status"
    fi
}

# Fetch and display user's cost quota
fetch_and_show_quota() {
    local api_url=$(get_agent_config "api_url")
    local access_token=$(get_agent_config "access_token")
    local endpoint="$api_url/agent/quota"

    local response=$(curl_with_retry 3 -s "$endpoint" \
        -H "Authorization: Bearer $access_token" \
        -H "Content-Type: application/json")

    # Check for errors
    local error=$(json_get_error "$response")

    if [ -n "$error" ] && [ "$error" != "None" ] && [ "$error" != "" ]; then
        echo -e "${RED}Error: $error${NC}"
        return 1
    fi

    # Parse and display quota info
    # Use temp file to avoid heredoc quote escaping issues
    local tmp_response=$(mktemp)
    echo "$response" > "$tmp_response"
    python3 - "$tmp_response" <<'PYEOF'
import json
import sys

BOLD = "\033[1m"
DIM = "\033[2m"
NC = "\033[0m"
RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
CYAN = "\033[0;36m"

tmp_file = sys.argv[1]
with open(tmp_file) as f:
    response = f.read()
try:
    data = json.loads(response)
except:
    print(f"{RED}Error parsing quota response{NC}")
    sys.exit(1)

print("")
print(f"{BOLD}╔══════════════════════════════════════════════════════════╗{NC}")
print(f"{BOLD}║                      PRESUPUESTO                         ║{NC}")
print(f"{BOLD}╚══════════════════════════════════════════════════════════╝{NC}")
print("")

if not data.get("has_quota"):
    print(f"  {GREEN}∞{NC}  Sin límite configurado")
    print(f"     Coste acumulado: {BOLD}${data.get('current_cost', '0.00')}{NC}")
else:
    monthly_limit = data.get("monthly_limit", "?")
    current_cost = data.get("current_cost", "0.00")
    remaining = data.get("remaining", "?")
    usage_pct = data.get("usage_percent", 0) or 0
    is_enforced = data.get("is_enforced", False)
    is_exceeded = data.get("is_exceeded", False)

    # Status indicator
    if is_exceeded:
        status = f"{RED}⛔ LÍMITE EXCEDIDO{NC}"
    elif usage_pct >= 80:
        status = f"{YELLOW}⚠️  Cerca del límite ({usage_pct:.0f}%){NC}"
    else:
        status = f"{GREEN}✓{NC}  Dentro del límite"

    print(f"  {status}")
    print("")

    # Progress bar
    bar_width = 40
    filled = int(min(100, usage_pct) / 100 * bar_width)
    empty = bar_width - filled

    if usage_pct >= 100:
        bar_color = RED
    elif usage_pct >= 80:
        bar_color = YELLOW
    else:
        bar_color = GREEN

    bar = f"{bar_color}{'█' * filled}{NC}{DIM}{'░' * empty}{NC}"
    print(f"  [{bar}] {usage_pct:.1f}%")
    print("")

    # Details
    print(f"  {BOLD}Límite mensual:{NC}  ${monthly_limit}")
    print(f"  {BOLD}Coste actual:{NC}    ${current_cost}")
    print(f"  {BOLD}Restante:{NC}        ${remaining}")
    print("")

    # Enforcement status
    if is_enforced:
        print(f"  {DIM}Modo:{NC} {RED}Bloqueo activo{NC} (se denegarán requests al exceder)")
    else:
        print(f"  {DIM}Modo:{NC} {YELLOW}Solo aviso{NC} (se permite continuar)")

print("")
print(f"{BOLD}══════════════════════════════════════════════════════════════{NC}")
print("")
PYEOF
    rm -f "$tmp_response"
}

# ============================================================================
# MODELS API
# ============================================================================

# Fetch available LLM models
fetch_available_models() {
    local api_url=$(get_agent_config "api_url")
    local access_token=$(get_agent_config "access_token")
    local endpoint="$api_url/agent/models"

    curl_with_retry 3 -s "$endpoint" \
        -H "Authorization: Bearer $access_token" \
        -H "Content-Type: application/json"
}

# Show available models in a nice format
show_available_models() {
    local response=$(fetch_available_models)

    # Check for errors
    local error=$(json_get_error "$response")

    if [ -n "$error" ] && [ "$error" != "None" ] && [ "$error" != "" ]; then
        echo -e "${RED}Error: $error${NC}"
        return 1
    fi

    # Get current model from config
    local current_model=$(get_agent_config "preferred_model")

    # Display models
    # Use temp file to avoid heredoc quote escaping issues
    local tmp_response=$(mktemp)
    echo "$response" > "$tmp_response"
    python3 - "$tmp_response" "$current_model" <<'PYEOF'
import json
import sys

BOLD = "\033[1m"
DIM = "\033[2m"
NC = "\033[0m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
CYAN = "\033[0;36m"
RED = "\033[0;31m"

tmp_file = sys.argv[1]
current_model = sys.argv[2] if len(sys.argv) > 2 else ""

with open(tmp_file) as f:
    response = f.read()

try:
    data = json.loads(response)
except:
    print(f"{BOLD}Error parsing response{NC}")
    sys.exit(1)

models = data.get("models", [])
default_model = data.get("default_model", "")

print("")
print(f"{BOLD}╔══════════════════════════════════════════════════════════════╗{NC}")
print(f"{BOLD}║                    MODELOS DISPONIBLES                       ║{NC}")
print(f"{BOLD}╚══════════════════════════════════════════════════════════════╝{NC}")
print("")

if not models:
    print(f"  {DIM}No hay modelos configurados.{NC}")
else:
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
        indicators = []
        if current_model and current_model == model_id:
            indicators.append(f"{GREEN}◉ ACTIVO{NC}")
        elif is_default:
            indicators.append(f"{CYAN}★ default{NC}")

        # Status indicator
        if status == "no_credits":
            indicators.append(f"{RED}💳 sin créditos{NC}")
        elif status == "degraded":
            indicators.append(f"{YELLOW}⚠ limitado{NC}")
        elif status == "error":
            indicators.append(f"{RED}✗ error{NC}")
        elif status == "available":
            indicators.append(f"{GREEN}✓{NC}")
        # 'unknown' status: no indicator (not yet tested)

        indicator_str = " ".join(indicators)
        if indicator_str:
            indicator_str = f"  {indicator_str}"

        # Model line - dim if not available
        if not available:
            print(f"  {DIM}{model_id}{NC}{indicator_str}")
            print(f"    {DIM}{name} ({provider}){NC}")
            if status_message:
                print(f"    {RED}{status_message}{NC}")
        else:
            print(f"  {BOLD}{model_id}{NC}{indicator_str}")
            print(f"    {DIM}{name} ({provider}){NC}")
        print(f"    {DIM}Precio: ${input_price}/1M in, ${output_price}/1M out{NC}")
        print("")

print(f"{DIM}Uso: /model <id> para cambiar de modelo{NC}")
print(f"{DIM}     /model auto para usar routing automático{NC}")
print("")
PYEOF
    rm -f "$tmp_response"
}

# ============================================================================
# HYBRID CHAT API
# ============================================================================

# Send hybrid chat request and process SSE response
send_chat_hybrid() {
    local prompt="$1"
    local conversation_id="$2"
    local tool_results_json="$3"  # JSON array de tool results o vacio
    local max_iterations="${4:-10}"
    local subagent_id="${5:-}"    # Optional: ID del subagente a usar
    local images_json="${6:-}"    # Optional: JSON array de imagenes

    local api_url=$(get_agent_config "api_url")
    local access_token=$(get_agent_config "access_token")
    local endpoint="$api_url/agent/chat/hybrid"

    # Generar contexto del proyecto: completo en primer mensaje, minimal en continuaciones
    local project_context=""
    local git_remote_url=""
    if [ -z "$tool_results_json" ]; then
        if [ -z "$conversation_id" ]; then
            # First message: full context
            project_context=$(generate_project_context)
        elif [ -n "$prompt" ]; then
            # Continuing conversation with new prompt: send minimal context (type + rules)
            local project_type=$(detect_project_type)
            local tmp_rules=$(mktemp)
            for rules_file in ".claude-project" "CLAUDE.md" ".agent-rules"; do
                if [ -f "$rules_file" ]; then
                    head -300 "$rules_file" > "$tmp_rules" 2>/dev/null
                    break
                fi
            done
            project_context=$(python3 - "$project_type" "$(basename "$PWD")" "$PWD" "$tmp_rules" << 'PYEOF'
import json, sys
ctx = {"project_type": sys.argv[1], "project_name": sys.argv[2], "root_path": sys.argv[3]}
try:
    with open(sys.argv[4]) as f:
        rules = f.read().strip()
    if rules:
        ctx["project_rules"] = rules
except:
    pass
print(json.dumps(ctx))
PYEOF
)
            rm -f "$tmp_rules"
        fi
    fi

    # Get git remote URL for RAG context - always send with new prompts (not tool_results)
    if [ -z "$tool_results_json" ] && [ -n "$prompt" ]; then
        git_remote_url=$(get_rag_git_url 2>/dev/null || echo "")
    fi

    # Get debug mode setting
    local debug_mode=$(get_agent_config "debug_mode")

    # Get preferred model (user-selected model override)
    local preferred_model=$(get_agent_config "preferred_model")

    # Guardar datos en directorio temporal unico
    local tmp_dir=$(mktemp -d)
    echo "$prompt" > "$tmp_dir/prompt"
    echo "$project_context" > "$tmp_dir/context"
    echo "$tool_results_json" > "$tmp_dir/results"
    echo "$subagent_id" > "$tmp_dir/subagent"
    echo "$git_remote_url" > "$tmp_dir/git_url"
    echo "$images_json" > "$tmp_dir/images"
    echo "$preferred_model" > "$tmp_dir/model"

    # Construir payload con Python
    local payload=$(python3 - "$tmp_dir" "$conversation_id" "$max_iterations" "$debug_mode" << 'PYEOF'
import json
import sys
import os

try:
    tmp_dir = sys.argv[1]
    conv_id = sys.argv[2]
    max_iter_str = sys.argv[3]
    debug_mode = sys.argv[4] == "true" if len(sys.argv) > 4 else False

    def read_tmp(name):
        try:
            with open(os.path.join(tmp_dir, name)) as f:
                return f.read().strip()
        except:
            return ""

    # Parse max_iterations with fallback
    try:
        max_iter = int(max_iter_str) if max_iter_str else 10
    except ValueError:
        max_iter = 10

    data = {"max_iterations": max_iter}

    # Leer prompt
    prompt = read_tmp("prompt")
    if prompt:
        data["prompt"] = prompt

        # Detect @mentions for cross-project RAG
        import re
        mention_mapping = {
            '@back': 'backend',
            '@backend': 'backend',
            '@server': 'backend',
            '@api': 'backend',
            '@ios': 'ios',
            '@android': 'android',
            '@front': 'web_frontend',
            '@frontend': 'web_frontend',
            '@web': 'web_frontend',
            '@flutter': 'flutter',
            '@mobile': 'ios',
        }
        prompt_lower = prompt.lower()
        for mention, project_type in mention_mapping.items():
            if mention in prompt_lower:
                data["target_project_type"] = project_type
                if debug_mode:
                    print(f"[DEBUG] Detected mention '{mention}' -> target_project_type='{project_type}'", file=sys.stderr)
                break

    # Agregar conversation_id si existe
    if conv_id:
        try:
            data["conversation_id"] = int(conv_id)
        except ValueError:
            pass

    # Leer contexto del proyecto
    project_ctx = read_tmp("context")
    if project_ctx:
        try:
            data["project_context"] = json.loads(project_ctx)
        except:
            pass

    # Leer tool_results
    tool_results = read_tmp("results")
    if tool_results:
        try:
            parsed_results = json.loads(tool_results)
            if parsed_results:
                data["tool_results"] = parsed_results
        except json.JSONDecodeError as e:
            print(f"Warning: Failed to parse tool_results: {e}", file=sys.stderr)

    # Leer subagent_id
    subagent_id = read_tmp("subagent")
    if subagent_id:
        data["subagent_id"] = subagent_id

    # Leer git_remote_url para RAG
    git_url = read_tmp("git_url")
    if git_url:
        data["git_remote_url"] = git_url

    # Leer imagenes
    images_str = read_tmp("images")
    if images_str:
        try:
            images = json.loads(images_str)
            if images and isinstance(images, list) and len(images) > 0:
                for img in images:
                    img.pop('source_path', None)
                data["images"] = images
        except:
            pass

    # Leer preferred_model
    model_id = read_tmp("model")
    if model_id and model_id != "null" and model_id != "auto":
        data["preferred_model"] = model_id
        if debug_mode:
            print(f"[DEBUG] Using preferred_model={model_id}", file=sys.stderr)

    # Debug
    if debug_mode and data.get("target_project_type"):
        print(f"[DEBUG] Sending target_project_type={data['target_project_type']}", file=sys.stderr)

    # Check for inline user input
    user_inline_input = os.environ.get('TURIA_USER_INLINE_INPUT', '').strip()
    if user_inline_input:
        data["user_context"] = user_inline_input
        if debug_mode:
            print(f"[DEBUG] Including user inline input: {user_inline_input[:50]}", file=sys.stderr)
        os.environ['TURIA_USER_INLINE_INPUT'] = ''

    print(json.dumps(data))

except Exception as e:
    print(f"Error building payload: {e}", file=sys.stderr)
    fallback = {"max_iterations": 10, "error": str(e)}
    print(json.dumps(fallback))
PYEOF
)
    rm -rf "$tmp_dir"

    # Validate payload is not empty
    if [ -z "$payload" ]; then
        echo '{"error": "Failed to build request payload", "response": ""}'
        return 1
    fi

    # Validate payload has either prompt or tool_results (required by server)
    local has_prompt=$(json_get "$payload" "prompt")
    local has_tools=$(json_get "$payload" "tool_results")
    if [ -z "$has_prompt" ] && [ -z "$has_tools" ]; then
        echo '{"error": "Request must have either prompt or tool_results", "response": ""}'
        return 1
    fi

    # Guardar payload en archivo temporal
    local tmp_payload=$(mktemp)
    echo "$payload" > "$tmp_payload"

    # Pass terminal width to Python subprocess
    # Must use /dev/tty since we're likely in a subshell where stdout is captured
    export COLUMNS=$(stty size < /dev/tty 2>/dev/null | awk '{print $2}' || tput cols 2>/dev/null || echo 80)

    # Llamar al endpoint y procesar SSE con UI mejorada
    python3 - "$endpoint" "$access_token" "$tmp_payload" << 'PYEOF'
import sys
import json
import subprocess
import time
import threading
import os

# ============================================================================
# UI Configuration
# ============================================================================

# Colors
BOLD = "\033[1m"
DIM = "\033[2m"
NC = "\033[0m"
RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
BLUE = "\033[0;34m"
CYAN = "\033[0;36m"
WHITE_BRIGHT = "\033[1;37m"  # Agent response text
TOOL_COLOR = "\033[0;90m"    # Dark gray for tool activity

# Cursor control
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"
CLEAR_LINE = "\033[2K"
CURSOR_START = "\r"

# Spinner frames
SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

# ============================================================================
# Markdown to ANSI converter
# ============================================================================

import re
import unicodedata

def display_width(text):
    """Calculate the display width of a string, accounting for Unicode."""
    # Strip ANSI codes first
    clean = re.sub(r'\x1b\[[0-9;]*m', '', text)
    # Normalize to NFC to combine accented characters
    clean = unicodedata.normalize('NFC', clean)
    width = 0
    i = 0
    while i < len(clean):
        char = clean[i]
        # Skip zero-width characters and combining marks
        cat = unicodedata.category(char)
        if cat.startswith('M') or cat == 'Cf':  # Mark or Format
            i += 1
            continue
        # Check for emoji sequences (char + variation selector + optional ZWJ sequences)
        if i + 1 < len(clean) and clean[i + 1] in '\ufe0e\ufe0f':  # Variation selectors
            width += 2
            i += 2
            # Skip ZWJ sequences
            while i + 1 < len(clean) and clean[i] == '\u200d':
                i += 2
            continue
        # East Asian Width: F, W are double width
        ea = unicodedata.east_asian_width(char)
        if ea in ('F', 'W'):
            width += 2
        # Emoji and symbols typically take 2 columns
        elif cat == 'So':  # Symbol, Other (includes most emoji)
            width += 2
        else:
            width += 1
        i += 1
    return width

def format_markdown_table(table_lines):
    """Format a markdown table with proper alignment and borders."""
    if not table_lines:
        return ""

    # Parse cells from each row
    rows = []
    separator_idx = -1
    for i, line in enumerate(table_lines):
        # Remove leading/trailing pipes and split
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        # Check if this is a separator row (contains only dashes, colons, spaces)
        if all(re.match(r'^:?-+:?$', c.strip()) for c in cells if c.strip()):
            separator_idx = i
        rows.append(cells)

    if not rows:
        return ""

    # Calculate column widths (EXCLUDING separator row - it's just dashes)
    num_cols = max(len(row) for row in rows)
    col_widths = [0] * num_cols
    for row_idx, row in enumerate(rows):
        if row_idx == separator_idx:
            continue  # Skip separator row for width calculation
        for i, cell in enumerate(row):
            if i < num_cols:
                # Use display_width for proper Unicode handling
                col_widths[i] = max(col_widths[i], display_width(cell))

    # Ensure minimum column width
    col_widths = [max(w, 3) for w in col_widths]

    # Build formatted table
    result = []

    # Box drawing characters
    TOP_LEFT = "┌"
    TOP_RIGHT = "┐"
    BOT_LEFT = "└"
    BOT_RIGHT = "┘"
    HORIZ = "─"
    VERT = "│"
    T_DOWN = "┬"
    T_UP = "┴"
    T_RIGHT = "├"
    T_LEFT = "┤"
    CROSS = "┼"

    # Top border
    top_border = TOP_LEFT + T_DOWN.join(HORIZ * (w + 2) for w in col_widths) + TOP_RIGHT
    result.append(f"{DIM}{top_border}{NC}")

    for i, row in enumerate(rows):
        # Skip separator row (we'll draw our own)
        if i == separator_idx:
            # Draw separator line
            sep = T_RIGHT + CROSS.join(HORIZ * (w + 2) for w in col_widths) + T_LEFT
            result.append(f"{DIM}{sep}{NC}")
            continue

        # Pad row to have correct number of columns
        padded_row = row + [''] * (num_cols - len(row))

        # Build row with cells
        cells_formatted = []
        for j in range(num_cols):
            cell = padded_row[j] if j < len(padded_row) else ''
            width = col_widths[j]
            # Calculate padding using display_width for proper Unicode
            padding = max(0, width - display_width(cell))
            # Header row (first row) - make bold
            if i == 0:
                cells_formatted.append(f" {BOLD}{cell}{NC}{' ' * padding} ")
            else:
                cells_formatted.append(f" {cell}{' ' * padding} ")

        row_str = f"{DIM}{VERT}{NC}" + f"{DIM}{VERT}{NC}".join(cells_formatted) + f"{DIM}{VERT}{NC}"
        result.append(row_str)

    # Bottom border
    bot_border = BOT_LEFT + T_UP.join(HORIZ * (w + 2) for w in col_widths) + BOT_RIGHT
    result.append(f"{DIM}{bot_border}{NC}")

    return "\n".join(result)


def format_unicode_table(table_lines):
    """Reformat a Unicode box-drawing table with proper column alignment."""
    if not table_lines:
        return ""

    # Strip any ANSI codes from input lines
    def strip_ansi_local(s):
        return re.sub(r'\x1b\[[0-9;]*m', '', s)

    clean_lines = [strip_ansi_local(line) for line in table_lines]

    # Box drawing characters
    BOX_CHARS = set('┌┐└┘├┤┬┴┼│─')
    TOP_LEFT = "┌"
    TOP_RIGHT = "┐"
    BOT_LEFT = "└"
    BOT_RIGHT = "┘"
    HORIZ = "─"
    VERT = "│"
    T_DOWN = "┬"
    T_UP = "┴"
    T_RIGHT = "├"
    T_LEFT = "┤"
    CROSS = "┼"

    # First pass: determine expected column count from separator/border rows
    expected_cols = 0
    for line in clean_lines:
        stripped = line.strip()
        if stripped.startswith(TOP_LEFT) or stripped.startswith(T_RIGHT):
            # Count columns from border (number of ┬ or ┼ + 1)
            col_count = stripped.count(T_DOWN) + stripped.count(CROSS) + 1
            if col_count > expected_cols:
                expected_cols = col_count

    # Parse content rows (lines with │)
    rows = []
    row_types = []  # 'header', 'separator', 'data'

    for line in clean_lines:
        stripped = line.strip()

        # Top border (┌───┬───┐)
        if stripped.startswith(TOP_LEFT):
            row_types.append('top')
            rows.append([])
        # Bottom border (└───┴───┘)
        elif stripped.startswith(BOT_LEFT):
            row_types.append('bottom')
            rows.append([])
        # Separator (├───┼───┤)
        elif stripped.startswith(T_RIGHT):
            row_types.append('separator')
            rows.append([])
        # Content row (│ ... │)
        elif VERT in stripped:
            # Extract cells between │
            parts = stripped.split(VERT)
            # Remove empty first and last (from leading/trailing │)
            cells = [p.strip() for p in parts[1:-1]] if len(parts) > 2 else [p.strip() for p in parts if p.strip()]

            # If we have more cells than expected columns, merge extras into last cell
            if expected_cols > 0 and len(cells) > expected_cols:
                merged = cells[:expected_cols-1]
                # Merge remaining cells into the last one
                merged.append(' | '.join(cells[expected_cols-1:]))
                cells = merged

            rows.append(cells)
            # First content row is header
            if not any(t == 'data' for t in row_types):
                row_types.append('header')
            else:
                row_types.append('data')
        else:
            # Unknown line, keep as-is
            row_types.append('unknown')
            rows.append([stripped])

    if not rows:
        return "\n".join(table_lines)

    # Calculate max columns and widths (use expected_cols if we have it)
    num_cols = expected_cols if expected_cols > 0 else max((len(r) for r in rows if r), default=0)
    if num_cols == 0:
        return "\n".join(table_lines)

    # Remove empty trailing columns (LLM sometimes generates extra empty columns)
    while num_cols > 1:
        all_empty = True
        for row, rtype in zip(rows, row_types):
            if rtype in ('header', 'data') and len(row) >= num_cols:
                if row[num_cols - 1].strip():
                    all_empty = False
                    break
        if all_empty:
            num_cols -= 1
            # Also trim the rows
            for i, (row, rtype) in enumerate(zip(rows, row_types)):
                if rtype in ('header', 'data') and len(row) > num_cols:
                    rows[i] = row[:num_cols]
        else:
            break

    col_widths = [0] * num_cols
    for row, rtype in zip(rows, row_types):
        if rtype in ('header', 'data'):
            for i, cell in enumerate(row):
                if i < num_cols:
                    col_widths[i] = max(col_widths[i], display_width(cell))

    # Ensure minimum width
    col_widths = [max(w, 3) for w in col_widths]

    # Rebuild table
    result = []

    for row, rtype in zip(rows, row_types):
        if rtype == 'top':
            line = TOP_LEFT + T_DOWN.join(HORIZ * (w + 2) for w in col_widths) + TOP_RIGHT
            result.append(f"{DIM}{line}{NC}")
        elif rtype == 'bottom':
            line = BOT_LEFT + T_UP.join(HORIZ * (w + 2) for w in col_widths) + BOT_RIGHT
            result.append(f"{DIM}{line}{NC}")
        elif rtype == 'separator':
            line = T_RIGHT + CROSS.join(HORIZ * (w + 2) for w in col_widths) + T_LEFT
            result.append(f"{DIM}{line}{NC}")
        elif rtype == 'header':
            # Pad cells
            padded = row + [''] * (num_cols - len(row))
            cells_fmt = []
            for j, cell in enumerate(padded):
                w = col_widths[j] if j < len(col_widths) else 3
                padding = max(0, w - display_width(cell))
                cells_fmt.append(f" {BOLD}{cell}{NC}{' ' * padding} ")
            line = f"{DIM}{VERT}{NC}" + f"{DIM}{VERT}{NC}".join(cells_fmt) + f"{DIM}{VERT}{NC}"
            result.append(line)
        elif rtype == 'data':
            padded = row + [''] * (num_cols - len(row))
            cells_fmt = []
            for j, cell in enumerate(padded):
                w = col_widths[j] if j < len(col_widths) else 3
                padding = max(0, w - display_width(cell))
                cells_fmt.append(f" {cell}{' ' * padding} ")
            line = f"{DIM}{VERT}{NC}" + f"{DIM}{VERT}{NC}".join(cells_fmt) + f"{DIM}{VERT}{NC}"
            result.append(line)
        else:
            # Unknown, keep original
            result.append(row[0] if row else '')

    return "\n".join(result)


class StreamingTableFormatter:
    """Handles buffering and formatting of Unicode tables during streaming."""

    def __init__(self):
        self.unicode_table_buffer = []
        self.in_unicode_table = False

    def process_chunk(self, text):
        """Process a streaming chunk, buffering Unicode tables for reformatting."""
        lines = text.split('\n')
        result_parts = []

        for line in lines:
            stripped = line.strip()

            # Detect Unicode table start (┌)
            if '┌' in stripped and '─' in stripped:
                self.in_unicode_table = True
                self.unicode_table_buffer = [line]
                continue

            # If we're in a Unicode table, buffer the line
            if self.in_unicode_table:
                self.unicode_table_buffer.append(line)
                # Check for table end (└)
                if stripped.startswith('└') and '┘' in stripped:
                    # Table complete - format and output
                    formatted_table = format_unicode_table(self.unicode_table_buffer)
                    result_parts.append(formatted_table)
                    self.unicode_table_buffer = []
                    self.in_unicode_table = False
                continue

            # Not in a table - output line directly
            result_parts.append(line)

        return '\n'.join(result_parts)

    def flush(self):
        """Flush any remaining buffered content (incomplete table)."""
        if self.unicode_table_buffer:
            # Output incomplete table as-is
            result = '\n'.join(self.unicode_table_buffer)
            self.unicode_table_buffer = []
            self.in_unicode_table = False
            return result
        return ""

# Global streaming table formatter instance
streaming_formatter = StreamingTableFormatter()

def strip_ansi(text):
    """Remove ANSI escape codes from text."""
    return re.sub(r'\x1b\[[0-9;]*m', '', text)

def get_terminal_width():
    """Get current terminal width, default 80."""
    # First try COLUMNS env var (most reliable in subprocesses)
    try:
        cols = int(os.environ.get("COLUMNS", 0))
        if cols > 0:
            return cols
    except (ValueError, TypeError):
        pass
    # Try /dev/tty for actual terminal width
    try:
        import fcntl, termios, struct
        with open('/dev/tty', 'r') as tty:
            result = fcntl.ioctl(tty.fileno(), termios.TIOCGWINSZ, b'\x00' * 8)
            return struct.unpack('HHHH', result)[1]
    except:
        pass
    # Fallback to os.get_terminal_size
    try:
        return os.get_terminal_size().columns
    except:
        return 80

def wrap_ansi_text(text, indent=2):
    """Wrap text to terminal width, preserving ANSI codes and indentation."""
    width = get_terminal_width() - indent  # Account for leading indent
    if width < 40:
        width = 40

    lines = text.split('\n')
    wrapped = []
    for line in lines:
        clean = strip_ansi(line)
        # Don't wrap code blocks, tables, short lines, or lines with special chars
        if len(clean) <= width or clean.startswith('┌') or clean.startswith('│') or clean.startswith('└') or clean.startswith('```'):
            wrapped.append(line)
            continue

        # Simple word wrap preserving ANSI codes
        # Build character map: for each visible char, track its position in the original string
        words = line.split(' ')
        current_line = ''
        current_visible_len = 0

        for i, word in enumerate(words):
            word_visible_len = len(strip_ansi(word))
            separator = ' ' if current_line else ''
            sep_len = 1 if current_line else 0

            if current_visible_len + sep_len + word_visible_len > width and current_line:
                wrapped.append(current_line)
                current_line = word
                current_visible_len = word_visible_len
            else:
                current_line += separator + word
                current_visible_len += sep_len + word_visible_len

        if current_line:
            wrapped.append(current_line)

    return '\n'.join(wrapped)

def markdown_to_ansi(text, use_streaming_formatter=False):
    """Convert basic markdown to ANSI terminal codes."""

    # Process Unicode tables (┌...┘) - detect and reformat for alignment
    lines = text.split('\n')
    result_lines = []
    unicode_table_buffer = []
    in_unicode_table = False
    markdown_table_buffer = []
    in_markdown_table = False

    for line in lines:
        # Strip ANSI codes for detection but keep original line for output
        clean_line = strip_ansi(line)
        stripped = clean_line.strip()

        # Detect Unicode table start (┌)
        if not in_unicode_table and stripped.startswith('┌') and '─' in stripped:
            in_unicode_table = True
            unicode_table_buffer = [line]
            continue

        # If we're in a Unicode table
        if in_unicode_table:
            unicode_table_buffer.append(line)
            # Check for table end (└)
            if stripped.startswith('└') and '┘' in stripped:
                # Table complete - format and output
                formatted = format_unicode_table(unicode_table_buffer)
                result_lines.append(formatted)
                unicode_table_buffer = []
                in_unicode_table = False
            continue

        # Detect markdown table rows (start with | or contain | surrounded by content)
        is_markdown_table = bool(re.match(r'^\s*\|.*\|', stripped))

        if is_markdown_table:
            in_markdown_table = True
            markdown_table_buffer.append(line)
        else:
            if in_markdown_table and markdown_table_buffer:
                # Process accumulated markdown table
                result_lines.append(format_markdown_table(markdown_table_buffer))
                markdown_table_buffer = []
                in_markdown_table = False
            result_lines.append(line)

    # Don't forget remaining tables at end of text
    if unicode_table_buffer:
        # Incomplete Unicode table - output as-is
        result_lines.extend(unicode_table_buffer)
    if markdown_table_buffer:
        result_lines.append(format_markdown_table(markdown_table_buffer))

    text = '\n'.join(result_lines)

    # Code blocks (```lang ... ``` or `` ... ``) - handle 2+ backticks
    def replace_code_block(match):
        code = match.group(2) or match.group(0)
        return f"{DIM}{code}{NC}"
    text = re.sub(r'`{2,}(\w*)\n?(.*?)`{2,}', replace_code_block, text, flags=re.DOTALL)

    # Inline code (`code`) - dim - but not if already processed
    text = re.sub(r'(?<!`)`([^`\n]+)`(?!`)', f'{DIM}\\1{NC}', text)

    # Headers with ## syntax - bold + color
    text = re.sub(r'^####\s*(.+)$', f'{BOLD}{BLUE}\\1{NC}', text, flags=re.MULTILINE)
    text = re.sub(r'^###\s*(.+)$', f'{BOLD}{CYAN}\\1{NC}', text, flags=re.MULTILINE)
    text = re.sub(r'^##\s*(.+)$', f'{BOLD}{YELLOW}\\1{NC}', text, flags=re.MULTILINE)
    text = re.sub(r'^#\s*(.+)$', f'{BOLD}{GREEN}\\1{NC}', text, flags=re.MULTILINE)

    # Lines starting with emoji (likely headers) - make bold
    text = re.sub(r'^([🏦🏗️⚡🔑🔄🛡️🎨🔗🎯✅❌📊📋📁💳💾👤🔐💰📱🧠💾]+ .+)$', f'{BOLD}\\1{NC}', text, flags=re.MULTILINE)

    # Bold (**text** or __text__) - bold
    text = re.sub(r'\*\*([^*]+)\*\*', f'{BOLD}\\1{NC}', text)
    text = re.sub(r'__([^_]+)__', f'{BOLD}\\1{NC}', text)

    # Numbered lists - add blank line before items for breathing room
    text = re.sub(r'(?<=\S)\n(\d+\.\s)', r'\n\n\1', text)
    # Style numbered items bold
    text = re.sub(r'^(\d+\.)\s(.+)$', f'{BOLD}\\1{NC} \\2', text, flags=re.MULTILINE)

    # Bullet points - visual hierarchy by indent level
    # Add blank line before top-level bullets that follow non-blank, non-bullet lines
    text = re.sub(r'(?<=\S)\n([-•] )', r'\n\n\1', text)
    # Top-level bullets: cyan dot
    text = re.sub(r'^[-•] (.+)$', f'{CYAN}•{NC} \\1', text, flags=re.MULTILINE)
    # Sub-bullets (indented): dim arrow, clean indent
    text = re.sub(r'^(\s+)[-•] (.+)$', f'  {DIM}→{NC} \\2', text, flags=re.MULTILINE)

    # Horizontal rules (---) - dim line
    text = re.sub(r'^-{3,}$', f'{DIM}───────────────────────────────{NC}', text, flags=re.MULTILINE)

    return text

# ============================================================================
# Render with glow (or fallback)
# ============================================================================

def render_table_with_glow(table_text):
    """Render a markdown table using glow for nice Unicode output."""
    import shutil
    import subprocess

    glow_path = shutil.which('glow')
    if not glow_path:
        return None

    try:
        result = subprocess.run(
            [glow_path, '-s', 'dark', '-w', str(get_terminal_width() - 4), '-'],
            input=table_text,
            capture_output=True,
            text=True,
            timeout=3
        )

        if result.returncode == 0 and len(result.stdout.strip()) > 10:
            # Return glow output, stripped of extra whitespace
            return result.stdout.rstrip()
    except:
        pass

    return None


def render_hybrid(text):
    """Hybrid rendering: glow for tables, markdown_to_ansi for everything else."""
    lines = text.split('\n')
    result_parts = []
    current_text = []
    table_buffer = []
    in_table = False

    for line in lines:
        stripped = line.strip()

        # Detect markdown table (lines with | ... |)
        is_table_line = bool(re.match(r'^\|.*\|$', stripped)) or bool(re.match(r'^\|?[\s:-]+\|[\s:-|]+$', stripped))

        if is_table_line:
            # Starting or continuing a table
            if not in_table and current_text:
                # Flush current text before table
                result_parts.append(('text', '\n'.join(current_text)))
                current_text = []
            in_table = True
            table_buffer.append(line)
        else:
            if in_table:
                # End of table - render it with glow
                table_text = '\n'.join(table_buffer)
                glow_output = render_table_with_glow(table_text)
                if glow_output:
                    result_parts.append(('glow_table', glow_output))
                else:
                    # Fallback: add table as text
                    result_parts.append(('text', table_text))
                table_buffer = []
                in_table = False

            current_text.append(line)

    # Handle remaining content
    if in_table and table_buffer:
        table_text = '\n'.join(table_buffer)
        glow_output = render_table_with_glow(table_text)
        if glow_output:
            result_parts.append(('glow_table', glow_output))
        else:
            result_parts.append(('text', table_text))

    if current_text:
        result_parts.append(('text', '\n'.join(current_text)))

    # Now render each part appropriately
    final_output = []
    for part_type, content in result_parts:
        if part_type == 'glow_table':
            final_output.append(content)
        else:
            # Use markdown_to_ansi for non-table content
            final_output.append(markdown_to_ansi(content))

    # Combine, wrap to terminal width, and add indentation
    formatted = '\n'.join(final_output)
    formatted = wrap_ansi_text(formatted)
    formatted = "  " + formatted.replace("\n", "\n  ")
    sys.stderr.write(formatted)
    sys.stderr.flush()

# ============================================================================
# Spinner class
# ============================================================================

class Spinner:
    def __init__(self):
        self.running = False
        self.message = ""
        self.thread = None
        self.frame = 0
        self.start_time = None

    def start(self, message=""):
        self.message = message
        self.running = True
        self.start_time = time.time()
        self.frame = 0
        sys.stderr.write(HIDE_CURSOR)
        self.thread = threading.Thread(target=self._spin, daemon=True)
        self.thread.start()

    def _spin(self):
        while self.running:
            frame = SPINNER[self.frame % len(SPINNER)]
            elapsed = time.time() - self.start_time
            line = f"{CURSOR_START}{CLEAR_LINE}  {CYAN}{frame}{NC} {self.message} {DIM}({elapsed:.1f}s){NC}"
            sys.stderr.write(line)
            sys.stderr.flush()
            self.frame += 1
            time.sleep(0.08)

    def update(self, message):
        self.message = message

    def stop(self, final_message=None, status="success"):
        self.running = False
        if self.thread:
            self.thread.join(timeout=0.2)

        # ALWAYS ensure cursor is visible and line is cleared
        try:
            sys.stderr.write(f"{CURSOR_START}{CLEAR_LINE}{SHOW_CURSOR}")
            sys.stderr.flush()
        except:
            pass  # Ignore errors if stderr is closed

        if final_message:
            elapsed = time.time() - self.start_time if self.start_time else 0
            if status == "success":
                icon = f"{GREEN}✓{NC}"
            elif status == "error":
                icon = f"{RED}✗{NC}"
            else:
                icon = f"{CYAN}ℹ{NC}"
            sys.stderr.write(f"  {icon} {final_message} {DIM}({elapsed:.1f}s){NC}\n")

        sys.stderr.flush()

# ============================================================================
# Main processing
# ============================================================================

endpoint = sys.argv[1]
access_token = sys.argv[2]
tmp_payload = sys.argv[3]

with open(tmp_payload) as f:
    payload = f.read().strip()

# Initialize
spinner = Spinner()
start_time = time.time()
tools_executed = 0
got_complete_event = False  # Track if we received the 'complete' event from server

# Check if we need to clear previous tool output lines
tool_lines_to_clear = int(os.environ.get('TURIA_TOOL_OUTPUT_LINES', '0'))
if tool_lines_to_clear > 0:
    # Clear the environment variable so it's not used again
    os.environ['TURIA_TOOL_OUTPUT_LINES'] = '0'

# Kill bash typing indicator if running (from agent_chat.sh)
typing_pid = os.environ.get('TURIA_TYPING_PID')
if typing_pid:
    try:
        os.kill(int(typing_pid), 9)  # SIGKILL
        # Clear the line left by bash spinner
        sys.stderr.write("\r\033[2K")
        sys.stderr.flush()
    except:
        pass  # Process already dead or invalid PID

# Start spinner immediately (before curl connects)
spinner.start("Conectando con el servidor...")

# Run curl and process stream
proc = subprocess.Popen(
    ["curl", "-s", "-N", "-X", "POST", endpoint,
     "-H", "Content-Type: application/json",
     "-H", f"Authorization: Bearer {access_token}",
     "-d", payload],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    bufsize=1  # Line buffered for real-time output
)

event_type = None
texts = []
streaming_text = False  # Track if we're in text streaming mode
header_shown = False  # Track if Agent header was already printed
rendered_chars = 0  # Track how many chars of text have been rendered (for incremental streaming)
rag_indicator_for_header = ""  # RAG indicator to show in Agent header
result = {
    "conversation_id": None,
    "total_cost": 0,
    "total_tokens": 0,
    "max_iterations_reached": False,
    "response": "",
    "error": None,
    "tool_requests": None,
    "elapsed_time": 0,
    "tools_count": 0
}

try:
    first_line = True
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue

        # Check for HTTP error response (JSON without SSE format)
        if first_line and not line.startswith("event:") and not line.startswith("data:"):
            first_line = False
            # Try to parse as JSON error
            try:
                error_data = json.loads(line)
                error_msg = None

                # Handle array of errors (FastAPI validation errors)
                if isinstance(error_data, list) and error_data:
                    error_msg = error_data[0].get("message", str(error_data))
                # Handle object with detail, error, or message
                elif isinstance(error_data, dict):
                    if "detail" in error_data or "error" in error_data or "message" in error_data:
                        error_msg = error_data.get("detail") or error_data.get("error") or error_data.get("message", "Error del servidor")
                        # Handle list inside detail
                        if isinstance(error_msg, list):
                            error_msg = error_msg[0].get("message", str(error_msg)) if error_msg else "Error del servidor"

                if error_msg:
                    result["error"] = str(error_msg)
                    spinner.stop(f"Error: {result['error']}", "error")
                    break
            except:
                pass
        first_line = False

        if line.startswith("event:"):
            event_type = line[7:].strip()
            continue

        if line.startswith("data:"):
            data = line[6:].strip()
            try:
                parsed = json.loads(data)
            except json.JSONDecodeError as e:
                # Log JSON parse errors for debugging
                sys.stderr.write(f"\n  {YELLOW}⚠ JSON parse error:{NC} {str(e)[:50]}\n")
                sys.stderr.flush()
                continue

            if event_type == "started":
                result["conversation_id"] = parsed.get("conversation_id")
                result["rag_enabled"] = parsed.get("rag_enabled", False)
                result["model"] = parsed.get("model", {})
                result["task_type"] = parsed.get("task_type", "")
                conv_id = parsed.get("conversation_id")
                rag_enabled = parsed.get("rag_enabled", False)
                rag_info = parsed.get("rag", {})
                model_info = parsed.get("model", {})
                model_name = model_info.get("model", "")

                # Build RAG indicator based on scope (save for later display)
                rag_indicator_for_header = ""
                if rag_enabled and rag_info:
                    rag_scope = rag_info.get("scope", "current")
                    rag_chunks = rag_info.get("chunks", 0)
                    rag_projects = rag_info.get("projects", "")
                    if rag_scope == "related":
                        # Multi-project RAG - show with special indicator
                        rag_indicator = f" {CYAN}[RAG:{rag_chunks} multi-proyecto]{NC}"
                        rag_indicator_for_header = f" {CYAN}[RAG:{rag_chunks} multi-proyecto]{NC}"
                    else:
                        rag_indicator = f" {GREEN}[RAG:{rag_chunks}]{NC}"
                        rag_indicator_for_header = f" {GREEN}[RAG:{rag_chunks}]{NC}"
                elif rag_enabled:
                    rag_indicator = f" {GREEN}[RAG]{NC}"
                    rag_indicator_for_header = f" {GREEN}[RAG]{NC}"
                else:
                    rag_indicator = ""

                model_indicator = f" {DIM}({model_name}){NC}" if model_name else ""
                spinner.start(f"Conversacion #{conv_id}{rag_indicator}{model_indicator}")

            elif event_type == "thinking":
                model_info = parsed.get("model", {})
                model_name = model_info.get("model", "")
                if model_name:
                    spinner.update(f"Pensando... {DIM}({model_name}){NC}")
                else:
                    spinner.update("Pensando...")

            elif event_type == "rag_search":
                # RAG search initiated - show what the LLM is searching for
                search_query = parsed.get("query", "")[:60]
                search_project = parsed.get("project_type", "")
                project_label = f" @{search_project}" if search_project else ""

                spinner.stop()
                sys.stderr.write(f"  {TOOL_COLOR}🔍 Buscando{project_label}: \"{search_query}...\"{NC}\n")
                spinner.start("Buscando en codebase...")

            elif event_type == "rag_context":
                # RAG context event - show results found
                rag_chunks = parsed.get("chunks", 0)
                rag_scope = parsed.get("scope", "current")
                rag_projects = parsed.get("projects", "")
                rag_project_type = parsed.get("project_type", "")

                # Build visible RAG indicator
                if rag_scope == "related":
                    rag_indicator_for_header = f" {CYAN}[RAG:{rag_chunks} multi-proyecto]{NC}"
                else:
                    project_label = f" @{rag_project_type}" if rag_project_type and rag_project_type != "current" else ""
                    rag_indicator_for_header = f" {GREEN}[RAG:{rag_chunks}{project_label}]{NC}"

                # Show results count
                spinner.stop()
                if rag_chunks > 0:
                    sys.stderr.write(f"  {GREEN}✓{NC} {TOOL_COLOR}Encontrados {rag_chunks} chunks relevantes{NC}\n")
                else:
                    sys.stderr.write(f"  {YELLOW}○{NC} {TOOL_COLOR}No se encontraron chunks relevantes{NC}\n")
                spinner.start("Procesando respuesta...")

            elif event_type == "delegation":
                # Subagent delegation event
                subagent_id = parsed.get("subagent_id", "")
                task_preview = parsed.get("task", "")[:80]
                if len(parsed.get("task", "")) > 80:
                    task_preview += "..."
                spinner.stop()
                sys.stderr.write(f"  {TOOL_COLOR}👤 Delegando a subagente: {NC}{BOLD}{subagent_id}{NC}\n")
                sys.stderr.write(f"  {TOOL_COLOR}Tarea: {task_preview}{NC}\n")
                spinner.start(f"Subagente {subagent_id} trabajando...")

            elif event_type == "text":
                content = parsed.get("content", "")
                msg_model = parsed.get("model", "")
                if content:
                    # First text chunk - show header and start streaming
                    if not streaming_text:
                        streaming_text = True
                        result["msg_model"] = msg_model
                        spinner.stop()

                        # Clear previous tool output lines
                        if tool_lines_to_clear > 0:
                            for _ in range(tool_lines_to_clear):
                                sys.stderr.write(f"\033[A\033[2K")
                            sys.stderr.flush()
                            tool_lines_to_clear = 0

                        # Print header once
                        model_tag = f" {DIM}({msg_model}){NC}" if msg_model else ""
                        if not header_shown:
                            sys.stderr.write(f"\n  {BOLD}{GREEN}Agent:{NC}{model_tag}{rag_indicator_for_header}\n\n")
                            header_shown = True

                    # Stream text in real-time with markdown conversion
                    texts.append(content)
                    # Render incrementally: process complete lines
                    full_so_far = "".join(texts)
                    lines = full_so_far.split('\n')
                    # Keep last incomplete line in buffer, render complete lines
                    if len(lines) > 1:
                        complete_lines = '\n'.join(lines[:-1])
                        # Only render new lines we haven't shown yet
                        new_content = complete_lines[rendered_chars:]
                        if new_content:
                            # Apply markdown formatting and word wrap
                            formatted = markdown_to_ansi(new_content)
                            formatted = wrap_ansi_text(formatted)
                            formatted = "  " + formatted.replace("\n", "\n  ")
                            sys.stderr.write(formatted + "\n")
                            sys.stderr.flush()
                            rendered_chars = len(complete_lines) + 1  # +1 for the \n

            elif event_type == "tool_requests":
                tool_calls = parsed.get("tool_calls", [])
                result["tool_requests"] = tool_calls
                result["conversation_id"] = parsed.get("conversation_id")
                tools_executed = len(tool_calls)

                # Capture session info from tool_requests
                result["session_cost"] = parsed.get("session_cost", 0)
                result["session_tokens"] = parsed.get("session_input_tokens", 0) + parsed.get("session_output_tokens", 0)

                # Flush any remaining buffered text before tools
                if texts:
                    spinner.stop()
                    full_text = "".join(texts)
                    remaining = full_text[rendered_chars:]
                    if remaining.strip():
                        if not header_shown:
                            msg_model = result.get("msg_model", "")
                            model_tag = f" {DIM}({msg_model}){NC}" if msg_model else ""
                            sys.stderr.write(f"\n  {BOLD}{YELLOW}Agent:{NC}{model_tag}{rag_indicator_for_header}\n\n")
                            header_shown = True
                        formatted = markdown_to_ansi(remaining)
                        formatted = wrap_ansi_text(formatted)
                        formatted = "  " + formatted.replace("\n", "\n  ")
                        sys.stderr.write(formatted + "\n")
                        sys.stderr.flush()
                    rendered_chars = len(full_text)
                    texts.clear()

                if streaming_text:
                    sys.stderr.write("\n")
                    sys.stderr.flush()
                spinner.stop()

            elif event_type == "complete":
                got_complete_event = True
                result["conversation_id"] = parsed.get("conversation_id")
                result["total_cost"] = parsed.get("total_cost", 0)
                result["total_tokens"] = parsed.get("total_input_tokens", 0) + parsed.get("total_output_tokens", 0)
                result["session_cost"] = parsed.get("session_cost", 0)
                result["session_tokens"] = parsed.get("session_input_tokens", 0) + parsed.get("session_output_tokens", 0)
                # Internal LLM cost (compaction, classifier, RAG enhancer, …)
                # tracked separately so the user sees the FULL spend.
                result["session_internal_cost"] = parsed.get("session_internal_cost", 0)
                result["total_internal_cost"] = parsed.get("total_internal_cost", 0)
                result["max_iterations_reached"] = parsed.get("max_iterations_reached", False)
                result["truncation_stats"] = parsed.get("truncation_stats", {})

                # Flush any remaining buffered text
                if texts:
                    spinner.stop()
                    full_text = "".join(texts)
                    remaining = full_text[rendered_chars:]
                    if remaining.strip():
                        if not header_shown:
                            msg_model = result.get("msg_model", "")
                            model_tag = f" {DIM}({msg_model}){NC}" if msg_model else ""
                            sys.stderr.write(f"\n  {BOLD}{YELLOW}Agent:{NC}{model_tag}{rag_indicator_for_header}\n\n")
                            header_shown = True
                        formatted = markdown_to_ansi(remaining)
                        formatted = wrap_ansi_text(formatted)
                        formatted = "  " + formatted.replace("\n", "\n  ")
                        sys.stderr.write(formatted)
                    sys.stderr.write("\n")
                    sys.stderr.flush()
                    texts.clear()
                elif streaming_text:
                    sys.stderr.write("\n")
                    sys.stderr.flush()
                else:
                    spinner.stop()

            elif event_type == "cost_warning":
                # User is approaching their cost limit
                usage_pct = parsed.get("usage_percent", 0)
                remaining = parsed.get("remaining", "?")
                monthly_limit = parsed.get("monthly_limit", "?")
                result["cost_warning"] = True
                result["cost_usage_percent"] = usage_pct
                # Show inline warning but continue processing
                sys.stderr.write(f"\n  {YELLOW}⚠️  Has usado {usage_pct:.0f}% de tu límite mensual (${remaining} restante de ${monthly_limit}){NC}\n")
                sys.stderr.flush()

            elif event_type == "cost_limit_exceeded":
                # User has exceeded their cost limit - request blocked
                result["cost_limit_exceeded"] = True
                result["cost_current"] = parsed.get("current_cost", "?")
                result["cost_limit"] = parsed.get("monthly_limit", "?")
                spinner.stop(f"❌ Límite de coste mensual alcanzado (${result['cost_current']} / ${result['cost_limit']})", "error")

            elif event_type == "rate_limited":
                result["rate_limited"] = True
                result["rate_limit_message"] = parsed.get("message", "Rate limit alcanzado")
                result["conversation_id"] = parsed.get("conversation_id")
                spinner.stop(f"⚠️ {result['rate_limit_message']}", "info")

            elif event_type == "provider_fallback":
                # Provider switched due to error (credits, rate limit, etc.)
                failed_provider = parsed.get("failed_provider", "?")
                new_provider = parsed.get("new_provider", "?")
                new_model = parsed.get("new_model", "")
                reason = parsed.get("reason", "error")
                message = parsed.get("message", f"Cambiando de {failed_provider} a {new_provider}")

                result["provider_fallback"] = True
                result["failed_provider"] = failed_provider
                result["new_provider"] = new_provider

                # Show warning about provider switch
                spinner.stop()
                if reason == "insufficient_credits":
                    sys.stderr.write(f"  {YELLOW}💳 {failed_provider} sin créditos{NC} → {GREEN}Usando {new_provider}{NC}")
                    if new_model:
                        sys.stderr.write(f" {DIM}({new_model}){NC}")
                    sys.stderr.write("\n")
                else:
                    sys.stderr.write(f"  {YELLOW}⚠️ {message}{NC}\n")
                sys.stderr.flush()
                spinner.start(f"Procesando con {new_provider}...")

            elif event_type == "no_providers_available":
                # All providers failed (no fallback or all have issues)
                providers_tried = parsed.get("providers_tried", [])
                message = parsed.get("message", "No hay proveedores disponibles")
                result["no_providers_available"] = True
                result["providers_tried"] = providers_tried
                spinner.stop()
                sys.stderr.write(f"\n  {RED}❌ {message}{NC}\n")
                if providers_tried:
                    sys.stderr.write(f"  {DIM}Proveedores intentados: {', '.join(providers_tried)}{NC}\n")
                sys.stderr.write(f"  {YELLOW}💡 Opciones:{NC}\n")
                sys.stderr.write(f"     - Recarga créditos en el proveedor\n")
                sys.stderr.write(f"     - Configura un proveedor alternativo\n")
                sys.stderr.write(f"     - Usa /model para seleccionar otro modelo\n")
                sys.stderr.flush()

            elif event_type == "repaired":
                # Conversation was repaired due to interrupted session
                # Show as warning - conversation may continue processing
                result["repaired"] = True
                result["repaired_message"] = parsed.get("message", "Conversation repaired")
                # Show message but restart spinner (more events may come)
                spinner.stop(f"⚠️ Conversacion recuperada (estaba interrumpida)", "info")
                spinner.start("Continuando...")

            elif event_type == "internal_call":
                # Internal LLM call completed (compaction, task classifier,
                # RAG enhancer, subagent, …). Show a one-liner so the user
                # sees where time/cost is going. The cost is NOT in
                # session_cost — it's in session_internal_cost (complete event).
                ic_caller = parsed.get("caller", "internal")
                ic_model = parsed.get("model_id", "")
                ic_cost = parsed.get("cost", 0.0)
                ic_tokens = (
                    parsed.get("input_tokens", 0)
                    + parsed.get("output_tokens", 0)
                    + parsed.get("cache_creation_tokens", 0)
                    + parsed.get("cache_read_tokens", 0)
                )

                ic_labels = {
                    "compaction": ("🧠", "Compactando contexto"),
                    "rag_enhancer_or_classifier": ("🏷 ", "Clasificando tarea"),
                    "rag_architecture_guide": ("📐", "Analizando arquitectura"),
                    "subagent": ("🤖", "Subagente trabajando"),
                    "subagent_fallback": ("🤖", "Subagente trabajando"),
                    "llm_router": ("🔀", "Enrutando modelo"),
                    "llm_router_fallback": ("🔀", "Enrutando modelo"),
                }
                ic_emoji, ic_label = ic_labels.get(ic_caller, ("⚙", ic_caller))

                ic_was_spinning = spinner.running
                if ic_was_spinning:
                    spinner.stop()

                ic_cost_tag = f" {DIM}· ${ic_cost:.3f}{NC}" if ic_cost > 0 else ""
                sys.stderr.write(
                    f"  {DIM}{ic_emoji} {ic_label}{NC}{ic_cost_tag}\n"
                )
                sys.stderr.flush()

                if ic_was_spinning:
                    spinner.start("Pensando...")

            elif event_type == "error":
                result["error"] = parsed.get("error", "Unknown error")
                spinner.stop(f"Error: {result['error']}", "error")

except KeyboardInterrupt:
    spinner.stop("Cancelado", "error")
    proc.terminate()
except Exception as e:
    # Capture any unexpected errors
    spinner.stop(f"Error inesperado: {str(e)[:50]}", "error")
    result["error"] = f"Error de procesamiento: {str(e)}"
finally:
    # ALWAYS ensure cursor is visible and spinner is stopped
    sys.stderr.write(SHOW_CURSOR)
    sys.stderr.flush()
    if spinner.running:
        spinner.stop()

proc.wait()

# Check if stream ended without proper completion
if not result.get("error") and not got_complete_event and not result.get("tool_requests"):
    # Server disconnected without sending 'complete' event
    result["error"] = "El servidor cerro la conexion sin completar la respuesta"
    sys.stderr.write(f"\n  {RED}✗{NC} El servidor cerro la conexion sin completar\n")
    sys.stderr.write(f"  {DIM}La respuesta puede estar incompleta. Intenta de nuevo.{NC}\n")
    sys.stderr.flush()
    # If we have partial text, include it in the response anyway
    if texts:
        result["response"] = "".join(texts)
        result["partial"] = True

# Calculate elapsed time
result["elapsed_time"] = round(time.time() - start_time, 2)
result["tools_count"] = tools_executed
result["text_streamed"] = streaming_text  # Flag to indicate text was already shown

# Combine all text responses
result["response"] = "".join(texts) if texts else ""

# Cleanup and output
import os
os.unlink(tmp_payload)
print(json.dumps(result))
PYEOF
}

# ============================================================================
# LOCAL TOOL EXECUTION
# ============================================================================

# Execute tools locally and return results
execute_tools_locally() {
    local tool_requests="$1"
    local request_start_time="${2:-$(date +%s)}"  # Start time for total elapsed

    # Guardar tool_requests en archivo temporal
    local tmp_requests=$(mktemp)
    echo "$tool_requests" > "$tmp_requests"

    python3 - "$tmp_requests" "$AGENT_SCRIPT_DIR" "$request_start_time" << 'PYEOF'
import json
import subprocess
import sys
import os
import time
import threading
import concurrent.futures
import tempfile

# ============================================================================
# UI Configuration
# ============================================================================

BOLD = "\033[1m"
DIM = "\033[2m"
NC = "\033[0m"
RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
BLUE = "\033[0;34m"
CYAN = "\033[0;36m"
TOOL_COLOR = "\033[0;90m"    # Dark gray for tool activity

HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"
CLEAR_LINE = "\033[2K"
CURSOR_START = "\r"

SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

TOOL_ICONS = {
    "read_file": "📖",
    "write_file": "✏️",
    "edit_file": "✏️",
    "list_files": "📁",
    "search_code": "🔍",
    "run_command": "⌘",
    "git_info": "🔀",
}

# Action verbs for clearer display
TOOL_VERBS = {
    "read_file": "Leyendo",
    "write_file": "Escribiendo",
    "edit_file": "Editando",
    "list_files": "Listando",
    "search_code": "Buscando",
    "run_command": "Ejecutando",
    "git_info": "Git",
}

# ============================================================================
# Keyboard monitor for ESC abort and inline input capture
# ============================================================================

import select
import termios
import tty

class KeyboardMonitor:
    """Monitor for ESC key to abort tool execution."""

    def __init__(self):
        self.aborted = False
        self.old_settings = None

    def start(self):
        """Start monitoring (set terminal to raw mode)."""
        try:
            self.old_settings = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())
        except:
            pass  # Not a TTY, ignore

    def stop(self):
        """Stop monitoring (restore terminal settings)."""
        if self.old_settings:
            try:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.old_settings)
            except:
                pass

    def pause(self):
        """Temporarily restore normal terminal mode (for subprocess input)."""
        if self.old_settings:
            try:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.old_settings)
            except:
                pass

    def resume(self):
        """Re-enable cbreak mode after subprocess completes."""
        try:
            tty.setcbreak(sys.stdin.fileno())
        except:
            pass

    def get_buffered_input(self):
        """Return empty string - inline input disabled for now."""
        return ""

    def check_abort(self):
        """Check if ESC was pressed (non-blocking)."""
        if self.aborted:
            return True
        try:
            while select.select([sys.stdin], [], [], 0)[0]:
                ch = sys.stdin.read(1)
                if ch == '\x1b':  # ESC key
                    self.aborted = True
                    return True
                # Ignore other keys for now
        except:
            pass
        return False

# ============================================================================
# Spinner for tool execution
# ============================================================================

class ToolSpinner:
    def __init__(self):
        self.running = False
        self.message = ""
        self.thread = None
        self.frame = 0
        self.start_time = None

    def start(self, message=""):
        self.message = message
        self.running = True
        self.start_time = time.time()
        self.frame = 0
        sys.stderr.write(HIDE_CURSOR)
        self.thread = threading.Thread(target=self._spin, daemon=True)
        self.thread.start()

    def _spin(self):
        while self.running:
            frame = SPINNER[self.frame % len(SPINNER)]
            elapsed = time.time() - self.start_time
            line = f"{CURSOR_START}{CLEAR_LINE}    {TOOL_COLOR}{frame} {self.message} ({elapsed:.1f}s){NC}"
            sys.stderr.write(line)
            sys.stderr.flush()
            self.frame += 1
            time.sleep(0.08)

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=0.2)
        sys.stderr.write(f"{CURSOR_START}{CLEAR_LINE}{SHOW_CURSOR}")
        sys.stderr.flush()
        return time.time() - self.start_time if self.start_time else 0

# ============================================================================
# Read file cache (persisted across subprocess calls via JSON file)
# ============================================================================

PARALLEL_SAFE_TOOLS = {"read_file", "search_code", "list_files", "git_info"}
SEQUENTIAL_TOOLS = {"write_file", "edit_file", "run_command"}

def _get_cache_path():
    """Get session-specific cache file path."""
    approve_dir = os.environ.get("TURIA_AUTO_APPROVE_DIR", "")
    if approve_dir:
        return os.path.join(approve_dir, "read_file_cache.json")
    return None

def _load_cache():
    """Load read_file cache from disk."""
    cache_path = _get_cache_path()
    if cache_path and os.path.exists(cache_path):
        try:
            with open(cache_path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}

def _save_cache(cache):
    """Save read_file cache to disk."""
    cache_path = _get_cache_path()
    if cache_path:
        try:
            with open(cache_path, "w") as f:
                json.dump(cache, f)
        except IOError:
            pass

def _invalidate_cache_path(cache, path):
    """Remove a path from cache (called when write_file/edit_file modifies it)."""
    # Normalize path for matching
    abs_path = os.path.abspath(path)
    keys_to_remove = [k for k in cache if os.path.abspath(k) == abs_path]
    for k in keys_to_remove:
        del cache[k]

def _get_tool_detail(tc_name, tc_input):
    """Extract display detail and action message for a tool call."""
    icon = TOOL_ICONS.get(tc_name, "⚡")
    verb = TOOL_VERBS.get(tc_name, tc_name)

    if tc_name == "read_file":
        path = tc_input.get("path", "")
        filename = os.path.basename(path) if path else ""
        detail = filename or path
        action_msg = f"{verb} {filename}"
    elif tc_name == "write_file":
        path = tc_input.get("path", "")
        filename = os.path.basename(path) if path else ""
        detail = filename or path
        action_msg = f"{verb} {filename}"
    elif tc_name == "edit_file":
        path = tc_input.get("path", "")
        filename = os.path.basename(path) if path else ""
        detail = filename or path
        action_msg = f"{verb} {filename}"
    elif tc_name == "list_files":
        path = tc_input.get("path", ".")
        pattern = tc_input.get("pattern", "*")
        detail = f"{path}/{pattern}"
        action_msg = f"{verb} {pattern}"
    elif tc_name == "search_code":
        query = tc_input.get("query", "")[:30]
        detail = f'"{query}"'
        action_msg = f'{verb} "{query}"'
    elif tc_name == "run_command":
        cmd = tc_input.get("command", "")
        cmd_name = cmd.split()[0] if cmd else ""
        detail = cmd[:40] + "..." if len(cmd) > 40 else cmd
        action_msg = f"{verb} {cmd_name}"
    elif tc_name == "git_info":
        git_type = tc_input.get("type", "status")
        detail = git_type
        action_msg = f"{verb} {git_type}"
    else:
        detail = str(tc_input)[:40]
        action_msg = f"{verb} {tc_name}"

    return icon, verb, detail, action_msg

def _execute_tool(tc_name, tc_input, agent_script_dir, cache=None):
    """Execute a single tool and return (output, success). For parallel-safe tools only."""
    # Check read_file cache
    if tc_name == "read_file" and cache is not None:
        path = tc_input.get("path", "")
        if path in cache:
            return cache[path], True

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tf:
        tf.write(json.dumps(tc_input))
        input_file = tf.name

    try:
        cmd = f'source "{agent_script_dir}/agent_local_tools.sh" && execute_tool_locally "{tc_name}" "{input_file}"'
        tool_timeout = 120
        result = subprocess.run(
            ["bash", "-c", cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            text=True,
            timeout=tool_timeout,
            env={**os.environ, "AGENT_SCRIPT_DIR": agent_script_dir}
        )
        output = result.stdout or "Sin resultado"
        success = result.returncode == 0 and not output.startswith("Error:")
    except subprocess.TimeoutExpired:
        output = "Error: Timeout ejecutando tool (120s)"
        success = False
    except Exception as e:
        output = f"Error: {str(e)}"
        success = False
    finally:
        os.unlink(input_file)

    # Truncate long output
    if len(output) > 10000:
        output = output[:10000] + "\n... [truncado]"

    # Update read_file cache on success
    if tc_name == "read_file" and success and cache is not None:
        path = tc_input.get("path", "")
        if path:
            cache[path] = output

    return output, success

# ============================================================================
# Main processing
# ============================================================================

tmp_file = sys.argv[1]
agent_script_dir = sys.argv[2]
request_start_time = int(sys.argv[3]) if len(sys.argv) > 3 else int(time.time())

with open(tmp_file) as f:
    tool_requests = json.load(f)

# Results indexed by original position
results = [None] * len(tool_requests)
total_tools = len(tool_requests)
aborted = False

# Calculate total elapsed time
total_elapsed = int(time.time()) - request_start_time

# Track lines output for later clearing
tool_output_lines = 0
tool_type_counts = {}
failed_tools = []
batch_start_time = time.time()

# Load read_file cache
read_cache = _load_cache()

# Separate into parallel-safe and sequential groups, preserving original indices
parallel_tasks = []  # list of (original_index, tc)
sequential_tasks = []  # list of (original_index, tc)

for idx, tc in enumerate(tool_requests):
    if tc["name"] in PARALLEL_SAFE_TOOLS:
        parallel_tasks.append((idx, tc))
    else:
        sequential_tasks.append((idx, tc))

# --- Execute parallel-safe tools concurrently ---
if parallel_tasks:
    parallel_count = len(parallel_tasks)

    # Show what tools are about to run (detailed feedback)
    tool_descriptions = []
    for _, tc in parallel_tasks:
        icon, verb, detail, action_msg = _get_tool_detail(tc["name"], tc["input"])
        tool_descriptions.append(f"{icon} {action_msg}")

    spinner = ToolSpinner()
    # Show first 3 tool descriptions in spinner
    desc_preview = " · ".join(tool_descriptions[:3])
    if len(tool_descriptions) > 3:
        desc_preview += f" · +{len(tool_descriptions) - 3} más"
    spinner.start(desc_preview)

    def _run_parallel_tool(item):
        orig_idx, tc = item
        tc_name = tc["name"]
        tc_input = tc["input"]
        output, success = _execute_tool(tc_name, tc_input, agent_script_dir, cache=read_cache)
        return orig_idx, tc, output, success

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(parallel_count, 8)) as executor:
        futures = {executor.submit(_run_parallel_tool, item): item for item in parallel_tasks}
        for future in concurrent.futures.as_completed(futures):
            orig_idx, tc, output, success = future.result()
            tc_name = tc["name"]
            tc_input = tc["input"]
            icon, verb, detail, action_msg = _get_tool_detail(tc_name, tc_input)

            # Track tool types
            tool_type_counts[tc_name] = tool_type_counts.get(tc_name, 0) + 1
            if not success:
                failed_tools.append(f"{RED}✗ {verb} {detail}{NC}")

            results[orig_idx] = {
                "tool_call_id": tc["id"],
                "tool_name": tc_name,
                "result": output
            }

    spinner.stop()

    # Show compact summary with tool details
    parallel_elapsed = time.time() - batch_start_time
    has_parallel_errors = any(
        results[orig_idx] and results[orig_idx]["result"].startswith("Error:")
        for orig_idx, _ in parallel_tasks
        if results[orig_idx]
    )
    status = f"{GREEN}✓{NC}" if not has_parallel_errors else f"{YELLOW}⚠{NC}"

    # Show each tool with its detail on one line
    for _, tc in parallel_tasks:
        icon, verb, detail, action_msg = _get_tool_detail(tc["name"], tc["input"])
        sys.stderr.write(f"  {status} {TOOL_COLOR}{icon} {action_msg}{NC}\n")
        tool_output_lines += 1

    # Show timing
    sys.stderr.write(f"  {TOOL_COLOR}  ⎿ {parallel_count} herramientas en {parallel_elapsed:.1f}s{NC}\n")
    tool_output_lines += 1

    # Show any failed parallel tools
    for fail_line in failed_tools:
        sys.stderr.write(f"  {fail_line}\n")
        tool_output_lines += 1
    sys.stderr.flush()

# --- Execute sequential tools one by one ---
seq_start_idx = len(parallel_tasks)  # for progress display
for seq_num, (orig_idx, tc) in enumerate(sequential_tasks, 1):
    tc_id = tc["id"]
    tc_name = tc["name"]
    tc_input = tc["input"]

    icon, verb, detail, action_msg = _get_tool_detail(tc_name, tc_input)

    # Track start time for this tool
    tool_start_time = time.time()

    # Show spinner with current tool
    spinner = ToolSpinner()
    progress_indicator = f"({seq_start_idx + seq_num}/{total_tools}) " if total_tools > 1 else ""
    spinner.start(f"{progress_indicator}{icon} {action_msg}")

    # Write input to temp file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tf:
        tf.write(json.dumps(tc_input))
        input_file = tf.name

    try:
        cmd = f'source "{agent_script_dir}/agent_local_tools.sh" && execute_tool_locally "{tc_name}" "{input_file}"'
        spinner.stop()
        # Interactive tools (write/edit/run) may wait for user confirmation — longer timeout
        tool_timeout = 600 if tc_name in ("write_file", "edit_file", "run_command") else 120
        result = subprocess.run(
            ["bash", "-c", cmd],
            stdout=subprocess.PIPE,
            stderr=None,
            stdin=sys.stdin,
            text=True,
            timeout=tool_timeout,
            env={**os.environ, "AGENT_SCRIPT_DIR": agent_script_dir}
        )
        output = result.stdout or "Sin resultado"
        success = result.returncode == 0 and not output.startswith("Error:")
    except subprocess.TimeoutExpired:
        output = "Error: Timeout ejecutando tool (120s)"
        success = False
    except Exception as e:
        output = f"Error: {str(e)}"
        success = False
    finally:
        os.unlink(input_file)
        # Reset terminal settings on /dev/tty in case subprocess left it in raw mode
        os.system('stty sane < /dev/tty 2>/dev/null')
        sys.stderr.write(SHOW_CURSOR)
        sys.stderr.flush()

    tool_elapsed = time.time() - tool_start_time

    # Truncate long output
    if len(output) > 10000:
        output = output[:10000] + "\n... [truncado]"

    # Invalidate read cache when write_file or edit_file modifies a path
    if tc_name in ("write_file", "edit_file") and success:
        modified_path = tc_input.get("path", "")
        if modified_path:
            _invalidate_cache_path(read_cache, modified_path)

    # Track tool types for summary and errors for inline display
    tool_type_counts[tc_name] = tool_type_counts.get(tc_name, 0) + 1
    if not success:
        failed_tools.append(f"{RED}✗ {verb} {detail}{NC}")

    # Show individual lines for write/edit operations and errors
    if tc_name in ("write_file", "edit_file"):
        status_icon = f"{GREEN}✓{NC}" if success else f"{RED}✗{NC}"
        elapsed_str = f" {TOOL_COLOR}({tool_elapsed:.1f}s){NC}" if tool_elapsed > 0.5 else ""
        sys.stderr.write(f"  {status_icon} {TOOL_COLOR}{verb:<12} {detail}{NC}{elapsed_str}\n")
        tool_output_lines += 1
    elif tc_name == "run_command":
        status_icon = f"{GREEN}✓{NC}" if success else f"{RED}✗{NC}"
        elapsed_str = f" {TOOL_COLOR}({tool_elapsed:.1f}s){NC}" if tool_elapsed > 0.5 else ""
        sys.stderr.write(f"  {status_icon} {TOOL_COLOR}{verb:<12} {detail}{NC}{elapsed_str}\n")
        tool_output_lines += 1
        if not success:
            # Show error preview for failed commands
            preview = output[:80].replace("\n", " ").strip()
            sys.stderr.write(f"    {TOOL_COLOR}→ {preview}{NC}\n")
            tool_output_lines += 1
    elif not success:
        sys.stderr.write(f"  {RED}✗ {TOOL_COLOR}{verb:<12} {detail}{NC}\n")
        tool_output_lines += 1

    sys.stderr.flush()

    results[orig_idx] = {
        "tool_call_id": tc_id,
        "tool_name": tc_name,
        "result": output
    }

# Save cache for next invocation
_save_cache(read_cache)

# Convert results list (filter out any None entries, though there shouldn't be any)
final_results = [r for r in results if r is not None]

# Output results with metadata
output_data = {
    "results": final_results,
    "aborted": aborted,
    "completed_tools": len(final_results),
    "total_tools": total_tools,
    "tool_output_lines": tool_output_lines,
}

# Always output full data (includes line count for clearing)
print(json.dumps(output_data))
PYEOF

    rm -f "$tmp_requests"
}

# ============================================================================
# HYBRID CHAT LOOP
# ============================================================================

# Complete hybrid chat loop with local tool execution
run_hybrid_chat() {
    local prompt="$1"
    local conversation_id="$2"
    local max_iterations="${3:-10}"
    local subagent_id="${4:-}"    # Optional: ID del subagente a usar

    local current_conv_id="$conversation_id"
    local tool_results=""
    local iteration=0
    local max_tool_iterations="${TURIA_MAX_TOOL_ITERATIONS:-30}"  # Limite de seguridad
    local start_time=$(date +%s)  # Track total elapsed time

    # Accumulate session costs across all HTTP calls
    local accumulated_session_tokens=0
    local accumulated_session_cost=0

    # Detect and encode images from the prompt
    local images_json=""
    local cleaned_prompt="$prompt"
    if [ -n "$prompt" ]; then
        images_json=$(detect_and_encode_images "$prompt")
        if [ -n "$images_json" ] && [ "$images_json" != "[]" ]; then
            # Remove image paths from prompt text
            cleaned_prompt=$(remove_image_paths_from_text "$prompt")
            local num_images=$(echo "$images_json" | jq 'length' 2>/dev/null || echo "0")
            if [ "$num_images" -gt 0 ]; then
                echo -e "  ${GREEN}📎${NC} ${num_images} imagen(es) detectada(s)" >&2
            fi
        fi
    fi

    while [ $iteration -lt $max_tool_iterations ]; do
        iteration=$((iteration + 1))

        # Llamar al servidor
        local response
        if [ $iteration -eq 1 ]; then
            # Primera llamada: enviar prompt (con subagent_id e imagenes si existen)
            response=$(send_chat_hybrid "$cleaned_prompt" "$current_conv_id" "" "$max_iterations" "$subagent_id" "$images_json")
        else
            # Llamadas siguientes: enviar tool_results (sin imagenes, mantener subagent_id)
            response=$(send_chat_hybrid "" "$current_conv_id" "$tool_results" "$max_iterations" "$subagent_id" "")
        fi

        # Verificar error - check both object format and array format (FastAPI)
        local error=$(json_get "$response" "error")
        # Also check for FastAPI array error format: [{"type":"request_error","message":"..."}]
        if [ -z "$error" ]; then
            local array_msg=$(echo "$response" | jq -r 'if type == "array" then .[0].message // empty else empty end' 2>/dev/null)
            [ -n "$array_msg" ] && error="$array_msg"
        fi
        if [ -n "$error" ]; then
            # Check if it's an auth error (case insensitive patterns)
            local error_lower=$(echo "$error" | tr '[:upper:]' '[:lower:]')
            if [[ "$error_lower" == *"not authenticated"* ]] || [[ "$error_lower" == *"token"* ]] || \
               [[ "$error_lower" == *"expired"* ]] || [[ "$error_lower" == *"401"* ]] || \
               [[ "$error_lower" == *"authentication"* ]] || [[ "$error_lower" == *"unauthorized"* ]] || \
               [[ "$error_lower" == *"not authorized"* ]] || [[ "$error_lower" == *"access denied"* ]] || \
               [[ "$error_lower" == *"connection already closed"* ]]; then
                echo '{"error": "auth_expired", "message": "Tu sesion ha expirado"}'
                return 2  # Special return code for auth errors
            fi
            echo "$response"
            return 1
        fi

        # Obtener conversation_id
        current_conv_id=$(json_get "$response" "conversation_id")

        # Accumulate session costs from this response
        local this_session_tokens=$(json_get_num "$response" "session_tokens")
        local this_session_cost=$(json_get_num "$response" "session_cost")
        accumulated_session_tokens=$((accumulated_session_tokens + this_session_tokens))
        accumulated_session_cost=$(echo "$accumulated_session_cost + $this_session_cost" | bc 2>/dev/null || echo "$accumulated_session_cost")

        # Verificar si hay tool_requests
        local tool_requests=$(echo "$response" | jq -c '.tool_requests // empty' 2>/dev/null)

        if [ -n "$tool_requests" ] && [ "$tool_requests" != "null" ]; then
            # Ejecutar tools localmente (pass start_time for elapsed calculation)
            local tool_output=$(execute_tools_locally "$tool_requests" "$start_time")

            # Validate tool_output is valid JSON
            if [ -z "$tool_output" ]; then
                echo '{"error": "Tool execution returned empty results", "response": ""}'
                return 1
            fi

            # Check if operation was aborted by user (ESC key)
            if json_is_true "$tool_output" "aborted"; then
                # Extract partial results and return abort response
                local completed_tools=$(json_get_num "$tool_output" "completed_tools")
                local total_tools=$(json_get_num "$tool_output" "total_tools")
                local total_elapsed=$(($(date +%s) - start_time))

                # Return abort response - conversation remains active
                echo "{\"error\": null, \"aborted\": true, \"conversation_id\": \"$current_conv_id\", \"total_elapsed\": $total_elapsed, \"session_tokens\": $accumulated_session_tokens, \"session_cost\": $accumulated_session_cost, \"response\": \"Operación cancelada ($completed_tools/$total_tools tools ejecutados)\", \"completed_tools\": $completed_tools, \"total_tools\": $total_tools}"
                return 0
            fi

            # Extract results array, line count, and user input from tool output
            local tool_output_lines=$(json_get_num "$tool_output" "tool_output_lines")
            local user_inline_input=$(json_get "$tool_output" "user_input")
            tool_results=$(echo "$tool_output" | jq -c '.results' 2>/dev/null)

            # Export line count for next send_chat_hybrid call to clear
            export TURIA_TOOL_OUTPUT_LINES="$tool_output_lines"

            # Export user input for next send_chat_hybrid call
            export TURIA_USER_INLINE_INPUT="$user_inline_input"

            # Verify it's valid JSON array
            local is_valid=$(echo "$tool_results" | jq -r 'if type == "array" and length > 0 then "yes" else "no" end' 2>/dev/null)
            if [ "$is_valid" != "yes" ]; then
                local debug_preview=$(echo "$tool_results" | head -c 200)
                echo "{\"error\": \"Invalid tool results format\", \"response\": \"\", \"debug\": \"$debug_preview\"}"
                return 1
            fi

            # Continuar el loop para enviar resultados
            continue
        fi

        # No hay tool_requests, devolver respuesta final
        # Add total elapsed time and accumulated session costs to response
        local total_elapsed=$(($(date +%s) - start_time))
        # Ensure values are valid numbers
        [ -z "$accumulated_session_tokens" ] && accumulated_session_tokens=0
        [ -z "$accumulated_session_cost" ] && accumulated_session_cost=0
        echo "$response" | jq \
            --argjson elapsed "${total_elapsed:-0}" \
            --argjson tokens "${accumulated_session_tokens:-0}" \
            --argjson cost "${accumulated_session_cost:-0}" \
            '.total_elapsed = $elapsed | .session_tokens = $tokens | .session_cost = $cost' \
            2>/dev/null || echo "$response"
        return 0
    done

    # Max tool iterations reached - return special response for CLI to handle
    local total_elapsed=$(($(date +%s) - start_time))
    echo "{\"error\": null, \"max_tool_iterations_reached\": true, \"conversation_id\": \"$current_conv_id\", \"total_elapsed\": $total_elapsed, \"session_tokens\": $accumulated_session_tokens, \"session_cost\": $accumulated_session_cost, \"response\": \"\"}"
    return 0
}
