#!/usr/bin/env python3
"""
Python Feature Installation Script for Turia

This script handles the Python-specific installation logic after the repository
has been cloned by the main turia bash script.

Usage (called from python.sh):
  python3 python_install.py install <clone_dir> <feature_name> [--verbose]
  python3 python_install.py list <clone_dir> [--verbose]
"""

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional

SOURCE_DIR = 'features'
EXCLUDED_FILES = {"__pycache__", ".git", ".svn", ".hg", ".DS_Store", "Thumbs.db"}
CONFIGURATION_FILE = 'configuration.turia'

VERBOSE = False


def vprint(*args, **kwargs):
    """Print only if verbose mode is enabled"""
    if VERBOSE:
        print(*args, **kwargs)


class FeatureConfiguration:
    """Configuration class for a feature module"""

    def __init__(self, **kwargs):
        name = kwargs.get('name')
        if not name:
            raise ValueError("configuration.turia: 'name' is required")

        version = kwargs.get('version')
        if not version:
            raise ValueError("configuration.turia: 'version' is required")

        description = kwargs.get('description')
        if not description:
            raise ValueError("configuration.turia: 'description' is required")

        dependencies = kwargs.get('dependencies')
        if dependencies is not None and not isinstance(dependencies, list):
            raise ValueError("configuration.turia: 'dependencies' must be a list")

        apps = kwargs.get('apps')
        if apps is not None and not isinstance(apps, list):
            raise ValueError("configuration.turia: 'apps' must be a list")

        models = kwargs.get('models')
        if models is not None and not isinstance(models, dict):
            raise ValueError("configuration.turia: 'models' must be a dictionary")

        self.name: str = name
        self.version: str = version
        self.description: str = description
        self.dependencies: List[str] = dependencies if dependencies is not None else []
        self.apps: List[str] = apps if apps is not None else []
        self.models: Dict[str, str] = models if models is not None else {}


def discover_features(clone_dir: Path) -> List[str]:
    """Discover available features in the cloned repository."""
    features_path = clone_dir / SOURCE_DIR

    if not features_path.exists() or not features_path.is_dir():
        return []

    return sorted([
        item.name for item in features_path.iterdir()
        if item.is_dir() and not item.name.startswith('.')
    ])


def load_feature_configuration(feature_path: Path) -> FeatureConfiguration:
    """Load and parse the configuration.turia file from a feature directory."""
    config_file = feature_path / CONFIGURATION_FILE

    if not config_file.exists():
        raise RuntimeError(f"Configuration file not found: {config_file}")

    vprint(f"Loading configuration from: {config_file}")

    with config_file.open('r', encoding='utf-8') as f:
        data = json.load(f)
        return FeatureConfiguration(**data)


def _copy_directory_recursive(source_dir: Path, target_dir: Path) -> None:
    """Recursively copy directory contents."""
    for item in source_dir.iterdir():
        if item.name in EXCLUDED_FILES:
            continue

        target_item = target_dir / item.name

        if item.is_dir():
            target_item.mkdir(parents=True, exist_ok=True)
            _copy_directory_recursive(item, target_item)
        else:
            if item.suffix in {".pyc", ".pyo"}:
                continue
            if item.name == "__init__.py" and target_item.exists():
                continue

            target_item.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target_item)
            vprint(f"    Copied: {item.name}")


def copy_hexagonal_content(source_dir: Path) -> None:
    """Copy hexagonal architecture directories from source to current project."""
    if not source_dir.exists():
        raise RuntimeError(f"Source directory does not exist: {source_dir}")

    directories_to_copy = [
        "driving",
        "driven",
        "domain",
        "constants",
        "functions",
        "application/di",
        "application/ports",
        "application/services",
    ]

    cwd = Path.cwd()
    print(f"  Copying feature files to project...")

    for dir_path in directories_to_copy:
        source_subdir = source_dir / dir_path
        target_subdir = cwd / dir_path

        if not source_subdir.exists() or not source_subdir.is_dir():
            continue

        vprint(f"    Processing: {dir_path}")
        target_subdir.mkdir(parents=True, exist_ok=True)

        # Create __init__.py in intermediate directories
        current = target_subdir
        while current != current.parent and current > cwd:
            init_file = current / "__init__.py"
            if not init_file.exists():
                init_file.write_text("\n", encoding="utf-8")
            current = current.parent

        _copy_directory_recursive(source_subdir, target_subdir)

    print(f"  ✅ Feature files copied")


def update_dynamic_apps(new_apps: List[str]) -> None:
    """Update config/settings/dynamic_apps.py with new apps."""
    if not new_apps:
        return

    dynamic_apps_file = Path.cwd() / "config" / "settings" / "dynamic_apps.py"
    print(f"  Updating dynamic_apps.py...")

    existing_apps = []
    if dynamic_apps_file.exists():
        content = dynamic_apps_file.read_text(encoding="utf-8")
        import re
        match = re.search(r'DYNAMIC_APPS\s*=\s*\[(.*?)]', content, re.DOTALL)
        if match:
            list_content = match.group(1).strip()
            for line in list_content.split('\n'):
                line = line.strip()
                if line and (line.startswith("'") or line.startswith('"')):
                    app_name = line.rstrip(',').strip().strip("'\"")
                    if app_name:
                        existing_apps.append(app_name)

    all_apps = existing_apps.copy()
    added = 0
    for app in new_apps:
        if app not in all_apps:
            all_apps.append(app)
            added += 1
            vprint(f"    Adding app: {app}")

    dynamic_apps_file.parent.mkdir(parents=True, exist_ok=True)
    apps_list = ",\n    ".join(f"'{app}'" for app in all_apps)
    new_content = f"""# Project dynamic app declarations.
# Do not edit this file. Is autogenerated.

DYNAMIC_APPS = [
    {apps_list}
]
"""
    dynamic_apps_file.write_text(new_content, encoding="utf-8")
    print(f"  ✅ Added {added} app(s) to dynamic_apps.py")


def update_dynamic_models(models: Dict[str, str]) -> None:
    """Update config/settings/dynamic_models.py with new model definitions."""
    if not models:
        return

    dynamic_models_file = Path.cwd() / "config" / "settings" / "dynamic_models.py"
    print(f"  Updating dynamic_models.py...")

    if dynamic_models_file.exists():
        content = dynamic_models_file.read_text(encoding="utf-8")
    else:
        dynamic_models_file.parent.mkdir(parents=True, exist_ok=True)
        content = """# Project ORM dynamic model definitions
# Do not edit this file. Is autogenerated.


"""

    import re
    added = 0
    for model_name, model_path in models.items():
        model_definition = f"{model_name} = '{model_path}'"
        if model_definition in content:
            continue
        pattern = f"^{re.escape(model_name)}\\s*=.*$"
        if re.search(pattern, content, re.MULTILINE):
            continue
        if not content.endswith('\n'):
            content += '\n'
        content += f"{model_definition}\n"
        added += 1
        vprint(f"    Adding model: {model_name}")

    dynamic_models_file.write_text(content, encoding="utf-8")
    print(f"  ✅ Added {added} model(s) to dynamic_models.py")


def copy_locale_folder(source_feature_path: Path, module_name: str) -> Optional[str]:
    """Copy locale folder from feature to locales/{module_name}."""
    source_locale = source_feature_path / "locale"

    if not source_locale.exists() or not source_locale.is_dir():
        return None

    target_locale = Path.cwd() / "locales" / module_name
    print(f"  Copying locale folder...")
    target_locale.mkdir(parents=True, exist_ok=True)
    _copy_directory_recursive(source_locale, target_locale)
    print(f"  ✅ Locale copied to locales/{module_name}")

    return f"locales/{module_name}"


def update_dynamic_locales(locale_path: str) -> None:
    """Update config/settings/dynamic_locales.py with new locale path."""
    dynamic_locales_file = Path.cwd() / "config" / "settings" / "dynamic_locales.py"
    print(f"  Updating dynamic_locales.py...")

    existing_locales = []
    if dynamic_locales_file.exists():
        content = dynamic_locales_file.read_text(encoding="utf-8")
        import re
        match = re.search(r'DYNAMIC_LOCALES\s*=\s*\[(.*?)]', content, re.DOTALL)
        if match:
            list_content = match.group(1).strip()
            for line in list_content.split('\n'):
                line = line.strip()
                if line and (line.startswith("'") or line.startswith('"')):
                    locale = line.rstrip(',').strip().strip("'\"")
                    if locale:
                        existing_locales.append(locale)

    if locale_path in existing_locales:
        print(f"  ✅ Locale already registered")
        return

    existing_locales.append(locale_path)
    dynamic_locales_file.parent.mkdir(parents=True, exist_ok=True)
    locales_list = ",\n    ".join(f"'{locale}'" for locale in existing_locales)
    new_content = f"""# Project dynamic locale declarations.
# Do not edit this file. Is autogenerated.

DYNAMIC_LOCALES = [
    {locales_list}
]
"""
    dynamic_locales_file.write_text(new_content, encoding="utf-8")
    print(f"  ✅ Added locale to dynamic_locales.py")


def _resolve_turia_core_dependency(source_feature_path: Path) -> None:
    """Copy turia/core directory to project."""
    print(f"  Resolving turia/core dependency...")
    source_core_dir = source_feature_path.parent.parent / "core"

    if not source_core_dir.exists():
        raise RuntimeError(f"turia/core not found: {source_core_dir}")

    target_core_dir = Path.cwd() / "core"
    target_core_dir.mkdir(parents=True, exist_ok=True)
    _copy_directory_recursive(source_core_dir, target_core_dir)
    print(f"  ✅ turia/core copied")


def _resolve_package_dependency(package_name: str) -> None:
    """Add package dependency to pyproject.toml."""
    pyproject_file = Path.cwd() / "pyproject.toml"

    if not pyproject_file.exists():
        print(f"  ⚠️  pyproject.toml not found, skipping {package_name}")
        return

    content = pyproject_file.read_text(encoding="utf-8")

    import re
    start_match = re.search(r'dependencies\s*=\s*\[', content)
    if not start_match:
        print(f"  ⚠️  dependencies array not found in pyproject.toml")
        return

    search_start = start_match.end()
    end_match = re.search(r'\]\s*(?:\n|$)', content[search_start:])
    if not end_match:
        return

    deps_start = start_match.end()
    deps_end = search_start + end_match.start()
    deps_content = content[deps_start:deps_end]

    # Parse existing dependencies
    existing_deps = []
    dep_pattern = r'["\']([^"\']*(?:\\.[^"\']*)*)["\']'
    for match_dep in re.finditer(dep_pattern, deps_content):
        dep = match_dep.group(1).strip()
        if dep:
            existing_deps.append(dep)

    def extract_package_name(dependency: str) -> str:
        dep_without_extras = re.split(r'\[', dependency)[0]
        return re.split(r'[><=!~@]', dep_without_extras)[0].strip()

    new_package_name = extract_package_name(package_name)
    for existing_dep in existing_deps:
        if new_package_name.lower() == extract_package_name(existing_dep).lower():
            vprint(f"    Package {new_package_name} already exists")
            return

    existing_deps.append(package_name)
    print(f"    Adding dependency: {package_name}")

    deps_lines = ',\n    '.join(f'"{dep}"' for dep in existing_deps)
    new_deps_content = f"\n    {deps_lines},\n"
    new_content = content[:deps_start] + new_deps_content + content[deps_end:]
    pyproject_file.write_text(new_content, encoding="utf-8")


def resolve_dependencies(dependencies: List[str], source_feature_path: Path) -> None:
    """Resolve and install feature dependencies."""
    if not dependencies:
        return

    print(f"  Resolving {len(dependencies)} dependencies...")
    for dep in dependencies:
        if dep == "turia/core":
            _resolve_turia_core_dependency(source_feature_path)
        else:
            _resolve_package_dependency(dep)
    print(f"  ✅ Dependencies resolved")


def install_feature(clone_dir: Path, feature_name: str) -> int:
    """Install a feature from the cloned repository."""
    source_feature_path = clone_dir / SOURCE_DIR / feature_name

    if not source_feature_path.exists():
        print(f"❌ Feature '{feature_name}' not found in {clone_dir / SOURCE_DIR}")
        return 1

    # Load configuration
    print(f"  Loading feature configuration...")
    config = load_feature_configuration(source_feature_path)
    print(f"  ✅ Feature: {config.name} v{config.version}")

    # Copy feature files
    copy_hexagonal_content(source_feature_path)

    # Update dynamic apps
    if config.apps:
        update_dynamic_apps(config.apps)

    # Copy locale and update dynamic locales
    locale_path = copy_locale_folder(source_feature_path, config.name)
    if locale_path:
        update_dynamic_locales(locale_path)

    # Update dynamic models
    if config.models:
        update_dynamic_models(config.models)

    # Resolve dependencies
    if config.dependencies:
        resolve_dependencies(config.dependencies, source_feature_path)

    return 0


def list_features(clone_dir: Path) -> int:
    """List available features."""
    features = discover_features(clone_dir)

    if features:
        for feature in features:
            print(feature)
    return 0


def main(argv: List[str]) -> int:
    global VERBOSE

    parser = argparse.ArgumentParser(description="Python feature installation for Turia")
    parser.add_argument('command', choices=['install', 'list'])
    parser.add_argument('clone_dir', help='Path to cloned repository')
    parser.add_argument('feature_name', nargs='?', help='Feature name (for install)')
    parser.add_argument('--verbose', action='store_true')

    args = parser.parse_args(argv)
    VERBOSE = args.verbose

    clone_dir = Path(args.clone_dir)
    if not clone_dir.exists():
        print(f"❌ Clone directory not found: {clone_dir}", file=sys.stderr)
        return 1

    if args.command == 'list':
        return list_features(clone_dir)
    elif args.command == 'install':
        if not args.feature_name:
            print("❌ Feature name required for install", file=sys.stderr)
            return 1
        return install_feature(clone_dir, args.feature_name)

    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
