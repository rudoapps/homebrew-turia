#!/bin/bash

# Agent Subagents Module
# Handles subagent listing and invocation from within chat

# ============================================================================
# FETCH SUBAGENTS FROM BACKEND
# ============================================================================

# Fetch subagents list from backend
# Returns JSON array or empty on error
fetch_subagents_from_backend() {
    local api_url=$(get_agent_config "api_url")
    local access_token=$(get_agent_config "access_token")

    local response=$(curl -s -w "\n%{http_code}" "$api_url/agent/subagents" \
        -H "Authorization: Bearer $access_token" 2>/dev/null)

    local http_code=$(echo "$response" | tail -n1)
    local body=$(echo "$response" | sed '$d')

    # Check for auth errors
    if [ "$http_code" = "401" ] || [ "$http_code" = "403" ]; then
        echo "AUTH_ERROR"
        return 2
    fi

    # Check for success
    if [ "$http_code" = "200" ]; then
        echo "$body"
        return 0
    fi

    # Other errors
    echo "ERROR:$http_code"
    return 1
}

# ============================================================================
# LIST SUBAGENTS
# ============================================================================

# Show available subagents (fetched from backend)
show_available_subagents() {
    echo ""
    echo -e "${BOLD}Subagentes disponibles:${NC}"
    echo ""

    # Fetch from backend
    local response
    response=$(fetch_subagents_from_backend)
    local status=$?

    # Handle auth error
    if [ "$response" = "AUTH_ERROR" ]; then
        if handle_auth_error; then
            response=$(fetch_subagents_from_backend)
            status=$?
        else
            echo -e "  ${RED}Error: No autenticado${NC}"
            return 1
        fi
    fi

    # Handle other errors
    if [ $status -ne 0 ]; then
        echo -e "  ${RED}Error: No se pudo obtener la lista de subagentes${NC}"
        echo -e "  ${DIM}El servidor puede no tener este endpoint implementado${NC}"
        echo ""
        return 1
    fi

    # Parse and display subagents
    local subagent_count=$(echo "$response" | jq '.subagents | length' 2>/dev/null || echo "0")
    local parse_status=0

    if [ "$subagent_count" -eq 0 ] 2>/dev/null; then
        echo "  No hay subagentes disponibles."
    else
        echo "$response" | jq -r '.subagents[]? | "\(.id)\t\(.description // "Sin descripcion")"' 2>/dev/null | \
        while IFS=$'\t' read -r sid desc; do
            printf "  \033[0;36m%-16s\033[0m - %.50s\n" "$sid" "$desc"
        done
        if [ ${PIPESTATUS[0]} -ne 0 ]; then
            echo -e "  \033[0;31mError parseando respuesta\033[0m"
            parse_status=1
        fi
    fi

    echo ""
    if [ $parse_status -eq 0 ]; then
        echo -e "Uso: ${YELLOW}/subagent <id> <mensaje>${NC}"
        echo -e "Ejemplo: ${DIM}/subagent code-review src/auth.py${NC}"
    fi
    echo ""
}

# ============================================================================
# VALIDATE SUBAGENT
# ============================================================================

# Check if subagent_id is valid (by querying backend)
is_valid_subagent() {
    local subagent_id="$1"

    # Fetch subagents and check if the ID exists
    local response
    response=$(fetch_subagents_from_backend)
    local status=$?

    if [ $status -ne 0 ]; then
        # If we can't reach backend, allow it and let the server validate
        return 0
    fi

    # Check if subagent_id exists in the list
    echo "$response" | jq -e --arg id "$subagent_id" '.subagents[]? | select(.id == $id)' >/dev/null 2>&1
}

# ============================================================================
# INVOKE SUBAGENT
# ============================================================================

# Invoke a subagent within the chat context
# This function is called from agent_chat_interactive
invoke_subagent_in_chat() {
    local subagent_id="$1"
    local prompt="$2"
    local conversation_id="$3"

    # Show subagent header (validation will be done by server)
    echo ""
    echo -e "${CYAN}[Subagente: $subagent_id]${NC}"
    echo ""

    # Call server with subagent_id
    local response
    response=$(run_hybrid_chat "$prompt" "$conversation_id" "15" "$subagent_id")
    local run_status=$?

    # Handle auth errors with refresh
    if [ $run_status -eq 2 ]; then
        if handle_auth_error; then
            echo -e "${BOLD}Reintentando...${NC}"
            response=$(run_hybrid_chat "$prompt" "$conversation_id" "15" "$subagent_id")
            run_status=$?
        else
            return 1
        fi
    fi

    # Check for errors
    local error=$(json_get_error "$response")
    if [ -n "$error" ] && [ "$error" != "None" ]; then
        echo -e "${RED}Error: $error${NC}"
        return 1
    fi

    # Extract response data
    local text_response=$(json_get "$response" "response")
    local new_conv_id=$(json_get "$response" "conversation_id")
    local msg_cost=$(json_get_num "$response" "total_cost")
    local msg_tokens=$(json_get_num "$response" "total_tokens")
    local msg_elapsed=$(json_get_num "$response" "elapsed_time")
    local msg_tools=$(json_get_num "$response" "tools_count")

    # Display response using existing display_response function
    display_response "$text_response"

    # Display subagent-specific summary
    echo ""
    echo -e "${DIM}─────────────────────────────────────────────${NC}"
    local summary_info="${CYAN}[$subagent_id]${NC} "
    [ "$msg_tools" -gt 0 ] 2>/dev/null && summary_info="${summary_info}${GREEN}✓${NC} ${msg_tools} tool(s) "
    [ -n "$msg_tokens" ] && [ "$msg_tokens" != "0" ] && summary_info="${summary_info}${DIM}Tokens:${NC} ${msg_tokens} "
    [ -n "$msg_cost" ] && summary_info="${summary_info}${DIM}|${NC} ${DIM}\$${NC}${msg_cost} "
    [ -n "$msg_elapsed" ] && [ "$msg_elapsed" != "0" ] && summary_info="${summary_info}${DIM}|${NC} ${msg_elapsed}s"
    echo -e "  ${summary_info}"
    echo -e "${DIM}─────────────────────────────────────────────${NC}"

    # Return the new conversation_id if it was created
    echo "$new_conv_id"
}
