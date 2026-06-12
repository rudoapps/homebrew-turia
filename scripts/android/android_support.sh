#!/bin/bash


android_check_module_in_temporary_dir() {
  local module=$1
  if [ ! -d "$TEMPORARY_DIR/${module}" ]; then
    echo -e "${RED}Error: El módulo $module no existe en el repositorio.${NC}"
    echo -e "${RED}No encontrado en: $TEMPORARY_DIR"
    rm -rf "$TEMPORARY_DIR"
    exit 1
  fi
  echo -e "✅ Módulo existe correctamente"
}

android_detect_package_name() {
  if [ -d "$ANDROID_PROJECT_SRC" ]; then
    MAIN_DIRECTORY=$(find "$ANDROID_PROJECT_SRC" -type f \( -name "*.java" -o -name "*.kt" \) -print0 | xargs -0 -n1 dirname | sort -u | head -n 1)
    
    if [ -n "$MAIN_DIRECTORY" ]; then
      echo -e "${GREEN}✅ Encontrado package: $MAIN_DIRECTORY${NC}"
    else
      echo -e "${RED}No se encontraron archivos .java o .kt en $ANDROID_PROJECT_SRC${NC}"
    fi
  else
    echo -e "${RED}No se encontró la ruta base en: $ANDROID_PROJECT_SRC${NC}"
  fi
}


android_verify_module() {
  local module=$1
  MODULE_PATH="$module"
  if [ -d "$MODULE_PATH" ]; then
    echo -e "${YELLOW}El módulo $module ya existe en el proyecto destino.${NC}"

    # Si --force está activo, no preguntar
    if [ "$FORCE_INSTALL" == "true" ]; then
      echo -e "${GREEN}🔄 Actualizando con --force...${NC}"
    else
      read -p "¿Deseas actualizar el módulo existente? (s/n): " CONFIRM
      if [ "$CONFIRM" != "s" ]; then
        echo -e "${RED}Instalación del módulo cancelada.${NC}"
        exit 0
      fi
    fi
    rm -rf "$MODULE_PATH"
    echo -e "✅ Actualización en curso"
  else
    echo -e "✅ Módulo no detectado continua la instalación"
  fi
}

android_create_modules_dir() {
  # En modo integración, no creamos el directorio del módulo
  # porque los archivos se distribuirán en las capas existentes
  if [ "$INTEGRATE_MODE" == "true" ]; then
    echo -e "${YELLOW}ℹ️  Modo integración: el módulo se distribuirá en la estructura existente${NC}"
    return 0
  fi

  EXISTS_THIS_DIR=${MODULE_NAME}
  if [ ! -d "$EXISTS_THIS_DIR" ]; then
    echo -e "${YELLOW}La carpeta '${MODULE_NAME}' no existe. Creándola...${NC}"
    mkdir -p "$EXISTS_THIS_DIR"
    if [ $? -eq 0 ]; then
      echo -e "✅ Módulo '${MODULE_NAME}' creado correctamente"
    else
      echo -e "${RED}Error: No se pudo crear la carpeta '${MODULE_NAME}'.${NC}"
      exit 1
    fi
  fi
}

copy_file_or_create_folder() {
  local origin=$1
  local destination=$2

  if !(check_path_exists "$destination"); then
    echo "No existe CREAMOS DIRECTORIO"
    mkdir -p "$destination"
  fi

  cp -R "${origin}/." "${destination}"
  if [ $? -eq 0 ]; then
    echo "┌──────────────────────────────────────────────"
    echo "│"
    echo "│ Instalando $(basename "$destination ")  "
    echo "│ ✅ Copiado a ${destination} correctamente"
    echo "│"
    echo "└──────────────────────────────────────────────"

  else
    echo -e "${RED}Error: No se pudo copiar el fichero.${NC}"
    return
  fi
  android_install_libraries_dependencies "${origin}/configuration.turia"
  android_install_gradle_dependencies "${origin}/configuration.turia"

  # También procesar módulos anidados recursivamente
  android_install_modules_dependencies_recursive "${origin}/configuration.turia"
} 

android_rename_imports() {
  # Eliminar el string especificado de la ruta
  REMOVE_PATH=$ANDROID_PROJECT_SRC
  MODIFIED_PATH=$(echo "$MAIN_DIRECTORY" | sed "s|$REMOVE_PATH||")
  PACKAGE_NAME=$(echo "$MODIFIED_PATH" | sed 's|/|.|g')
  PACKAGE_NAME="${PACKAGE_NAME/.}"
  echo -e "${YELLOW}Renombrando imports de $TURIA_PACKAGE a $PACKAGE_NAME en los archivos del módulo...${NC}"

  find "$MAIN_DIRECTORY" -type f \( -name "*.java" -o -name "*.kt" \) -print0 | while IFS= read -r -d '' file; do
    sed -i '' "s#$TURIA_PACKAGE#$PACKAGE_NAME#g" "$file"
  done
  if [ $? -eq 0 ]; then
    echo -e "✅ Renombrado completado"
  else
    echo -e "${RED}Error: No se ha podido renombrar.${NC}"
    remove_temporary_dir
    exit 1
  fi
}

android_read_configuration_temporal() {
  local FILE=$1
  
  if [ ! -f "$FILE" ]; then
    echo -e "${RED}Error: El fichero $FILE no existe.${NC}"
  else
    echo "Extrayendo dependencias de: $TEMPORARY_DIR/${MODULE_NAME}/configuration.turia"
    while IFS= read -r line; do   
      if check_directory_exists "./$line"; then    
        copy_file "${TEMPORARY_DIR}/$line" "."
        if [ $? -eq 0 ]; then
          echo -e "✅ $line copiado correctamente"
        else
          echo -e "${RED}Error: No se ha podido renombrar.${NC}"
          remove_temporary_dir
          exit 1
        fi
      fi
    done < "$FILE"
  fi
}

android_read_configuration() {
  FILE="$TEMPORARY_DIR/${MODULE_NAME}/configuration.turia"
  if [ ! -f "$FILE" ]; then
    echo -e "${RED}Error: El fichero $FILE no existe.${NC}"
  else
    while IFS= read -r line; do
      type=$(echo "$line" | cut -d'/' -f1)
      path=$(echo "$line" | cut -d'/' -f2-)
      
      if [ "$type" == "libraries" ]; then
        android_install_library $path
      elif [[ "$type" == "drawables" || "$type" == "strings" ]]; then
        extension="${path##*.}"
        path_without_extension="${path%.*}"
        transformed_path=$(echo "$path_without_extension" | sed 's/\./\//g')
        final_path="$transformed_path.$extension"
        android_decide_what_to_do_with_file $type $final_path
      else
        transformed_path=$(echo "$path" | sed 's/\./\//g')
        android_decide_what_to_do_with_file $type $transformed_path
      fi
      
    done < "$FILE"
  fi
}

android_decide_what_to_do_with_file() {
  local type=$1
  local path=$2
  
  if [ "$type" == "components" ]; then
    component=$(basename "$2")    
      copy_file "${TEMPORARY_DIR}/${ANDROID_PROJECT_SRC}/${path}" "${MAIN_DIRECTORY}/shared/components/${component}"
  elif [[ "$type" == "drawables" || "$type" == "strings" ]]; then 
      copy_file "${TEMPORARY_DIR}/app/src/main/${path}" "app/src/main/${path}"
  else
    echo "Copying file of ${type}: ${path} to ${ANDROID_PROJECT_RES}/${path}"
    echo -e "${YELLOW}Este fichero no se va a copiar debe de revisarse antes${NC}"
  fi
}

android_install_library() {
  local type=$1
  echo "Instalando librería: ${path}"
  echo -e "${YELLOW}Esta librería no se va a instalar todavía.${NC}"

  BUILD_GRADLE_PATH="app/build.gradle.kts"  # Cambia esta ruta según el módulo

  if [ ! -f "$BUILD_GRADLE_PATH" ]; then
    echo "Error: No se encontró el archivo $BUILD_GRADLE_PATH."
    exit 1
  fi

  # android_add_library_if_missing ${path}
}

android_add_library_if_missing() {
  local library=$1
  if grep -q "$library" "$BUILD_GRADLE_PATH"; then
    echo "La librería '$library' ya está en $BUILD_GRADLE_PATH."
  else
    echo "Añadiendo '$library' a $BUILD_GRADLE_PATH."
    # Añadir la librería dentro del bloque dependencies {
    sed -i.bak "/dependencies {/a\    implementation  $library" "$BUILD_GRADLE_PATH"
  fi
}

transform_string() {
  local input_string="$1"
  # Remover el guion y capitalizar la parte después del guion
  transformed_string=$(echo "$input_string" | sed -E 's/-([a-z])/\U\1/g')
  echo "$transformed_string"
}

android_install_modules_dependencies() {
  android_install_modules_dependencies_recursive "$TEMPORARY_DIR/${MODULE_NAME}/configuration.turia"
}

android_install_modules_dependencies_recursive() {
  local json_file="$1"

  if [[ ! -f "$json_file" ]]; then
    return
  fi

  modules=$(jq -r '.modules // empty' "$json_file")

  if [[ -z "$modules" ]]; then
    echo "El campo 'modules' no existe o está vacío en el archivo JSON: $json_file"
    return
  fi

  # Iterar sobre el array 'modules'
  for module in $(echo "$modules" | jq -r '.[]'); do
    copy_file_or_create_folder "${TEMPORARY_DIR}/${module}" "./${module}"

    # Procesar recursivamente las dependencias del módulo recién instalado
    local nested_config="${TEMPORARY_DIR}/${module}/configuration.turia"
    if [[ -f "$nested_config" ]]; then
      echo "✅ Procesando dependencias anidadas de: $module"
      android_install_modules_dependencies_recursive "$nested_config"
    fi
  done
}

android_read_versions_and_install_toml() {
  local json_file="$1" 
  local toml_file=$2
  added_libraries=()
  libraries_to_add=""
  start_versions_line=$(grep -n '^\[versions\]$' "$toml_file" | cut -d: -f1)

  if [[ -z "$start_versions_line" ]]; then
    echo "No se encontró la sección [versions] en el archivo TOML"
    return
  fi

  echo "   ┌──────────────────────────────────────────"
  echo "   │ [VERSIONS] Buscando dependencias"
  echo "   │ Configuración: ${json_file}"
  echo "   │ Toml: ${toml_file}"
  echo "   │"
  while read -r entry; do
    name=$(echo "$entry" | jq -r '.name')
    version=$(echo "$entry" | jq -r '.version')
    group=$(echo "$entry" | jq -r '.group // empty')
    module=$(echo "$entry" | jq -r '.module // empty')

    if grep -q "${name} = \"" "$toml_file"; then
      echo "   │ ✅ $name ya está en la versión $version en el TOML"
    else
      echo "   │ ➕ $name no está en el TOML. Añadiendo a la lista para [versions]..."
      libraries_to_add+="$name = \"$version\"\n"
      added_libraries+=("$name")
    fi
  done < <(
    jq -c '
      . as $root
      | (if ($root | has("toml") and (.toml|type=="array")) then .toml
         elif ($root | has("versions") and (.versions|type=="array")) then .versions
         elif ($root | has("dependencies") and (.dependencies|type=="array")) then .dependencies
         elif ($root | has("libs") and (.libs|type=="array")) then .libs
         else [] end
        )[]' "$json_file"
  )

  if [[ ${#added_libraries[@]} -gt 0 ]]; then
    echo "   │ Librerías añadidas al archivo TOML en la sección [versions]:"

    libraries_to_add=$(printf "%b" "$libraries_to_add")

    if [[ "$OSTYPE" == "darwin"* ]]; then
      # macOS
      printf '%s\n' "$libraries_to_add" | sed -i '' "/^\[versions\]/r /dev/stdin" "$toml_file"
    else
      printf '%s\n' "$libraries_to_add" | sed -i "/^\[versions\]/r /dev/stdin" "$toml_file"
    fi
    echo "   │ ✅ Versiones instaladas."
  else
    echo "   │ ❌No se han añadido elementos a [versions]."
  fi
  echo "   └──────────────────────────────────────────"
  echo ""
}

android_read_libraries_and_install_toml() {
  local json_file="$1" 
  local toml_file=$2
  libraries_to_add=""
  
  start_libraries_line=$(grep -n '^\[libraries\]$' "$toml_file" | cut -d: -f1)

  if [[ -z "$start_libraries_line" ]]; then
    echo "No se encontró la sección [libraries] en el archivo TOML"
    return
  fi

  echo "   ┌──────────────────────────────────────────"
  echo "   │ [LIBRARIES] Buscando dependencias"
  echo "   │ Configuración: ${json_file}"
  echo "   │ Toml: ${toml_file}"
  echo "   │"
  while read -r entry; do
    name=$(echo "$entry" | jq -r '.name')
    group=$(echo "$entry" | jq -r '.group // empty')
    module=$(echo "$entry" | jq -r '.module // empty')
    id=$(echo "$entry" | jq -r '.id // empty')

    if [[ -n "$group" ]]; then
      new_library="$id = { group = \"$group\", name = \"$name\", version.ref = \"$name\" }"
    elif [[ -n "$module" ]]; then
      new_library="$id = { module = \"$module\", name = \"$name\", version.ref = \"$name\"  }"
    else
      continue  # Si no hay ni group ni module, saltar
    fi

    if grep -q "= \"$group\"" "$toml_file"; then
      echo "   │ ✅ $name ya está en [libraries] del TOML"
    elif grep -q "= \"$module\"" "$toml_file"; then      
      echo "   │ ✅ $name ya está en [libraries] del TOML"
    else
      echo "   │ ➕ $name no está en [libraries]. Añadiendo a la lista para [libraries]..."
      libraries_to_add+="$new_library\n"
    fi

  done < <(
    jq -c '
      . as $root
      | (if ($root | has("toml") and (.toml|type=="array")) then .toml
         elif ($root | has("libraries") and (.libraries|type=="array")) then .libraries
         elif ($root | has("libs") and (.libs|type=="array")) then .libs
         else [] end
        )[]' "$json_file"
  )
 
  if [[ -n "$libraries_to_add" ]]; then
    libraries_to_add=$(printf "%b" "$libraries_to_add")

    if [[ "$OSTYPE" == "darwin"* ]]; then
      # macOS
      printf '%s\n' "$libraries_to_add" | sed -i '' "/^\[libraries\]/r /dev/stdin" "$toml_file"
    else
      printf '%s\n' "$libraries_to_add" | sed -i "/^\[libraries\]/r /dev/stdin" "$toml_file"
    fi
    echo "   │ ✅ Librerias instaladas."
  else
    echo "   │ ❌ No se han añadido elementos a [libraries]."
  fi
  echo "   └──────────────────────────────────────────"
  echo ""
}

android_read_plugins_and_install_toml() {
  local json_file="$1" 
  local toml_file=$2
  plugins_to_add=""

  start_libraries_line=$(grep -n '^\[plugins\]$' "$toml_file" | cut -d: -f1)

  if [[ -z "$start_libraries_line" ]]; then
    echo "No se encontró la sección [plugins] en el archivo TOML"
    return
  fi

  echo "   ┌──────────────────────────────────────────"
  echo "   │ [PLUGINS] Buscando dependencias"
  echo "   │ Configuración: ${json_file}"
  echo "   │ Toml: ${toml_file}"
  echo "   │"
  while read -r entry; do
    name=$(echo "$entry" | jq -r '.name')
    plugin=$(echo "$entry" | jq -r '.plugin // empty')
    id=$(echo "$entry" | jq -r '.id // empty')

    if [[ -n "$plugin" ]]; then
      new_plugin="$id = { id = \"$plugin\", version.ref = \"$name\" }"
    else
      continue
    fi

    if grep -q "= \"$plugin\"" "$toml_file"; then
      echo "   │ ✅ $id ya está en [plugins] del TOML"
    else
      plugins_to_add+="$new_plugin\n"
    fi
  done < <(
    jq -c '
      . as $root
      | (if ($root | has("toml") and (.toml|type=="array")) then .toml
         elif ($root | has("plugins") and (.plugins|type=="array")) then .plugins
         else [] end
        )[]' "$json_file"
  )

  if [[ -n "$plugins_to_add" ]]; then
    plugins_to_add=$(printf "%b" "$plugins_to_add")
    if [[ "$OSTYPE" == "darwin"* ]]; then
      # macOS
      printf '%s\n' "$plugins_to_add" | sed -i '' "/^\[plugins\]/r /dev/stdin" "$toml_file"
    else
      printf '%s\n' "$plugins_to_add" | sed -i "/^\[plugins\]/r /dev/stdin" "$toml_file"
    fi
    echo "   │ ✅ Plugins instalados."
  else
    echo "   │ ❌ No se han añadido elementos a [plugins]."
  fi
  echo "   └──────────────────────────────────────────"
  echo ""
}

android_install_libraries_dependencies() {
  local json_file="$1"  
  toml_file="gradle/libs.versions.toml"
  
  if [[ ! -f "$json_file" ]]; then
    return
  fi

  if [[ ! -f "$toml_file" ]]; then
    return
  fi

  android_read_versions_and_install_toml $json_file $toml_file
  android_read_libraries_and_install_toml $json_file $toml_file
  android_read_plugins_and_install_toml $json_file $toml_file
}

android_install_gradle_dependencies() {
  local json_file="$1"
  gradle_file="settings.gradle.kts"
  echo "   ┌──────────────────────────────────────────"
  echo "   │ [GRADLE] Buscando dependencias para "
  echo "   │ Configuración: ${json_file}"
  echo "   │"

  if [[ ! -f "$json_file" ]]; then
    echo "El archivo JSON no existe: $json_file"
    return
  fi

  if [[ ! -f "$gradle_file" ]]; then
    echo "El archivo Gradle no existe: $gradle_file"
    return
  fi
  
  includes=$(jq -c 'if .gradle.includes then .gradle.includes[] else empty end' "$json_file")
  dependencies=$(jq -c 'if .gradle.dependencies then .gradle.dependencies[] else empty end' "$json_file")

  includes_to_add=""

  echo "   │ [1/2] Leyendo includes..."

  for include in $includes; do
    if grep -q "include($include)" "$gradle_file"; then
      echo "   │ ✅ $include ya está en el archivo"
    else
      echo "   │ ➕ $include no está en el archivo. Instalando..."
      includes_to_add+="include(${include})"
    fi
  done

  if [[ -n "$includes_to_add" ]]; then    
    includes_to_add=$(printf "%b" "$includes_to_add")

    if [[ "$OSTYPE" == "darwin"* ]]; then
      printf '%s\n' "$includes_to_add" | sed -i '' "/^include(\"/r /dev/stdin" "$gradle_file"
    else
      printf '%s\n' "$includes_to_add" | sed -i "/^include(\"/r /dev/stdin" "$gradle_file"
    fi
    echo "   │ ✅ Instalados includes en gradle"
  else
    echo "   │ ❌ No hay información nueva que añadir."
  fi
  echo "   │ "

  repositories_to_add=""

  echo "   │ [2/2] Leyendo dependencias..."

  for dep in $dependencies; do
    name=$(echo "$dep" | jq -r '.name')
    url=$(echo "$dep" | jq -r '.url')

    if grep -q "$name(\"$url\")" "$gradle_file"; then
      echo "   │ ✅ $url ya está en el archivo"
    else
      echo "   │ ➕ $url no está en el archivo. Añadiendo..."
      repositories_to_add+="\t\t${name}(\"$url\")"
    fi
  done

  if [[ -n "$repositories_to_add" ]]; then
    echo "   │ Añadiendo nuevos repositorios al archivo..."

    # Usamos awk para insertar los nuevos repositorios después de 'repositories {' dentro de 'dependencyResolutionManagement'
    awk -v repos="$repositories_to_add" '
      /dependencyResolutionManagement/ {in_dependency_block=1}
      in_dependency_block && /repositories {/ {print; print repos; in_dependency_block=0; next}
      {print}
    ' "$gradle_file" > tmp && mv tmp "$gradle_file"

    echo "   │ ✅ Repositorios añadidos en build.gradle.kts"
  else
    echo "   │ ❌ No hay nuevos repositorios que añadir."
  fi

  echo "   │ ✅ Modificaciones completadas."
  echo "   └──────────────────────────────────────────"
  echo ""
}

android_install_main_dependencies() {
  json_file="${TEMPORARY_DIR}/configuration.turia"
  gradle_file="build.gradle.kts"

  plugins_to_add=""
  echo "   ┌──────────────────────────────────────────"
  echo "   │ [TOML] Instalando dependencias generales"
  while read -r plugin; do
    alias=$(echo "$plugin" | jq -r '.alias')
    apply=$(echo "$plugin" | jq -r '.apply')

    if grep -q "alias($alias)" "$gradle_file"; then
      echo "   │ ✅ $alias ya está en el archivo"
    else
      echo "   │ ➕ $alias no está en el archivo. Añadiendo..."
      plugins_to_add+="\talias($alias) apply $apply\n"
    fi
  done < <(jq -c '.plugins // [] | .[]' "$json_file")

  if [[ -n "$plugins_to_add" ]]; then
    echo "   │ Añadiendo nuevos plugins al archivo..."
    plugins_to_add=$(printf "%b" "$plugins_to_add")

    if [[ "$OSTYPE" == "darwin"* ]]; then
      # macOS
      printf '%s\n' "$plugins_to_add" | sed -i '' "/plugins {/r /dev/stdin" "$gradle_file"
    else
      printf '%s\n' "$plugins_to_add" | sed -i "/plugins {/r /dev/stdin" "$gradle_file"
    fi
    echo "   │ ✅ Plugins añadidos en build.gradle.kts"
  else
    echo "   │ ❌ No hay nuevos plugins que añadir."
  fi
  echo "   └──────────────────────────────────────────"
}