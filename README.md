# Turia

## Descripcion

Turia es una herramienta CLI para acelerar el desarrollo con arquetipos y modulos predefinidos. Soporta proyectos **Android**, **iOS**, **Flutter** y **Python**.

## Requisitos

Antes de utilizar turia, asegurate de tener instalado Homebrew: https://brew.sh/

```bash
brew tap rudoapps/turia
brew install turia
```

## Actualizacion

Recomendamos mantener turia actualizado:

```bash
brew update && brew upgrade turia
```

## Uso

```bash
turia <comando> [opciones]
```

## Comandos disponibles

### Agente AI

| Comando | Descripcion |
|---------|-------------|
| `chat` | Inicia conversacion con el agente AI |
| `login` | Inicia sesion en el agente AI |
| `logout` | Cierra sesion del agente AI |
| `setup` | Instala dependencias del agente AI |
| `whoami` | Muestra el usuario actual del agente |
| `undo` | Lista y restaura backups de archivos modificados |

### Modulos y Proyectos

| Comando | Descripcion |
|---------|-------------|
| `list` | Lista modulos disponibles para el proyecto actual |
| `install` | Instala uno o varios modulos en el proyecto |
| `create` | Crea un nuevo proyecto con arquitectura predefinida |
| `template` | Genera templates con arquitecturas predefinidas |
| `branches` | Lista ramas disponibles en repositorios |
| `status` | Muestra el estado del proyecto y modulos instalados |
| `validate` | Valida archivos configuration.turia del proyecto |
| `install-hook` | Instala pre-commit hook para validar configuration.turia |
| `help` | Muestra la ayuda |

## Opciones globales

| Opcion | Descripcion |
|--------|-------------|
| `--key=XXXX` | Clave de acceso para repositorios privados |
| `--branch=YYYY` | Rama especifica del repositorio |
| `--tag=ZZZZ` | Tag especifico del repositorio |
| `--type=ZZZZ` | Tipo de template: `clean`, `fastapi` |
| `--archetype=ZZZZ` | Plataforma: `android`, `ios`, `flutter`, `python` |
| `--force` | Forzar reinstalacion sin confirmar |
| `--module` | Instalar como modulo completo (modo por defecto) |
| `--integrate` | [Solo iOS] Integrar en estructura existente |
| `--list` | Lista todos los templates disponibles |
| `--json` | Salida en formato JSON |
| `--help`, `-h` | Muestra la ayuda |

## Ejemplos de uso

### Usar el agente AI

```bash
# Instalar dependencias del agente
turia setup

# Iniciar sesion
turia login

# Modo interactivo
turia chat

# Mensaje unico
turia chat "Hola"

# Continuar ultima conversacion
turia chat --continue

# Ver usuario actual
turia whoami

# Cerrar sesion
turia logout
```

### Listar modulos disponibles

```bash
turia list --key=mi_clave
turia list --key=mi_clave --branch=development
```

### Instalar modulos

```bash
# Instalar un modulo
turia install authentication --key=mi_clave

# Instalar con rama especifica
turia install network --key=mi_clave --branch=feature-branch

# Instalar con tag especifico
turia install network --key=mi_clave --tag=v1.0.0

# Forzar reinstalacion
turia install authentication --key=mi_clave --force

# Instalar como modulo completo (sin preguntar)
turia install authentication --key=mi_clave --module

# [iOS] Integrar en capas existentes (data→data, domain→domain)
turia install authentication --key=mi_clave --integrate

# Instalar multiples modulos (batch)
turia install login,wallet,payments --key=mi_clave
```

### Crear nuevos proyectos

```bash
turia create android --key=mi_clave
turia create ios --key=mi_clave
turia create flutter --key=mi_clave
turia create python --key=mi_clave
```

### Generar templates

```bash
# Ver templates disponibles
turia template --list

# Generar un template
turia template user
turia template product --type=clean

# Generar multiples templates
turia template user,product,order
```

### Listar ramas disponibles

```bash
# Auto-detecta el tipo de proyecto
turia branches --key=mi_clave

# Para consultar arquetipos especificos
turia branches --key=mi_clave --archetype=flutter
```

### Ver estado del proyecto

```bash
turia status
```

### Validar configuracion

```bash
# Validar todos los configuration.turia
turia validate

# Validar solo archivos en staging (pre-commit)
turia validate --staged

# Instalar hook de pre-commit
turia install-hook
```

## Plataformas soportadas

| Plataforma | Descripcion |
|------------|-------------|
| Android | Proyectos nativos Android con Clean Architecture |
| iOS | Proyectos nativos iOS con Clean Architecture |
| Flutter | Aplicaciones multiplataforma Flutter |
| Python | APIs backend con FastAPI o Django |

## Arquitecturas disponibles

- **Android & iOS**: Clean Architecture (Repository, UseCase, ViewModel)
- **Flutter**: Clean Architecture (BLoC, Repository, UseCase)
- **Python**: Arquitectura Hexagonal (Adaptadores y Puertos)

## Notas

- `chat/login/setup`: Comandos del agente AI, usa `turia setup` primero para instalar dependencias
- `template`: No requiere `--key` (usa templates locales)
- `install/list`: Requiere `--key` para acceder a repositorios privados
- `create`: Requiere `--key` para descargar arquetipos
- `--integrate`: Solo disponible para proyectos iOS
- Los comandos `list/install` detectan automaticamente el tipo de proyecto
- Todas las operaciones se registran en `.turia.log` (formato JSON)
- Use `turia status` para ver el historial de operaciones

## Contribuir

Si deseas contribuir a este proyecto, haz un fork del repositorio, realiza tus modificaciones y envia un pull request.

## Licencia

Este proyecto es propiedad de Rudo Apps y esta bajo licencia MIT.
