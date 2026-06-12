"""Cross-platform compatibility tests.

Catches common issues before they break on Linux:
- f-string backslashes (Python 3.10 incompatible)
- Platform-specific imports without fallbacks
- Hardcoded Mac-only paths
- ripgrep flag compatibility

Run: python3 scripts/agent/tests/test_compatibility.py
"""

import ast
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

TURIA_ROOT = os.path.join(os.path.dirname(__file__), "..", "turia_chat")


def find_python_files():
    """Find all Python files in the project."""
    files = []
    for root, dirs, filenames in os.walk(TURIA_ROOT):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in filenames:
            if f.endswith(".py"):
                files.append(os.path.join(root, f))
    return sorted(files)


def test_no_fstring_backslash():
    """Python 3.10 doesn't allow backslashes inside f-string expressions."""
    issues = []
    # Pattern: f"...{expression_with_backslash}..."
    # This catches: f"{'\\n'.join(x)}" but NOT f"text\nmore{var}"
    pattern = re.compile(r"""f['"].*\{[^}]*\\[^}]*\}""")

    for filepath in find_python_files():
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for lineno, line in enumerate(f, 1):
                    if pattern.search(line):
                        rel = os.path.relpath(filepath, TURIA_ROOT)
                        issues.append(f"{rel}:{lineno}: {line.strip()[:80]}")
        except Exception:
            pass

    return issues


def test_no_walrus_operator_310():
    """Check for walrus operator in contexts that might confuse 3.10."""
    # This is a soft check — walrus is fine in 3.10 but just flagging for awareness
    return []  # walrus is fine in 3.10+


def test_no_match_statement():
    """Python 3.10+ has match/case but we should avoid for 3.9 compat if needed."""
    issues = []
    pattern = re.compile(r'^\s*match\s+\w+\s*:')

    for filepath in find_python_files():
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for lineno, line in enumerate(f, 1):
                    if pattern.match(line):
                        rel = os.path.relpath(filepath, TURIA_ROOT)
                        issues.append(f"{rel}:{lineno}: match statement (Python 3.10+)")
        except Exception:
            pass

    return issues


def test_no_hardcoded_mac_paths():
    """Check for hardcoded macOS-only paths."""
    issues = []
    mac_patterns = [
        re.compile(r'/opt/homebrew/'),
        re.compile(r'/Applications/'),
        re.compile(r'~/Library/'),
    ]
    # Exclude platform-detection files
    exclude = {"os_notify.py", "auth_service.py", "container.py", "image_detector.py"}

    for filepath in find_python_files():
        if os.path.basename(filepath) in exclude:
            continue
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for lineno, line in enumerate(f, 1):
                    if line.strip().startswith("#"):
                        continue
                    for pat in mac_patterns:
                        if pat.search(line):
                            rel = os.path.relpath(filepath, TURIA_ROOT)
                            issues.append(f"{rel}:{lineno}: {line.strip()[:80]}")
                            break
        except Exception:
            pass

    return issues


def test_no_subprocess_without_timeout():
    """Check that subprocess calls have timeouts to prevent hangs."""
    issues = []
    # Look for subprocess.run or create_subprocess without timeout
    pattern_run = re.compile(r'subprocess\.run\(')
    pattern_no_timeout = re.compile(r'subprocess\.run\([^)]*\)\s*$')

    for filepath in find_python_files():
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
                # Simple heuristic: find subprocess.run calls without timeout=
                for match in pattern_run.finditer(content):
                    # Get the full call (rough: find matching paren)
                    start = match.start()
                    # Check next 500 chars for timeout=
                    snippet = content[start:start + 500]
                    paren_end = snippet.find(")")
                    if paren_end > 0:
                        # Look further for multiline calls
                        extended = content[start:start + 1000]
                        next_paren = extended.find(")")
                        call = extended[:next_paren + 1] if next_paren > 0 else snippet[:paren_end + 1]
                        if "timeout" not in call and "capture_output" in call:
                            lineno = content[:start].count("\n") + 1
                            rel = os.path.relpath(filepath, TURIA_ROOT)
                            issues.append(f"{rel}:{lineno}: subprocess.run without timeout")
        except Exception:
            pass

    return issues


def test_ripgrep_flags():
    """Check that ripgrep flags are cross-platform compatible."""
    issues = []
    # Known incompatible flags
    bad_flags = [
        ("--binary-file", "--no-binary"),
        ("--sort=", "--sort <value>"),
    ]

    for filepath in find_python_files():
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for lineno, line in enumerate(f, 1):
                    for bad, good in bad_flags:
                        if bad in line and not line.strip().startswith("#"):
                            rel = os.path.relpath(filepath, TURIA_ROOT)
                            issues.append(f"{rel}:{lineno}: '{bad}' → use '{good}'")
        except Exception:
            pass

    return issues


def test_python_version_compat():
    """Check minimum Python version compatibility."""
    version = sys.version_info
    issues = []
    if version < (3, 10):
        issues.append(f"Python {version.major}.{version.minor} — minimum 3.10 required")
    return issues


def run_all():
    """Run all compatibility tests."""
    tests = [
        ("f-string backslash (Python 3.10)", test_no_fstring_backslash),
        ("match statement (Python 3.10+)", test_no_match_statement),
        ("Hardcoded Mac paths", test_no_hardcoded_mac_paths),
        ("Subprocess without timeout", test_no_subprocess_without_timeout),
        ("Ripgrep flag compatibility", test_ripgrep_flags),
        ("Python version", test_python_version_compat),
    ]

    total_issues = 0

    for name, test_fn in tests:
        issues = test_fn()
        if issues:
            print(f"  \033[33m⚠\033[0m {name} — {len(issues)} issue(s)")
            for issue in issues[:5]:
                print(f"    {issue}")
            if len(issues) > 5:
                print(f"    ... and {len(issues) - 5} more")
            total_issues += len(issues)
        else:
            print(f"  \033[32m✓\033[0m {name}")

    print()
    if total_issues:
        print(f"  Results: {total_issues} compatibility warnings found")
    else:
        print(f"  Results: All compatibility checks passed")

    return total_issues == 0


if __name__ == "__main__":
    print()
    print("  Running compatibility tests...")
    print()
    ok = run_all()
    sys.exit(0 if ok else 1)
