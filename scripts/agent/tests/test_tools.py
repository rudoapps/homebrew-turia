"""Automated tests for all tool executors.

Run: python3 -m pytest scripts/agent/tests/test_tools.py -v
Or:  python3 scripts/agent/tests/test_tools.py
"""

import asyncio
import os
import sys
import tempfile
import shutil

# Add project to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from turia_chat.driven.tools.local_executor import LocalToolExecutor
from turia_chat.driven.tools.path_validator import PathValidator
from turia_chat.driven.tools.file_backup import FileBackup
from turia_chat.domain.entities.tool_call import ToolCall


class TestContext:
    """Manages a temp directory for tests."""

    def __init__(self):
        self.tmpdir = tempfile.mkdtemp(prefix="turia_test_")
        self.validator = PathValidator(self.tmpdir)
        self.backup = FileBackup()
        self.executor = LocalToolExecutor(self.validator, self.backup)

        # Create test files
        os.makedirs(os.path.join(self.tmpdir, "src"), exist_ok=True)
        with open(os.path.join(self.tmpdir, "test.py"), "w") as f:
            f.write("class TestClass:\n    def hello(self):\n        return 'world'\n\ndef main():\n    pass\n")
        with open(os.path.join(self.tmpdir, "src", "app.py"), "w") as f:
            f.write("import os\n\nclass App:\n    pass\n")
        with open(os.path.join(self.tmpdir, "README.md"), "w") as f:
            f.write("# Test Project\n\nHello world\n")

        # Init git repo for git tests
        os.system(f"cd {self.tmpdir} && git init -q && git add -A && git commit -q -m 'init'")

    def cleanup(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def run(self, name: str, inp: dict) -> tuple:
        """Execute a tool and return (success, output)."""
        tc = ToolCall(id=f"test_{name}", name=name, input=inp)
        result = await self.executor.execute(tc)
        return result.success, result.output


async def run_tests():
    """Run all tool tests."""
    ctx = TestContext()
    passed = 0
    failed = 0
    errors = []

    tests = [
        # ── File tools ──
        ("read_file: basic", "read_file", {"path": "test.py"}),
        ("read_file: offset/limit", "read_file", {"path": "test.py", "offset": 2, "limit": 2}),
        ("read_file: not found", "read_file", {"path": "nonexistent.py"}),
        ("write_file: create new", "write_file", {"path": "new_file.txt", "content": "hello\nworld\n"}),
        ("read_file: verify write", "read_file", {"path": "new_file.txt"}),
        ("edit_file: replace", "edit_file", {"path": "test.py", "old_string": "return 'world'", "new_string": "return 'turia'"}),
        ("edit_file: replace_all", "edit_file", {"path": "test.py", "old_string": "pass", "new_string": "print('ok')", "replace_all": True}),
        ("edit_file: not found string", "edit_file", {"path": "test.py", "old_string": "NOTHERE", "new_string": "X"}),
        ("move_file", "move_file", {"source": "new_file.txt", "destination": "moved_file.txt"}),
        ("read_file: verify move", "read_file", {"path": "moved_file.txt"}),
        ("undo_edit: restore", "undo_edit", {"path": "test.py"}),

        # ── Search tools ──
        ("list_files: root", "list_files", {"path": "."}),
        ("list_files: pattern", "list_files", {"path": ".", "pattern": "*.py"}),
        ("search_code: basic", "search_code", {"query": "class", "output_mode": "files_with_matches"}),
        ("search_code: content", "search_code", {"query": "def main", "output_mode": "content"}),
        ("search_code: count", "search_code", {"query": "import", "output_mode": "count"}),
        ("search_code: no results", "search_code", {"query": "ZZZZNOTFOUND"}),
        ("grep: basic", "grep", {"pattern": "class", "output_mode": "files_with_matches"}),
        ("grep: case insensitive", "grep", {"pattern": "CLASS", "case_insensitive": True, "output_mode": "files_with_matches"}),

        # ── Code analysis ──
        ("symbols", "symbols", {"path": "test.py"}),
        ("find_definition", "find_definition", {"symbol": "TestClass"}),
        ("find_references", "find_references", {"symbol": "TestClass"}),

        # ── Shell tools ──
        ("git_info: status", "git_info", {"type": "status"}),
        ("git_info: log", "git_info", {"type": "log"}),
        ("git_info: branch", "git_info", {"type": "branch"}),
        ("file_diff", "file_diff", {"path": "test.py"}),
        ("run_command: echo", "run_command", {"command": "echo hello"}),
        ("run_command: timeout", "run_command", {"command": "echo fast", "timeout": 5}),

        # ── Web tools ──
        ("web_fetch", "web_fetch", {"url": "https://httpbin.org/get"}),
    ]

    # Expected failures (should return success=False)
    expected_failures = {
        "read_file: not found",
        "edit_file: not found string",
    }

    for label, name, inp in tests:
        try:
            success, output = await ctx.run(name, inp)

            if label in expected_failures:
                if not success:
                    print(f"  \033[32m✓\033[0m {label} (expected failure)")
                    passed += 1
                else:
                    print(f"  \033[31m✗\033[0m {label} — expected failure but got success")
                    failed += 1
                    errors.append(f"{label}: expected failure")
            else:
                if success:
                    print(f"  \033[32m✓\033[0m {label}")
                    passed += 1
                else:
                    print(f"  \033[31m✗\033[0m {label} — {output[:100]}")
                    failed += 1
                    errors.append(f"{label}: {output[:100]}")
        except Exception as e:
            print(f"  \033[31m✗\033[0m {label} — EXCEPTION: {e}")
            failed += 1
            errors.append(f"{label}: {e}")

    ctx.cleanup()

    print()
    print(f"  Results: {passed} passed, {failed} failed, {passed + failed} total")

    if errors:
        print()
        print("  Failures:")
        for e in errors:
            print(f"    - {e}")

    return failed == 0


if __name__ == "__main__":
    print()
    print("  Running turia tool tests...")
    print()
    ok = asyncio.run(run_tests())
    sys.exit(0 if ok else 1)
