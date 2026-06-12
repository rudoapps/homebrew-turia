#!/usr/bin/env bash

# Constants
ARCH_REPO="git@bitbucket.org:rudoapps/architecture-ios"
ARCH_ASP_NAME="Template"
ARCH_APP_ID="com.template"

# Storing execution path
execPath=$PWD

# Help function
helpFun(){
    echo -e "\n\033[1;1m[Usage]\n$0 -d <project_destination_path> -g <git_repo> -b <bundle_id> -v <archetype_version> -u <user_name> -e <user_email>"
    echo -e "\n\033[1;1m[Parameters]"
    echo -e "\033[1;1m\t-d\tDestination path for the new project. The archetype will be cloned into this path. E.g. '../NewApp'"
    echo -e "\033[1;1m\t-g\tThe url of the GIT repository for this new app."
    echo -e "\033[1;1m\t-n\tName of the new app (Optional) E.g. 'NewApp'"
    echo -e "\033[1;1m\t-b\tThe base bundle identifier. E.g. 'com.rudo.archetype'"
    exit 1
}

get_token_for_ios() {
    echo "┌──────────────────────────────────────────────"
    echo "│"
    echo "│ Validando key"
    echo "│ "
    echo "└──────────────────────────────────────────────"
    TURIA_COMMAND="create"
    get_access_token $KEY "ios"
}




# Check the step execution result
checkResult(){
    if [ $? != 0 ]
    then
        echo "│"
        echo "│ ❌ '$1' paso FALLIDO.\n"
        echo "│"
        echo "└──────────────────────────────────────────────" 
    exit 1
    fi
}

# Check the step execution result - Environment
optionalCheckResult(){
    if [ $? != 0 ]
    then
    echo -e "\n❌ '$1' paso FALLIDO.\n"
    echo -e "\nContinuando...\n"
    fi
}

pause(){
    read -p "Presiona [Enter] para continuar..."
}

ios_create_project() {
    # Reading parameters
    # Preguntar parámetros al usuario  
    echo -e "\nIntroduce la ruta de destino para el nuevo proyecto (por ejemplo: NuevaApp)"
    read -r projectPath

    echo -e "\nIntroduce el nombre de la nueva app (o dejalo en blanco para dejar el del arquetipo):"
    read -r appName

    echo -e "\nIntroduce el nombre del bundle (e.g. com.rudo.archetype):"
    read -r appId
    echo "──────────────────────────────────────────────"

    # Validación básica
    if [ -z "$projectPath" ] || [ -z "$appId" ]; then
        echo -e "\n❌ Faltan campos requeridos (ruta del proyecto y bundle ID).\n"
        return 1
    fi

    echo -e "Iniciando configuración"

    # Getting app name
    echo -e "Obteniendo nombre de la nueva app ...\n"
    if [ -z "$appName" ]; then
        if [[ $gitRepo =~ ^.*\/(.*)\.git$ ]]; then
            appName=${BASH_REMATCH[1]}
        else
            echo -e "\n❌ El nombre de la app no es válido.\n"

            exit 1
        fi
    fi
    echo -e "✅ Nombre de la app encontrado: $appName\n"

    # Cloning archetype
    echo -e "Clonando el repositorio del arquetipo de rudo..."
    get_token_for_ios

    # Verificar si la carpeta destino ya existe
    if [ -d "$projectPath" ]; then
        echo -e "📁 La carpeta destino ya existe: $projectPath"
        echo -e "📥 Clonando contenido directamente en la carpeta existente..."

        # Clonar en una carpeta temporal
        local temp_clone_dir=$(mktemp -d)

        if [ -n "${BRANCH:-}" ]; then
            echo -e "🌿 Usando rama: $BRANCH"
            git clone --branch "$BRANCH" "https://x-token-auth:$ACCESSTOKEN@bitbucket.org/rudoapps/architecture-ios.git" "$temp_clone_dir/repo"
        else
            git clone "https://x-token-auth:$ACCESSTOKEN@bitbucket.org/rudoapps/architecture-ios.git" "$temp_clone_dir/repo"
        fi
        checkResult "Clonando archetype repository"

        # Mover el contenido a la carpeta destino
        # Usamos rsync para manejar archivos ocultos correctamente
        if command -v rsync >/dev/null 2>&1; then
            rsync -a "$temp_clone_dir/repo/" "$projectPath/"
        else
            # Fallback: usar cp con archivos ocultos
            cp -R "$temp_clone_dir/repo/." "$projectPath/"
        fi
        checkResult "Moviendo contenido a carpeta destino"

        # Limpiar carpeta temporal
        rm -rf "$temp_clone_dir"
        echo -e "✅ Contenido clonado en carpeta existente"
    else
        # Comportamiento normal: la carpeta no existe, git la crea
        if [ -n "${BRANCH:-}" ]; then
            echo -e "🌿 Usando rama: $BRANCH"
            git clone --branch "$BRANCH" "https://x-token-auth:$ACCESSTOKEN@bitbucket.org/rudoapps/architecture-ios.git" "$projectPath"
        else
            git clone "https://x-token-auth:$ACCESSTOKEN@bitbucket.org/rudoapps/architecture-ios.git" "$projectPath"
        fi
        checkResult "Clonando archetype repository"
    fi
    echo "┌──────────────────────────────────────────────"
    echo "│"
    echo "│ ✅ Clonado completado"
    echo "│"
    # Moving to new app directory
    echo "│ Moviendo a la carpeta: '$execPath/$projectPath'..."
    cd $execPath/$projectPath
    checkResult "Moviendo a la carpeta"
    echo "│"
    echo "│ ✅ Movimiento completado"
    echo "│"

    # Rename Main target directory
    echo "│ Renombrando la carpeta ${ARCH_ASP_NAME} a ${appName} ... "
    mv ${ARCH_ASP_NAME} ${appName}
    checkResult "Renombrando carpeta ${ARCH_ASP_NAME}"
    echo "│"
    echo "│ ✅ Renombrado completado"
    echo "│"
    

    # Rename Tests target directory∫
    echo "│ Renombrando la carpeta ${ARCH_ASP_NAME}Tests a ${appName}Tests ..."
    mv ${ARCH_ASP_NAME}Tests ${appName}Tests
    checkResult "Renombrando carpeta ${ARCH_ASP_NAME}Tests"
    echo "│"
    echo "│ ✅ Renombrado completado"
    echo "│"

    # Rename main test file if it exists
    if [ -f "${appName}Tests/${ARCH_ASP_NAME}Tests.swift" ]; then
        echo "│ Renombrando ${ARCH_ASP_NAME}Tests.swift a ${appName}Tests.swift ..."
        mv "${appName}Tests/${ARCH_ASP_NAME}Tests.swift" "${appName}Tests/${appName}Tests.swift"
        checkResult "Renombrando archivo de test principal"
        echo "│"
        echo "│ ✅ Renombrado completado"
        echo "│"
    else
        echo "│ No se encontró ${ARCH_ASP_NAME}Tests.swift, saltando este paso."
    fi

    # Rename .xcodeproj bundle
    echo "│ Renombrando ${ARCH_ASP_NAME}.xcodeproj a ${appName}.xcodeproj ..."
    mv ${ARCH_ASP_NAME}.xcodeproj ${appName}.xcodeproj
    checkResult "Renaming ${ARCH_ASP_NAME}.xcodeproj"
    echo "│"
    echo "│ ✅ Renombrado completado"
    echo "│"

    # Rename paths
    echo "│ Renombrado el fichero de pbxproj ..."
    sed -i'' -e 's/${ARCH_ASP_NAME}/${appName}/g' ${appName}.xcodeproj/project.pbxproj
    checkResult "Renombrando pbxproj"
    echo "│"
    echo "│ ✅ Renombrado completado"
    echo "│"

    # Update references in project.pbxproj
    echo "│ Actualizando referencias ${ARCH_ASP_NAME} a ${appName} en project.pbxproj ..."
    cmd="s/${ARCH_ASP_NAME}/${appName}/g"
    sed $cmd "${appName}.xcodeproj/project.pbxproj" > tmp; mv tmp "${appName}.xcodeproj/project.pbxproj"
    checkResult "Cambiando viejas referencias"
    echo "│"
    echo "│ ✅ Cambio completado"
    echo "│"

    # Update SwiftApp files
    echo "│ Actualizando ficheros SwiftApp ..."
    mv "${appName}/Presentation/App/${ARCH_ASP_NAME}App.swift" "${appName}/Presentation/App/${appName}App.swift"
    sed -i '' "/${ARCH_ASP_NAME}App/ s/${ARCH_ASP_NAME}App/${appName}App/" ${appName}/Presentation/App/${appName}App.swift 
    echo "│"
    echo "│ ✅ Actualización completa"
    echo "│"

    # Update TestPlan files
    #echo "│ Actualizando ficheros TestPlan ..."
    #mv "${ARCH_ASP_NAME}.xctestplan" "${appName}.xctestplan"
    #echo "│"
    #echo "│ ✅ Actualización completa"
    #echo "│"

    # Updating Software license in source files"
    echo "│ Actualización Software license  ..."
    newAuthor="RUDO"
    newOwnerCopyright="RUDO"
    date=`date +%d\\\\/%m\\\\/%Y`
    year=`date +%Y`
    filepaths=$(find ./${appName}* -type f -name "*.swift")
    filepathsSplitted=$(echo ${filepaths} | sed -E 's/( \.)/;./g')
    OIFS=$IFS
    IFS=';'
    for i in $filepathsSplitted; do
    sed "s/\/\/  ${ARCH_ASP_NAME}/\/\/  $appName/g" $i > tmp; mv tmp $i;
    sed -E "s/Created by (.*) on [0-9]{2}\/[0-9]{2}\/[0-9]{4}/Created by ${newAuthor} on ${date}/g" $i > tmp; mv tmp $i
    sed -E "s/Copyright © [0-9]{4} ([^\.]*)\./Copyright © ${year} $newOwnerCopyright./g" $i > tmp; mv tmp $i
    done
    IFS=$OIFS
    echo "│"
    echo "│ ✅ Actualización completa"
    echo "│"

    # Updating Tests imports in source files"
    echo "│ Actualizando Test imports  ..."
    archNameFormatted=${ARCH_ASP_NAME//"-"/"_"}
    appNameFormatted=${appName//"-"/"_"}
    filepaths=$(find ./${appName}Tests* -type f -name "*.swift")
    filepathsSplitted=$(echo ${filepaths} | sed -E 's/( \.)/;./g')
    OIFS=$IFS
    IFS=';'
    for i in $filepathsSplitted; do
    sed "s/import ${archNameFormatted}/import ${appNameFormatted}/g" $i > tmp; mv tmp $i;
    sed "s/@testable import ${archNameFormatted}/@testable import ${appNameFormatted}/g" $i > tmp; mv tmp $i;
    done
    IFS=$OIFS
    echo "│"
    echo "│ ✅ Actualización completa"
    echo "│"

    # Update Bundle ID
    echo "│ Actualizando Bundle ID ..."
    cmd="s/${ARCH_APP_ID}/${appId}/g"
    sed $cmd ${appName}.xcodeproj/project.pbxproj > tmp; mv tmp ${appName}.xcodeproj/project.pbxproj
    checkResult "Actualizando Bundle Id"
    echo "│"
    echo "│ ✅ Actualización completa"
    echo "│"

    # Empty CHANGELOG.md
    echo "│ Vaciando CHANGELOG.md  ..."
    cat /dev/null > CHANGELOG.md
    checkResult "Vaciando CHANGELOG.md"
    echo "│"
    echo "│ ✅ CHANGELOG.md cambiado"
    echo "│"

    # Delete old README
    echo "│ Eliminando README.md  ..."
    rm README.md;
    checkResult "Eliminando README.md"
    echo "│"
    echo "│ ✅ CREADME.md eliminado"
    echo "│"

    # Remove .gitkeep placeholders
    echo "│ Eliminando ficheros .gitkeep ..."
    find . -type f -name ".gitkeep" -delete
    checkResult "Eliminando .gitkeep"
    echo "│"
    echo "│ ✅ Ficheros .gitkeep eliminados"
    echo "│"

    # Removing .git directory
    echo "│ Eliminando .git directory"
    rm -rf .git
    checkResult "Eliminando .git directory"
    echo "│"
    echo "│ ✅ Eliminado"
    echo "│"

    # Success

    echo "│"
    echo "│ 👍 Configuración completada"
    echo "│ Proyecto creado en $projectPath"

    # Registrar la creación del proyecto
    echo "│"
    echo "│ 📝 Creando archivo de auditoría .turia.log..."

    # El script ya nos deja en el directorio del proyecto, no necesitamos cambiar
    # Solo verificar que estamos en el lugar correcto
    if [ ! -d "./$appName" ]; then
        echo "│ ❌ Error: No se encontró el directorio del proyecto"
        echo "│"
        echo "└──────────────────────────────────────────────"
        echo ""
        return
    fi

    # Variables básicas
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
    \"platform\": \"ios\",
    \"project_name\": \"$appName\",
    \"branch\": \"$BRANCH_LOG\",
    \"commit\": \"$COMMIT_LOG\",
    \"created_by\": \"$CREATED_BY_LOG\",
    \"turia_version\": \"$VERSION\"
  },
  \"operations\": [
    {
      \"timestamp\": \"$TIMESTAMP_LOG\",
      \"operation\": \"create\",
      \"platform\": \"ios\",
      \"module\": \"$appName\",
      \"branch\": \"$BRANCH_LOG\",
      \"commit\": \"$COMMIT_LOG\",
      \"status\": \"success\",
      \"details\": \"iOS project created with bundle ID: $appId\",
      \"created_by\": \"$CREATED_BY_LOG\",
      \"turia_version\": \"$VERSION\"
    }
  ],
  \"installed_modules\": {}
}" > .turia.log

    # Verificar si se creó el archivo
    if [ -f ".turia.log" ]; then
        echo "│ ✅ Archivo .turia.log creado exitosamente"
    else
        echo "│ ⚠️ No se pudo crear el archivo .turia.log"
    fi

    echo "│"
    echo "└──────────────────────────────────────────────"
    echo ""
}