#!/bin/bash

# Agent Authentication Module
# Handles login, logout, token validation, and refresh

# ============================================================================
# AUTHENTICATION CHECK
# ============================================================================

# Check if authenticated (has token)
is_agent_authenticated() {
    local token=$(get_agent_config "access_token")
    [ -n "$token" ] && [ "$token" != "None" ] && [ "$token" != "null" ]
}

# Validate if the current token is still valid
validate_agent_token() {
    local api_url=$(get_agent_config "api_url")
    local access_token=$(get_agent_config "access_token")

    if [ -z "$access_token" ] || [ "$access_token" = "None" ] || [ "$access_token" = "null" ]; then
        return 1
    fi

    # Make a test request to check token validity
    local response=$(curl -s -w "\n%{http_code}" "$api_url/agent/conversations" \
        -H "Authorization: Bearer $access_token" 2>/dev/null)

    local http_code=$(echo "$response" | tail -n1)
    local body=$(echo "$response" | sed '$d')

    # Explicit auth rejection
    if [ "$http_code" = "401" ] || [ "$http_code" = "403" ]; then
        return 1
    fi

    # Server 500 with auth-related messages (server closes connection on expired token)
    if [ "$http_code" = "500" ]; then
        local body_lower=$(echo "$body" | tr '[:upper:]' '[:lower:]')
        if [[ "$body_lower" == *"connection already closed"* ]] || \
           [[ "$body_lower" == *"not authorized"* ]] || \
           [[ "$body_lower" == *"not authenticated"* ]]; then
            return 1
        fi
    fi

    return 0
}

# ============================================================================
# TOKEN REFRESH
# ============================================================================

# Refresh the access token using the refresh token
refresh_agent_token() {
    local api_url=$(get_agent_config "api_url")
    local refresh_token=$(get_agent_config "refresh_token")

    if [ -z "$refresh_token" ] || [ "$refresh_token" = "None" ] || [ "$refresh_token" = "null" ]; then
        return 1
    fi

    # Call refresh endpoint
    local response=$(curl -s -X POST "$api_url/users/refresh" \
        -H "Content-Type: application/json" \
        -d "{\"refresh_token\": \"$refresh_token\"}" 2>/dev/null)

    # Check if we got new tokens
    local new_access_token=$(json_get "$response" "access_token")
    local new_refresh_token=$(json_get "$response" "refresh_token")

    if [ -n "$new_access_token" ] && [ "$new_access_token" != "null" ] && [ "$new_access_token" != "" ]; then
        # Save new tokens
        set_agent_config "access_token" "$new_access_token"
        if [ -n "$new_refresh_token" ] && [ "$new_refresh_token" != "null" ]; then
            set_agent_config "refresh_token" "$new_refresh_token"
        fi
        return 0
    fi

    return 1
}

# Ensure we have a valid token, trying refresh first
ensure_valid_token_with_refresh() {
    # First check if we have any token
    if ! is_agent_authenticated; then
        return 1
    fi

    # Check if current token is valid
    if validate_agent_token; then
        return 0
    fi

    # Token expired, try to refresh silently
    echo -e "  ${DIM}Renovando sesion...${NC}" >&2
    if refresh_agent_token; then
        echo -e "  ${GREEN}✓${NC} Sesion renovada" >&2
        return 0
    fi

    # Refresh failed, token is truly expired
    return 1
}

# ============================================================================
# LOGIN / LOGOUT
# ============================================================================

# Agent login via browser
agent_login() {
    init_agent_config

    local api_url=$(get_agent_config "api_url")
    [ -z "$api_url" ] && api_url="$AGENT_API_URL"

    echo -e "${BOLD}-----------------------------------------------${NC}"
    echo -e "${BOLD}Agent Login${NC}"
    echo -e "${BOLD}-----------------------------------------------${NC}"

    # Check if already authenticated
    if is_agent_authenticated; then
        echo -e "${YELLOW}Ya estas autenticado.${NC}"
        read -p "Deseas volver a iniciar sesion? (s/n): " CONFIRM
        if [ "$CONFIRM" != "s" ]; then
            echo -e "${GREEN}Sesion activa.${NC}"
            return 0
        fi
    fi

    echo -e "Creando sesion de autenticacion..."

    # Create session
    local response=$(curl -s -X POST "$api_url/cli-auth/session")
    local session_id=$(json_get "$response" "session_id")

    if [ -z "$session_id" ]; then
        echo -e "${RED}Error: No se pudo crear la sesion de autenticacion${NC}"
        # Parse error message from response
        local err_msg=$(echo "$response" | jq -r 'if type == "array" then .[0].message // empty else .error // .detail // empty end' 2>/dev/null)
        if [ -n "$err_msg" ]; then
            echo -e "${DIM}Servidor: $err_msg${NC}"
        fi
        echo -e "${YELLOW}Verifica que el servidor este disponible e intenta de nuevo.${NC}"
        return 1
    fi

    # Open browser
    local login_url="$api_url/cli-auth/login?session=$session_id"
    echo -e "${GREEN}Abriendo navegador para login...${NC}"
    echo -e "URL: $login_url"

    # Open browser (macOS specific, could be extended for Linux)
    if command -v open &> /dev/null; then
        open "$login_url"
    elif command -v xdg-open &> /dev/null; then
        xdg-open "$login_url"
    else
        echo -e "${YELLOW}No se pudo abrir el navegador automaticamente.${NC}"
        echo -e "Abre esta URL manualmente: $login_url"
    fi

    echo ""
    echo -e "${BOLD}Esperando autenticacion en el navegador...${NC}"
    echo -e "(Presiona Ctrl+C para cancelar)"

    # Poll for completion
    local max_attempts=60
    local attempt=0

    while [ $attempt -lt $max_attempts ]; do
        sleep 2
        local poll_response=$(curl -s "$api_url/cli-auth/poll?session=$session_id")
        local status=$(json_get "$poll_response" "status")

        case "$status" in
            "completed")
                local access_token=$(json_get "$poll_response" "access_token")
                local refresh_token=$(json_get "$poll_response" "refresh_token")
                local user_email=$(json_get "$poll_response" "user_email")

                set_agent_config "access_token" "$access_token"
                set_agent_config "refresh_token" "$refresh_token"
                set_agent_config "user_email" "$user_email"

                echo ""
                echo -e "${GREEN}-----------------------------------------------${NC}"
                echo -e "${GREEN}Login exitoso!${NC}"
                echo -e "${GREEN}Usuario: $user_email${NC}"
                echo -e "${GREEN}-----------------------------------------------${NC}"
                return 0
                ;;
            "pending")
                printf "."
                ;;
            "expired")
                echo ""
                echo -e "${RED}La sesion ha expirado. Intenta de nuevo.${NC}"
                return 1
                ;;
            "not_found")
                echo ""
                echo -e "${RED}Sesion no encontrada.${NC}"
                return 1
                ;;
        esac

        attempt=$((attempt + 1))
    done

    echo ""
    echo -e "${RED}Tiempo de espera agotado. Intenta de nuevo.${NC}"
    return 1
}

# Agent logout
agent_logout() {
    init_agent_config

    echo -e "${BOLD}-----------------------------------------------${NC}"
    echo -e "${BOLD}Agent Logout${NC}"
    echo -e "${BOLD}-----------------------------------------------${NC}"

    if ! is_agent_authenticated; then
        echo -e "${YELLOW}No hay sesion activa.${NC}"
        return 0
    fi

    set_agent_config "access_token" "null"
    set_agent_config "refresh_token" "null"
    set_agent_config "user_email" "null"

    echo -e "${GREEN}Sesion cerrada correctamente.${NC}"
}

# Agent status
agent_status() {
    init_agent_config

    echo -e "${BOLD}-----------------------------------------------${NC}"
    echo -e "${BOLD}Agent Status${NC}"
    echo -e "${BOLD}-----------------------------------------------${NC}"

    local api_url=$(get_agent_config "api_url")
    echo -e "API URL: ${YELLOW}$api_url${NC}"

    if is_agent_authenticated; then
        local user_email=$(get_agent_config "user_email")
        echo -e "Estado: ${GREEN}Autenticado${NC}"
        echo -e "Usuario: ${GREEN}$user_email${NC}"

        # Verificar si el token sigue siendo valido
        if validate_agent_token; then
            echo -e "Token: ${GREEN}Valido${NC}"
        else
            echo -e "Token: ${YELLOW}Expirado${NC}"
            # Check if we can refresh
            local refresh_token=$(get_agent_config "refresh_token")
            if [ -n "$refresh_token" ] && [ "$refresh_token" != "None" ] && [ "$refresh_token" != "null" ]; then
                echo -e "Refresh: ${GREEN}Disponible${NC} (se renovara automaticamente)"
            else
                echo -e "Refresh: ${RED}No disponible${NC}"
                echo -e "Ejecuta: ${YELLOW}turia agent login${NC}"
            fi
        fi
    else
        echo -e "Estado: ${RED}No autenticado${NC}"
        echo -e "Ejecuta: ${YELLOW}turia agent login${NC}"
    fi
}

# ============================================================================
# AUTH ERROR HANDLING
# ============================================================================

# Handle auth error during operations - try refresh, then prompt login
handle_auth_error() {
    local retry_command="${1:-}"  # Optional, not currently used

    echo -e "  ${DIM}Sesion expirada, intentando renovar...${NC}"
    if refresh_agent_token; then
        echo -e "  ${GREEN}✓${NC} Sesion renovada"
        return 0  # Caller should retry
    else
        echo -e "${YELLOW}No se pudo renovar la sesion.${NC}"
        echo ""
        read -p "Deseas iniciar sesion de nuevo? (s/n): " relogin
        if [[ "$relogin" =~ ^[sS]$ ]]; then
            echo ""
            set_agent_config "access_token" "null"
            set_agent_config "refresh_token" "null"
            if agent_login; then
                echo ""
                return 0  # Caller should retry
            fi
        fi
        return 1  # Don't retry
    fi
}
