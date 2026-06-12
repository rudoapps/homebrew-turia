#!/bin/bash

ANDROID_PROJECT_SRC="app/src/main/java"
TURIA_PACKAGE="app.turia.com"
MODULES_PATH="modules"

install_android_modules_batch() {
  echo -e "${BOLD}-----------------------------------------------${NC}"
  echo -e "${BOLD}Instalación BATCH de ${#MODULE_NAMES[@]} módulos Android${NC}"
  echo -e "${BOLD}Módulos: ${MODULE_NAMES[*]}${NC}"
  echo -e "${BOLD}-----------------------------------------------${NC}"

  echo -e "${BOLD}-----------------------------------------------${NC}"
  echo -e "${BOLD}Prerequisitos: Validando.${NC}"
  echo -e "${BOLD}-----------------------------------------------${NC}"

  # Variable para controlar si la instalación fue exitosa
  local installation_success=false
  local modules_installed=()

  # Función para manejar errores durante la instalación
  handle_installation_error() {
    if [ "$installation_success" = false ]; then
      echo -e "${RED}❌ Error durante la instalación batch de módulos Android${NC}"
      for module in "${modules_installed[@]}"; do
        log_operation "install" "android" "$module" "${BRANCH:-main}" "error" "Instalación batch interrumpida"
      done
      remove_temporary_dir
    fi
  }

  # Configurar trap para capturar errores y interrupciones
  trap handle_installation_error ERR EXIT

  TURIA_COMMAND="install"
  get_access_token $KEY "android"

  echo -e "${BOLD}-----------------------------------------------${NC}"
  echo -e "${BOLD}STEP1 - Clonación temporal del proyecto de TURIA.${NC}"
  echo -e "${BOLD}-----------------------------------------------${NC}"

  if [ -n "${TAG:-}" ]; then
    echo -e "🏷️  Usando tag: ${YELLOW}$TAG${NC}"
    git clone --branch "$TAG" "https://x-token-auth:$ACCESSTOKEN@bitbucket.org/rudoapps/turia-android.git" "$TEMPORARY_DIR"
  elif [ -n "${BRANCH:-}" ]; then
    echo -e "🌿 Usando rama: ${YELLOW}$BRANCH${NC}"
    git clone --branch "$BRANCH" "https://x-token-auth:$ACCESSTOKEN@bitbucket.org/rudoapps/turia-android.git" "$TEMPORARY_DIR"
  else
    git clone "https://x-token-auth:$ACCESSTOKEN@bitbucket.org/rudoapps/turia-android.git" "$TEMPORARY_DIR"
  fi

  echo -e "${BOLD}-----------------------------------------------${NC}"
  echo -e "${BOLD}STEP2 - Localizar package name del proyecto.${NC}"
  echo -e "${BOLD}-----------------------------------------------${NC}"

  android_detect_package_name

  echo -e "${BOLD}-----------------------------------------------${NC}"
  echo -e "${BOLD}STEP3 - Verificar existencia carpeta modules.${NC}"
  echo -e "${BOLD}-----------------------------------------------${NC}"
  android_create_modules_dir

  echo -e "${BOLD}-----------------------------------------------${NC}"
  echo -e "${BOLD}STEP4 - Copiar ficheros de todos los módulos.${NC}"
  echo -e "${BOLD}-----------------------------------------------${NC}"

  # Iterar sobre cada módulo
  for MODULE_NAME in "${MODULE_NAMES[@]}"; do
    echo ""
    echo -e "${YELLOW}📦 Procesando módulo: ${BOLD}$MODULE_NAME${NC}"

    # Verificar si el módulo ya está instalado
    local is_reinstall=false
    if is_module_installed "android" "$MODULE_NAME"; then
      if ! handle_module_reinstallation "android" "$MODULE_NAME" "${BRANCH:-main}"; then
        echo -e "${YELLOW}⏭️  Saltando módulo $MODULE_NAME${NC}"
        continue
      fi
      is_reinstall=true
    else
      log_operation "install" "android" "$MODULE_NAME" "${BRANCH:-main}" "started"
    fi

    modules_installed+=("$MODULE_NAME")

    # Verificar que el módulo existe en el repositorio clonado
    if ! android_check_module_in_temporary_dir "$MODULE_NAME"; then
      echo -e "${RED}❌ Error: Módulo $MODULE_NAME no encontrado en el repositorio${NC}"
      log_operation "install" "android" "$MODULE_NAME" "${BRANCH:-main}" "error" "Módulo no encontrado"
      continue
    fi

    # Copiar el módulo al proyecto destino
    echo -e "${YELLOW}Inicio copiado del módulo ${TEMPORARY_DIR}/${MODULE_NAME} en: ${MODULE_NAME}${NC}"
    copy_files "${TEMPORARY_DIR}/${MODULE_NAME}" "."
    echo -e "${GREEN}✅ Módulo $MODULE_NAME copiado${NC}"

    # Instalar dependencias del módulo
    android_install_libraries_dependencies "$TEMPORARY_DIR/${MODULE_NAME}/configuration.turia"
    android_install_gradle_dependencies "$TEMPORARY_DIR/${MODULE_NAME}/configuration.turia"
  done

  echo ""
  echo -e "${BOLD}-----------------------------------------------${NC}"
  echo -e "${BOLD}STEP5 - Instalar dependencias principales.${NC}"
  echo -e "${BOLD}-----------------------------------------------${NC}"
  android_install_main_dependencies

  echo -e "${BOLD}-----------------------------------------------${NC}"
  echo -e "${BOLD}STEP6 - Instalar dependencias de módulos.${NC}"
  echo -e "${BOLD}-----------------------------------------------${NC}"
  android_install_modules_dependencies

  echo -e "${GREEN}-----------------------------------------------${NC}"
  echo -e "${GREEN}Proceso batch finalizado. ${#modules_installed[@]} módulos instalados.${NC}"
  echo -e "${GREEN}-----------------------------------------------${NC}"

  # Marcar instalación como exitosa
  installation_success=true

  # Log éxito de cada módulo instalado
  for MODULE_NAME in "${modules_installed[@]}"; do
    log_operation "install" "android" "$MODULE_NAME" "${BRANCH:-main}" "success"
    log_installed_module "android" "$MODULE_NAME" "${BRANCH:-main}"
  done

  # Remover trap de error ya que la instalación fue exitosa
  trap - ERR EXIT

  echo -e "${BOLD}-----------------------------------------------${NC}"
  echo -e "${BOLD}STEP7 - Eliminación repositorio temporal.${NC}"
  echo -e "${BOLD}-----------------------------------------------${NC}"
  remove_temporary_dir
}

list_android() {
  echo -e "${BOLD}-----------------------------------------------${NC}"
  echo -e "${BOLD}Prerequisitos: Validando.${NC}"
  echo -e "${BOLD}-----------------------------------------------${NC}"

  # Log operación de listado
  log_operation "list" "android" "modules" "${BRANCH:-main}" "started"

  TURIA_COMMAND="list"
  get_access_token $KEY "android"

  # Intentar obtener módulos permitidos del backend
  local allowed_modules=$(get_allowed_modules "$KEY" "android")
  local get_modules_result=$?

  # Si el backend devuelve módulos filtrados, mostrarlos sin clonar
  if [ $get_modules_result -eq 0 ] && [ "$allowed_modules" != "UNRESTRICTED" ] && [ "$allowed_modules" != "FALLBACK_TO_OLD_METHOD" ]; then
    echo ""
    echo -e "${GREEN}✅ Usando lista de módulos desde el servidor${NC}"
    echo -e "${BOLD}Lista de módulos disponibles:"
    echo -e "${BOLD}-----------------------------------------------${NC}"
    echo "$allowed_modules"
    echo -e "${BOLD}-----------------------------------------------${NC}"
    log_operation "list" "android" "modules" "${BRANCH:-main}" "success"
    return 0
  fi

  # Si no hay módulos permitidos
  if [ "$allowed_modules" = "NO_MODULES_ALLOWED" ]; then
    echo ""
    echo -e "${RED}⚠️  Tu cuenta no tiene acceso a ningún módulo de Android${NC}"
    echo -e "${RED}   Contacta con el administrador para obtener permisos${NC}"
    log_operation "list" "android" "modules" "${BRANCH:-main}" "error" "no_modules_allowed"
    return 1
  fi

  # Si unrestricted o fallback, usar método tradicional (clonar repo)
  echo -e "${BOLD}-----------------------------------------------${NC}"
  echo -e "${BOLD}STEP1 - Clonación temporal del proyecto de TURIA.${NC}"
  echo -e "${BOLD}-----------------------------------------------${NC}"

  if [ -n "${TAG:-}" ]; then
    echo -e "🏷️  Usando tag: ${YELLOW}$TAG${NC}"
    git clone --branch "$TAG" "https://x-token-auth:$ACCESSTOKEN@bitbucket.org/rudoapps/turia-android.git" "$TEMPORARY_DIR"
  elif [ -n "${BRANCH:-}" ]; then
    echo -e "🌿 Usando rama: ${YELLOW}$BRANCH${NC}"
    git clone --branch "$BRANCH" "https://x-token-auth:$ACCESSTOKEN@bitbucket.org/rudoapps/turia-android.git" "$TEMPORARY_DIR"
  else
    git clone "https://x-token-auth:$ACCESSTOKEN@bitbucket.org/rudoapps/turia-android.git" "$TEMPORARY_DIR"
  fi
  echo ""
  echo -e "${BOLD}Lista de módulos disponibles:"
  echo -e "${BOLD}-----------------------------------------------${NC}"
  standardized_list_modules "" "app" "gradle" "shared"
  echo -e "${BOLD}-----------------------------------------------${NC}"

  # Log éxito del listado
  log_operation "list" "android" "modules" "${BRANCH:-main}" "success"

  remove_temporary_dir
}

install_android_module() {
  echo -e "${BOLD}-----------------------------------------------${NC}"
  echo -e "${BOLD}Prerequisitos: Validando.${NC}"
  echo -e "${BOLD}-----------------------------------------------${NC}"

  # Verificar si el módulo ya está instalado
  local is_reinstall=false
  if is_module_installed "android" "$MODULE_NAME"; then
    if ! handle_module_reinstallation "android" "$MODULE_NAME" "${BRANCH:-main}"; then
      exit 0  # Usuario canceló la instalación
    fi
    is_reinstall=true
  else
    # Log inicio de operación (solo para nuevas instalaciones)
    log_operation "install" "android" "$MODULE_NAME" "${BRANCH:-main}" "started"
  fi

  # Variable para controlar si la instalación fue exitosa
  local installation_success=false

  # Función para manejar errores durante la instalación
  handle_installation_error() {
    # Solo registrar error si la instalación no fue marcada como exitosa
    if [ "$installation_success" = false ]; then
      echo -e "${RED}❌ Error durante la instalación del módulo Android${NC}"
      if [ "$is_reinstall" = true ]; then
        log_operation "reinstall" "android" "$MODULE_NAME" "${BRANCH:-main}" "error" "Instalación interrumpida o falló"
      else
        log_operation "install" "android" "$MODULE_NAME" "${BRANCH:-main}" "error" "Instalación interrumpida o falló"
      fi
      remove_temporary_dir
    fi
  }

  # Configurar trap para capturar errores y interrupciones
  trap handle_installation_error ERR EXIT

  TURIA_COMMAND="install"
  get_access_token $KEY "android"
  
  echo -e "${BOLD}-----------------------------------------------${NC}"
  echo -e "${BOLD}STEP1 - Clonación temporal del proyecto de TURIA.${NC}"
  echo -e "${BOLD}-----------------------------------------------${NC}"

  if [ -n "${TAG:-}" ]; then
    echo -e "🏷️  Usando tag: ${YELLOW}$TAG${NC}"
    git clone --branch "$TAG" "https://x-token-auth:$ACCESSTOKEN@bitbucket.org/rudoapps/turia-android.git" "$TEMPORARY_DIR"
  elif [ -n "${BRANCH:-}" ]; then
    echo -e "🌿 Usando rama: ${YELLOW}$BRANCH${NC}"
    git clone --branch "$BRANCH" "https://x-token-auth:$ACCESSTOKEN@bitbucket.org/rudoapps/turia-android.git" "$TEMPORARY_DIR"
  else
    git clone "https://x-token-auth:$ACCESSTOKEN@bitbucket.org/rudoapps/turia-android.git" "$TEMPORARY_DIR"
  fi

  echo -e "${BOLD}-----------------------------------------------${NC}"
  echo -e "${BOLD}STEP2 - Localizar package name del proyecto.${NC}"
  echo -e "${BOLD}-----------------------------------------------${NC}"
  
  android_detect_package_name 

  # Verificar que el módulo existe en el repositorio clonado
  echo -e "${BOLD}-----------------------------------------------${NC}"
  echo -e "${BOLD}STEP3 - Verificación de la existencia del módulo: ${MODULE_NAME}.${NC}"
  echo -e "${BOLD}-----------------------------------------------${NC}"
  android_check_module_in_temporary_dir $MODULE_NAME

  # Verificar si el módulo ya está instalado en el proyecto destino
  echo -e "${BOLD}-----------------------------------------------${NC}"
  echo -e "${BOLD}STEP4 - Verificación instalación previa del módulo: ${MODULE_NAME}.${NC}"
  echo -e "${BOLD}-----------------------------------------------${NC}"
  android_verify_module $MODULE_NAME
  
  # Verificar si la carpeta 'modules' existe; si no, crearla
  echo -e "${BOLD}-----------------------------------------------${NC}"
  echo -e "${BOLD}STEP5 - Verificación existencia carpeta: ${MODULE_NAME}.${NC}"
  echo -e "${BOLD}-----------------------------------------------${NC}"
  android_create_modules_dir

  # Copiar el módulo al proyecto destino
  echo -e "${BOLD}-----------------------------------------------${NC}"
  echo -e "${BOLD}STEP6 - Copiar ficheros al proyecto.${NC}"
  echo -e "${BOLD}-----------------------------------------------${NC}"

  # Copiar módulo completo
  echo -e "${YELLOW}Inicio copiado del módulo ${TEMPORARY_DIR}/${MODULE_NAME} en: ${MODULE_NAME}${NC}"
  copy_files "${TEMPORARY_DIR}/${MODULE_NAME}" "."

   # Renombrar los imports en los archivos .java y .kt del módulo copiado
  echo -e "${BOLD}-----------------------------------------------${NC}"
  echo -e "${BOLD}STEP7 - Renombrar imports.${NC}"
  echo -e "${BOLD}-----------------------------------------------${NC}"
  # android_rename_imports

  echo -e "${BOLD}-----------------------------------------------${NC}"
  echo -e "${BOLD}STEP8 - Instalar dependencias principales.${NC}"
  echo -e "${BOLD}-----------------------------------------------${NC}"
  android_install_main_dependencies

  echo -e "${BOLD}-----------------------------------------------${NC}"
  echo -e "${BOLD}STEP9 - Copiar/instalar las dependencias.${NC}"
  echo -e "${BOLD}-----------------------------------------------${NC}"
  android_install_libraries_dependencies "$TEMPORARY_DIR/${MODULE_NAME}/configuration.turia"
  android_install_gradle_dependencies "$TEMPORARY_DIR/${MODULE_NAME}/configuration.turia"
  android_install_modules_dependencies

  echo -e "${GREEN}-----------------------------------------------${NC}"
  echo -e "${GREEN}Proceso finalizado.${NC}"
  echo -e "${GREEN}-----------------------------------------------${NC}"
  
  # Marcar instalación como exitosa antes de la limpieza
  installation_success=true
  
  # Log éxito de instalación
  if [ "$is_reinstall" = true ]; then
    log_operation "reinstall" "android" "$MODULE_NAME" "${BRANCH:-main}" "success"
  else
    log_operation "install" "android" "$MODULE_NAME" "${BRANCH:-main}" "success"
  fi
  log_installed_module "android" "$MODULE_NAME" "${BRANCH:-main}"
  
  # Remover trap de error ya que la instalación fue exitosa
  trap - ERR EXIT
  
  echo -e "${BOLD}-----------------------------------------------${NC}"
  echo -e "${BOLD}STEP10 - Eliminación repositorio temporal.${NC}"
  echo -e "${BOLD}-----------------------------------------------${NC}"
  remove_temporary_dir
}

install_templates_android() {
  echo -e "${BOLD}-----------------------------------------------${NC}"
  echo -e "${BOLD}Iniciando instalación de templates Android.${NC}"
  echo -e "${BOLD}-----------------------------------------------${NC}"
  
  # Log inicio de generación de template
  log_operation "template" "android" "$MODULE_NAME" "local" "started"
  
  android_install_all_templates "$MODULE_NAME"

  if [ $? -eq 0 ]; then
    echo -e "✅ El template '$MODULE_NAME' fue generado correctamente."
    # Log éxito de generación de template
    log_operation "template" "android" "$MODULE_NAME" "local" "success"
  else
    echo -e "${RED}Error: Algo salió mal al ejecutar ${NC}"
    # Log error de generación de template
    log_operation "template" "android" "$MODULE_NAME" "local" "error" "Error durante la generación del template"
    exit 1
  fi
}