#!/bin/bash

android_install_all_templates() {
    # Validar entrada
    if [ -z "$1" ]; then
        echo "Error: Debes proporcionar un nombre para el módulo o caso de uso."
        echo "Uso: turia template <ModuleName> [--type=clean|mvvm|mvc]"
        exit 1
    fi

    local TEMPLATE_NAME=$1
    local TEMPLATE_TYPE=${TEMPLATE_TYPE:-clean}
    
    PROJECT_DIR=$(pwd)
    echo ""
    echo "Generando templates para Android en: $PROJECT_DIR"
    echo "🔍 Debug: Template name=$TEMPLATE_NAME, type=$TEMPLATE_TYPE"

    # Verificar si es un proyecto Android válido
    echo "🔍 Debug: Verificando archivos build.gradle..."
    if [ ! -f "app/build.gradle" ] && [ ! -f "app/build.gradle.kts" ]; then
        echo "Error: No se encontró un proyecto Android válido en el directorio actual"
        exit 1
    fi
    echo "🔍 Debug: Proyecto Android válido encontrado"

    # Usar ruta relativa desde el directorio de scripts
    TEMPLATES_DIR="$scripts_dir/support/templates/android/$TEMPLATE_TYPE"
    echo "🔍 Debug: Buscando templates en: $TEMPLATES_DIR"

    if [ ! -d "$TEMPLATES_DIR" ]; then
        echo "Error: No se encontró el directorio de plantillas en $TEMPLATES_DIR"
        exit 1
    fi
    echo "🔍 Debug: Directorio de templates encontrado"

    echo -e "${BOLD}-----------------------------------------------${NC}"
    echo -e "${BOLD}Instalando templates Android ($TEMPLATE_TYPE).${NC}"
    echo -e "${BOLD}-----------------------------------------------${NC}"
    
    CapitalizedModuleName=$(echo "$TEMPLATE_NAME" | awk '{print toupper(substr($0, 1, 1)) tolower(substr($0, 2))}')
    camelCaseModuleName=$(echo "$TEMPLATE_NAME" | awk '{print tolower(substr($0, 1, 1)) substr($0, 2)}')

    # Detectar package name del proyecto - usar valor hardcoded por ahora para evitar problemas
    PACKAGE_NAME="ejemplo.rudo.es"
    echo "📦 Package usado: $PACKAGE_NAME"
    
    PACKAGE_PATH=$(echo $PACKAGE_NAME | tr '.' '/')
    BASE_PATH="app/src/main/java/$PACKAGE_PATH"

    # Crear directorios necesarios
    mkdir -p "$BASE_PATH/domain/entities"
    mkdir -p "$BASE_PATH/domain/repositories"
    mkdir -p "$BASE_PATH/domain/usecases"
    mkdir -p "$BASE_PATH/data/dto"
    mkdir -p "$BASE_PATH/data/datasources"
    mkdir -p "$BASE_PATH/data/repositories"
    mkdir -p "$BASE_PATH/presentation/screen/$camelCaseModuleName"
    mkdir -p "$BASE_PATH/di"

    generate_from_template() {
        local template_file=$1
        local output_file=$2

        if [ ! -f "$template_file" ]; then
            echo "Error: La plantilla no existe: $template_file"
            return 1
        fi

        # Generar el archivo reemplazando placeholders
        sed -e "s/{{TEMPLATE_NAME}}/$CapitalizedModuleName/g" \
            -e "s/{{PARAM_NAME}}/$camelCaseModuleName/g" \
            -e "s/{{PACKAGE_NAME}}/$PACKAGE_NAME/g" "$template_file" > "$output_file"
        echo "✅ Archivo generado: $output_file"
    }

    # Generar archivos usando templates
    generate_from_template "$TEMPLATES_DIR/domain_entity" "$BASE_PATH/domain/entities/$CapitalizedModuleName.kt"
    generate_from_template "$TEMPLATES_DIR/domain_repository" "$BASE_PATH/domain/repositories/${CapitalizedModuleName}Repository.kt"
    generate_from_template "$TEMPLATES_DIR/domain_usecase" "$BASE_PATH/domain/usecases/${CapitalizedModuleName}UseCases.kt"
    generate_from_template "$TEMPLATES_DIR/data_dto" "$BASE_PATH/data/dto/${CapitalizedModuleName}Dto.kt"
    generate_from_template "$TEMPLATES_DIR/data_datasource" "$BASE_PATH/data/datasources/${CapitalizedModuleName}RemoteDataSource.kt"
    generate_from_template "$TEMPLATES_DIR/data_repository" "$BASE_PATH/data/repositories/${CapitalizedModuleName}RepositoryImpl.kt"
    generate_from_template "$TEMPLATES_DIR/presentation_viewmodel" "$BASE_PATH/presentation/screen/$camelCaseModuleName/${CapitalizedModuleName}ViewModel.kt"
    generate_from_template "$TEMPLATES_DIR/presentation_fragment" "$BASE_PATH/presentation/screen/$camelCaseModuleName/${CapitalizedModuleName}View.kt"
    generate_from_template "$TEMPLATES_DIR/di_module" "$BASE_PATH/di/${CapitalizedModuleName}Module.kt"
    
    echo ""
    echo -e "${GREEN}✅ Templates Android generados correctamente para: $CapitalizedModuleName${NC}"
    echo -e "${GREEN}📁 Archivos creados en: $BASE_PATH${NC}"
    echo ""
}