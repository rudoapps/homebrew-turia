#!/bin/bash

# Agent RAG Module
# Handles RAG (Retrieval Augmented Generation) integration with the server

# ============================================================================
# RAG CACHE (TTL: 5 minutes)
# ============================================================================
RAG_STATUS_CACHE=""
RAG_STATUS_TIMESTAMP=0
RAG_CACHE_TTL="${TURIA_RAG_CACHE_TTL:-300}"  # 5 minutes in seconds

# ============================================================================
# GIT REMOTE URL FUNCTIONS
# ============================================================================

# Get normalized git remote URL from current directory
# Returns HTTPS URL normalized (without .git suffix)
get_git_remote_url() {
    local url=$(git remote get-url origin 2>/dev/null)

    if [ -z "$url" ]; then
        echo ""
        return 1
    fi

    # Convert SSH to HTTPS: git@host:org/repo -> https://host/org/repo
    if [[ "$url" == git@* ]]; then
        url="${url#git@}"
        url="https://${url%%:*}/${url#*:}"
    fi

    # Remove user@ from URL (https://user@host -> https://host)
    url=$(echo "$url" | sed 's|https://[^@]*@|https://|')

    # Remove .git suffix
    url="${url%.git}"

    # Remove trailing slash
    url="${url%/}"

    echo "$url"
}

# ============================================================================
# RAG INDEX CHECK
# ============================================================================

# Check if project has RAG index on server - WITH CACHE (5 min TTL)
# Returns JSON: {has_index: bool, status: string, project_id: int, ...}
check_rag_index() {
    local git_remote_url=$(get_git_remote_url)

    if [ -z "$git_remote_url" ]; then
        echo '{"has_index": false, "status": "no_git_remote", "message": "No git remote configured"}'
        return 0
    fi

    # Check cache validity
    local now=$(date +%s)
    local cache_age=$((now - RAG_STATUS_TIMESTAMP))

    if [[ -n "$RAG_STATUS_CACHE" ]] && ((cache_age < RAG_CACHE_TTL)); then
        # Cache hit - return cached result
        echo "$RAG_STATUS_CACHE"
        return 0
    fi

    local api_url=$(get_agent_config "api_url")
    local access_token=$(get_agent_config "access_token")
    local endpoint="$api_url/rag/check"

    # URL encode the git_remote_url
    local encoded_url=$(jq -rn --arg url "$git_remote_url" '$url | @uri')

    # Make request to check endpoint
    local response=$(curl -s -X GET \
        "$endpoint?git_remote_url=$encoded_url" \
        -H "Authorization: Bearer $access_token" \
        -H "Content-Type: application/json" \
        2>/dev/null)

    if [ -z "$response" ]; then
        echo '{"has_index": false, "status": "error", "message": "Failed to connect to server"}'
        return 1
    fi

    # Parse response and add git_remote_url for reference
    local result
    if echo "$response" | jq -e 'type == "array"' >/dev/null 2>&1; then
        # Handle error responses (list format from FastAPI)
        local error_msg=$(echo "$response" | jq -r '.[0].message // "Unknown error"' 2>/dev/null)
        result=$(jq -n --arg msg "$error_msg" --arg url "$git_remote_url" \
            '{has_index: false, status: "error", message: $msg, git_remote_url: $url}')
    else
        # Normal dict response — add git_remote_url
        result=$(echo "$response" | jq --arg url "$git_remote_url" '. + {git_remote_url: $url}' 2>/dev/null)
        if [ -z "$result" ]; then
            result=$(jq -n --arg url "$git_remote_url" \
                '{has_index: false, status: "error", message: "Invalid response", git_remote_url: $url}')
        fi
    fi

    # Cache the result
    RAG_STATUS_CACHE="$result"
    RAG_STATUS_TIMESTAMP=$(date +%s)

    echo "$result"
}

# ============================================================================
# RAG STATUS DISPLAY
# ============================================================================

# Display RAG status for current project (human-readable)
show_rag_status() {
    local rag_info=$(check_rag_index)

    local has_index=$(echo "$rag_info" | jq -r '.has_index // false' 2>/dev/null)
    local status=$(echo "$rag_info" | jq -r '.status // "unknown"' 2>/dev/null)
    local git_url=$(echo "$rag_info" | jq -r '.git_remote_url // ""' 2>/dev/null)
    local total_chunks=$(echo "$rag_info" | jq -r '.total_chunks // 0' 2>/dev/null)
    local message=$(echo "$rag_info" | jq -r '.message // ""' 2>/dev/null)

    # Colors
    local GREEN="\033[0;32m"
    local YELLOW="\033[1;33m"
    local RED="\033[0;31m"
    local CYAN="\033[0;36m"
    local DIM="\033[2m"
    local NC="\033[0m"
    local BOLD="\033[1m"

    echo -e "\n${BOLD}RAG Status${NC}"
    echo -e "${DIM}─────────────────────────────────────${NC}"

    if [ -z "$git_url" ] || [ "$status" = "no_git_remote" ]; then
        echo -e "  ${YELLOW}⚠${NC}  No git remote configurado"
        echo -e "     ${DIM}RAG requiere un repositorio git${NC}"
        return 1
    fi

    echo -e "  ${CYAN}Repository:${NC} $git_url"

    case "$status" in
        "ready")
            echo -e "  ${GREEN}●${NC} ${GREEN}Indexado${NC} - RAG activo"
            echo -e "     ${DIM}$total_chunks chunks disponibles${NC}"
            ;;
        "pending")
            echo -e "  ${YELLOW}●${NC} ${YELLOW}Pendiente${NC} - Esperando configuracion"
            [ -n "$message" ] && echo -e "     ${DIM}$message${NC}"
            ;;
        "indexing")
            echo -e "  ${CYAN}●${NC} ${CYAN}Indexando${NC} - En progreso..."
            ;;
        "error")
            echo -e "  ${RED}●${NC} ${RED}Error${NC} - Fallo en indexacion"
            [ -n "$message" ] && echo -e "     ${DIM}$message${NC}"
            ;;
        *)
            echo -e "  ${DIM}●${NC} Estado: $status"
            [ -n "$message" ] && echo -e "     ${DIM}$message${NC}"
            ;;
    esac

    echo ""
}

# ============================================================================
# RAG CONTEXT HELPER
# ============================================================================

# Check if RAG should be used for current project
# Returns 0 (true) if RAG is available and should be used
should_use_rag() {
    local rag_info=$(check_rag_index)
    local has_index=$(echo "$rag_info" | jq -r 'if .has_index then "true" else "false" end' 2>/dev/null)

    [ "$has_index" = "true" ]
}

# Get git_remote_url and ensure project is registered for RAG
# This is used by agent_api.sh to include in requests
# Also triggers auto-registration of new projects
get_rag_git_url() {
    local git_url=$(get_git_remote_url)

    if [ -z "$git_url" ]; then
        echo ""
        return 0
    fi

    # Call check endpoint to auto-register project if new
    # This ensures the project exists in the RAG system
    local rag_info=$(check_rag_index 2>/dev/null)
    local status=$(echo "$rag_info" | jq -r '.status // "unknown"' 2>/dev/null)

    # Show message if project was just registered
    if [ "$status" = "pending" ]; then
        echo -e "  ${YELLOW}📋${NC} Proyecto registrado para RAG (pendiente de indexar)" >&2
    fi

    echo "$git_url"
}
