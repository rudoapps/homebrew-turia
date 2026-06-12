#!/bin/bash

clone() {
  # Clonar el repositorio específico desde Bitbucket en un directorio temporal
  remove_temporary_dir
  local repository=$1
  
  if [ -n "${BRANCH:-}" ]; then
    echo -e "🌿 Usando rama: ${YELLOW}$BRANCH${NC}"
    git clone "$repository" --branch "$BRANCH" --single-branch --depth 1 "${TEMPORARY_DIR}"
  else
    git clone "$repository" --single-branch --depth 1 "${TEMPORARY_DIR}"
  fi
  
  if [ $? -eq 0 ]; then
      echo -e "✅ Clonado correctamente en el directorio temporal"
  else
    echo -e "${RED}Se ha producido un error descargando el repositorio.${NC}"
    exit 1
  fi 
}

deep_clone() {
  # Clonar el repositorio específico desde Bitbucket en un directorio temporal
  remove_temporary_dir
  local repository=$1
  
  local branch_to_use="main"
  if [ -n "${BRANCH:-}" ]; then
    branch_to_use="$BRANCH"
    echo -e "🌿 Usando rama: ${YELLOW}$BRANCH${NC}"
  fi
  
  git clone "$repository" --branch "$branch_to_use" --single-branch "${TEMPORARY_DIR}"
  if [ $? -eq 0 ]; then
      echo -e "✅ Clonado correctamente en el directorio temporal"
  else
    echo -e "${RED}Se ha producido un error descargando el repositorio.${NC}"
    exit 1
  fi
}
