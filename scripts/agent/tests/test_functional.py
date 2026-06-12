"""Functional end-to-end tests with minimal mocking.

Only the HTTP layer is mocked. Everything else runs for real:
commands, tool orchestrator, file operations, permission modes,
memory system, header rendering, etc.

Run: python3 scripts/agent/tests/test_functional.py
"""

import asyncio
import io
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from turia_chat.domain.entities.tool_call import ToolCall
from turia_chat.domain.entities.permission_mode import PermissionMode
from turia_chat.driven.tools.local_executor import LocalToolExecutor
from turia_chat.driven.tools.path_validator import PathValidator
from turia_chat.driven.tools.file_backup import FileBackup
from turia_chat.driven.memory.local_memory import LocalMemory, MEMORY_DIR
from turia_chat.driving.cli.commands import SlashCommandRegistry, CommandResult


# ── Test infrastructure ─────────────────────────────────────────────

class TestProject:
    """Creates a real temp project with git, files, etc."""

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="turia_func_test_")

        # Create project structure
        for d in ["src", "tests", "src/models", "src/views"]:
            os.makedirs(os.path.join(self.root, d), exist_ok=True)

        # Create files
        self._write("src/app.py", (
            "import os\n\n"
            "class Application:\n"
            "    def __init__(self):\n"
            "        self.name = 'test'\n\n"
            "    def run(self):\n"
            "        print('running')\n"
        ))
        self._write("src/models/user.py", (
            "from dataclasses import dataclass\n\n"
            "@dataclass\n"
            "class User:\n"
            "    name: str\n"
            "    email: str\n\n"
            "class UserRepository:\n"
            "    def get_by_id(self, id: int) -> User:\n"
            "        pass\n"
        ))
        self._write("src/views/home.py", (
            "from src.models.user import User\n\n"
            "def render_home(user: User) -> str:\n"
            "    return f'Hello {user.name}'\n"
        ))
        self._write("tests/test_app.py", (
            "def test_app():\n    assert True\n"
        ))
        self._write("README.md", "# Test Project\n")
        self._write("requirements.txt", "flask\nrequests\n")

        # Init git
        os.system(f"cd {self.root} && git init -q && git add -A && git commit -q -m 'init' 2>/dev/null")

    def _write(self, path, content):
        full = os.path.join(self.root, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(content)

    def read(self, path):
        with open(os.path.join(self.root, path)) as f:
            return f.read()

    def exists(self, path):
        return os.path.exists(os.path.join(self.root, path))

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)


class TestSession:
    """Wires up real components for testing."""

    def __init__(self, project: TestProject):
        self.project = project
        self.validator = PathValidator(project.root)
        self.backup = FileBackup()
        self.executor = LocalToolExecutor(self.validator, self.backup)

    async def tool(self, name: str, inp: dict) -> tuple:
        """Execute a tool, return (success, output)."""
        tc = ToolCall(id=f"t_{name}", name=name, input=inp)
        result = await self.executor.execute(tc)
        return result.success, result.output


# ── Functional tests ────────────────────────────────────────────────

async def test_full_file_workflow():
    """Test: read → edit → verify → undo → verify."""
    proj = TestProject()
    sess = TestSession(proj)

    # 1. Read file
    ok, out = await sess.tool("read_file", {"path": "src/app.py"})
    assert ok, f"read_file failed: {out}"
    assert "class Application" in out, "Should contain class"

    # 2. Edit file
    ok, out = await sess.tool("edit_file", {
        "path": "src/app.py",
        "old_string": "self.name = 'test'",
        "new_string": "self.name = 'turia'",
    })
    assert ok, f"edit_file failed: {out}"

    # 3. Verify edit
    ok, out = await sess.tool("read_file", {"path": "src/app.py"})
    assert ok
    assert "self.name = 'turia'" in out, "Edit should be applied"
    assert "self.name = 'test'" not in out, "Old content should be gone"

    # 4. Undo
    ok, out = await sess.tool("undo_edit", {"path": "src/app.py"})
    assert ok, f"undo failed: {out}"

    # 5. Verify undo
    ok, out = await sess.tool("read_file", {"path": "src/app.py"})
    assert ok
    assert "self.name = 'test'" in out, "Undo should restore original"

    proj.cleanup()
    return True


async def test_edit_replace_all():
    """Test: replace_all replaces every occurrence."""
    proj = TestProject()
    sess = TestSession(proj)

    ok, out = await sess.tool("edit_file", {
        "path": "src/models/user.py",
        "old_string": "User",
        "new_string": "Person",
        "replace_all": True,
    })
    assert ok, f"edit failed: {out}"

    content = proj.read("src/models/user.py")
    assert "User" not in content, "All 'User' should be replaced"
    assert "Person" in content, "Should contain 'Person'"
    assert content.count("Person") >= 3, f"Should have 3+ occurrences, got {content.count('Person')}"

    proj.cleanup()
    return True


async def test_write_new_file_and_move():
    """Test: write new file → move it → verify."""
    proj = TestProject()
    sess = TestSession(proj)

    # Write new file
    ok, out = await sess.tool("write_file", {
        "path": "src/new_module.py",
        "content": "def hello():\n    return 'world'\n",
    })
    assert ok, f"write failed: {out}"
    assert proj.exists("src/new_module.py")

    # Move it
    ok, out = await sess.tool("move_file", {
        "source": "src/new_module.py",
        "destination": "src/views/new_module.py",
    })
    assert ok, f"move failed: {out}"
    assert not proj.exists("src/new_module.py"), "Source should not exist"
    assert proj.exists("src/views/new_module.py"), "Dest should exist"

    # Read moved file
    ok, out = await sess.tool("read_file", {"path": "src/views/new_module.py"})
    assert ok
    assert "def hello" in out

    proj.cleanup()
    return True


async def test_search_all_modes():
    """Test: search_code in content, files_with_matches, count modes."""
    proj = TestProject()
    sess = TestSession(proj)

    # Content mode
    ok, out = await sess.tool("search_code", {
        "query": "class",
        "output_mode": "content",
        "head_limit": 10,
    })
    assert ok, f"content search failed: {out}"
    assert "class" in out.lower()

    # Files mode
    ok, out = await sess.tool("search_code", {
        "query": "class",
        "output_mode": "files_with_matches",
    })
    assert ok
    assert "app.py" in out or "user.py" in out

    # Count mode
    ok, out = await sess.tool("search_code", {
        "query": "import",
        "output_mode": "count",
    })
    assert ok

    proj.cleanup()
    return True


async def test_grep_advanced():
    """Test: grep with case insensitive, file type, context."""
    proj = TestProject()
    sess = TestSession(proj)

    # Case insensitive
    ok, out = await sess.tool("grep", {
        "pattern": "APPLICATION",
        "case_insensitive": True,
        "output_mode": "files_with_matches",
    })
    assert ok
    assert "app.py" in out, "Should find Application case-insensitive"

    # With context
    ok, out = await sess.tool("grep", {
        "pattern": "def run",
        "output_mode": "content",
        "context_after": 2,
    })
    assert ok
    assert "print" in out, "Context should show the print line after def run"

    proj.cleanup()
    return True


async def test_symbols_and_definitions():
    """Test: symbols extracts classes/functions, find_definition finds them."""
    proj = TestProject()
    sess = TestSession(proj)

    # Symbols
    ok, out = await sess.tool("symbols", {"path": "src/models/user.py"})
    assert ok, f"symbols failed: {out}"
    assert "class" in out.lower()
    assert "User" in out
    assert "UserRepository" in out

    # Find definition
    ok, out = await sess.tool("find_definition", {"symbol": "Application"})
    assert ok
    assert "app.py" in out, "Should find Application in app.py"

    # Find references
    ok, out = await sess.tool("find_references", {"symbol": "User"})
    assert ok
    assert "user.py" in out, "Should find User in user.py"

    proj.cleanup()
    return True


async def test_find_and_replace_across_files():
    """Test: find_and_replace modifies multiple files."""
    proj = TestProject()
    sess = TestSession(proj)

    # Replace 'User' with 'Account' across project
    ok, out = await sess.tool("find_and_replace", {
        "search": "User",
        "replace": "Account",
        "file_pattern": "*.py",
    })
    assert ok, f"find_and_replace failed: {out}"
    assert "archivos modificados" in out

    # Verify in both files
    user_content = proj.read("src/models/user.py")
    assert "Account" in user_content
    assert "User" not in user_content

    home_content = proj.read("src/views/home.py")
    assert "Account" in home_content

    proj.cleanup()
    return True


async def test_git_operations():
    """Test: git_info and file_diff work correctly."""
    proj = TestProject()
    sess = TestSession(proj)

    # Status (clean repo)
    ok, out = await sess.tool("git_info", {"type": "status"})
    assert ok

    # Make a change
    await sess.tool("edit_file", {
        "path": "README.md",
        "old_string": "# Test Project",
        "new_string": "# Modified Project",
    })

    # Diff
    ok, out = await sess.tool("file_diff", {"path": "README.md"})
    assert ok
    assert "Modified" in out or "Test" in out, "Diff should show changes"

    # Log
    ok, out = await sess.tool("git_info", {"type": "log"})
    assert ok
    assert "init" in out, "Should show init commit"

    # Branch
    ok, out = await sess.tool("git_info", {"type": "branch"})
    assert ok

    proj.cleanup()
    return True


async def test_run_command():
    """Test: run_command executes and captures output."""
    proj = TestProject()
    sess = TestSession(proj)

    ok, out = await sess.tool("run_command", {"command": "echo 'hello turia'"})
    assert ok, f"run failed: {out}"
    assert "hello turia" in out

    # Command with exit code
    ok, out = await sess.tool("run_command", {"command": "exit 1"})
    assert ok  # Tool succeeds even if command fails
    assert "exit code: 1" in out

    proj.cleanup()
    return True


async def test_permission_modes():
    """Test: auto mode approves everything, plan mode blocks."""
    proj = TestProject()
    sess = TestSession(proj)

    # Default mode is ASK — but with no approval callback, it auto-approves
    assert sess.executor.permission_mode == PermissionMode.ASK

    # Switch to AUTO
    sess.executor.set_permission_mode(PermissionMode.AUTO)
    assert sess.executor.permission_mode == PermissionMode.AUTO

    ok, out = await sess.tool("write_file", {"path": "auto_test.txt", "content": "auto mode"})
    assert ok, "AUTO mode should approve writes"

    # Switch to PLAN
    sess.executor.set_permission_mode(PermissionMode.PLAN)
    assert sess.executor.permission_mode == PermissionMode.PLAN

    ok, out = await sess.tool("write_file", {"path": "plan_test.txt", "content": "plan mode"})
    assert not ok, "PLAN mode should block writes"
    assert "PLAN" in out, "Should indicate PLAN mode blocked"
    assert not proj.exists("plan_test.txt"), "File should not be created in PLAN mode"

    proj.cleanup()
    return True


async def test_read_file_offset_limit():
    """Test: offset/limit returns correct line range."""
    proj = TestProject()
    sess = TestSession(proj)

    # Read full file
    ok, full = await sess.tool("read_file", {"path": "src/app.py"})
    assert ok
    full_lines = full.strip().split("\n")

    # Read with offset
    ok, partial = await sess.tool("read_file", {"path": "src/app.py", "offset": 3, "limit": 2})
    assert ok
    partial_lines = partial.strip().split("\n")
    assert len(partial_lines) == 2, f"Should have 2 lines, got {len(partial_lines)}"
    assert "3" in partial_lines[0][:6], "First line should be line 3"

    proj.cleanup()
    return True


async def test_memory_lifecycle():
    """Test: remember → memories → forget lifecycle."""
    # Use a temp memory dir to not pollute real config
    test_mem_dir = tempfile.mkdtemp(prefix="turia_mem_test_")
    import turia_chat.driven.memory.local_memory as mem_mod
    original_dir = mem_mod.MEMORY_DIR
    original_index = mem_mod.MEMORY_INDEX
    mem_mod.MEMORY_DIR = __import__("pathlib").Path(test_mem_dir)
    mem_mod.MEMORY_INDEX = mem_mod.MEMORY_DIR / "MEMORY.md"

    try:
        mem = LocalMemory()

        # Save
        path = mem.save_memory("test preference", "Always use tabs", "feedback")
        assert os.path.exists(path), "Memory file should exist"

        # List
        memories = mem.list_memories()
        assert len(memories) >= 1, "Should have at least 1 memory"
        assert any("test preference" in m["name"] for m in memories)

        # Get all (for system prompt injection)
        content = mem.get_all_memories()
        assert "Always use tabs" in content, "Memory content should be retrievable"

        # Delete
        filename = memories[0]["file"]
        deleted = mem.delete_memory(filename)
        assert deleted, "Should delete successfully"

        # Verify deleted
        memories_after = mem.list_memories()
        assert len(memories_after) == 0, "Should have no memories after delete"
    finally:
        mem_mod.MEMORY_DIR = original_dir
        mem_mod.MEMORY_INDEX = original_index
        shutil.rmtree(test_mem_dir, ignore_errors=True)

    return True


async def test_slash_commands():
    """Test: slash command registry dispatches correctly."""
    from turia_chat.application.ports.driven.config_port import ConfigPort

    # Minimal mock for config
    class MockConfig:
        def get_config(self):
            from turia_chat.domain.entities.config import AppConfig
            return AppConfig(preferred_model="auto")
        def set_config(self, k, v): pass
        def get_project_conversation(self): return None
        def set_project_conversation(self, v): pass
        def clear_project_conversation(self): pass

    class MockClipboard:
        def copy(self, text): pass

    class MockAuth:
        async def ensure_valid_token(self): pass
        def get_config(self):
            from turia_chat.domain.entities.config import AppConfig
            return AppConfig()

    class MockApi:
        pass

    class MockSubagent:
        async def list_subagents(self): return []

    registry = SlashCommandRegistry(
        config_port=MockConfig(),
        clipboard_port=MockClipboard(),
        auth_service=MockAuth(),
        api_client=MockApi(),
        subagent_service=MockSubagent(),
        get_last_response=lambda: "",
        get_total_cost=lambda: 0.0,
    )

    # Test basic commands (dispatch takes full input string with /)
    result = registry.dispatch("/help")
    assert result.handled, "/help should be handled"
    assert result.output, "/help should produce output"

    result = registry.dispatch("/new")
    assert result.handled
    assert result.action == "new_conversation"

    result = registry.dispatch("/mode auto")
    assert result.handled
    assert result.action == "change_mode"
    assert result.action_data == "auto"

    result = registry.dispatch("/mode invalid")
    assert result.handled
    assert "auto" in result.output.lower() or "ask" in result.output.lower()

    result = registry.dispatch("/commit fix: test")
    assert result.handled
    assert result.action == "commit_with_message"
    assert result.action_data == "fix: test"

    result = registry.dispatch("/review")
    assert result.handled
    assert result.action == "review_changes"

    result = registry.dispatch("/context")
    assert result.handled
    assert result.action == "show_context"

    result = registry.dispatch("/changes")
    assert result.handled
    assert result.action == "show_changes"

    result = registry.dispatch("/analyze")
    assert result.handled
    assert result.action == "analyze_architecture"

    result = registry.dispatch("/nonexistent")
    assert result.handled, "Unknown command should be handled (with error message)"
    assert "desconocido" in result.output.lower(), "Should show unknown command message"

    return True


async def test_header_rendering():
    """Test: header renders all data without crashing."""
    from turia_chat.driving.ui.header import SessionHeader

    header = SessionHeader()

    # Capture stderr (where Rich writes)
    old_stderr = sys.stderr
    sys.stderr = io.StringIO()

    try:
        # Full header with all data
        header.show(
            project_name="test-project",
            conversation_id=42,
            rag_info={
                "has_index": True,
                "total_chunks": 1500,
                "last_indexed_at": "2026-04-01T00:00:00",
                "linked_projects": [
                    {"name": "backend", "mention": "@back", "status": "ready",
                     "last_indexed_at": "2026-04-01"},
                ],
            },
            broadcast_messages=[
                {"id": 1, "message": "Test broadcast", "message_type": "info"},
            ],
            active_skill="Python Rudo",
        )
        output = sys.stderr.getvalue()
        assert "test-project" in output, "Project name missing"
        assert "42" in output, "Conversation ID missing"
        assert "1500" in output, "Chunk count missing"
        assert "@back" in output, "Linked project missing"
        assert "Test broadcast" in output, "Broadcast missing"
        assert "Python Rudo" in output, "Skill missing"

        # Minimal header
        sys.stderr = io.StringIO()
        header.show(project_name="minimal")
        output = sys.stderr.getvalue()
        assert "minimal" in output

        # Header with no RAG
        sys.stderr = io.StringIO()
        header.show(
            project_name="no-rag",
            rag_info={"status": "pending"},
        )
        output = sys.stderr.getvalue()
        assert "pendiente" in output

    finally:
        sys.stderr = old_stderr

    return True


async def test_web_fetch():
    """Test: web_fetch handles URLs (tolerant to network/env issues)."""
    proj = TestProject()
    sess = TestSession(proj)

    ok, out = await sess.tool("web_fetch", {"url": "https://httpbin.org/get"})
    # Tool always returns success=True (errors in output text)
    # Just verify it didn't crash and returned something
    assert ok, "web_fetch should not crash"
    assert len(out) > 0, "Should return some output"

    proj.cleanup()
    return True


async def test_tool_error_handling():
    """Test: tools handle errors gracefully (no crashes)."""
    proj = TestProject()
    sess = TestSession(proj)

    # Read nonexistent
    ok, out = await sess.tool("read_file", {"path": "does/not/exist.py"})
    assert not ok

    # Edit with wrong old_string
    ok, out = await sess.tool("edit_file", {
        "path": "README.md",
        "old_string": "THIS DOES NOT EXIST",
        "new_string": "replacement",
    })
    assert not ok

    # Move nonexistent
    ok, out = await sess.tool("move_file", {
        "source": "nonexistent.py",
        "destination": "somewhere.py",
    })
    assert not ok

    # Unknown tool
    ok, out = await sess.tool("totally_fake_tool", {"foo": "bar"})
    assert not ok
    assert "desconocida" in out.lower()

    # Empty required params
    ok, out = await sess.tool("read_file", {"path": ""})
    assert not ok

    ok, out = await sess.tool("search_code", {"query": ""})
    assert not ok

    proj.cleanup()
    return True


# ── Runner ──────────────────────────────────────────────────────────

async def run_all():
    tests = [
        ("Full file workflow (read→edit→verify→undo)", test_full_file_workflow),
        ("Edit replace_all", test_edit_replace_all),
        ("Write + move + verify", test_write_new_file_and_move),
        ("Search all modes (content/files/count)", test_search_all_modes),
        ("Grep advanced (case insensitive, context)", test_grep_advanced),
        ("Symbols + find_definition + find_references", test_symbols_and_definitions),
        ("Find and replace across files", test_find_and_replace_across_files),
        ("Git operations (status/diff/log/branch)", test_git_operations),
        ("Run command (echo + exit code)", test_run_command),
        ("Permission modes (auto/ask/plan)", test_permission_modes),
        ("Read file offset/limit", test_read_file_offset_limit),
        ("Memory lifecycle (save/list/get/delete)", test_memory_lifecycle),
        ("Slash commands dispatch", test_slash_commands),
        ("Header rendering (full/minimal/no-rag)", test_header_rendering),
        ("Web fetch (real HTTP)", test_web_fetch),
        ("Tool error handling (graceful failures)", test_tool_error_handling),
    ]

    passed = 0
    failed = 0
    errors = []

    for name, test_fn in tests:
        try:
            result = await test_fn()
            if result:
                print(f"  \033[32m✓\033[0m {name}")
                passed += 1
            else:
                print(f"  \033[31m✗\033[0m {name} — returned False")
                failed += 1
                errors.append(name)
        except AssertionError as e:
            print(f"  \033[31m✗\033[0m {name} — {e}")
            failed += 1
            errors.append(f"{name}: {e}")
        except Exception as e:
            print(f"  \033[31m✗\033[0m {name} — EXCEPTION: {type(e).__name__}: {e}")
            failed += 1
            errors.append(f"{name}: {type(e).__name__}: {e}")

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
    print("  Running functional tests...")
    print()
    ok = asyncio.run(run_all())
    sys.exit(0 if ok else 1)
