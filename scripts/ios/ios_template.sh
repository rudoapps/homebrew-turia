#!/bin/bash

check_xcode_version() {
    echo -e "${BOLD}-----------------------------------------------${NC}"
    echo -e "${BOLD}Comprobando versión xcodeproj.${NC}"
    echo -e "${BOLD}-----------------------------------------------${NC}"
    ruby "${scripts_dir}/ios/ruby/check_version_xcode.rb"
    if [ $? -eq 0 ]; then
        echo -e "✅ script de ruby ejecutado correctamente"
    else
        echo -e "${RED}Error: No se ha podido copiar los templates de ${MODULE_NAME}.${NC}"
        echo ""
        exit 1
    fi
}

ios_install_all_templates() {
# Validar entrada
    if [ -z "$1" ]; then
      echo "Error: Debes proporcionar un nombre para el módulo o caso de uso."
      echo "Uso: ./ios_template.sh <ModuleName>"
      exit 1
    fi

    check_xcode_version

    PROJECT_DIR=$(pwd)
    echo ""
    echo "Buscando en el directorio actual: $PROJECT_DIR"

    # Verificar si el directorio existe (siempre será el caso con $(pwd))
    if [ ! -d "$PROJECT_DIR" ]; then
      echo "Error: El directorio actual no existe, algo está mal."
      exit 1
    fi

    # Buscar el archivo .xcodeproj en el directorio actual
    XCODEPROJ_FILE=$(find "$PROJECT_DIR" -maxdepth 1 -type d -name "*.xcodeproj" | head -n 1)

    # Verificar si se encontró el archivo
    if [ -z "$XCODEPROJ_FILE" ]; then
      echo "Error: No se encontró ningún archivo .xcodeproj en el directorio $PROJECT_DIR"
      exit 1
    fi

    XCODEPROJ_NAME=$(basename "$XCODEPROJ_FILE" .xcodeproj)
    echo ""
    echo -e "${BOLD}El archivo .xcodeproj encontrado es: $XCODEPROJ_NAME ${NC}"
    echo ""


    # Usar ruta relativa desde el directorio de scripts
    TEMPLATES_DIR="$scripts_dir/support/ios/templates"

    if [ ! -d "$TEMPLATES_DIR" ]; then
      echo "Error: No se encontró el directorio de plantillas en $TEMPLATES_DIR"
      exit 1
    fi

    echo -e "${BOLD}-----------------------------------------------${NC}"
    echo -e "${BOLD}Instalando templates.${NC}"
    echo -e "${BOLD}-----------------------------------------------${NC}"
    TEMPLATE_NAME=$1
    CapitalizedModuleName=$(echo "$TEMPLATE_NAME" | awk '{print toupper(substr($0, 1, 1)) tolower(substr($0, 2))}')
    camelCaseModuleName=$(echo "$TEMPLATE_NAME" | awk '{print tolower(substr($0, 1, 1)) substr($0, 2)}')

    DOMAIN_DIR="Domain"
    DATA_DIR="Data"
    PRESENTATION_DIR="Presentation"

    mkdir -p $XCODEPROJ_NAME/$DOMAIN_DIR/Entities
    mkdir -p $XCODEPROJ_NAME/$DOMAIN_DIR/UseCases
    mkdir -p $XCODEPROJ_NAME/$DOMAIN_DIR/Repositories
    mkdir -p $XCODEPROJ_NAME/$DATA_DIR/DataSources/$CapitalizedModuleName/API/DTO
    mkdir -p $XCODEPROJ_NAME/$DATA_DIR/DataSources/$CapitalizedModuleName
    mkdir -p $XCODEPROJ_NAME/$DATA_DIR/Repositories
    mkdir -p $XCODEPROJ_NAME/$PRESENTATION_DIR/Screen/$CapitalizedModuleName
    mkdir -p $XCODEPROJ_NAME/DI

    generate_from_template() {
        local template_file=$1
        local output_file=$2

        if [ ! -f "$template_file" ]; then
            echo "Error: La plantilla no existe: $template_file"
            return 1
        fi

        # Generar el archivo reemplazando placeholders
        sed -e "s/{{TEMPLATE_NAME}}/$CapitalizedModuleName/g" \
            -e "s/{{PARAM_NAME}}/$camelCaseModuleName/g" "$template_file" > "$output_file"
        echo "✅ Archivo generado: $output_file"
    }

    # Generar archivos usando templates
    generate_from_template "$TEMPLATES_DIR/domain_entity" "$XCODEPROJ_NAME/$DOMAIN_DIR/Entities/$CapitalizedModuleName.swift"
    generate_from_template "$TEMPLATES_DIR/domain_repository" "$XCODEPROJ_NAME/$DOMAIN_DIR/Repositories/${CapitalizedModuleName}RepositoryProtocol.swift"
    generate_from_template "$TEMPLATES_DIR/domain_usecase" "$XCODEPROJ_NAME/$DOMAIN_DIR/UseCases/${CapitalizedModuleName}UseCases.swift"
    generate_from_template "$TEMPLATES_DIR/data_datasource_dto" "$XCODEPROJ_NAME/$DATA_DIR/DataSources/$CapitalizedModuleName/API/DTO/${CapitalizedModuleName}DTO.swift"
    generate_from_template "$TEMPLATES_DIR/data_datasource_protocol" "$XCODEPROJ_NAME/$DATA_DIR/DataSources/$CapitalizedModuleName/${CapitalizedModuleName}RemoteDataSourceProtocol.swift"
    generate_from_template "$TEMPLATES_DIR/data_datasource_impl" "$XCODEPROJ_NAME/$DATA_DIR/DataSources/$CapitalizedModuleName/API/${CapitalizedModuleName}RemoteDataSource.swift"
    generate_from_template "$TEMPLATES_DIR/data_repository" "$XCODEPROJ_NAME/$DATA_DIR/Repositories/${CapitalizedModuleName}Repository.swift"
    generate_from_template "$TEMPLATES_DIR/presentation_builder" "$XCODEPROJ_NAME/$PRESENTATION_DIR/Screen/$CapitalizedModuleName/${CapitalizedModuleName}Builder.swift"
    generate_from_template "$TEMPLATES_DIR/presentation_view" "$XCODEPROJ_NAME/$PRESENTATION_DIR/Screen/$CapitalizedModuleName/${CapitalizedModuleName}View.swift"
    generate_from_template "$TEMPLATES_DIR/presentation_viewmodel" "$XCODEPROJ_NAME/$PRESENTATION_DIR/Screen/$CapitalizedModuleName/${CapitalizedModuleName}ViewModel.swift"
    generate_from_template "$TEMPLATES_DIR/di_container" "$XCODEPROJ_NAME/DI/${CapitalizedModuleName}Container.swift"
    echo ""

}
