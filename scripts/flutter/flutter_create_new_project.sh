#!/usr/bin/env bash
set -euo pipefail

# =========================
# Config por defecto (ajusta si hace falta)
# =========================
ARCH_REPO_SSH="git@bitbucket.org:rudoapps/architecture-flutter.git"
ARCH_REPO_HTTPS="https://bitbucket.org/rudoapps/architecture-flutter.git"
ARCH_DIR_NAME="architecture-flutter"

OLD_PACKAGE="es.rudo.archetypeflutter"
OLD_PROJECT_NAME="archetype_flutter"

LIB_DIR="lib" # directorio principal de código Dart

# =========================
# Utilidades
# =========================
err() {
    echo "│"
    echo "│ ❌ $*"
    echo "│">&2; exit 1;  
}
info() {
    echo "│"
    echo "│ $*"
    echo "│"
}
ok() { 
    echo "│"
    echo "│ ✅ $*"
    echo "│"
}

# sed compatible macOS/Linux
sed_inplace() {
  if sed --version >/dev/null 2>&1; then
    sed -i "$@"
  else
    # macOS BSD sed
    local expr="$1"; shift
    sed -i '' "$expr" "$@"
  fi
}

# Convierte com.foo.bar -> com/foo/bar
ns_to_path() {
  echo "$1" | tr '.' '/'
}

get_token_for_flutter() {
    echo "│"
    echo "│ Validando key"
    echo "│ "
    TURIA_COMMAND="create"
    get_access_token $KEY "flutter"
}

flutter_create_project() {
    # =========================
    # Input interactivo
    # =========================
    read -r -p "Ruta de destino del nuevo proyecto (ej: ../NuevaApp): " PROJECT_PATH
    read -r -p "Nombre de la app [opcional, Enter para mantener]: " APP_NAME
    read -r -p "Nuevo package name (ej: com.yourcompany.yourapp): " NEW_PACKAGE
    echo "──────────────────────────────────────────────"

    [ -z "$PROJECT_PATH" ] && err "Debes indicar PROJECT_PATH."
    [ -z "$NEW_PACKAGE" ] && err "Debes indicar NEW_PACKAGE (p. ej. com.miempresa.miapp)."

    EXEC_PATH="$PWD"

    # =========================
    # Clonado
    # =========================
    echo "┌──────────────────────────────────────────────"    
    # Moving to new app directory
    info "Clonando arquetipo Flutter…"
    get_token_for_flutter
    
    if [ -n "${BRANCH:-}" ]; then
        info "🌿 Usando rama: $BRANCH"
        git clone --branch "$BRANCH" "https://x-token-auth:$ACCESSTOKEN@bitbucket.org/rudoapps/architecture-flutter.git" "$PROJECT_PATH"
    else
        git clone "https://x-token-auth:$ACCESSTOKEN@bitbucket.org/rudoapps/architecture-flutter.git" "$PROJECT_PATH"
    fi    
    ok "Repositorio clonado en ${PROJECT_PATH}"

    cd "$PROJECT_PATH"

    # Si el repo clona en carpeta 'architecture-flutter', muévelo al root del nuevo proyecto
    if [ -d "$ARCH_DIR_NAME" ] && [ "$(ls -A . | wc -l)" -gt 1 ]; then
      info "Estructura detectada: carpeta raíz '$ARCH_DIR_NAME'. Reubicando contenido…"
      shopt -s dotglob
      mv "$ARCH_DIR_NAME"/* .
      rmdir "$ARCH_DIR_NAME"
      shopt -u dotglob
      ok "Contenido reubicado."
    fi

    # =========================
    # Actualizar pubspec.yaml
    # =========================
    PUBSPEC_FILE="pubspec.yaml"
    if [ -f "${PUBSPEC_FILE}" ] && [ -n "${APP_NAME:-}" ]; then
      info "Actualizando name en ${PUBSPEC_FILE}..."
      # Convertir APP_NAME a snake_case para Flutter
      SNAKE_CASE_NAME=$(echo "${APP_NAME}" | sed 's/[A-Z]/_&/g' | sed 's/^_//' | tr '[:upper:]' '[:lower:]' | sed 's/-/_/g')
      sed_inplace 's/^[[:space:]]*name[[:space:]]*:.*/name: '"${SNAKE_CASE_NAME}"'/' "${PUBSPEC_FILE}" || true
      ok "name actualizado -> ${SNAKE_CASE_NAME}"
    else
      info "Saltando cambio de name (no especificado o archivo no encontrado)."
    fi

    # =========================
    # Actualizar package name en Android (para Flutter)
    # =========================
    ANDROID_BUILD="android/app/build.gradle"
    if [ -f "${ANDROID_BUILD}" ]; then
      info "Actualizando applicationId en ${ANDROID_BUILD}..."
      
      # Actualizar applicationId en el archivo build.gradle de Android
      if grep -q "applicationId" "${ANDROID_BUILD}"; then
        sed_inplace "s/applicationId[[:space:]]*[\"'][^\"']*[\"']/applicationId \"${NEW_PACKAGE}\"/" "${ANDROID_BUILD}" || true
        ok "applicationId actualizado -> ${NEW_PACKAGE}"
      else
        info "No se encontró applicationId en ${ANDROID_BUILD}."
      fi
    else
      info "No se encontró ${ANDROID_BUILD}; puede ser un proyecto Flutter diferente."
    fi
    
    # Actualizar package en iOS (Info.plist)
    IOS_INFO_PLIST="ios/Runner/Info.plist"
    if [ -f "${IOS_INFO_PLIST}" ]; then
      info "Actualizando CFBundleIdentifier en ${IOS_INFO_PLIST}..."
      sed_inplace "s/<string>[^<]*<\/string>\(.*CFBundleIdentifier.*\)/<string>${NEW_PACKAGE}<\/string>/" "${IOS_INFO_PLIST}" || true
      ok "CFBundleIdentifier actualizado -> ${NEW_PACKAGE}"
    else
      info "No se encontró ${IOS_INFO_PLIST}; puede ser un proyecto Flutter diferente."
    fi

    # =========================
    # Verificar estructura de Flutter
    # =========================
    if [ -d "$LIB_DIR" ]; then
      info "Estructura Flutter detectada en $LIB_DIR"
      ok "Directorio lib encontrado"
    else
      info "No se encontró directorio lib estándar de Flutter."
    fi

    # =========================
    # Actualizar imports en archivos .dart
    # =========================
    info "Actualizando imports en archivos Dart…"
    find "$LIB_DIR" -type f -name "*.dart" -print0 | while IFS= read -r -d '' f; do
      # Actualizar imports del paquete anterior
      sed_inplace "s/import[[:space:]]*'package:$OLD_PROJECT_NAME\//import 'package:${SNAKE_CASE_NAME:-${OLD_PROJECT_NAME}}\//g" "$f" || true
      # Actualizar cualquier referencia hardcoded del paquete anterior
      sed_inplace "s/$OLD_PACKAGE/$NEW_PACKAGE/g" "$f" || true
    done
    ok "Archivos Dart actualizados."

    # =========================
    # AndroidManifest.xml (Flutter)
    # =========================
    ANDROID_MANIFEST="android/app/src/main/AndroidManifest.xml"
    if [ -f "$ANDROID_MANIFEST" ]; then
      info "Actualizando AndroidManifest.xml de Flutter…"
      # Cambiar atributo package si existe
      if grep -q 'package=' "$ANDROID_MANIFEST"; then
        sed_inplace 's/package="[^"]*"/package="'"$NEW_PACKAGE"'"/' "$ANDROID_MANIFEST" || true
      fi
      # Actualizar cualquier referencia al paquete anterior
      sed_inplace "s/$OLD_PACKAGE/$NEW_PACKAGE/g" "$ANDROID_MANIFEST" || true
      ok "AndroidManifest actualizado."
    else
      info "No se encontró $ANDROID_MANIFEST; puede ser un proyecto Flutter diferente."
    fi

    # =========================
    # Actualización en todos los archivos Flutter
    # =========================
    SRC_DIR="."
    info "Actualizando package names en todo el código Flutter..."
    find "$SRC_DIR" -type f \( -name "*.dart" -o -name "*.yaml" -o -name "*.yml" -o -name "*.gradle" -o -name "*.xml" -o -name "*.plist" \) -print0 | while IFS= read -r -d '' file; do
        # Cambia el package antiguo por el nuevo
        sed_inplace "s/${OLD_PACKAGE//./\\.}/${NEW_PACKAGE//./\\.}/g" "$file"
        # Cambia el project name anterior por el nuevo (si se especificó)
        if [ -n "${SNAKE_CASE_NAME:-}" ]; then
          sed_inplace "s/$OLD_PROJECT_NAME/$SNAKE_CASE_NAME/g" "$file"
        fi
    done
    ok "Reemplazo global completado."

    # =========================
    # Actualización nombre en recursos Flutter
    # =========================
    if [ -n "${APP_NAME:-}" ]; then
      info "Actualizando nombres de app en recursos..."
      
      # Busca strings.xml en el proyecto Flutter Android
      find . -type f -path "*/android/app/src/main/res/values/strings.xml" -print0 | while IFS= read -r -d '' file; do
          if grep -q '<string name="app_name">' "$file"; then
              sed_inplace "s|<string name=\"app_name\">.*</string>|<string name=\"app_name\">${APP_NAME}</string>|" "$file"
              ok "app_name actualizado en $file"
          fi
      done
      
      # Actualizar Info.plist en iOS si existe
      IOS_INFO_PLIST="ios/Runner/Info.plist"
      if [ -f "${IOS_INFO_PLIST}" ]; then
        info "Actualizando CFBundleDisplayName en iOS..."
        if grep -q "CFBundleDisplayName" "${IOS_INFO_PLIST}"; then
          sed_inplace "s/<string>[^<]*<\/string>\(.*CFBundleDisplayName.*\)/<string>${APP_NAME}<\/string>/" "${IOS_INFO_PLIST}" || true
          ok "CFBundleDisplayName actualizado -> ${APP_NAME}"
        fi
      fi
    else
      info "No se especificó nombre de app, saltando actualización de recursos."
    fi

    # =========================
    # Limpiezas varias
    # =========================
    # Quitar el repo git original
    if [ -d ".git" ]; then
      info "Eliminando .git del arquetipo…"
      rm -rf .git
      ok ".git eliminado."
    fi

    # Remove .gitkeep placeholders
    info "Eliminando ficheros .gitkeep ..."
    find . -type f -name ".gitkeep" -delete
    ok "Ficheros .gitkeep eliminados"

    # Vaciar CHANGELOG si existe
    if [ -f "CHANGELOG.md" ]; then
      : > CHANGELOG.md
      ok "CHANGELOG.md vaciado."
    fi

    # Quitar README del arquetipo (opcional)
    if [ -f "README.md" ]; then
      rm -f README.md
      ok "README.md eliminado."
    fi

    echo "│ 👍 Proyecto Flutter preparado en: $(pwd)"
    [ -n "${APP_NAME:-}" ] && echo "│ • name = ${SNAKE_CASE_NAME:-$APP_NAME}"
    echo "│ • package = ${NEW_PACKAGE}"

    # Registrar la creación del proyecto
    echo "│"
    echo "│ 📝 Creando archivo de auditoría .turia.log..."

    # Ya estamos en el directorio del proyecto
    TIMESTAMP_LOG=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    BRANCH_LOG="${BRANCH:-main}"
    COMMIT_LOG=""
    CREATED_BY_LOG="unknown"
    PROJECT_NAME="${SNAKE_CASE_NAME:-${APP_NAME:-ArchetypeFlutter}}"

    # Intentar obtener el username
    if [ -n "$KEY" ]; then
        if command -v get_username_from_api >/dev/null 2>&1; then
            CREATED_BY_LOG=$(get_username_from_api "$KEY" 2>/dev/null | tr -d '\n\r' || echo "unknown")
            # Si está vacío, usar "unknown"
            [ -z "$CREATED_BY_LOG" ] && CREATED_BY_LOG="unknown"
        fi
    fi

    # Crear el archivo .turia.log
    echo "{
  \"project_info\": {
    \"created\": \"$TIMESTAMP_LOG\",
    \"platform\": \"flutter\",
    \"project_name\": \"$PROJECT_NAME\",
    \"branch\": \"$BRANCH_LOG\",
    \"commit\": \"$COMMIT_LOG\",
    \"created_by\": \"$CREATED_BY_LOG\",
    \"turia_version\": \"$VERSION\"
  },
  \"operations\": [
    {
      \"timestamp\": \"$TIMESTAMP_LOG\",
      \"operation\": \"create\",
      \"platform\": \"flutter\",
      \"module\": \"$PROJECT_NAME\",
      \"branch\": \"$BRANCH_LOG\",
      \"commit\": \"$COMMIT_LOG\",
      \"status\": \"success\",
      \"details\": \"Flutter project created with package: $NEW_PACKAGE\",
      \"created_by\": \"$CREATED_BY_LOG\",
      \"turia_version\": \"$VERSION\"
    }
  ],
  \"installed_modules\": {}
}" > .turia.log

    if [ -f ".turia.log" ]; then
        echo "│ ✅ Archivo .turia.log creado exitosamente"
    else
        echo "│ ⚠️ No se pudo crear el archivo .turia.log"
    fi

    echo "│ "
    echo "└──────────────────────────────────────────────"
    echo ""
}