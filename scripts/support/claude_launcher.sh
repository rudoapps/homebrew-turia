#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# claude_launcher.sh — Flujo de `turia` SIN argumentos:
#   1. Analiza la carpeta actual y detecta el/los tipo(s) de proyecto.
#   2. Consulta el pool (claude_pool.conf) y ve qué skills de Claude Code faltan.
#   3. Instala las que falten con `claude plugin install`.
#   4. Arranca `claude` en la carpeta actual.
#
# Reutiliza las variables de color globales de turia (GREEN, RED, YELLOW, DIM…).
# El pool se puede sobreescribir con la variable de entorno TURIA_CLAUDE_POOL.
# ─────────────────────────────────────────────────────────────────────────────

# ── Detección del tipo de proyecto ───────────────────────────────────────────
# Imprime, una por línea, los tipos detectados en el directorio actual usando
# los mismos nombres que las claves del pool.
detect_claude_project_types() {
  local types=()

  # Python
  if [ -f pyproject.toml ] || [ -f requirements.txt ] || [ -f setup.py ] \
     || compgen -G "*.py" >/dev/null; then
    types+=("python")
  fi
  # iOS / Swift
  if compgen -G "*.xcodeproj" >/dev/null || [ -f Package.swift ] \
     || compgen -G "*.swift" >/dev/null; then
    types+=("ios")
  fi
  # Android (Gradle)
  if [ -f build.gradle ] || [ -f build.gradle.kts ] || [ -f settings.gradle ] \
     || [ -f settings.gradle.kts ]; then
    types+=("android")
  fi
  # Flutter
  if [ -f pubspec.yaml ]; then
    types+=("flutter")
  fi
  # TypeScript / Angular / JS
  if [ -f angular.json ] || [ -f tsconfig.json ] \
     || { [ -f package.json ] && compgen -G "*.ts" >/dev/null; }; then
    types+=("typescript")
  fi
  # PHP
  if [ -f composer.json ] || compgen -G "*.php" >/dev/null; then
    types+=("php")
  fi
  # Go
  if [ -f go.mod ]; then
    types+=("go")
  fi
  # Rust
  if [ -f Cargo.toml ]; then
    types+=("rust")
  fi

  [ "${#types[@]}" -eq 0 ] && return 0
  printf '%s\n' "${types[@]}" | awk 'NF' | sort -u
}

# ── Lectura del pool ─────────────────────────────────────────────────────────
# _claude_pool_file: ruta efectiva del pool.
_claude_pool_file() {
  if [ -n "${TURIA_CLAUDE_POOL:-}" ]; then
    echo "$TURIA_CLAUDE_POOL"
  else
    echo "${scripts_dir}/support/claude_pool.conf"
  fi
}

# _claude_pool_entries_for <tipo> → líneas "plugin|descripción" para ese tipo.
_claude_pool_entries_for() {
  local want="$1" pool
  pool="$(_claude_pool_file)"
  [ -f "$pool" ] || return 0
  while IFS='|' read -r type plugin desc; do
    [[ "$type" =~ ^[[:space:]]*# ]] && continue
    [ -z "${type// }" ] && continue
    [ "$type" = "$want" ] && echo "${plugin}|${desc}"
  done < "$pool"
}

# ── Plugins ya instalados en Claude Code ─────────────────────────────────────
_claude_installed_plugins() {
  claude plugin list 2>/dev/null \
    | grep -Eo '[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+' | sort -u
}

# ── Flujo principal ──────────────────────────────────────────────────────────
launch_claude_with_skills() {
  if ! command -v claude >/dev/null 2>&1; then
    echo -e "${RED}No encuentro el ejecutable 'claude' en el PATH.${NC}"
    echo -e "Instala Claude Code antes de usar este comando."
    exit 1
  fi

  # Gate de usuario: forzar sesión válida antes de continuar (bloquea).
  if ! ensure_agent_login; then
    echo -e "${RED}Login requerido para usar turia. Abortando.${NC}"
    exit 1
  fi
  echo

  echo -e "${DIM}Analizando $(pwd)…${NC}\n"

  local types
  types="$(detect_claude_project_types)"

  if [ -z "$types" ]; then
    echo -e "${YELLOW}No he reconocido el tipo de proyecto en esta carpeta.${NC}"
  else
    echo -e "${GREEN}Tipos de proyecto detectados:${NC}"
    while read -r t; do echo -e "    • $t"; done <<< "$types"
  fi
  echo

  local installed
  installed="$(_claude_installed_plugins)"

  local recommend=()   # plugin|desc
  local already=()
  if [ -n "$types" ]; then
    while read -r t; do
      [ -z "$t" ] && continue
      while IFS='|' read -r plugin desc; do
        [ -z "$plugin" ] && continue
        if echo "$installed" | grep -qx "$plugin"; then
          already+=("$plugin")
        else
          local dup=0
          if [ "${#recommend[@]}" -gt 0 ]; then
            for r in "${recommend[@]}"; do [ "${r%%|*}" = "$plugin" ] && dup=1; done
          fi
          [ "$dup" -eq 0 ] && recommend+=("${plugin}|${desc}")
        fi
      done < <(_claude_pool_entries_for "$t")
    done <<< "$types"
  fi

  if [ "${#already[@]}" -gt 0 ]; then
    echo -e "${DIM}Skills del pool ya instaladas:${NC}"
    for p in $(printf '%s\n' "${already[@]}" | sort -u); do
      echo -e "    ${DIM}✔ $p${NC}"
    done
    echo
  fi

  if [ "${#recommend[@]}" -eq 0 ]; then
    echo -e "${GREEN}No hay skills nuevas que instalar para este proyecto.${NC}"
  else
    echo -e "${YELLOW}Skills recomendadas del pool (aún no instaladas):${NC}"
    for entry in "${recommend[@]}"; do
      echo -e "    + ${entry%%|*}  ${DIM}${entry#*|}${NC}"
    done
    echo

    local ans="Y"
    if [ -t 0 ]; then
      read -r -p "$(echo -e "¿Instalar estas skills en Claude Code? [${BOLD}Y${NC}/n] ")" ans
      ans="${ans:-Y}"
    fi
    if [[ "$ans" =~ ^[Yy] ]]; then
      for entry in "${recommend[@]}"; do
        local plugin="${entry%%|*}"
        echo -e "${GREEN}Instalando ${plugin}…${NC}"
        if claude plugin install "$plugin"; then
          echo -e "${GREEN}✔ Instalado ${plugin}${NC}"
        else
          echo -e "${RED}✗ Falló la instalación de ${plugin} (continúo)${NC}"
        fi
      done
    else
      echo -e "${YELLOW}Instalación omitida.${NC}"
    fi
  fi

  echo
  echo -e "${GREEN}Arrancando claude…${NC}\n"
  exec claude
}
