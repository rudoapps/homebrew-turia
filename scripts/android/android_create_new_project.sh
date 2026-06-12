#!/usr/bin/env bash
set -euo pipefail

# =========================
# Config por defecto (ajusta si hace falta)
# =========================
ARCH_REPO_SSH="git@bitbucket.org:rudoapps/architecture-android.git"
ARCH_REPO_HTTPS="https://bitbucket.org/rudoapps/architecture-android.git"
ARCH_DIR_NAME="architecture-android"

OLD_NAMESPACE="es.rudo.archetypeandroid"
OLD_NS_PATH="es/rudo/archetypeandroid"

APP_MODULE_DIR="app" # si el módulo no es "app", cambia aquí

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

get_token_for_android() {
    echo "│"
    echo "│ Validando key"
    echo "│ "
    TURIA_COMMAND="create"
    get_access_token $KEY "android"
}

android_create_project() {
    # =========================
    # Input interactivo
    # =========================
    read -r -p "Ruta de destino del nuevo proyecto (ej: ../NuevaApp): " PROJECT_PATH
    read -r -p "Nombre de la app (rootProject.name) [opcional, Enter para mantener]: " APP_NAME
    read -r -p "Nuevo namespace (ej: com.yourcompany.yourapp): " NEW_NAMESPACE
    echo "──────────────────────────────────────────────"

    [ -z "$PROJECT_PATH" ] && err "Debes indicar PROJECT_PATH."
    [ -z "$NEW_NAMESPACE" ] && err "Debes indicar NEW_NAMESPACE (p. ej. com.miempresa.miapp)."

    NEW_NS_PATH="$(ns_to_path "$NEW_NAMESPACE")"
    EXEC_PATH="$PWD"

    # =========================
    # Clonado
    # =========================
    echo "┌──────────────────────────────────────────────"    
    # Moving to new app directory
    info "Clonando arquetipo…"
    get_token_for_android
    
    if [ -n "${BRANCH:-}" ]; then
        info "🌿 Usando rama: $BRANCH"
        git clone --branch "$BRANCH" "https://x-token-auth:$ACCESSTOKEN@bitbucket.org/rudoapps/architecture-android.git" "$PROJECT_PATH"
    else
        git clone "https://x-token-auth:$ACCESSTOKEN@bitbucket.org/rudoapps/architecture-android.git" "$PROJECT_PATH"
    fi    
    ok "Repositorio clonado en ${PROJECT_PATH}"

    cd "$PROJECT_PATH"

    # Si el repo clona en carpeta 'architecture-android', muévelo al root del nuevo proyecto
    if [ -d "$ARCH_DIR_NAME" ] && [ "$(ls -A . | wc -l)" -gt 1 ]; then
      info "Estructura detectada: carpeta raíz '$ARCH_DIR_NAME'. Reubicando contenido…"
      shopt -s dotglob
      mv "$ARCH_DIR_NAME"/* .
      rmdir "$ARCH_DIR_NAME"
      shopt -u dotglob
      ok "Contenido reubicado."
    fi

    # =========================
    # Renombrar proyecto (settings.gradle.kts)
    # =========================
    SETTINGS_FILE="settings.gradle.kts"
    if [ -f "${SETTINGS_FILE}" ] && [ -n "${APP_NAME:-}" ]; then
      info "Actualizando rootProject.name en ${SETTINGS_FILE}..."
      sed_inplace 's/^[[:space:]]*rootProject\.name[[:space:]]*=.*/rootProject.name = "'"${APP_NAME//\//\/}"'"/' "${SETTINGS_FILE}" || true
      ok "rootProject.name actualizado -> ${APP_NAME}"
    else
      info "Saltando cambio de rootProject.name (no especificado o archivo no encontrado)."
    fi

    # =========================
    # Cambiar namespace en build.gradle.kts (del módulo app)
    # =========================
    APP_BUILD="app/build.gradle.kts"
    if [ -f "${APP_BUILD}" ]; then
      info "Actualizando namespace en ${APP_BUILD}..."

      # ¿Existe bloque android { … } ?
      if grep -Eq '^[[:space:]]*android[[:space:]]*\{' "${APP_BUILD}"; then

        if grep -Eq '^[[:space:]]*namespace[[:space:]]*=' "${APP_BUILD}"; then
          # REEMPLAZAR el valor de namespace manteniendo indentación y comentario
          awk -v ns="${NEW_NAMESPACE}" '
            {
              if ($0 ~ /^[[:space:]]*namespace[[:space:]]*=/) {
                # indentación
                match($0, /^[[:space:]]*/); indent = substr($0, 1, RLENGTH)
                # comentario final (si lo hay)
                c = index($0, "//")
                tail = (c > 0) ? substr($0, c) : ""
                # imprime línea nueva
                if (tail != "") {
                  print indent "namespace = \"" ns "\" " tail
                } else {
                  print indent "namespace = \"" ns "\""
                }
                next
              }
              print
            }
          ' "${APP_BUILD}" > "${APP_BUILD}.tmp" && mv "${APP_BUILD}.tmp" "${APP_BUILD}"
          ok "namespace configurado -> ${NEW_NAMESPACE}"
        else
          # INSERTAR el namespace tras la línea 'android {'
          awk -v ns="${NEW_NAMESPACE}" '
            {
              print $0
              if ($0 ~ /^[[:space:]]*android[[:space:]]*\{/) {
                print "    namespace = \"" ns "\""
              }
            }
          ' "${APP_BUILD}" > "${APP_BUILD}.tmp" && mv "${APP_BUILD}.tmp" "${APP_BUILD}"
          ok "namespace insertado -> ${NEW_NAMESPACE}"
        fi

      else
        info "No se encontró bloque android { } en ${APP_BUILD}. Saltando."
      fi

      # (OPCIONAL) applicationId -> reemplaza si existe, preservando indent y comentario
      if grep -Eq '^[[:space:]]*applicationId[[:space:]]*"' "${APP_BUILD}"; then
        awk -v ns="${NEW_NAMESPACE}" '
          {
            if ($0 ~ /^[[:space:]]*applicationId[[:space:]]*"/) {
              match($0, /^[[:space:]]*/); indent = substr($0, 1, RLENGTH)
              c = index($0, "//")
              tail = (c > 0) ? substr($0, c) : ""
              if (tail != "") {
                print indent "applicationId \"" ns "\" " tail
              } else {
                print indent "applicationId \"" ns "\""
              }
              next
            }
            print
          }
        ' "${APP_BUILD}" > "${APP_BUILD}.tmp" && mv "${APP_BUILD}.tmp" "${APP_BUILD}"
        ok "applicationId actualizado (si existía)."
      fi
    else
      info "No se encontró ${APP_BUILD}; comprueba el nombre del módulo."
    fi

    # =========================
    # Reubicar código fuente al nuevo paquete
    # =========================
    JAVA_DIR="$APP_MODULE_DIR/src/main/java"
    if [ -d "$JAVA_DIR/$OLD_NS_PATH" ]; then
      info "Reubicando código Java/Kotlin al nuevo namespace…"
      mkdir -p "$JAVA_DIR/$NEW_NS_PATH"
      shopt -s dotglob
      mv "$JAVA_DIR/$OLD_NS_PATH"/* "$JAVA_DIR/$NEW_NS_PATH"/
      # Elimina residuos de la ruta antigua si quedan vacíos
      rmdir "$JAVA_DIR/$OLD_NS_PATH" || true
      rmdir "$JAVA_DIR/es/rudo" 2>/dev/null || true
      rmdir "$JAVA_DIR/es" 2>/dev/null || true
      shopt -u dotglob
      ok "Carpeta movida a $JAVA_DIR/$NEW_NS_PATH"
    else
      info "No existe $JAVA_DIR/$OLD_NS_PATH; se intentará ajuste por búsqueda global."
    fi

    # =========================
    # Actualizar declaraciones package/import en .kt/.java
    # =========================
    info "Actualizando declaraciones 'package' e 'import' en código fuente…"
    find "$APP_MODULE_DIR/src" -type f \( -name "*.kt" -o -name "*.java" \) -print0 | while IFS= read -r -d '' f; do
      sed_inplace "s/\bpackage[[:space:]]\+$OLD_NAMESPACE\b/package $NEW_NAMESPACE/" "$f" || true
      sed_inplace "s/\bimport[[:space:]]\+$OLD_NAMESPACE\./import $NEW_NAMESPACE./g" "$f" || true
      # Cualquier hardcode del viejo paquete
      sed_inplace "s/$OLD_NAMESPACE/$NEW_NAMESPACE/g" "$f" || true
    done
    ok "Código actualizado."

    # =========================
    # AndroidManifest.xml
    # =========================
    MAIN_MANIFEST="$APP_MODULE_DIR/src/main/AndroidManifest.xml"
    if [ -f "$MAIN_MANIFEST" ]; then
      info "Actualizando AndroidManifest.xml…"
      # Cambiar atributo package si existe
      if grep -q 'package=' "$MAIN_MANIFEST"; then
        sed_inplace 's/package="\([^"]*\)"/package="'"$NEW_NAMESPACE"'"/' "$MAIN_MANIFEST" || true
      fi
      # Actualizar nombres completos de actividades/servicios si referencian el antiguo paquete
      sed_inplace "s/$OLD_NAMESPACE/$NEW_NAMESPACE/g" "$MAIN_MANIFEST" || true
      ok "Manifest actualizado."
    else
      info "No se encontró $MAIN_MANIFEST; quizá el arquetipo depende solo de namespace (AGP moderno)."
    fi

    # =========================
    # Actualización en todos los ficheros
    # =========================
    SRC_DIR="."
    info "Actualizando applicationId y namespaces en todo el código fuente..."
    find "$SRC_DIR" -type f \( -name "*.kt" -o -name "*.java" -o -name "*.gradle.kts" \) -print0 | while IFS= read -r -d '' file; do
        # Cambia el applicationId antiguo por el nuevo
        sed_inplace "s/es\.rudo\.archetypeandroid/${NEW_NAMESPACE//./\\.}/g" "$file"
    done
    ok "Reemplazo global completado."

    # =========================
    # Actualización nombre en strings.xml
    # =========================
    info "Actualizando app_name en recursos..."

    # Busca todos los strings.xml que contengan app_name
    find . -type f -path "*/res/values/strings.xml" -print0 | while IFS= read -r -d '' file; do
        if grep -q '<string name="app_name">' "$file"; then
            # Reemplaza el valor entre etiquetas app_name
            sed_inplace "s|<string name=\"app_name\">.*</string>|<string name=\"app_name\">${APP_NAME}</string>|" "$file"
            ok "app_name actualizado en $file"
        fi
    done

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

    echo "│ 👍 Proyecto Android preparado en: $(pwd)"
    [ -n "${APP_NAME:-}" ] && echo "│ • rootProject.name = ${APP_NAME}"
    echo "│ • namespace = ${NEW_NAMESPACE}"

    # Registrar la creación del proyecto
    echo "│"
    echo "│ 📝 Creando archivo de auditoría .turia.log..."

    # Ya estamos en el directorio del proyecto
    TIMESTAMP_LOG=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    BRANCH_LOG="${BRANCH:-main}"
    COMMIT_LOG=""
    CREATED_BY_LOG="unknown"

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
    \"platform\": \"android\",
    \"project_name\": \"${APP_NAME:-ArchetypeAndroid}\",
    \"branch\": \"$BRANCH_LOG\",
    \"commit\": \"$COMMIT_LOG\",
    \"created_by\": \"$CREATED_BY_LOG\",
    \"turia_version\": \"$VERSION\"
  },
  \"operations\": [
    {
      \"timestamp\": \"$TIMESTAMP_LOG\",
      \"operation\": \"create\",
      \"platform\": \"android\",
      \"module\": \"${APP_NAME:-ArchetypeAndroid}\",
      \"branch\": \"$BRANCH_LOG\",
      \"commit\": \"$COMMIT_LOG\",
      \"status\": \"success\",
      \"details\": \"Android project created with namespace: $NEW_NAMESPACE\",
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