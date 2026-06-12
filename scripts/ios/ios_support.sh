#!/bin/bash

ios_check_xcodeproj() {
	# Comprobar si la gema 'xcodeproj' está instalada
	if ! gem list -i xcodeproj > /dev/null 2>&1; then
		echo "La gema 'xcodeproj' no está instalada. Procediendo con la instalación..."
		gem install xcodeproj -v '~> 1.27.0' --user-install --no-document
		if [ $? -eq 0 ]; then
			echo -e "✅ 'xcodeproj' se ha instalado correctamente en la versión requerida."
		else
			echo -e "${RED}Error: No se ha podido instalar 'xcodeproj' necesaria para continuar ${MODULE_NAME}.${NC}"
			exit 1
		fi
	else
		# Obtener la versión instalada de 'xcodeproj' usando gem list y awk
		VERSION=$(gem list xcodeproj | awk -F'[()]' '/xcodeproj/ {print $2}')
		REQUIRED_VERSION="1.27.0"

		# Comprobar si la versión es menor que 1.27.0
		if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]; then
			echo "La versión de 'xcodeproj' es $VERSION, menor a la requerida ($REQUIRED_VERSION). Actualizando..."
			gem install xcodeproj -v '~> 1.27.0' --user-install --no-document
			if [ $? -eq 0 ]; then
				echo -e "✅ 'xcodeproj' se ha actualizado correctamente a la versión requerida."
			else
				echo -e "${RED}Error: No se ha podido actualizar 'xcodeproj' a la versión necesaria para continuar ${MODULE_NAME}.${NC}"
				exit 1
			fi
		else
			echo "✅ La gema 'xcodeproj' ya está instalada en la versión $VERSION."
		fi
	fi
}

ios_copy_and_add_to_xcode() {
	ruby "${scripts_dir}/ios/ruby/copy_and_add_xcode.rb" "${TEMPORARY_DIR}/${DIRECTORY_PATH}" "Modules/${MODULE_NAME}" "${TEMPORARY_DIR}"
	if [ $? -eq 0 ]; then
		echo -e "✅ script de ruby ejecutado correctamente"
	else
		echo -e "${RED}Error: No se ha podido copiar el módulo ${MODULE_NAME}.${NC}"
		exit 1
	fi
}

ios_copy_and_add_to_xcode_integrated() {
	ruby "${scripts_dir}/ios/ruby/copy_and_add_xcode_integrated.rb" "${TEMPORARY_DIR}/${DIRECTORY_PATH}" "${MODULE_NAME}" "${TEMPORARY_DIR}"
	if [ $? -eq 0 ]; then
		echo -e "✅ script de ruby (modo integración) ejecutado correctamente"
	else
		echo -e "${RED}Error: No se ha podido integrar el módulo ${MODULE_NAME}.${NC}"
		exit 1
	fi
}

ios_install_dependencies() {
	local dependencies_file=$1
	json=$(cat $dependencies_file)
	# Recorrer el array 'shared'
	echo "Recorriendo 'shared':"
	echo "$json" | jq -r '.shared[]' | while read shared_item; do
	  echo "Elemento compartido: $shared_item"
	done

	# Recorrer el array 'libraries' y obtener cada campo
	echo "Recorriendo 'libraries':"
	echo "$json" | jq -c '.libraries[]' | while read library; do
	  name=$(echo "$library" | jq -r '.name')
	  url=$(echo "$library" | jq -r '.url')
	  version=$(echo "$library" | jq -r '.version')
	  echo "Librería: $name, URL: $url, Versión: $version"
	done
}