#!/bin/bash

TEMPORARY_DIR="temp-turia"
MODULE_NAME=""
KEY=""
ACCESSTOKEN=""
TURIA_COMMAND=""

# Version: read from VERSION file (single source of truth)
# Search in order: alongside scripts (homebrew), parent dir (development)
_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$_script_dir/../VERSION" ]; then
    VERSION=$(cat "$_script_dir/../VERSION")
elif [ -f "$_script_dir/VERSION" ]; then
    VERSION=$(cat "$_script_dir/VERSION")
else
    VERSION="dev"
fi
unset _script_dir

# Definir colores
RED='\033[1;31m'
GREEN='\033[1;32m'
YELLOW='\033[1;33m'
BLUE='\033[1;34m'
MAGENTA='\033[1;35m'
CYAN='\033[1;36m'
WHITE='\033[1;37m'
BOLD='\033[1m'
DIM='\033[2m'
ITALIC='\033[3m'
NC='\033[0m'

# Colores para gum (256 colors)
GUM_ACCENT="212"      # Rosa/magenta
GUM_SUBTLE="240"      # Gris
GUM_SUCCESS="78"      # Verde
GUM_WARNING="214"     # Naranja