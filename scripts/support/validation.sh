#!/bin/bash

# Función para instalar el pre-commit hook
install_validation_hook() {
  echo ""
  echo -e "${BOLD}═══════════════════════════════════════════════${NC}"
  echo -e "${BOLD}     INSTALACIÓN DE PRE-COMMIT HOOK (TURIA)     ${NC}"
  echo -e "${BOLD}═══════════════════════════════════════════════${NC}"
  echo ""

  # Verificar que estamos en un repositorio git
  if [ ! -d ".git" ]; then
    echo -e "${RED}❌ Error: No se encontró un repositorio git en el directorio actual${NC}"
    echo -e "${YELLOW}Este comando debe ejecutarse desde la raíz del proyecto${NC}"
    return 1
  fi

  # Crear directorio de hooks si no existe
  if [ ! -d ".git/hooks" ]; then
    echo -e "${YELLOW}📁 Creando directorio .git/hooks${NC}"
    mkdir -p .git/hooks
  fi

  local hook_file=".git/hooks/pre-commit"
  local hook_exists=false
  local append_mode=false

  # Verificar si ya existe un pre-commit hook
  if [ -f "$hook_file" ]; then
    hook_exists=true

    # Verificar si ya contiene validación de turia
    if grep -q "turia validate --staged" "$hook_file" 2>/dev/null; then
      echo -e "${GREEN}✅ El hook de validación de turia ya está instalado${NC}"
      return 0
    fi

    echo -e "${YELLOW}⚠️  Ya existe un archivo pre-commit${NC}"
    echo ""
    echo -e "${BOLD}¿Qué deseas hacer?${NC}"
    echo "  1) Reemplazar el hook existente (se perderá el contenido actual)"
    echo "  2) Añadir validación de turia al hook existente (recomendado)"
    echo "  3) Cancelar instalación"
    echo ""

    while true; do
      read -p "Selecciona una opción (1-3): " choice
      case $choice in
        1)
          echo -e "${YELLOW}🔄 Reemplazando hook existente...${NC}"
          append_mode=false
          break
          ;;
        2)
          echo -e "${GREEN}📝 Añadiendo validación al hook existente...${NC}"
          append_mode=true
          break
          ;;
        3)
          echo -e "${YELLOW}❌ Instalación cancelada${NC}"
          return 0
          ;;
        *)
          echo -e "${RED}Opción inválida. Por favor selecciona 1, 2 o 3.${NC}"
          ;;
      esac
    done
  fi

  # Crear o actualizar el hook
  if [ "$append_mode" = true ]; then
    # Añadir al final del hook existente
    cat >> "$hook_file" << 'EOF'

# ═══════════════════════════════════════════════
# Validación de archivos .turia - TURIA
# ═══════════════════════════════════════════════
echo ""
echo "🔍 Validando archivos .turia..."

if command -v turia >/dev/null 2>&1; then
    turia validate --staged
    if [ $? -ne 0 ]; then
        echo ""
        echo "❌ Pre-commit fallido: Hay errores en archivos .turia"
        echo "Por favor corrige los errores antes de hacer commit"
        exit 1
    fi
    echo "✅ Validación de archivos .turia completada"
else
    echo "⚠️  Advertencia: turia no está instalado, saltando validación"
fi
# ═══════════════════════════════════════════════
EOF
    echo -e "${GREEN}✅ Validación de turia añadida al pre-commit hook existente${NC}"
  else
    # Crear nuevo hook
    cat > "$hook_file" << 'EOF'
#!/bin/sh
#
# Pre-commit hook generado por TURIA
# Valida archivos .turia antes de hacer commit
#

echo "🔍 Validando archivos .turia..."
echo ""

# Verificar si turia está disponible
if ! command -v turia >/dev/null 2>&1; then
    echo "⚠️  Advertencia: turia no está instalado o no está en el PATH"
    echo "Saltando validación de archivos .turia"
    exit 0
fi

# Ejecutar validación de archivos en staging
turia validate --staged

# Capturar el código de salida
validation_result=$?

if [ $validation_result -ne 0 ]; then
    echo ""
    echo "❌ Pre-commit hook falló: Hay errores en los archivos .turia"
    echo "Por favor corrige los errores antes de hacer commit"
    exit 1
fi

echo ""
echo "✅ Validación de archivos .turia completada"
exit 0
EOF
    echo -e "${GREEN}✅ Pre-commit hook creado exitosamente${NC}"
  fi

  # Dar permisos de ejecución
  chmod +x "$hook_file"
  echo -e "${GREEN}✅ Permisos de ejecución configurados${NC}"

  echo ""
  echo -e "${BOLD}───────────────────────────────────────────────${NC}"
  echo -e "${GREEN}🎉 Instalación completada${NC}"
  echo ""
  echo -e "${BOLD}El pre-commit hook ahora validará automáticamente los${NC}"
  echo -e "${BOLD}archivos .turia antes de cada commit.${NC}"
  echo ""
  echo -e "${BOLD}Para probarlo:${NC}"
  echo "  1. Modifica un archivo .turia (configuration.turia o *.turia en iOS)"
  echo "  2. Añádelo a staging: git add <archivo>"
  echo "  3. Intenta hacer commit: git commit -m \"test\""
  echo ""
  echo -e "${YELLOW}💡 Si necesitas hacer un commit sin validación:${NC}"
  echo "   git commit --no-verify -m \"mensaje\""
  echo ""
  echo -e "${BOLD}═══════════════════════════════════════════════${NC}"

  return 0
}

# Función para validar archivos configuration.turia en el proyecto
validate_configuration_files() {
  local project_type=""
  local error_count=0
  local warning_count=0
  local validated_count=0

  echo ""
  echo -e "${BOLD}═══════════════════════════════════════════════${NC}"
  echo -e "${BOLD}        VALIDACIÓN DE CONFIGURATION.TURIA        ${NC}"
  echo -e "${BOLD}═══════════════════════════════════════════════${NC}"
  echo ""

  # Detectar tipo de proyecto
  if check_type_of_project; then
    type=0
  else
    type=$?
  fi

  case "$type" in
    0) project_type="Android" ;;
    1) project_type="iOS" ;;
    2) project_type="Flutter" ;;
    3) project_type="Python" ;;
    *)
      echo -e "${RED}❌ Error: No se detectó un tipo de proyecto válido${NC}"
      return 1
      ;;
  esac

  echo -e "${GREEN}✅ Tipo de proyecto detectado: $project_type${NC}"
  echo ""

  # Buscar archivos según el tipo de proyecto
  local config_files=""
  if [ "$project_type" == "iOS" ]; then
    # En iOS buscar todos los archivos .turia
    config_files=$(find . -name "*.turia" -type f 2>/dev/null)
    if [ -z "$config_files" ]; then
      echo -e "${YELLOW}⚠️  No se encontraron archivos .turia en el proyecto${NC}"
      return 0
    fi
  else
    # Para otros proyectos buscar configuration.turia
    config_files=$(find . -name "configuration.turia" -type f 2>/dev/null)
    if [ -z "$config_files" ]; then
      echo -e "${YELLOW}⚠️  No se encontraron archivos configuration.turia en el proyecto${NC}"
      return 0
    fi
  fi

  local total_files=$(echo "$config_files" | wc -l | tr -d ' ')
  echo -e "${BOLD}📋 Archivos encontrados: $total_files${NC}"
  echo ""

  # Validar cada archivo
  while IFS= read -r config_file; do
    if [ -z "$config_file" ]; then
      continue
    fi

    # Capturar el resultado - no usar local result=$? directamente
    validate_single_configuration "$config_file" "$project_type" && result=0 || result=$?

    if [ $result -eq 0 ]; then
      validated_count=$((validated_count + 1))
    elif [ $result -eq 1 ]; then
      error_count=$((error_count + 1))
    else
      warning_count=$((warning_count + 1))
    fi
  done <<< "$config_files"

  # Resumen final
  echo ""
  echo -e "${BOLD}═══════════════════════════════════════════════${NC}"
  echo -e "${BOLD}                    RESUMEN                     ${NC}"
  echo -e "${BOLD}═══════════════════════════════════════════════${NC}"
  echo -e "${GREEN}✅ Archivos válidos: $validated_count${NC}"
  echo -e "${YELLOW}⚠️  Advertencias: $warning_count${NC}"
  echo -e "${RED}❌ Errores: $error_count${NC}"
  echo -e "${BOLD}───────────────────────────────────────────────${NC}"

  if [ $error_count -gt 0 ]; then
    echo ""
    echo -e "${RED}❌ Validación fallida: Se encontraron $error_count errores${NC}"
    return 1
  elif [ $warning_count -gt 0 ]; then
    echo ""
    echo -e "${YELLOW}⚠️  Validación completada con $warning_count advertencias${NC}"
    return 0
  else
    echo ""
    echo -e "${GREEN}✅ Todos los archivos configuration.turia son válidos${NC}"
    return 0
  fi
}

# Función para validar un archivo configuration.turia individual
validate_single_configuration() {
  local config_file=$1
  local project_type=$2
  local has_errors=0
  local has_warnings=0

  echo -e "${BOLD}──────────────────────────────────────────────${NC}"
  echo -e "${BOLD}📄 Archivo: $config_file${NC}"
  echo ""

  # Verificar que el archivo existe
  if [ ! -f "$config_file" ]; then
    echo -e "${RED}  ❌ El archivo no existe${NC}"
    return 1
  fi

  # Obtener el directorio base del archivo
  local config_dir=$(dirname "$config_file")

  # 1. Validar JSON
  echo -e "  🔍 Validando formato JSON..."
  if ! jq empty "$config_file" 2>/dev/null; then
    echo -e "${RED}  ❌ JSON inválido - El archivo no tiene un formato JSON correcto${NC}"
    has_errors=1
  else
    echo -e "${GREEN}  ✅ JSON válido${NC}"
  fi

  # Si hay errores de JSON, no continuar con otras validaciones
  if [ $has_errors -eq 1 ]; then
    return 1
  fi

  # 2. Validar según el tipo de proyecto
  case "$project_type" in
    "Android")
      validate_android_configuration "$config_file" "$config_dir"
      local result=$?
      if [ $result -eq 1 ]; then
        has_errors=1
      elif [ $result -eq 2 ]; then
        has_warnings=1
      fi
      ;;
    "iOS")
      validate_ios_configuration "$config_file" "$config_dir"
      local result=$?
      if [ $result -eq 1 ]; then
        has_errors=1
      elif [ $result -eq 2 ]; then
        has_warnings=1
      fi
      ;;
    "Flutter")
      validate_flutter_configuration "$config_file" "$config_dir"
      local result=$?
      if [ $result -eq 1 ]; then
        has_errors=1
      elif [ $result -eq 2 ]; then
        has_warnings=1
      fi
      ;;
    "Python")
      validate_python_configuration "$config_file" "$config_dir"
      local result=$?
      if [ $result -eq 1 ]; then
        has_errors=1
      elif [ $result -eq 2 ]; then
        has_warnings=1
      fi
      ;;
  esac

  echo ""

  if [ $has_errors -eq 1 ]; then
    return 1
  elif [ $has_warnings -eq 1 ]; then
    return 2
  else
    return 0
  fi
}

# Validación específica para Android
validate_android_configuration() {
  local config_file=$1
  local config_dir=$2
  local has_errors=0
  local has_warnings=0

  echo -e "  🔍 Validando configuración Android..."

  # Verificar estructura esperada
  local has_gradle=$(jq 'has("gradle")' "$config_file")
  local has_toml=$(jq 'has("toml")' "$config_file")
  local has_modules=$(jq 'has("modules")' "$config_file")

  if [ "$has_gradle" != "true" ] && [ "$has_toml" != "true" ]; then
    echo -e "${YELLOW}  ⚠️  Advertencia: No se encontró sección 'gradle' ni 'toml'${NC}"
    has_warnings=1
  fi

  # Validar includes en gradle si existen
  if [ "$has_gradle" == "true" ]; then
    local includes=$(jq -r '.gradle.includes[]? // empty' "$config_file")
    if [ -n "$includes" ]; then
      echo -e "  🔍 Validando includes de Gradle..."
      while IFS= read -r include; do
        if [ -n "$include" ]; then
          echo -e "    • Verificando: $include"
          # Los includes en Gradle usan formato :path:to:module
          # No necesariamente corresponden directamente a directorios
          # Esto es solo una advertencia informativa
        fi
      done <<< "$includes"
      echo -e "${GREEN}    ✅ Includes de Gradle encontrados${NC}"
    fi
  fi

  # Validar módulos referenciados si existen
  if [ "$has_modules" == "true" ]; then
    echo -e "  🔍 Validando módulos referenciados..."
    local modules=$(jq -r '.modules[]? // empty' "$config_file")
    if [ -n "$modules" ]; then
      while IFS= read -r module; do
        if [ -n "$module" ]; then
          # Buscar el módulo en el proyecto (puede estar en diferentes ubicaciones)
          local module_path=""

          # Intentar encontrar el módulo desde el directorio raíz del proyecto
          local project_root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
          local search_path="$project_root/$module"

          if [ -d "$search_path" ]; then
            echo -e "${GREEN}    ✅ Módulo encontrado: $module${NC}"
          else
            echo -e "${RED}    ❌ Módulo no encontrado: $module${NC}"
            echo -e "${YELLOW}       Buscado en: $search_path${NC}"
            has_errors=1
          fi
        fi
      done <<< "$modules"
    fi
  fi

  # Validar dependencias TOML si existen
  if [ "$has_toml" == "true" ]; then
    local toml_count=$(jq '[.toml[]?] | length' "$config_file")
    if [ "$toml_count" -gt 0 ]; then
      echo -e "  🔍 Validando dependencias TOML..."

      # Validar estructura de cada dependencia
      # En Android TOML, 'id' es obligatorio siempre
      local invalid_deps=$(jq -r '[.toml[]? | select(.id == null or .id == "")] | length' "$config_file")
      if [ "$invalid_deps" -gt 0 ]; then
        echo -e "${RED}    ❌ Hay $invalid_deps dependencias sin 'id'${NC}"
        has_errors=1
      fi

      # Verificar que tienen module, plugin o group (al menos uno es requerido)
      local no_source=$(jq -r '[.toml[]? | select(.module == null and .plugin == null and .group == null)] | length' "$config_file")
      if [ "$no_source" -gt 0 ]; then
        echo -e "${RED}    ❌ Hay $no_source dependencias sin 'module', 'plugin' ni 'group'${NC}"
        has_errors=1
      fi

      # NOTA: 'name' y 'version' son opcionales en Android
      # Algunas dependencias no los necesitan (ej: cuando usan BOM para gestionar versiones)
      # Por lo tanto, no se valida su presencia como obligatoria

      if [ $has_errors -eq 0 ]; then
        echo -e "${GREEN}    ✅ Dependencias TOML válidas ($toml_count encontradas)${NC}"
      fi
    fi
  fi

  # Validar repositorios en gradle.dependencies si existen
  if [ "$has_gradle" == "true" ]; then
    local gradle_deps=$(jq 'has("gradle.dependencies")' "$config_file")
    if [ "$gradle_deps" == "true" ]; then
      echo -e "  🔍 Validando repositorios Maven..."
      local invalid_repos=$(jq -r '[.gradle.dependencies[]? | select(.name == null or .name == "" or .url == null or .url == "")] | length' "$config_file")

      if [ "$invalid_repos" -gt 0 ]; then
        echo -e "${RED}    ❌ Hay $invalid_repos repositorios sin 'name' o 'url'${NC}"
        has_errors=1
      else
        local repos_count=$(jq '[.gradle.dependencies[]?] | length' "$config_file")
        if [ "$repos_count" -gt 0 ]; then
          echo -e "${GREEN}    ✅ Repositorios Maven válidos ($repos_count encontrados)${NC}"
        fi
      fi
    fi
  fi

  if [ $has_errors -eq 1 ]; then
    return 1
  elif [ $has_warnings -eq 1 ]; then
    return 2
  else
    return 0
  fi
}

# Validación específica para iOS
validate_ios_configuration() {
  local config_file=$1
  local config_dir=$2
  local has_errors=0
  local has_warnings=0

  echo -e "  🔍 Validando configuración iOS..."

  # Verificar estructura esperada para iOS
  local has_libraries=$(jq 'has("libraries")' "$config_file")
  local has_shared=$(jq 'has("shared")' "$config_file")

  if [ "$has_libraries" != "true" ] && [ "$has_shared" != "true" ]; then
    echo -e "${YELLOW}  ⚠️  Advertencia: No se encontró sección 'libraries' ni 'shared'${NC}"
    has_warnings=1
  fi

  # Validar libraries si existen
  if [ "$has_libraries" == "true" ]; then
    echo -e "  🔍 Validando libraries..."
    local libraries_count=$(jq '[.libraries[]?] | length' "$config_file")

    if [ "$libraries_count" -gt 0 ]; then
      # Validar que cada librería tenga name, url y version
      local invalid_libs=$(jq -r '[.libraries[]? | select(.name == null or .name == "" or .url == null or .url == "" or .version == null or .version == "")] | length' "$config_file")

      if [ "$invalid_libs" -gt 0 ]; then
        echo -e "${RED}    ❌ Hay $invalid_libs librerías sin 'name', 'url' o 'version'${NC}"
        has_errors=1
      else
        echo -e "${GREEN}    ✅ Libraries válidas ($libraries_count encontradas)${NC}"
      fi
    fi
  fi

  # Validar shared (rutas a módulos compartidos)
  if [ "$has_shared" == "true" ]; then
    echo -e "  🔍 Validando rutas en shared..."
    local shared_items=$(jq -r '.shared[]? // empty' "$config_file")

    if [ -n "$shared_items" ]; then
      # Usar el directorio donde está el archivo config como base, no la raíz de git
      local config_dir_abs=$(cd "$(dirname "$config_file")" && pwd)
      local project_root="$config_dir_abs"

      # Subir hasta encontrar el .xcodeproj (esto es el proyecto iOS)
      while [[ "$project_root" != "/" ]] && ! ls "$project_root"/*.xcodeproj &>/dev/null; do
        project_root=$(dirname "$project_root")
      done

      # Si no encontramos xcodeproj, usar pwd como fallback
      if [[ "$project_root" == "/" ]]; then
        project_root=$(pwd)
      fi

      while IFS= read -r shared_path; do
        if [ -n "$shared_path" ]; then
          local search_path=""
          local found=false

          if [[ "$shared_path" == Turia/* ]]; then
            # Convertir ruta del repositorio a ruta local del proyecto
            # Turia/Shared/Error -> {appName}/Shared/Error
            local_path="${shared_path#Turia/}"

            # Buscar el directorio de la app (el que tiene .xcodeproj como padre)
            app_dir=""

            # Buscar cualquier directorio .xcodeproj en el proyecto
            xcodeproj=$(find "$project_root" -maxdepth 2 -name "*.xcodeproj" -type d 2>/dev/null | head -1)

            if [ -n "$xcodeproj" ]; then
              # El directorio de la app tiene el mismo nombre que el .xcodeproj
              app_name=$(basename "$xcodeproj" .xcodeproj)
              app_dir="$project_root/$app_name"
            fi

            # Intentar encontrar la ruta en diferentes ubicaciones

            if [ -n "$app_dir" ] && [ -d "$app_dir/$local_path" ]; then
              search_path="$app_dir/$local_path"
              found=true
            elif [ -d "$project_root/$local_path" ]; then
              search_path="$project_root/$local_path"
              found=true
            elif [ -n "$TEMPORARY_DIR" ] && [ -d "$TEMPORARY_DIR/$shared_path" ]; then
              # Durante instalación, buscar en TEMPORARY_DIR
              search_path="$TEMPORARY_DIR/$shared_path"
              found=true
            fi
          else
            # Es una ruta local del proyecto (sin prefijo Turia/)
            if [ -d "$project_root/$shared_path" ]; then
              search_path="$project_root/$shared_path"
              found=true
            fi
          fi

          if [ "$found" = true ] && [ -n "$search_path" ] && [ -d "$search_path" ]; then
            echo -e "${GREEN}    ✅ Ruta encontrada: $shared_path${NC}"
          else
            # Determinar si estamos en el repositorio de módulos o en un proyecto de usuario
            if [[ -d "$project_root/Turia" ]]; then
              # Estamos en el repositorio, esto es un error
              echo -e "${RED}    ❌ Módulo no existe: $shared_path${NC}"
              has_errors=1
            else
              # Estamos en un proyecto de usuario, puede no estar instalado aún
              echo -e "${YELLOW}    ⚠️  Ruta no encontrada: $shared_path${NC}"
              echo -e "${YELLOW}       Puede ser válida si el módulo aún no está instalado${NC}"
              has_warnings=1
            fi
          fi
        fi
      done <<< "$shared_items"
    fi
  fi

  if [ $has_errors -eq 1 ]; then
    return 1
  elif [ $has_warnings -eq 1 ]; then
    return 2
  else
    return 0
  fi
}

# Validación específica para Flutter
validate_flutter_configuration() {
  local config_file=$1
  local config_dir=$2
  local has_errors=0
  local has_warnings=0

  echo -e "  🔍 Validando configuración Flutter..."

  # Verificar estructura esperada para Flutter
  local has_libraries=$(jq 'has("libraries")' "$config_file")
  local has_dev_libraries=$(jq 'has("dev_libraries")' "$config_file")
  local has_shared=$(jq 'has("shared")' "$config_file")

  if [ "$has_libraries" != "true" ] && [ "$has_dev_libraries" != "true" ] && [ "$has_shared" != "true" ]; then
    echo -e "${YELLOW}  ⚠️  Advertencia: No se encontró sección 'libraries', 'dev_libraries' ni 'shared'${NC}"
    has_warnings=1
  fi

  # Validar libraries si existen
  if [ "$has_libraries" == "true" ]; then
    echo -e "  🔍 Validando libraries..."
    local libraries_count=$(jq '[.libraries[]?] | length' "$config_file")

    if [ "$libraries_count" -gt 0 ]; then
      # Validar librerías inválidas (excluyendo dependencias especiales como flutter sdk)
      # Una librería es inválida si:
      # - No tiene 'name' Y tampoco tiene referencias especiales (flutter, cupertino_icons con path, etc)
      # - O tiene 'name' pero no tiene ni 'version' ni 'git.url'
      local invalid_libs=$(jq -r '[.libraries[]? | select(
        (.name == null or .name == "") and
        (.flutter == null) and
        (.cupertino_icons == null)
      )] | length' "$config_file")

      if [ "$invalid_libs" -gt 0 ]; then
        echo -e "${RED}    ❌ Hay $invalid_libs librerías sin 'name' ni referencia válida${NC}"
        has_errors=1
      fi

      # Validar que las librerías con name tengan version o git.url
      local no_source=$(jq -r '[.libraries[]? | select(
        (.name != null and .name != "") and
        (.version == null or .version == "") and
        (.git.url == null or .git.url == "")
      )] | length' "$config_file")

      if [ "$no_source" -gt 0 ]; then
        echo -e "${RED}    ❌ Hay $no_source librerías sin 'version' ni 'git.url'${NC}"
        has_errors=1
      fi

      if [ $has_errors -eq 0 ]; then
        echo -e "${GREEN}    ✅ Libraries válidas ($libraries_count encontradas)${NC}"
      fi
    fi
  fi

  # Validar dev_libraries si existen
  if [ "$has_dev_libraries" == "true" ]; then
    echo -e "  🔍 Validando dev_libraries..."
    local dev_libraries_count=$(jq '[.dev_libraries[]?] | length' "$config_file")

    if [ "$dev_libraries_count" -gt 0 ]; then
      # Validar que cada librería tenga name
      local no_name=$(jq -r '[.dev_libraries[]? | select(.name == null or .name == "")] | length' "$config_file")
      if [ "$no_name" -gt 0 ]; then
        echo -e "${RED}    ❌ Hay $no_name dev_libraries sin 'name'${NC}"
        has_errors=1
      fi

      # Validar que tengan version o git.url
      local no_source=$(jq -r '[.dev_libraries[]? | select((.version == null or .version == "") and (.git.url == null or .git.url == ""))] | length' "$config_file")
      if [ "$no_source" -gt 0 ]; then
        echo -e "${RED}    ❌ Hay $no_source dev_libraries sin 'version' ni 'git.url'${NC}"
        has_errors=1
      fi

      if [ $has_errors -eq 0 ]; then
        echo -e "${GREEN}    ✅ Dev_libraries válidas ($dev_libraries_count encontradas)${NC}"
      fi
    fi
  fi

  # Validar shared (rutas a módulos compartidos)
  if [ "$has_shared" == "true" ]; then
    echo -e "  🔍 Validando rutas en shared..."
    local shared_items=$(jq -r '.shared[]? // empty' "$config_file")

    if [ -n "$shared_items" ]; then
      local project_root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)

      while IFS= read -r shared_path; do
        if [ -n "$shared_path" ]; then
          # Las rutas en shared pueden ser relativas al directorio lib/
          local search_path=""

          # Intentar buscar desde la raíz del proyecto
          search_path="$project_root/lib/$shared_path"

          if [ -d "$search_path" ]; then
            echo -e "${GREEN}    ✅ Ruta encontrada: $shared_path${NC}"
          else
            # Verificar si es una ruta del TEMPORARY_DIR
            if [ -n "$TEMPORARY_DIR" ] && [ -d "$TEMPORARY_DIR/lib/$shared_path" ]; then
              echo -e "${GREEN}    ✅ Ruta encontrada en repositorio: $shared_path${NC}"
            else
              echo -e "${YELLOW}    ⚠️  Ruta no encontrada: $shared_path (se validará durante instalación)${NC}"
              has_warnings=1
            fi
          fi
        fi
      done <<< "$shared_items"
    fi
  fi

  if [ $has_errors -eq 1 ]; then
    return 1
  elif [ $has_warnings -eq 1 ]; then
    return 2
  else
    return 0
  fi
}

# Validación específica para Python
validate_python_configuration() {
  local config_file=$1
  local config_dir=$2
  local has_errors=0
  local has_warnings=0

  echo -e "  🔍 Validando configuración Python..."

  # Verificar estructura esperada para Python
  local has_requirements=$(jq 'has("requirements")' "$config_file")
  local has_modules=$(jq 'has("modules")' "$config_file")

  if [ "$has_requirements" != "true" ]; then
    echo -e "${YELLOW}  ⚠️  Advertencia: No se encontró sección 'requirements'${NC}"
    has_warnings=1
  fi

  # Validar módulos referenciados si existen
  if [ "$has_modules" == "true" ]; then
    echo -e "  🔍 Validando módulos referenciados..."
    local modules=$(jq -r '.modules[]? // empty' "$config_file")
    if [ -n "$modules" ]; then
      while IFS= read -r module; do
        if [ -n "$module" ]; then
          local project_root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
          local search_path="$project_root/$module"

          if [ -d "$search_path" ]; then
            echo -e "${GREEN}    ✅ Módulo encontrado: $module${NC}"
          else
            echo -e "${RED}    ❌ Módulo no encontrado: $module${NC}"
            has_errors=1
          fi
        fi
      done <<< "$modules"
    fi
  fi

  if [ $has_errors -eq 1 ]; then
    return 1
  elif [ $has_warnings -eq 1 ]; then
    return 2
  else
    return 0
  fi
}

# Función para validar solo archivos staged en git (para pre-commit)
validate_staged_configurations() {
  echo ""
  echo -e "${BOLD}═══════════════════════════════════════════════${NC}"
  echo -e "${BOLD}   VALIDACIÓN DE ARCHIVOS .TURIA (STAGED)       ${NC}"
  echo -e "${BOLD}═══════════════════════════════════════════════${NC}"
  echo ""

  # Detectar tipo de proyecto primero
  local project_type=""
  if check_type_of_project; then
    type=0
  else
    type=$?
  fi

  case "$type" in
    0) project_type="Android" ;;
    1) project_type="iOS" ;;
    2) project_type="Flutter" ;;
    3) project_type="Python" ;;
    *)
      echo -e "${RED}❌ Error: No se detectó un tipo de proyecto válido${NC}"
      return 1
      ;;
  esac

  # Obtener archivos .turia en staging según el tipo de proyecto
  local staged_configs=""
  if [ "$project_type" == "iOS" ]; then
    # En iOS buscar todos los archivos .turia
    staged_configs=$(git diff --cached --name-only --diff-filter=ACMR | grep "\.turia$" || true)
  else
    # Para otros proyectos buscar configuration.turia
    staged_configs=$(git diff --cached --name-only --diff-filter=ACMR | grep "configuration\.turia$" || true)
  fi

  if [ -z "$staged_configs" ]; then
    if [ "$project_type" == "iOS" ]; then
      echo -e "${GREEN}✅ No hay archivos .turia en staging${NC}"
    else
      echo -e "${GREEN}✅ No hay archivos configuration.turia en staging${NC}"
    fi
    return 0
  fi

  if [ "$project_type" == "iOS" ]; then
    echo -e "${BOLD}Archivos .turia encontrados en staging:${NC}"
  else
    echo -e "${BOLD}Archivos configuration.turia encontrados en staging:${NC}"
  fi
  echo "$staged_configs"
  echo ""
  echo -e "${GREEN}✅ Tipo de proyecto detectado: $project_type${NC}"
  echo ""

  local error_count=0

  # Validar cada archivo staged
  while IFS= read -r config_file; do
    if [ -n "$config_file" ]; then
      # Capturar el resultado - no usar local result=$? directamente
      validate_single_configuration "$config_file" "$project_type" && result=0 || result=$?

      if [ $result -eq 1 ]; then
        error_count=$((error_count + 1))
      fi
    fi
  done <<< "$staged_configs"

  echo ""
  if [ $error_count -gt 0 ]; then
    echo -e "${RED}❌ Validación fallida: $error_count archivo(s) con errores${NC}"
    echo -e "${YELLOW}Por favor corrige los errores antes de hacer commit${NC}"
    return 1
  else
    if [ "$project_type" == "iOS" ]; then
      echo -e "${GREEN}✅ Todos los archivos .turia en staging son válidos${NC}"
    else
      echo -e "${GREEN}✅ Todos los archivos configuration.turia en staging son válidos${NC}"
    fi
    return 0
  fi
}
