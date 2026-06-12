"""Build project context for the chat API — pure-Python port of agent_local_tools.sh."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


# Directories to always skip when building the file tree.
_SKIP_DIRS: Set[str] = {
    ".git",
    "node_modules",
    "__pycache__",
    "venv",
    ".venv",
    "build",
    "dist",
    ".build",
    "Pods",
    ".dart_tool",
    "DerivedData",
    ".gradle",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    "egg-info",
}

# File extensions / names to skip in the tree.
_SKIP_EXTENSIONS: Set[str] = {".pyc", ".class", ".o"}
_SKIP_NAMES: Set[str] = {
    "package-lock.json",
    "yarn.lock",
    "Podfile.lock",
    ".DS_Store",
}
_SKIP_SUFFIXES: Set[str] = {".pbxproj", ".xcscheme", ".lock"}

# Candidate key files, checked in order.
_KEY_FILE_CANDIDATES: List[str] = [
    "README.md",
    "readme.md",
    "requirements.txt",
    "pyproject.toml",
    "setup.py",
    "package.json",
    "tsconfig.json",
    "pubspec.yaml",
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "settings.gradle.kts",
    "Package.swift",
    "Podfile",
    "Cargo.toml",
    "go.mod",
    "Makefile",
    "Dockerfile",
    "docker-compose.yml",
    ".env.example",
    "configuration.turia",
]

# Project-type-specific entry points to look for.
_ENTRY_POINTS: Dict[str, List[str]] = {
    "python": ["main.py", "app.py", "manage.py", "wsgi.py", "asgi.py"],
    "node": [
        "index.ts",
        "index.js",
        "src/index.ts",
        "src/index.js",
        "src/app.ts",
        "src/app.js",
    ],
    "flutter": ["lib/main.dart"],
}

# Project rules files, first match wins.
_RULES_FILES: List[str] = [".claude-project", "CLAUDE.md", ".agent-rules"]


class ProjectContextBuilder:
    """Detects project metadata and builds a context dict for the chat API.

    The context is cached after the first build.  Call ``rebuild()`` to force
    a fresh scan.

    Args:
        root: Project root directory.  Defaults to the current working directory.
        max_depth: Maximum directory depth for the file tree (default 4).
        max_files: Maximum entries in the file tree (default 100).
    """

    def __init__(
        self,
        root: Optional[str] = None,
        max_depth: int = 4,
        max_files: int = 100,
    ) -> None:
        self._root = Path(root) if root else Path.cwd()
        self._max_depth = max_depth
        self._max_files = max_files
        self._cache: Optional[Dict[str, Any]] = None

    # ── public API ───────────────────────────────────────────────────────

    def build(self) -> Dict[str, Any]:
        """Return the full project context dict (cached after first call).

        The returned dict matches the ``project_context`` parameter expected
        by ``payload_builder.build_chat_payload``.
        """
        if self._cache is not None:
            return self._cache

        project_type = self.detect_project_type()

        context: Dict[str, Any] = {
            "project_type": project_type,
            "project_name": self._root.name,
            "root_path": str(self._root),
            "file_tree": self._generate_file_tree(),
            "key_files": self._detect_key_files(project_type),
            "dependencies": self._get_dependencies_summary(project_type),
            "project_rules": self._read_project_rules(),
        }

        # Git info (branch + short status)
        git_info = self._get_git_info()
        context.update(git_info)

        self._cache = context
        return self._cache

    def build_minimal(self) -> Dict[str, Any]:
        """Return a lightweight context for follow-up messages.

        Includes only the project type, name, root path, and project rules.
        """
        full = self.build()
        minimal: Dict[str, Any] = {
            "project_type": full["project_type"],
            "project_name": full["project_name"],
            "root_path": full["root_path"],
        }
        rules = full.get("project_rules")
        if rules:
            minimal["project_rules"] = rules
        return minimal

    def get_git_remote_url(self) -> Optional[str]:
        """Return the git remote URL for RAG, or None."""
        url = self._git("remote", "get-url", "origin")
        return url if url else None

    def rebuild(self) -> Dict[str, Any]:
        """Force a fresh context scan, discarding the cache."""
        self._cache = None
        return self.build()

    def detect_project_type(self) -> str:
        """Detect the project type from marker files in the root directory.

        Returns:
            A string identifier such as ``"python"``, ``"ios"``, ``"node"``,
            ``"flutter"``, ``"android"``, ``"rust"``, ``"go"``, or ``"unknown"``.
        """
        root = self._root

        if (root / "pubspec.yaml").exists():
            return "flutter"

        if (root / "Package.swift").exists() or self._has_glob("*.xcodeproj") or self._has_glob("*.xcworkspace"):
            return "ios"

        if (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
            return "android"

        if (root / "pyproject.toml").exists() or (root / "requirements.txt").exists() or (root / "setup.py").exists():
            # Refine: django / fastapi detection
            return self._refine_python_type()

        if (root / "package.json").exists():
            return self._refine_node_type()

        if (root / "Cargo.toml").exists():
            return "rust"

        if (root / "go.mod").exists():
            return "go"

        return "unknown"

    # ── private helpers ──────────────────────────────────────────────────

    def _has_glob(self, pattern: str) -> bool:
        """Check if any file matches *pattern* directly under root."""
        return any(self._root.glob(pattern))

    def _refine_python_type(self) -> str:
        """Distinguish plain python / django / fastapi."""
        root = self._root
        # Django markers
        if (root / "manage.py").exists():
            return "python/django"
        # FastAPI markers — check for import in common entry files
        for name in ("main.py", "app.py", "app/main.py", "src/main.py"):
            candidate = root / name
            if candidate.is_file():
                try:
                    head = candidate.read_text(errors="replace")[:2000]
                    if "fastapi" in head.lower():
                        return "python/fastapi"
                except OSError:
                    pass
        return "python"

    def _refine_node_type(self) -> str:
        """Distinguish plain node / react / next etc."""
        root = self._root
        pkg = root / "package.json"
        if pkg.is_file():
            try:
                import json

                data = json.loads(pkg.read_text(errors="replace"))
                deps = {
                    *data.get("dependencies", {}).keys(),
                    *data.get("devDependencies", {}).keys(),
                }
                if "next" in deps:
                    return "node/next"
                if "react" in deps:
                    return "node/react"
                if "vue" in deps:
                    return "node/vue"
                if "express" in deps:
                    return "node/express"
            except (OSError, ValueError, KeyError):
                pass
        return "node"

    # ── file tree ────────────────────────────────────────────────────────

    def _generate_file_tree(self) -> str:
        """Walk the project directory and return a newline-separated file tree."""
        entries: List[str] = []
        root = self._root

        for dirpath, dirnames, filenames in os.walk(root):
            rel_dir = os.path.relpath(dirpath, root)
            depth = 0 if rel_dir == "." else rel_dir.count(os.sep) + 1

            if depth > self._max_depth:
                dirnames.clear()
                continue

            # Prune skippable directories in-place (modifying dirnames)
            dirnames[:] = sorted(
                d
                for d in dirnames
                if d not in _SKIP_DIRS and not d.startswith(".")
            )

            # Add directory entry
            if rel_dir != ".":
                entries.append(f"./{rel_dir}/")
                if len(entries) >= self._max_files:
                    break

            # Add file entries
            for fname in sorted(filenames):
                if fname in _SKIP_NAMES:
                    continue
                ext = os.path.splitext(fname)[1]
                if ext in _SKIP_EXTENSIONS or ext in _SKIP_SUFFIXES:
                    continue
                if fname.startswith("."):
                    continue

                if rel_dir == ".":
                    entries.append(f"./{fname}")
                else:
                    entries.append(f"./{rel_dir}/{fname}")

                if len(entries) >= self._max_files:
                    break

            if len(entries) >= self._max_files:
                break

        return "\n".join(entries)

    # ── key files ────────────────────────────────────────────────────────

    def _detect_key_files(self, project_type: str) -> List[str]:
        """Return a list of key project files that exist."""
        root = self._root
        found: List[str] = []

        for name in _KEY_FILE_CANDIDATES:
            if (root / name).exists():
                found.append(name)

        # Project-type-specific entry points
        base_type = project_type.split("/")[0]
        for name in _ENTRY_POINTS.get(base_type, []):
            if (root / name).exists():
                found.append(name)

        # iOS-specific deep searches
        if base_type == "ios":
            found.extend(self._find_ios_key_files())

        # Android-specific
        if base_type == "android":
            found.extend(self._find_android_key_files())

        return found

    def _find_ios_key_files(self) -> List[str]:
        """Find iOS-specific key files up to depth 3."""
        targets = {
            "AppDelegate.swift",
            "SceneDelegate.swift",
            "App.swift",
            "Info.plist",
        }
        results: List[str] = []
        for dirpath, dirnames, filenames in os.walk(self._root):
            rel = os.path.relpath(dirpath, self._root)
            depth = 0 if rel == "." else rel.count(os.sep) + 1
            if depth > 3:
                dirnames.clear()
                continue
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for f in filenames:
                if f in targets or f.endswith("App.swift"):
                    results.append(os.path.join(rel, f) if rel != "." else f)
            # xcodeproj / xcworkspace
            for d in list(dirnames):
                if d.endswith(".xcodeproj") or d.endswith(".xcworkspace"):
                    results.append(os.path.join(rel, d) if rel != "." else d)
            if len(results) >= 7:
                break
        return results

    def _find_android_key_files(self) -> List[str]:
        """Find Android-specific key files up to depth 5."""
        targets = {"AndroidManifest.xml", "MainActivity.kt", "MainApplication.kt"}
        results: List[str] = []
        for dirpath, dirnames, filenames in os.walk(self._root):
            rel = os.path.relpath(dirpath, self._root)
            depth = 0 if rel == "." else rel.count(os.sep) + 1
            if depth > 5:
                dirnames.clear()
                continue
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for f in filenames:
                if f in targets:
                    results.append(os.path.join(rel, f) if rel != "." else f)
            if len(results) >= 3:
                break
        return results

    # ── git info ─────────────────────────────────────────────────────────

    def _get_git_info(self) -> Dict[str, str]:
        """Return git branch, remote URL, and short status."""
        info: Dict[str, str] = {}

        info["git_branch"] = self._git("branch", "--show-current")
        info["git_status"] = self._git("status", "--short")
        info["git_remote_url"] = self._git("remote", "get-url", "origin")

        # Recent commits (last 5, one-line format)
        log = self._git("log", "--oneline", "-5")
        if log:
            info["recent_commits"] = log

        return info

    def _git(self, *args: str) -> str:
        """Run a git command in the project root and return stripped stdout."""
        try:
            result = subprocess.run(
                ["git", *args],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=str(self._root),
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (subprocess.SubprocessError, OSError):
            pass
        return ""

    # ── dependencies ─────────────────────────────────────────────────────

    def _get_dependencies_summary(self, project_type: str) -> str:
        """Read a summary of project dependencies."""
        base_type = project_type.split("/")[0]
        root = self._root

        if base_type == "python":
            return self._python_deps(root)
        if base_type == "node":
            return self._node_deps(root)
        if base_type == "flutter":
            return self._flutter_deps(root)
        if base_type == "ios":
            return self._ios_deps(root)
        if base_type == "android":
            return self._android_deps(root)
        if base_type == "rust":
            return self._read_head(root / "Cargo.toml", 60)
        if base_type == "go":
            return self._read_head(root / "go.mod", 60)

        return ""

    def _python_deps(self, root: Path) -> str:
        req = root / "requirements.txt"
        if req.is_file():
            return self._read_head(req, 60)
        pyproject = root / "pyproject.toml"
        if pyproject.is_file():
            try:
                text = pyproject.read_text(errors="replace")
                idx = text.find("[project]\n")
                deps_idx = text.find("dependencies", idx if idx >= 0 else 0)
                if deps_idx >= 0:
                    chunk = text[deps_idx : deps_idx + 2000]
                    lines = chunk.splitlines()[:60]
                    return "\n".join(lines)
            except OSError:
                pass
        return ""

    def _node_deps(self, root: Path) -> str:
        import json as _json

        pkg = root / "package.json"
        if not pkg.is_file():
            return ""
        try:
            data = _json.loads(pkg.read_text(errors="replace"))
            parts: List[str] = []
            deps = data.get("dependencies", {})
            if deps:
                items = [f"{k}@{v}" for k, v in list(deps.items())[:40]]
                parts.append("deps: " + ", ".join(items))
            dev = data.get("devDependencies", {})
            if dev:
                items = [f"{k}@{v}" for k, v in list(dev.items())[:20]]
                parts.append("devDeps: " + ", ".join(items))
            return "\n".join(parts)
        except (OSError, ValueError):
            return ""

    def _flutter_deps(self, root: Path) -> str:
        return self._read_head(root / "pubspec.yaml", 50)

    def _ios_deps(self, root: Path) -> str:
        parts: List[str] = []
        spm = root / "Package.swift"
        if spm.is_file():
            try:
                text = spm.read_text(errors="replace")
                lines = [
                    ln.strip()
                    for ln in text.splitlines()
                    if ".package(" in ln or ".product(" in ln
                ][:20]
                if lines:
                    parts.append("=== Swift Package Manager ===")
                    parts.extend(lines)
            except OSError:
                pass
        podfile = root / "Podfile"
        if podfile.is_file():
            try:
                text = podfile.read_text(errors="replace")
                lines = [
                    ln.strip()
                    for ln in text.splitlines()
                    if ln.strip().startswith("pod ")
                ][:30]
                if lines:
                    parts.append("=== CocoaPods ===")
                    parts.extend(lines)
            except OSError:
                pass
        return "\n".join(parts)

    def _android_deps(self, root: Path) -> str:
        parts: List[str] = []
        for name in ("build.gradle", "build.gradle.kts", "app/build.gradle", "app/build.gradle.kts"):
            gradle = root / name
            if gradle.is_file():
                try:
                    text = gradle.read_text(errors="replace")
                    lines = [
                        ln.strip()
                        for ln in text.splitlines()
                        if any(
                            kw in ln
                            for kw in (
                                "implementation",
                                "api(",
                                "api ",
                                "kapt",
                                "ksp",
                                "annotationProcessor",
                            )
                        )
                    ][:30]
                    if lines:
                        parts.append(f"=== {name} ===")
                        parts.extend(lines)
                except OSError:
                    pass
        return "\n".join(parts)

    # ── project rules ────────────────────────────────────────────────────

    def _read_project_rules(self) -> str:
        """Read project rules (max 300 lines total).

        Sources, concatenated in order:
          1. The first legacy single-file rule (`.claude-project`,
             `CLAUDE.md`, or `.agent-rules`).
          2. Every `.turia/rules/*.md` — populated by skill `install-rules`
             commands from marketplace packs.
        """
        max_lines = 300
        collected: List[str] = []

        for name in _RULES_FILES:
            candidate = self._root / name
            if candidate.is_file():
                try:
                    collected.extend(candidate.read_text(errors="replace").splitlines())
                except OSError:
                    pass
                break

        rules_dir = self._root / ".turia" / "rules"
        if rules_dir.is_dir():
            for rule_file in sorted(rules_dir.glob("*.md")):
                if len(collected) >= max_lines:
                    break
                try:
                    collected.append(f"# {rule_file.name}")
                    collected.extend(rule_file.read_text(errors="replace").splitlines())
                except OSError:
                    pass

        return "\n".join(collected[:max_lines])

    # ── utility ──────────────────────────────────────────────────────────

    @staticmethod
    def _read_head(path: Path, max_lines: int = 60) -> str:
        """Read up to *max_lines* from a file."""
        if not path.is_file():
            return ""
        try:
            lines = path.read_text(errors="replace").splitlines()[:max_lines]
            return "\n".join(lines)
        except OSError:
            return ""
