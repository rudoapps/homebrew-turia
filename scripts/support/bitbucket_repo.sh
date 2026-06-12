#!/bin/bash

# =============================================================================
# Bitbucket Repository Management
# Funciones para crear repos en Bitbucket y hacer push inicial
# =============================================================================

# Crea un repositorio en Bitbucket usando la API REST v2
# Usa Basic Auth (usuario + App Password)
create_bitbucket_repo() {
  local user="$1"
  local token="$2"
  local workspace="$3"
  local repo_slug="$4"
  local is_private="${5:-true}"

  echo "│"
  echo "│ 📦 Creando repositorio en Bitbucket..."
  echo "│    Workspace: $workspace"
  echo "│    Repo: $repo_slug"
  echo "│"

  local response
  response=$(curl --silent --show-error --write-out "HTTPSTATUS:%{http_code}" \
    -X POST \
    "https://api.bitbucket.org/2.0/repositories/${workspace}/${repo_slug}" \
    -u "${user}:${token}" \
    -H "Content-Type: application/json" \
    -d "{
      \"scm\": \"git\",
      \"is_private\": ${is_private},
      \"forking_policy\": \"no_public_forks\"
    }" 2>/dev/null)

  local body
  body=$(echo "$response" | sed -e 's/HTTPSTATUS\:.*//g')
  local http_status
  http_status=$(echo "$response" | tr -d '\n' | sed -e 's/.*HTTPSTATUS://')

  if [ "$http_status" -eq 200 ] || [ "$http_status" -eq 201 ]; then
    echo "│ ✅ Repositorio creado exitosamente en Bitbucket"
    echo "│"
    return 0
  elif [ "$http_status" -eq 400 ]; then
    # Puede que ya exista
    if echo "$body" | grep -q "already exists"; then
      echo "│ ⚠️  El repositorio ya existe en Bitbucket. Se usará el existente."
      echo "│"
      return 0
    fi
    echo "│ ❌ Error al crear el repositorio (HTTP $http_status)"
    echo "│    $body"
    echo "│"
    return 1
  else
    echo "│ ❌ Error al crear el repositorio (HTTP $http_status)"
    echo "│    $body"
    echo "│"
    return 1
  fi
}

# Inicializa git, hace commit inicial y push al repo de Bitbucket
push_initial_commit() {
  local user="$1"
  local token="$2"
  local workspace="$3"
  local repo_slug="$4"

  echo "│ 🔧 Inicializando repositorio git..."
  echo "│"

  # Inicializar git si no existe
  if [ ! -d ".git" ]; then
    git init -b main > /dev/null 2>&1
    echo "│ ✅ Repositorio git inicializado"
  else
    echo "│ ✅ Repositorio git ya existía"
  fi

  # Añadir todos los archivos y hacer commit
  git add -A > /dev/null 2>&1
  git commit -m "Initial commit - project created with turia v${VERSION}" > /dev/null 2>&1
  echo "│ ✅ Commit inicial creado"

  # URL-encode usuario y token para evitar problemas con caracteres especiales (@, =, etc.)
  local encoded_user encoded_token
  encoded_user=$(printf '%s' "$user" | python3 -c "import sys, urllib.parse; print(urllib.parse.quote(sys.stdin.read(), safe=''))")
  encoded_token=$(printf '%s' "$token" | python3 -c "import sys, urllib.parse; print(urllib.parse.quote(sys.stdin.read(), safe=''))")

  # Configurar remote con Basic Auth (usuario:app_password)
  local remote_url="https://${encoded_user}:${encoded_token}@bitbucket.org/${workspace}/${repo_slug}.git"

  if git remote get-url origin > /dev/null 2>&1; then
    git remote set-url origin "$remote_url"
  else
    git remote add origin "$remote_url"
  fi

  echo "│ ✅ Remote configurado: bitbucket.org/${workspace}/${repo_slug}"
  echo "│"
  echo "│ 🚀 Haciendo push al repositorio..."

  if git -c credential.helper= push -u origin main 2>&1; then
    echo "│"
    echo "│ ✅ Push completado exitosamente"
    echo "│ 🔗 https://bitbucket.org/${workspace}/${repo_slug}"
  else
    echo "│"
    echo "│ ❌ Error haciendo push. Verifica el usuario, token y permisos."
    echo "│    Puedes hacer push manual con: git push -u origin main"
    return 1
  fi

  # Limpiar el token del remote (seguridad)
  local clean_url="git@bitbucket.org:${workspace}/${repo_slug}.git"
  git remote set-url origin "$clean_url" 2>/dev/null || true
  echo "│ 🔒 Remote actualizado a SSH: ${clean_url}"
  echo "│"
}

# Flujo completo: crear repo + init + commit + push
setup_bitbucket_repo() {
  local user="$1"
  local token="$2"
  local workspace="$3"
  local repo_slug="$4"
  local is_private="${5:-true}"

  echo "│"
  echo "│ ═══════════════════════════════════════════"
  echo "│  📡 Configuración de repositorio Bitbucket"
  echo "│ ═══════════════════════════════════════════"

  # Paso 1: Crear repo en Bitbucket
  if ! create_bitbucket_repo "$user" "$token" "$workspace" "$repo_slug" "$is_private"; then
    echo "│ ❌ No se pudo crear el repositorio. Abortando push."
    echo "│"
    return 1
  fi

  # Paso 2: Init + commit + push
  push_initial_commit "$user" "$token" "$workspace" "$repo_slug"
}
