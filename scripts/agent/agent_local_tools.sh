#!/bin/bash

# Agent Local Tools - Ejecuta herramientas localmente sobre el proyecto del usuario
# Este modulo permite al agente operar sobre archivos y comandos en la maquina del usuario

# Load agent_config.sh for get_agent_config, create_file_backup, etc.
AGENT_SCRIPT_DIR="${AGENT_SCRIPT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
if [ -f "$AGENT_SCRIPT_DIR/agent_config.sh" ]; then
    source "$AGENT_SCRIPT_DIR/agent_config.sh"
fi

# Configuracion de limites de seguridad (configurables via env vars)
MAX_FILE_SIZE="${TURIA_MAX_FILE_SIZE:-50000}"            # 50KB max por archivo
MAX_OUTPUT_LINES="${TURIA_MAX_OUTPUT_LINES:-200}"        # Maximo lineas de output
MAX_COMMAND_TIMEOUT="${TURIA_MAX_COMMAND_TIMEOUT:-30}"   # Timeout para comandos en segundos
MAX_SEARCH_RESULTS="${TURIA_MAX_SEARCH_RESULTS:-50}"     # Maximo resultados de busqueda

# ============================================================================
# INTERACTIVE SELECTOR (for confirmations)
# ============================================================================

# Interactive option selector with arrow keys
# Usage: selected=$(tool_interactive_select "Pregunta?" "Opción 1" "Opción 2")
tool_interactive_select() {
    local prompt="$1"
    shift
    local options=("$@")

    python3 - "$prompt" "${options[@]}" << 'PYEOF'
import sys
import os

BOLD = "\033[1m"
DIM = "\033[2m"
NC = "\033[0m"
CYAN = "\033[0;36m"
GREEN = "\033[0;32m"
RED = "\033[0;31m"
YELLOW = "\033[1;33m"

HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"
CLEAR_LINE = "\033[2K"
MOVE_UP = "\033[A"

prompt = sys.argv[1]
options = sys.argv[2:]

if not options:
    print("")
    sys.exit(1)

# Open /dev/tty directly for interactive input
import tty
import termios
import select
try:
    tty_file = open('/dev/tty', 'r')
    # Drain any buffered input (leftover enter key, etc.)
    fd = tty_file.fileno()
    old_drain = termios.tcgetattr(fd)
    tty.setraw(fd)
    while select.select([tty_file], [], [], 0)[0]:
        tty_file.read(1)
    termios.tcsetattr(fd, termios.TCSADRAIN, old_drain)
except Exception as e:
    sys.stderr.write(f"{RED}Error: No se puede abrir terminal: {e}{NC}\n")
    print("Rechazar")
    sys.exit(1)

# Check if we can use raw mode for arrow keys
use_arrow_keys = True
try:
    old_settings = termios.tcgetattr(tty_file.fileno())
except:
    use_arrow_keys = False
    old_settings = None

if not use_arrow_keys:
    # Fallback to simple letter input (no arrow keys)
    sys.stderr.write(f"  {BOLD}{prompt}{NC}\n")
    for i, opt in enumerate(options):
        key = chr(ord('a') + i)
        if "Permitir" in opt:
            sys.stderr.write(f"    {GREEN}[{key}]{NC} {opt}\n")
        elif "Rechazar" in opt:
            sys.stderr.write(f"    {RED}[{key}]{NC} {opt}\n")
        else:
            sys.stderr.write(f"    {CYAN}[{key}]{NC} {opt}\n")
    sys.stderr.write(f"\n  › ")
    sys.stderr.flush()

    try:
        # Read single char in cbreak mode
        tty.setcbreak(tty_file.fileno())
        choice = tty_file.read(1).lower()
        sys.stderr.write(f"{choice}\n")
        idx = ord(choice) - ord('a') if choice else -1
        if 0 <= idx < len(options):
            print(options[idx])
        else:
            print("Rechazar")
    except Exception as ex:
        sys.stderr.write(f"\n{RED}Error: {ex}{NC}\n")
        print("Rechazar")
    finally:
        tty_file.close()
    sys.exit(0)

tty_fd = tty_file.fileno()

# Save original terminal settings to restore on any exit (including signals)
_original_tty_settings = termios.tcgetattr(tty_fd)

import signal, atexit

def _restore_terminal():
    try:
        termios.tcsetattr(tty_fd, termios.TCSADRAIN, _original_tty_settings)
        sys.stderr.write(SHOW_CURSOR)
        sys.stderr.flush()
    except:
        pass

atexit.register(_restore_terminal)
signal.signal(signal.SIGTERM, lambda *_: (_restore_terminal(), sys.exit(1)))

def render(first_render=False):
    if not first_render:
        for _ in range(len(options) + 1):
            sys.stderr.write(f"{MOVE_UP}{CLEAR_LINE}")

    sys.stderr.write(f"  {BOLD}{prompt}{NC}\n")

    for i, opt in enumerate(options):
        if i == selected_idx:
            if "Permitir" in opt:
                sys.stderr.write(f"    {GREEN}❯ {opt}{NC}\n")
            elif "Rechazar" in opt or "Cancelar" in opt:
                sys.stderr.write(f"    {RED}❯ {opt}{NC}\n")
            else:
                sys.stderr.write(f"    {CYAN}❯ {opt}{NC}\n")
        else:
            sys.stderr.write(f"      {DIM}{opt}{NC}\n")

    sys.stderr.flush()

selected_idx = 0

sys.stderr.write(HIDE_CURSOR)
sys.stderr.flush()

try:
    # Set raw mode ONCE for the entire selection loop (avoids losing keypresses
    # during raw↔cooked transitions that caused the "press twice" bug)
    tty.setraw(tty_fd)

    render(first_render=True)

    while True:
        ch = tty_file.read(1)
        if ch == '\x1b':
            ch2 = tty_file.read(1)
            if ch2 == '[':
                ch3 = tty_file.read(1)
                if ch3 == 'A':  # up
                    selected_idx = (selected_idx - 1) % len(options)
                    render()
                elif ch3 == 'B':  # down
                    selected_idx = (selected_idx + 1) % len(options)
                    render()
            # esc - reject
            else:
                break
        elif ch in ('\r', '\n'):  # enter
            break
        elif ch == '\x03' or ch == 'q':  # ctrl-c or q
            selected_idx = -1
            break

finally:
    # Restore terminal settings ONCE at the end
    termios.tcsetattr(tty_fd, termios.TCSADRAIN, _original_tty_settings)
    sys.stderr.write(SHOW_CURSOR)
    sys.stderr.flush()
    tty_file.close()

if selected_idx >= 0 and selected_idx < len(options):
    print(options[selected_idx])
else:
    print("Rechazar")
PYEOF
}

# Archivos sensibles que NO se pueden leer
BLOCKED_FILE_EXTENSIONS=".pem .key .p12 .pfx .keystore .jks .secret .credentials"
BLOCKED_FILE_NAMES=".env .env.local .env.production .env.development id_rsa id_ed25519 id_dsa authorized_keys known_hosts .netrc .npmrc .pypirc"

# Audit log
AUDIT_LOG_FILE="$HOME/.config/turia-agent/audit.log"

# Función de audit logging
audit_log() {
    local action="$1"
    local details="$2"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    mkdir -p "$(dirname "$AUDIT_LOG_FILE")"
    echo "[$timestamp] $action: $details" >> "$AUDIT_LOG_FILE"
}

# ============================================================================
# GENERACION DE CONTEXTO DEL PROYECTO
# ============================================================================

# Detecta el tipo de proyecto basado en archivos presentes
detect_project_type() {
    if [ -f "pubspec.yaml" ]; then
        echo "flutter"
    elif [ -f "Package.swift" ] || ls *.xcodeproj 1> /dev/null 2>&1 || ls *.xcworkspace 1> /dev/null 2>&1; then
        echo "ios"
    elif [ -f "build.gradle" ] || [ -f "build.gradle.kts" ]; then
        echo "android"
    elif [ -f "pyproject.toml" ] || [ -f "requirements.txt" ] || [ -f "setup.py" ]; then
        echo "python"
    elif [ -f "package.json" ]; then
        echo "node"
    elif [ -f "Cargo.toml" ]; then
        echo "rust"
    elif [ -f "go.mod" ]; then
        echo "go"
    else
        echo "unknown"
    fi
}

# Genera arbol de archivos comprimido (excluye directorios comunes)
generate_file_tree() {
    local max_depth="${1:-5}"
    local max_files="${2:-200}"

    find . -maxdepth "$max_depth" \( -type f -o -type d \) \
        -not -path "*/\.*" \
        -not -path "*/node_modules/*" \
        -not -path "*/__pycache__/*" \
        -not -path "*/venv/*" \
        -not -path "*/.venv/*" \
        -not -path "*/.git/*" \
        -not -path "*/build/*" \
        -not -path "*/dist/*" \
        -not -path "*/.build/*" \
        -not -path "*/Pods/*" \
        -not -path "*/.dart_tool/*" \
        -not -path "*/DerivedData/*" \
        -not -path "*/.gradle/*" \
        -not -name "*.pyc" \
        -not -name "*.class" \
        -not -name "*.o" \
        -not -name "*.lock" \
        -not -name "package-lock.json" \
        -not -name "yarn.lock" \
        -not -name "Podfile.lock" \
        -not -name "*.pbxproj" \
        -not -name "*.xcscheme" \
        2>/dev/null | sort | head -"$max_files"
}

# Detecta archivos clave del proyecto
detect_key_files() {
    local key_files=()
    local candidates=(
        "README.md" "readme.md"
        "requirements.txt" "pyproject.toml" "setup.py"
        "package.json" "tsconfig.json"
        "pubspec.yaml"
        "build.gradle" "build.gradle.kts" "settings.gradle" "settings.gradle.kts"
        "Package.swift" "Podfile" "Podfile.lock"
        "Cargo.toml"
        "go.mod"
        "Makefile" "Dockerfile" "docker-compose.yml"
        ".env.example" "configuration.turia"
    )

    for f in "${candidates[@]}"; do
        if [ -f "$f" ]; then
            key_files+=("$f")
        fi
    done

    # Detect project-type specific entry points
    local project_type=$(detect_project_type)
    case "$project_type" in
        ios)
            # Find Swift entry points and key iOS files
            for f in $(find . -maxdepth 3 -name "AppDelegate.swift" -o -name "SceneDelegate.swift" -o -name "App.swift" -o -name "*App.swift" -o -name "Info.plist" 2>/dev/null | head -5); do
                key_files+=("$f")
            done
            # Find xcodeproj
            for f in $(find . -maxdepth 2 -name "*.xcodeproj" -o -name "*.xcworkspace" 2>/dev/null | head -2); do
                key_files+=("$f")
            done
            ;;
        android)
            # Find Android entry points
            for f in $(find . -maxdepth 5 -name "AndroidManifest.xml" -o -name "MainActivity.kt" -o -name "MainApplication.kt" 2>/dev/null | head -3); do
                key_files+=("$f")
            done
            ;;
        flutter)
            [ -f "lib/main.dart" ] && key_files+=("lib/main.dart")
            ;;
        python)
            for f in "main.py" "app.py" "manage.py" "wsgi.py" "asgi.py"; do
                [ -f "$f" ] && key_files+=("$f")
            done
            ;;
        node)
            for f in "index.ts" "index.js" "src/index.ts" "src/index.js" "src/app.ts" "src/app.js"; do
                [ -f "$f" ] && key_files+=("$f")
            done
            ;;
    esac

    # Convertir a JSON array
    printf '%s\n' "${key_files[@]}" | jq -Rsc 'split("\n") | map(select(length > 0))'
}

# Lee contenido de dependencias
get_dependencies_summary() {
    local project_type="$1"

    case "$project_type" in
        python)
            if [ -f "requirements.txt" ]; then
                head -60 requirements.txt
            elif [ -f "pyproject.toml" ]; then
                grep -A 80 "dependencies" pyproject.toml 2>/dev/null | head -60
            fi
            ;;
        node)
            if [ -f "package.json" ]; then
                local deps=$(jq -r '[.dependencies // {} | to_entries[] | "\(.key)@\(.value)"] | .[:40] | join(", ")' package.json 2>/dev/null)
                local dev_deps=$(jq -r '[.devDependencies // {} | to_entries[] | "\(.key)@\(.value)"] | .[:20] | join(", ")' package.json 2>/dev/null)
                [ -n "$deps" ] && echo "deps: $deps"
                [ -n "$dev_deps" ] && echo "devDeps: $dev_deps"
            fi
            ;;
        flutter)
            if [ -f "pubspec.yaml" ]; then
                grep -A 50 "dependencies:" pubspec.yaml 2>/dev/null | head -50
            fi
            ;;
        ios)
            # SPM dependencies
            if [ -f "Package.swift" ]; then
                echo "=== Swift Package Manager ==="
                grep -E '\.package\(|\.product\(' Package.swift 2>/dev/null | head -20
            fi
            # CocoaPods dependencies
            if [ -f "Podfile" ]; then
                echo "=== CocoaPods ==="
                grep -E "^\s*pod\s+" Podfile 2>/dev/null | head -30
            fi
            # Xcode project SPM dependencies (Package.resolved)
            local resolved=$(find . -name "Package.resolved" -maxdepth 3 2>/dev/null | head -1)
            if [ -n "$resolved" ] && [ -f "$resolved" ]; then
                echo "=== Resolved Packages ==="
                jq -r '.pins[]? | "\(.identity) @ \(.state?.version // .state?.branch // "unknown")"' "$resolved" 2>/dev/null | head -30 || \
                jq -r '.object?.pins[]? | "\(.package) @ \(.state?.version // .state?.branch // "unknown")"' "$resolved" 2>/dev/null | head -30
            fi
            ;;
        android)
            if [ -f "build.gradle" ]; then
                echo "=== Gradle Dependencies ==="
                grep -E "implementation|api\s|kapt|ksp|annotationProcessor" build.gradle 2>/dev/null | head -30
            elif [ -f "build.gradle.kts" ]; then
                echo "=== Gradle Dependencies ==="
                grep -E "implementation|api\(|kapt|ksp|annotationProcessor" build.gradle.kts 2>/dev/null | head -30
            fi
            # Also check app/build.gradle
            if [ -f "app/build.gradle" ]; then
                grep -E "implementation|api\s|kapt|ksp" app/build.gradle 2>/dev/null | head -30
            elif [ -f "app/build.gradle.kts" ]; then
                grep -E "implementation|api\(|kapt|ksp" app/build.gradle.kts 2>/dev/null | head -30
            fi
            ;;
        *)
            echo ""
            ;;
    esac
}

# Genera contexto completo del proyecto como JSON
generate_project_context() {
    local project_type=$(detect_project_type)
    local project_name=$(basename "$PWD")
    local git_branch=$(git branch --show-current 2>/dev/null || echo "")

    # Run independent operations in parallel using subshells
    local tmp_dir=$(mktemp -d)
    (generate_file_tree > "$tmp_dir/tree") &
    (git status --short 2>/dev/null | head -30 > "$tmp_dir/git") &
    (get_dependencies_summary "$project_type" > "$tmp_dir/deps") &
    (detect_key_files > "$tmp_dir/keys") &

    # Read project rules
    local project_rules=""
    for rules_file in ".claude-project" "CLAUDE.md" ".agent-rules"; do
        if [ -f "$rules_file" ]; then
            project_rules=$(head -300 "$rules_file" 2>/dev/null)
            break
        fi
    done
    echo "$project_rules" > "$tmp_dir/rules"

    # Wait for all parallel operations
    wait

    # Build JSON with Python reading from single tmp dir
    python3 - "$project_type" "$project_name" "$PWD" "$git_branch" "$tmp_dir" << 'PYEOF'
import json
import sys
import os

project_type = sys.argv[1]
project_name = sys.argv[2]
root_path = sys.argv[3]
git_branch = sys.argv[4]
tmp_dir = sys.argv[5]

def read_tmp(name):
    try:
        with open(os.path.join(tmp_dir, name)) as f:
            return f.read().strip()
    except:
        return ""

# Parse key_files JSON
key_files_raw = read_tmp("keys")
try:
    key_files = json.loads(key_files_raw) if key_files_raw else []
except:
    key_files = []

context = {
    "project_type": project_type,
    "project_name": project_name,
    "root_path": root_path,
    "file_tree": read_tmp("tree"),
    "git_branch": git_branch,
    "git_status": read_tmp("git"),
    "key_files": key_files,
    "dependencies": read_tmp("deps"),
    "project_rules": read_tmp("rules"),
}

print(json.dumps(context))
PYEOF

    rm -rf "$tmp_dir"
}

# ============================================================================
# EJECUCION DE HERRAMIENTAS LOCALES
# ============================================================================

# Lee un archivo del proyecto
tool_read_file() {
    local input="$1"
    local path=$(echo "$input" | jq -r '.path // ""')

    # Validar que no salga del directorio actual (usando realpath para resolver symlinks)
    local path_check=$(python3 -c "
import os
import sys
path = '$path'
cwd = os.getcwd()

# Validar contra null bytes (path traversal attack)
if '\\x00' in path or '\\0' in path:
    print('ERROR:Path contiene null bytes (ataque detectado)')
    sys.exit(1)

# Resolver ruta REAL (sigue symlinks) - protección contra symlink attacks
try:
    real_path = os.path.realpath(path)
except Exception as e:
    print('ERROR:Path inválido: ' + str(e))
    sys.exit(1)

# Verificar que está dentro del directorio actual usando commonpath (más robusto que startswith)
try:
    common = os.path.commonpath([cwd, real_path])
    if common == cwd:
        print('OK:' + real_path)
    else:
        print('ERROR:Path fuera del proyecto: ' + real_path)
except ValueError:
    # commonpath falla si las rutas están en diferentes drives (Windows)
    print('ERROR:Path fuera del proyecto (diferentes unidades): ' + real_path)
")

    if [[ "$path_check" == ERROR:* ]]; then
        audit_log "READ_BLOCKED" "Path fuera del proyecto: $path"
        echo "Error: ${path_check#ERROR:}"
        return 1
    fi

    # Usar la ruta resuelta
    local resolved_path="${path_check#OK:}"
    local filename=$(basename "$resolved_path")
    local extension=".${filename##*.}"

    # Verificar extensiones bloqueadas
    if [[ "$BLOCKED_FILE_EXTENSIONS" == *"$extension"* ]]; then
        audit_log "READ_BLOCKED" "Extensión bloqueada: $path ($extension)"
        echo "Error: No se permite leer archivos con extensión $extension (archivo sensible)"
        return 1
    fi

    # Verificar nombres de archivo bloqueados
    for blocked in $BLOCKED_FILE_NAMES; do
        if [[ "$filename" == "$blocked" ]]; then
            audit_log "READ_BLOCKED" "Archivo bloqueado: $path"
            echo "Error: No se permite leer $filename (archivo sensible de configuración)"
            return 1
        fi
    done

    if [ ! -f "$resolved_path" ]; then
        echo "Error: Archivo no encontrado: $path"
        return 1
    fi

    # Audit log de lectura exitosa
    audit_log "READ" "$path"

    # Verificar tamano
    local size=$(stat -f%z "$resolved_path" 2>/dev/null || stat -c%s "$resolved_path" 2>/dev/null)
    if [ "$size" -gt "$MAX_FILE_SIZE" ]; then
        local remaining=$((size - MAX_FILE_SIZE))
        echo "[TRUNCATED] File is ${size} bytes. Only first ${MAX_FILE_SIZE} bytes shown. Use read_file with line offset for the rest."
        echo "---"
        head -c "$MAX_FILE_SIZE" "$resolved_path" | cat -n
        echo ""
        echo "---"
        echo "[END_TRUNCATED: ${remaining} bytes not shown]"
    else
        cat -n "$resolved_path"
    fi
}

# Lista archivos en un directorio
tool_list_files() {
    local input="$1"
    local path=$(echo "$input" | jq -r '.path // "."')
    local pattern=$(echo "$input" | jq -r '.pattern // "*"')

    # Validar que no salga del directorio actual (usando realpath para symlinks)
    local path_check=$(python3 -c "
import os
import sys
path = '$path'
cwd = os.getcwd()

# Validar contra null bytes
if '\\x00' in path or '\\0' in path:
    print('ERROR:Path contiene null bytes (ataque detectado)')
    sys.exit(1)

# Resolver ruta REAL
try:
    real_path = os.path.realpath(path)
except Exception as e:
    print('ERROR:Path inválido: ' + str(e))
    sys.exit(1)

# Verificar que está dentro del directorio actual usando commonpath
try:
    common = os.path.commonpath([cwd, real_path])
    if common == cwd:
        print('OK:' + real_path)
    else:
        print('ERROR:Path fuera del proyecto: ' + real_path)
except ValueError:
    print('ERROR:Path fuera del proyecto (diferentes unidades): ' + real_path)
")

    if [[ "$path_check" == ERROR:* ]]; then
        audit_log "LIST_BLOCKED" "Path fuera del proyecto: $path"
        echo "Error: ${path_check#ERROR:}"
        return 1
    fi

    local resolved_path="${path_check#OK:}"

    if [ ! -d "$resolved_path" ]; then
        echo "Error: Directorio no encontrado: $path"
        return 1
    fi

    audit_log "LIST" "$path (pattern: $pattern)"

    find "$resolved_path" -maxdepth 3 -name "$pattern" -type f \
        -not -path "*/\.*" \
        -not -path "*/node_modules/*" \
        -not -path "*/__pycache__/*" \
        2>/dev/null | head -"$MAX_SEARCH_RESULTS"
}

# Busca texto en el codigo
tool_search_code() {
    local input="$1"
    local query=$(echo "$input" | jq -r '.query // ""')
    local file_pattern=$(echo "$input" | jq -r '.file_pattern // ""')
    local context_lines=$(echo "$input" | jq -r '.context_lines // "3"')

    if [ -z "$query" ]; then
        echo "Error: Se requiere un query de busqueda"
        return 1
    fi

    audit_log "SEARCH" "query='$query' pattern='$file_pattern' context=$context_lines"

    local grep_opts="-rn -E --color=never"

    # Add context lines for better understanding of matches
    if [ "$context_lines" != "0" ]; then
        grep_opts="$grep_opts -C $context_lines"
    fi

    if [ -n "$file_pattern" ]; then
        grep_opts="$grep_opts --include=$file_pattern"
    fi

    # Excluir directorios comunes
    local result
    result=$(grep $grep_opts \
        --exclude-dir=node_modules \
        --exclude-dir=__pycache__ \
        --exclude-dir=venv \
        --exclude-dir=.venv \
        --exclude-dir=.git \
        --exclude-dir=build \
        --exclude-dir=dist \
        --exclude-dir=Pods \
        --exclude-dir=.build \
        --exclude-dir=DerivedData \
        "$query" . 2>/dev/null | head -"$MAX_SEARCH_RESULTS")

    if [ -z "$result" ]; then
        echo "Sin resultado"
        return 0
    fi

    echo "$result"
}

# Escribe contenido a un archivo
# Arg: input_file - path to JSON file containing {path, content}
tool_write_file() {
    local input_file="$1"

    # Read path and content_size from input file using Python (avoids bash character issues)
    local path_and_size
    path_and_size=$(python3 -c "
import json
with open('$input_file', 'r') as f:
    data = json.load(f)
print(data.get('path', ''))
print(len(data.get('content', '')))
" 2>/dev/null)

    local path=$(echo "$path_and_size" | head -1)
    local content_size=$(echo "$path_and_size" | tail -1)

    if [ -z "$path" ]; then
        echo "Error: Se requiere una ruta de archivo"
        return 1
    fi

    # Validar que no salga del directorio actual (usando realpath para symlinks)
    local path_check=$(python3 -c "
import os
import sys
path = '$path'
cwd = os.getcwd()

# Validar contra null bytes
if '\\x00' in path or '\\0' in path:
    print('ERROR:Path contiene null bytes (ataque detectado)')
    sys.exit(1)

# Para archivos nuevos, resolver el directorio padre
parent = os.path.dirname(path) or '.'

try:
    if os.path.exists(path):
        real_path = os.path.realpath(path)
    else:
        # Archivo nuevo: verificar que el directorio padre está en el proyecto
        real_parent = os.path.realpath(parent)
        real_path = os.path.join(real_parent, os.path.basename(path))
except Exception as e:
    print('ERROR:Path inválido: ' + str(e))
    sys.exit(1)

# Verificar que está dentro del directorio actual usando commonpath
try:
    common = os.path.commonpath([cwd, real_path])
    if common == cwd:
        print('OK:' + real_path)
    else:
        print('ERROR:Path fuera del proyecto: ' + real_path)
except ValueError:
    print('ERROR:Path fuera del proyecto (diferentes unidades): ' + real_path)
")

    if [[ "$path_check" == ERROR:* ]]; then
        audit_log "WRITE_BLOCKED" "Path fuera del proyecto: $path"
        echo "Error: ${path_check#ERROR:}"
        return 1
    fi

    # Usar la ruta resuelta
    local resolved_path="${path_check#OK:}"

    # =========================================================================
    # ARCHIVOS SENSIBLES QUE REQUIEREN APROBACIÓN
    # =========================================================================
    local needs_approval=false
    local risk_reason=""
    local filename=$(basename "$path")

    # Patrones de archivos sensibles
    local sensitive_patterns=(
        ".env|Archivo de variables de entorno"
        ".env.local|Archivo de variables de entorno local"
        ".env.production|Archivo de variables de producción"
        "credentials|Archivo de credenciales"
        "secrets|Archivo de secretos"
        ".ssh|Configuración SSH"
        ".aws|Configuración AWS"
        ".gitignore|Configuración de Git ignore"
        ".gitattributes|Atributos de Git"
        "package.json|Configuración de Node.js"
        "Podfile|Dependencias de iOS"
        "Gemfile|Dependencias de Ruby"
        "requirements.txt|Dependencias de Python"
        "pyproject.toml|Configuración de Python"
        "Dockerfile|Configuración de Docker"
        "docker-compose|Configuración de Docker Compose"
        ".yml|Archivo YAML de configuración"
        ".yaml|Archivo YAML de configuración"
        "config.|Archivo de configuración"
        "settings.|Archivo de configuración"
    )

    for entry in "${sensitive_patterns[@]}"; do
        local pattern="${entry%%|*}"
        local reason="${entry#*|}"
        if [[ "$path" == *"$pattern"* ]] || [[ "$filename" == *"$pattern"* ]]; then
            needs_approval=true
            risk_reason="$reason"
            break
        fi
    done

    # Verificar si el archivo ya existe (sobrescritura)
    if [ -f "$resolved_path" ]; then
        if [ "$needs_approval" = false ]; then
            needs_approval=true
            risk_reason="Sobrescribir archivo existente"
        else
            risk_reason="$risk_reason + Sobrescribir existente"
        fi
    fi

    # Check global preview_mode setting
    local preview_mode=$(get_agent_config "preview_mode")
    if [ "$preview_mode" = "true" ] && [ "$needs_approval" = false ]; then
        needs_approval=true
        risk_reason="Preview mode activado"
    fi

    # Si requiere aprobación, preguntar al usuario (salvo auto-approve activo para write_file)
    if [ "$needs_approval" = true ] && [ ! -f "${TURIA_AUTO_APPROVE_DIR:-/dev/null}/write_file" ]; then
        echo "" >&2
        echo -e "${DIM}┌─${NC} ${CYAN}Confirmar escritura${NC} ${DIM}───────────────────────────┐${NC}" >&2
        echo -e "${DIM}│${NC}" >&2
        echo -e "${DIM}│${NC}  ${BOLD}$path${NC}" >&2
        echo -e "${DIM}│${NC}  ${DIM}$risk_reason · ${content_size} bytes${NC}" >&2
        echo -e "${DIM}│${NC}" >&2
        echo -e "${DIM}└────────────────────────────────────────────────┘${NC}" >&2
        echo "" >&2

        # Loop to allow "Ver cambios" and then decide
        local approval=""
        while true; do
            # Show selector
            if [ -f "$resolved_path" ]; then
                approval=$(tool_interactive_select "¿Qué deseas hacer?" "Permitir" "Permitir siempre" "Ver cambios" "Rechazar" < /dev/tty)
            else
                approval=$(tool_interactive_select "¿Qué deseas hacer?" "Permitir" "Permitir siempre" "Ver contenido" "Rechazar" < /dev/tty)
            fi

            if [ "$approval" = "Ver cambios" ] || [ "$approval" = "Ver contenido" ]; then
                echo "" >&2
                echo -e "${DIM}───────────────────────────────────────────────────────────────${NC}" >&2

                if [ -f "$resolved_path" ]; then
                    # Show diff for existing file
                    local tmp_old=$(mktemp)
                    local tmp_new=$(mktemp)
                    cat "$resolved_path" > "$tmp_old"
                    python3 -c "
import json
with open('$input_file', 'r') as f:
    data = json.load(f)
with open('$tmp_new', 'w') as f:
    f.write(data.get('content', ''))
"
                    # Show enhanced colored diff with stats
                    local diff_output=$(diff -u "$tmp_old" "$tmp_new" 2>/dev/null)
                    local total_lines=$(echo "$diff_output" | wc -l)
                    local added=$(echo "$diff_output" | grep -c "^+" || echo "0")
                    local removed=$(echo "$diff_output" | grep -c "^-" || echo "0")

                    # Show diff stats
                    echo -e "  ${BOLD}Cambios:${NC} ${GREEN}+$added${NC} ${RED}-$removed${NC} líneas" >&2
                    echo "" >&2

                    # Show colored diff (up to 50 lines)
                    echo "$diff_output" | tail -n +4 | head -50 | while IFS= read -r line; do
                        if [[ "$line" == +* ]]; then
                            echo -e "  ${GREEN}$line${NC}" >&2
                        elif [[ "$line" == -* ]]; then
                            echo -e "  ${RED}$line${NC}" >&2
                        elif [[ "$line" == @@* ]]; then
                            echo -e "  ${CYAN}$line${NC}" >&2
                        else
                            echo -e "  ${DIM}$line${NC}" >&2
                        fi
                    done

                    if [ "$total_lines" -gt 54 ]; then
                        echo -e "  ${DIM}... ($(($total_lines - 54)) líneas más)${NC}" >&2
                    fi

                    rm -f "$tmp_old" "$tmp_new"
                else
                    # Show content preview for new file
                    echo -e "  ${BOLD}Contenido nuevo:${NC}" >&2
                    python3 -c "
import json
with open('$input_file', 'r') as f:
    data = json.load(f)
content = data.get('content', '')
lines = content.split('\n')[:20]
for line in lines:
    print('  ' + line[:80])
if len(content.split('\n')) > 20:
    print('  ...(truncado)')
" >&2
                fi

                echo -e "${DIM}───────────────────────────────────────────────────────────────${NC}" >&2
                echo "" >&2
                # Continue loop to ask again
                continue
            fi

            # Not "Ver cambios" - exit loop
            break
        done

        # Handle approval result
        if [[ "$approval" == "Permitir siempre" ]]; then
            touch "${TURIA_AUTO_APPROVE_DIR}/write_file"
            echo -e "  ${GREEN}✓${NC} ${DIM}Escrituras auto-aprobadas para esta sesión${NC}" >&2
            echo "" >&2
        elif [[ "$approval" != "Permitir" ]]; then
            echo -e "  ${RED}✗${NC} ${DIM}Escritura rechazada${NC}" >&2
            echo "" >&2
            echo "[USUARIO_RECHAZÓ] El usuario ha decidido NO permitir esta escritura. No intentes escribir este archivo de nuevo. Pregunta al usuario qué quiere hacer."
            return 1
        fi

        echo -e "  ${GREEN}✓${NC} ${DIM}Escritura permitida${NC}" >&2
        echo "" >&2
    fi

    # Crear directorio si no existe
    local dir=$(dirname "$resolved_path")
    mkdir -p "$dir"

    # Capturar contenido anterior para mostrar diff
    local old_content=""
    local is_new_file=true
    if [ -f "$resolved_path" ]; then
        old_content=$(cat "$resolved_path")
        is_new_file=false

        # Create backup before overwriting
        local backup_path=$(create_file_backup "$resolved_path")
        if [ -n "$backup_path" ]; then
            echo -e "${DIM}💾 Backup creado: $(basename "$backup_path")${NC}" >&2
        fi
    fi

    # Escribir archivo directamente desde Python leyendo del archivo de input
    # (evita problemas con bash que pierden contenido)
    local write_result
    write_result=$(python3 -c "
import json
try:
    with open('$input_file', 'r') as f:
        data = json.load(f)
    content = data.get('content', '')
    path = '$resolved_path'
    with open(path, 'w') as f:
        f.write(content)
    print('OK:' + str(len(content)))
except Exception as e:
    print('ERROR:' + str(e))
" 2>&1)

    if [[ "$write_result" == ERROR:* ]]; then
        echo "Error escribiendo archivo: ${write_result#ERROR:}"
        return 1
    fi

    local content_len="${write_result#OK:}"

    # Audit log
    if [ "$is_new_file" = true ]; then
        audit_log "WRITE_NEW" "$path ($content_len bytes)"
    else
        audit_log "WRITE_MODIFY" "$path ($content_len bytes)"
    fi

    # Mostrar diff si es modificación de archivo existente
    if [ "$is_new_file" = false ]; then
        echo "" >&2

        # Crear archivos temporales para diff
        local tmp_old=$(mktemp)
        local tmp_new="$resolved_path"  # Usar el archivo recién escrito
        echo "$old_content" > "$tmp_old"

        # Contar líneas añadidas/eliminadas
        local additions=$(diff "$tmp_old" "$tmp_new" 2>/dev/null | grep -c "^>" || echo "0")
        local deletions=$(diff "$tmp_old" "$tmp_new" 2>/dev/null | grep -c "^<" || echo "0")

        # Header del diff estilo Claude Code
        local filename
        filename=$(basename "$path")
        echo -e "  ${BOLD}⏺ Update${NC}${DIM}(${filename})${NC}" >&2
        echo -e "  ${DIM}⎿${NC}  ${GREEN}+${additions}${NC} ${RED}-${deletions}${NC} líneas" >&2

        # Colores para diff
        local FG_GREEN='\033[32m'   # Texto verde
        local FG_RED='\033[31m'     # Texto rojo
        local BG_GREEN='\033[42;30m'  # Fondo verde, texto negro (para +)
        local BG_RED='\033[41;30m'    # Fondo rojo, texto negro (para -)

        # Generar diff limpio
        diff -u "$tmp_old" "$tmp_new" 2>/dev/null | tail -n +4 | while IFS= read -r line; do
            if [[ "$line" == @@* ]]; then
                # Hunk header - mostrar rango
                echo -e "${DIM}$line${NC}" >&2
            elif [[ "$line" == +* ]]; then
                # Línea añadida
                local content="${line:1}"
                echo -e "${FG_GREEN}+  ${content}${NC}" >&2
            elif [[ "$line" == -* ]]; then
                # Línea eliminada
                local content="${line:1}"
                echo -e "${FG_RED}-  ${content}${NC}" >&2
            else
                # Línea de contexto
                local content="${line:1}"
                echo -e "${DIM}   ${content}${NC}" >&2
            fi
        done

        rm -f "$tmp_old"  # Solo eliminar tmp_old, tmp_new es el archivo real

        echo "" >&2
        echo "Archivo modificado: $path ($content_len bytes)"
    else
        # Para archivos nuevos, mostrar preview (leer del archivo recién creado)
        local line_count=$(wc -l < "$resolved_path" | tr -d ' ')
        local filename
        filename=$(basename "$path")
        echo "" >&2
        echo -e "  ${BOLD}⏺ Create${NC}${DIM}(${filename})${NC}" >&2
        echo -e "  ${DIM}⎿${NC}  ${GREEN}+${line_count} líneas${NC}" >&2
        echo -e "${DIM}───────────────────────────────────────────────────────────────${NC}" >&2

        # Mostrar primeras líneas del archivo nuevo
        local BG_GREEN='\033[48;5;22m'
        local FG_GREEN='\033[38;5;114m'
        local preview_lines=10
        local current_line=1

        head -$preview_lines "$resolved_path" | while IFS= read -r line; do
            printf "${BG_GREEN}${FG_GREEN}%4s ${NC}${BG_GREEN} + %s${NC}\n" "$current_line" "$line" >&2
            ((current_line++))
        done

        if [ "$line_count" -gt "$preview_lines" ]; then
            local remaining=$((line_count - preview_lines))
            echo -e "${DIM}  ... +${remaining} líneas más${NC}" >&2
        fi

        echo "" >&2
        echo "Archivo creado: $path ($content_len bytes)"
    fi
}

# Edita un archivo con search & replace (similar a Claude Code Edit)
tool_edit_file() {
    local input_file="$1"

    # Read path, old_string, new_string from input file using Python
    local path
    path=$(python3 -c "
import json
with open('$input_file', 'r') as f:
    data = json.load(f)
print(data.get('path', ''))
" 2>/dev/null)

    if [ -z "$path" ]; then
        echo "Error: Se requiere una ruta de archivo"
        return 1
    fi

    # Validar que no salga del directorio actual (mismo patrón que write_file)
    local path_check=$(python3 -c "
import os
import sys
path = '$path'
cwd = os.getcwd()

# Validar contra null bytes
if '\\x00' in path or '\\0' in path:
    print('ERROR:Path contiene null bytes (ataque detectado)')
    sys.exit(1)

try:
    if os.path.exists(path):
        real_path = os.path.realpath(path)
    else:
        print('ERROR:El archivo no existe: ' + path)
        sys.exit(1)
except Exception as e:
    print('ERROR:Path inválido: ' + str(e))
    sys.exit(1)

# Verificar que está dentro del directorio actual usando commonpath
try:
    common = os.path.commonpath([cwd, real_path])
    if common == cwd:
        print('OK:' + real_path)
    else:
        print('ERROR:Path fuera del proyecto: ' + real_path)
except ValueError:
    print('ERROR:Path fuera del proyecto (diferentes unidades): ' + real_path)
")

    if [[ "$path_check" == ERROR:* ]]; then
        audit_log "EDIT_BLOCKED" "Path fuera del proyecto: $path"
        echo "Error: ${path_check#ERROR:}"
        return 1
    fi

    # Usar la ruta resuelta
    local resolved_path="${path_check#OK:}"

    # Ejecutar search & replace y generar diff con Python
    local edit_result
    edit_result=$(python3 - "$input_file" "$resolved_path" << 'PYEOF'
import json
import sys
import os
import difflib

input_file = sys.argv[1]
resolved_path = sys.argv[2]

BOLD = "\033[1m"
DIM = "\033[2m"
NC = "\033[0m"
CYAN = "\033[0;36m"
GREEN = "\033[32m"
RED = "\033[31m"

try:
    with open(input_file, 'r') as f:
        data = json.load(f)
except Exception as e:
    print(f"ERROR:No se pudo leer input: {e}")
    sys.exit(0)

old_string = data.get('old_string', '')
new_string = data.get('new_string', '')

if not old_string:
    print("ERROR:Se requiere old_string (texto a buscar)")
    sys.exit(0)

# Read the current file
try:
    with open(resolved_path, 'r') as f:
        content = f.read()
except Exception as e:
    print(f"ERROR:No se pudo leer el archivo: {e}")
    sys.exit(0)

# Check that old_string exists in the file
count = content.count(old_string)
if count == 0:
    print("ERROR:old_string no encontrado en el archivo. Verifica que el texto sea exacto (incluyendo espacios e indentación).")
    sys.exit(0)

if count > 1:
    print(f"ERROR:old_string encontrado {count} veces. Proporciona más contexto para que sea único.")
    sys.exit(0)

# Perform replacement
new_content = content.replace(old_string, new_string, 1)

# Generate compact diff for display on stderr
old_lines = content.splitlines(keepends=True)
new_lines = new_content.splitlines(keepends=True)

diff = list(difflib.unified_diff(old_lines, new_lines, fromfile=resolved_path, tofile=resolved_path, n=3))

if not diff:
    print("ERROR:old_string y new_string son idénticos. No hay cambios.")
    sys.exit(0)

# Count additions/deletions
additions = sum(1 for l in diff if l.startswith('+') and not l.startswith('+++'))
deletions = sum(1 for l in diff if l.startswith('-') and not l.startswith('---'))

# Print diff to stderr
sys.stderr.write(f"\n{DIM}───────────────────────────────────────────────────────────────{NC}\n")
sys.stderr.write(f" {BOLD}{data.get('path', resolved_path)}{NC}\n")
sys.stderr.write(f" {GREEN}+{additions}{NC} {RED}-{deletions}{NC}\n")
sys.stderr.write(f"{DIM}───────────────────────────────────────────────────────────────{NC}\n")

for line in diff[2:]:  # skip --- and +++ headers
    line_clean = line.rstrip('\n')
    if line.startswith('@@'):
        sys.stderr.write(f"{DIM}{line_clean}{NC}\n")
    elif line.startswith('+'):
        sys.stderr.write(f"{GREEN}+  {line_clean[1:]}{NC}\n")
    elif line.startswith('-'):
        sys.stderr.write(f"{RED}-  {line_clean[1:]}{NC}\n")
    else:
        sys.stderr.write(f"{DIM}   {line_clean[1:]}{NC}\n")

sys.stderr.write(f"{DIM}───────────────────────────────────────────────────────────────{NC}\n\n")

# Output: NEEDS_APPROVAL or READY, followed by new content length
print(f"READY:{len(new_content)}")

PYEOF
)

    # Check for errors from Python
    if [[ "$edit_result" == ERROR:* ]]; then
        echo "Error: ${edit_result#ERROR:}"
        return 1
    fi

    if [[ "$edit_result" != READY:* ]]; then
        echo "Error: Resultado inesperado del procesamiento"
        return 1
    fi

    local new_content_len="${edit_result#READY:}"

    # =========================================================================
    # ARCHIVOS SENSIBLES QUE REQUIEREN APROBACIÓN (mismo patrón que write_file)
    # =========================================================================
    local needs_approval=false
    local risk_reason=""
    local filename=$(basename "$path")

    local sensitive_patterns=(
        ".env|Archivo de variables de entorno"
        ".env.local|Archivo de variables de entorno local"
        ".env.production|Archivo de variables de producción"
        "credentials|Archivo de credenciales"
        "secrets|Archivo de secretos"
        ".ssh|Configuración SSH"
        ".aws|Configuración AWS"
        ".gitignore|Configuración de Git ignore"
        ".gitattributes|Atributos de Git"
        "package.json|Configuración de Node.js"
        "Podfile|Dependencias de iOS"
        "Gemfile|Dependencias de Ruby"
        "requirements.txt|Dependencias de Python"
        "pyproject.toml|Configuración de Python"
        "Dockerfile|Configuración de Docker"
        "docker-compose|Configuración de Docker Compose"
        ".yml|Archivo YAML de configuración"
        ".yaml|Archivo YAML de configuración"
        "config.|Archivo de configuración"
        "settings.|Archivo de configuración"
    )

    for entry in "${sensitive_patterns[@]}"; do
        local pattern="${entry%%|*}"
        local reason="${entry#*|}"
        if [[ "$path" == *"$pattern"* ]] || [[ "$filename" == *"$pattern"* ]]; then
            needs_approval=true
            risk_reason="$reason"
            break
        fi
    done

    # Check global preview_mode setting
    local preview_mode=$(get_agent_config "preview_mode")
    if [ "$preview_mode" = "true" ] && [ "$needs_approval" = false ]; then
        needs_approval=true
        risk_reason="Preview mode activado"
    fi

    # Si requiere aprobación, preguntar al usuario (salvo auto-approve activo para edit_file)
    if [ "$needs_approval" = true ] && [ ! -f "${TURIA_AUTO_APPROVE_DIR:-/dev/null}/edit_file" ]; then
        echo "" >&2
        echo -e "${DIM}┌─${NC} ${CYAN}Confirmar edición${NC} ${DIM}─────────────────────────────┐${NC}" >&2
        echo -e "${DIM}│${NC}" >&2
        echo -e "${DIM}│${NC}  ${BOLD}$path${NC}" >&2
        echo -e "${DIM}│${NC}  ${DIM}$risk_reason · search & replace${NC}" >&2
        echo -e "${DIM}│${NC}" >&2
        echo -e "${DIM}└────────────────────────────────────────────────┘${NC}" >&2
        echo "" >&2

        local approval=""
        approval=$(tool_interactive_select "¿Qué deseas hacer?" "Permitir" "Permitir siempre" "Rechazar" < /dev/tty)

        if [[ "$approval" == "Permitir siempre" ]]; then
            touch "${TURIA_AUTO_APPROVE_DIR}/edit_file"
            echo -e "  ${GREEN}✓${NC} ${DIM}Ediciones auto-aprobadas para esta sesión${NC}" >&2
            echo "" >&2
        elif [[ "$approval" != "Permitir" ]]; then
            echo -e "  ${RED}✗${NC} ${DIM}Edición rechazada${NC}" >&2
            echo "" >&2
            echo "[USUARIO_RECHAZÓ] El usuario ha decidido NO permitir esta edición. No intentes editar este archivo de nuevo. Pregunta al usuario qué quiere hacer."
            return 1
        else
            echo -e "  ${GREEN}✓${NC} ${DIM}Edición permitida${NC}" >&2
            echo "" >&2
        fi
    fi

    # Create backup before editing
    local backup_path=$(create_file_backup "$resolved_path")
    if [ -n "$backup_path" ]; then
        echo -e "${DIM}💾 Backup creado: $(basename "$backup_path")${NC}" >&2
    fi

    # Perform the actual replacement, write the file, and capture a window of
    # post-edit context (~10 lines around the change). The agent uses that
    # context to verify the edit and chain follow-up edits without re-reading
    # — see conv 219 (2026-04-11) for the re-read loop this was solving.
    local write_result
    write_result=$(python3 - "$input_file" "$resolved_path" << 'PYEOF'
import json
import sys
import base64

input_file = sys.argv[1]
resolved_path = sys.argv[2]

CONTEXT_LINES = 10
MAX_TOTAL_LINES = 60

try:
    with open(input_file, 'r') as f:
        data = json.load(f)

    old_string = data.get('old_string', '')
    new_string = data.get('new_string', '')

    with open(resolved_path, 'r') as f:
        content = f.read()

    new_content = content.replace(old_string, new_string, 1)

    with open(resolved_path, 'w') as f:
        f.write(new_content)

    # Build a line-numbered window around the inserted region.
    context_block = ""
    if new_string:
        pos = new_content.find(new_string)
        if pos != -1:
            prefix = new_content[:pos]
            start_line = prefix.count("\n") + 1
            new_string_line_count = max(1, new_string.count("\n") + 1)
            end_line = start_line + new_string_line_count - 1

            all_lines = new_content.split("\n")
            total_lines = len(all_lines)

            window_start = max(1, start_line - CONTEXT_LINES)
            window_end = min(total_lines, end_line + CONTEXT_LINES)

            if window_end - window_start + 1 > MAX_TOTAL_LINES:
                window_end = window_start + MAX_TOTAL_LINES - 1

            width = len(str(window_end))
            ctx_lines = [
                f"  (lineas {window_start}-{window_end} de {total_lines}, "
                f"'>' marca las lineas modificadas)"
            ]
            for ln in range(window_start, window_end + 1):
                marker = ">" if start_line <= ln <= end_line else " "
                ctx_lines.append(f"{ln:>{width}} {marker} {all_lines[ln - 1]}")
            context_block = "\n".join(ctx_lines)

    # base64 to keep the shell parser happy regardless of newlines/quotes
    encoded = base64.b64encode(context_block.encode("utf-8")).decode("ascii")
    print(f"OK:{len(new_content)}:{encoded}")
except Exception as e:
    print(f"ERROR:{e}")
PYEOF
)

    if [[ "$write_result" == ERROR:* ]]; then
        echo "Error escribiendo archivo: ${write_result#ERROR:}"
        return 1
    fi

    # Parse OK:<len>:<base64_context>
    local rest="${write_result#OK:}"
    local written_len="${rest%%:*}"
    local context_b64="${rest#*:}"
    local post_edit_context=""
    if [ -n "$context_b64" ]; then
        post_edit_context=$(echo "$context_b64" | base64 -d 2>/dev/null || echo "")
    fi

    # Audit log
    audit_log "EDIT_FILE" "$path ($written_len bytes, search & replace)"

    # Show diff for the edit (old_string → new_string)
    local old_string new_string
    read -r old_string new_string <<< "$(python3 -c "
import json
with open('$input_file', 'r') as f:
    data = json.load(f)
old = data.get('old_string', '')
new = data.get('new_string', '')
old_lines = old.count(chr(10))
new_lines = new.count(chr(10))
print(old_lines, new_lines)
")"
    local old_line_count="${old_string:-0}"
    local new_line_count="${new_string:-0}"
    local added=$((new_line_count - old_line_count > 0 ? new_line_count - old_line_count : 0))
    local removed=$((old_line_count - new_line_count > 0 ? old_line_count - new_line_count : 0))
    # Ensure at least 1 for changed lines
    if [ "$added" -eq 0 ] && [ "$removed" -eq 0 ]; then
        added=1
        removed=1
    fi

    local filename
    filename=$(basename "$path")

    echo "" >&2
    echo -e "  ${BOLD}⏺ Update${NC}${DIM}(${filename})${NC}" >&2
    echo -e "  ${DIM}⎿${NC}  ${GREEN}+${added}${NC} ${RED}-${removed}${NC} líneas" >&2

    # Show the actual diff content (old → new)
    python3 - "$input_file" << 'PYEOF' >&2
import json, sys, os

DIM = "\033[2m"
GREEN = "\033[32m"
RED = "\033[31m"
NC = "\033[0m"

with open(sys.argv[1], 'r') as f:
    data = json.load(f)

old_string = data.get('old_string', '')
new_string = data.get('new_string', '')

old_lines = old_string.split('\n')
new_lines = new_string.split('\n')

# Show max 20 lines of diff
max_lines = 20
shown = 0

for line in old_lines:
    if shown >= max_lines:
        remaining = len(old_lines) - shown + len(new_lines)
        print(f"  {DIM}  ... {remaining} líneas más{NC}")
        break
    display = line[:100]
    print(f"  {RED}-  {display}{NC}")
    shown += 1

for line in new_lines:
    if shown >= max_lines:
        remaining = len(new_lines) - (shown - len(old_lines))
        if remaining > 0:
            print(f"  {DIM}  ... {remaining} líneas más{NC}")
        break
    display = line[:100]
    print(f"  {GREEN}+  {display}{NC}")
    shown += 1
PYEOF

    echo "" >&2

    if [ -n "$post_edit_context" ]; then
        printf 'Archivo editado: %s (%s bytes)\n\nContexto post-edit (%s):\n%s\n' \
            "$path" "$written_len" "$path" "$post_edit_context"
    else
        echo "Archivo editado: $path ($written_len bytes)"
    fi
}

# Ejecuta un comando en terminal
tool_run_command() {
    local input="$1"
    local command=$(echo "$input" | jq -r '.command // ""')

    if [ -z "$command" ]; then
        echo "Error: Se requiere un comando"
        return 1
    fi

    # =========================================================================
    # WHITELIST DE COMANDOS PRE-APROBADOS POR EL USUARIO
    # =========================================================================
    local whitelist_file="$HOME/.config/turia-agent/allowed_commands.txt"
    local is_whitelisted=false

    if [ -f "$whitelist_file" ]; then
        while IFS= read -r pattern || [ -n "$pattern" ]; do
            # Ignorar líneas vacías y comentarios
            [[ -z "$pattern" || "$pattern" == \#* ]] && continue
            if [[ "$command" =~ $pattern ]]; then
                is_whitelisted=true
                break
            fi
        done < "$whitelist_file"
    fi

    # =========================================================================
    # COMANDOS SIEMPRE BLOQUEADOS (catastróficos, sin posibilidad de aprobar)
    # =========================================================================
    local blocked_patterns=(
        "rm -rf /"
        "rm -rf ~"
        "rm -rf \$HOME"
        "rm -rf /*"
        "mkfs"
        "> /dev/sd"
        "> /dev/nvme"
        "dd if=/dev/zero"
        "dd if=/dev/random"
        ":(){ :|:& };:"  # Fork bomb
        "chmod -R 777 /"
        "chown -R /"
        "curl.*|.*sh"
        "curl.*|.*bash"
        "wget.*|.*sh"
        "wget.*|.*bash"
        "/etc/passwd"
        "/etc/shadow"
        "~/.ssh/"
        "id_rsa"
        "id_ed25519"
        "ssh-keygen"
        "base64 -d.*|.*sh"
        "eval.*base64"
        "python.*-c.*import os"
        "nc -e"           # Netcat reverse shell
        "ncat -e"
        "/bin/sh -i"      # Interactive shell
        "bash -i"
        "0<&196"          # Bash reverse shell
        "exec 5<>"        # File descriptor manipulation
    )

    for pattern in "${blocked_patterns[@]}"; do
        if [[ "$command" == *"$pattern"* ]]; then
            audit_log "COMMAND_BLOCKED" "Patrón bloqueado: $pattern en: $command"
            echo "Error: Comando bloqueado permanentemente por seguridad: contiene '$pattern'"
            return 1
        fi
    done

    # =========================================================================
    # COMANDOS QUE REQUIEREN APROBACIÓN DEL USUARIO
    # =========================================================================
    local needs_approval=false
    local risk_reason=""

    # Patrones que requieren aprobación
    local approval_patterns=(
        "rm -rf|Eliminar recursivamente archivos"
        "rm -r|Eliminar recursivamente"
        "rm \\*|Eliminar con wildcard"
        "rm -f|Eliminar forzado"
        "sudo|Ejecutar como superusuario"
        "kill|Terminar proceso"
        "killall|Terminar todos los procesos"
        "pkill|Terminar procesos por nombre"
        "chmod|Cambiar permisos"
        "chown|Cambiar propietario"
        "mv /|Mover desde raíz"
        "cp -r /|Copiar desde raíz"
        "> |Sobrescribir archivo"
        ">>|Añadir a archivo"
        "curl.*-o|Descargar archivo"
        "wget|Descargar archivo"
        "npm install -g|Instalación global npm"
        "pip install|Instalar paquete Python"
        "brew install|Instalar con Homebrew"
        "apt install|Instalar con apt"
        "apt-get|Gestión de paquetes apt"
        "systemctl|Control de servicios"
        "service|Control de servicios"
        "shutdown|Apagar sistema"
        "reboot|Reiniciar sistema"
        "git push|Subir cambios a remoto"
        "git push -f|Push forzado"
        "git reset --hard|Reset destructivo"
        "docker rm|Eliminar contenedor"
        "docker rmi|Eliminar imagen"
        "docker system prune|Limpiar Docker"
    )

    for entry in "${approval_patterns[@]}"; do
        local pattern="${entry%%|*}"
        local reason="${entry#*|}"
        if [[ "$command" =~ $pattern ]]; then
            needs_approval=true
            risk_reason="$reason"
            break
        fi
    done

    # Si requiere aprobación, verificar whitelist, auto-approve, o preguntar al usuario
    if [ "$needs_approval" = true ]; then
        if [ "$is_whitelisted" = true ] || [ -f "${TURIA_AUTO_APPROVE_DIR:-/dev/null}/run_command" ]; then
            echo -e "${DIM}› auto-aprobado${NC}" >&2
        else
            echo "" >&2
            echo -e "${DIM}┌─${NC} ${CYAN}Confirmar ejecución${NC} ${DIM}───────────────────────────┐${NC}" >&2
            echo -e "${DIM}│${NC}" >&2
            echo -e "${DIM}│${NC}  ${MAGENTA}\$${NC} ${BOLD}$command${NC}" >&2
            echo -e "${DIM}│${NC}  ${DIM}$risk_reason${NC}" >&2
            echo -e "${DIM}│${NC}" >&2
            echo -e "${DIM}└────────────────────────────────────────────────┘${NC}" >&2
            echo "" >&2

            local approval=""
            approval=$(tool_interactive_select "¿Qué deseas hacer?" "Permitir" "Permitir siempre" "Rechazar" < /dev/tty)

            if [[ "$approval" == "Permitir siempre" ]]; then
                touch "${TURIA_AUTO_APPROVE_DIR}/run_command"
                echo -e "  ${GREEN}✓${NC} ${DIM}Comandos auto-aprobados para esta sesión${NC}" >&2
                echo "" >&2
            elif [[ "$approval" == "Permitir" ]]; then
                echo -e "  ${GREEN}✓${NC} ${DIM}Ejecutando...${NC}" >&2
                echo "" >&2
            else
                audit_log "COMMAND_REJECTED" "Usuario rechazó: $command"
                echo -e "  ${RED}✗${NC} ${DIM}Comando rechazado${NC}" >&2
                echo "" >&2
                echo "[USUARIO_RECHAZÓ] El usuario ha decidido NO ejecutar este comando. No intentes ejecutarlo de nuevo. Pregunta al usuario qué quiere hacer."
                return 1
            fi
        fi
    fi

    # =========================================================================
    # EJECUTAR COMANDO CON POSIBILIDAD DE CANCELACIÓN
    # =========================================================================

    # Audit log de ejecución
    audit_log "COMMAND_EXEC" "$command"

    # Mostrar hint de cancelación
    echo -e "${DIM}Ctrl+C para cancelar${NC}" >&2

    # Guardar el handler original de SIGINT
    local original_trap=$(trap -p SIGINT)

    # Variable para saber si fue cancelado
    local was_cancelled=false

    # Crear archivo temporal para el output
    local tmp_output=$(mktemp)

    # Ejecutar en background
    timeout "$MAX_COMMAND_TIMEOUT" bash -c "$command" > "$tmp_output" 2>&1 &
    local cmd_pid=$!

    # Handler para Ctrl+C - solo mata el comando, no el agente
    trap '
        was_cancelled=true
        kill $cmd_pid 2>/dev/null
        wait $cmd_pid 2>/dev/null
    ' SIGINT

    # Esperar a que termine el comando
    wait $cmd_pid 2>/dev/null
    local exit_code=$?

    # Restaurar el handler original
    eval "$original_trap"
    trap - SIGINT

    # Leer output
    local output=$(head -"$MAX_OUTPUT_LINES" "$tmp_output")
    rm -f "$tmp_output"

    # Mostrar resultado según el caso
    if [ "$was_cancelled" = true ]; then
        echo -e "\n${DIM}Comando cancelado${NC}"
        return 130  # Código estándar para SIGINT
    elif [ $exit_code -eq 124 ]; then
        echo "$output"
        echo -e "\n${YELLOW}Timeout (${MAX_COMMAND_TIMEOUT}s)${NC}"
    else
        echo "$output"
    fi

    return $exit_code
}

# Obtiene informacion de git
tool_git_info() {
    local input="$1"
    local info_type=$(echo "$input" | jq -r '.type // "status"')

    if ! git rev-parse --git-dir > /dev/null 2>&1; then
        echo "Error: No es un repositorio git"
        return 1
    fi

    case "$info_type" in
        status)
            git status
            ;;
        log)
            git log --oneline -20
            ;;
        diff)
            git diff --stat
            ;;
        branch)
            git branch -a
            ;;
        *)
            echo "Tipo no soportado: $info_type (usa: status, log, diff, branch)"
            ;;
    esac
}

# Dispatcher principal de herramientas
# Args: tool_name, input_file_path (JSON file with tool input)
execute_tool_locally() {
    local tool_name="$1"
    local input_file="$2"

    # For write_file and edit_file, pass file path directly (avoids content mangling)
    # For other tools, read content from file
    if [ "$tool_name" = "write_file" ]; then
        tool_write_file "$input_file"
    elif [ "$tool_name" = "edit_file" ]; then
        tool_edit_file "$input_file"
    else
        # Read tool input from file for other tools
        local tool_input
        if [ -f "$input_file" ]; then
            tool_input=$(cat "$input_file")
        else
            tool_input="$input_file"  # Fallback: treat as content directly
        fi

        case "$tool_name" in
            read_file)
                tool_read_file "$tool_input"
                ;;
            list_files)
                tool_list_files "$tool_input"
                ;;
            search_code)
                tool_search_code "$tool_input"
                ;;
            run_command)
                tool_run_command "$tool_input"
                ;;
            git_info)
                tool_git_info "$tool_input"
                ;;
            *)
                echo "Error: Tool desconocido: $tool_name"
                return 1
                ;;
        esac
    fi
}

# ============================================================================
# UTILIDADES
# ============================================================================

# Muestra informacion del proyecto actual
show_project_info() {
    local project_type=$(detect_project_type)
    local project_name=$(basename "$PWD")
    local file_count=$(generate_file_tree | wc -l | tr -d ' ')
    local git_branch=$(git branch --show-current 2>/dev/null || echo "N/A")

    echo -e "${BOLD}Proyecto: ${GREEN}$project_name${NC}"
    echo -e "Tipo: ${YELLOW}$project_type${NC}"
    echo -e "Archivos: ${YELLOW}$file_count${NC}"
    echo -e "Branch: ${YELLOW}$git_branch${NC}"
    echo -e "Ruta: ${YELLOW}$PWD${NC}"
}
