"""UI safety tests — catch property-vs-method confusion and other common
rendering bugs BEFORE they hit users at runtime.

Run: python3 scripts/agent/tests/test_ui_safety.py

History: on 2026-04-12 a bug shipped to v0.0.346 where
SSERenderer._handle_internal_call called spinner.is_running() with
parentheses — but is_running is a @property, not a method. The result
was ``'bool' object is not callable`` in production. These tests exist
to prevent that class of bug from recurring.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_spinner_is_running_is_property():
    """Spinner.is_running MUST be a property, not a method.

    Any code that calls spinner.is_running() instead of spinner.is_running
    will get 'bool' object is not callable at runtime. This test ensures
    the property decorator is present so code review and grep can trust
    the convention.
    """
    from turia_chat.driving.ui.spinner import Spinner

    # Verify it's a property descriptor on the CLASS
    attr = getattr(Spinner, "is_running", None)
    assert isinstance(attr, property), (
        f"Spinner.is_running should be a @property, got {type(attr).__name__}. "
        "If it was changed to a regular method, update ALL callers to add () "
        "— or better, keep it as a @property for consistency."
    )

    # Verify accessing on an INSTANCE returns a bool (not raises)
    s = Spinner()
    val = s.is_running  # no parentheses — this is the correct way
    assert isinstance(val, bool), f"Expected bool, got {type(val).__name__}"


def test_renderer_handle_internal_call_does_not_crash():
    """SSERenderer._handle_internal_call must not crash on a valid event.

    This is the exact code path that triggered the is_running() bug in
    v0.0.346. If this test passes, the renderer can handle internal_call
    events without blowing up.
    """
    from turia_chat.domain.entities.sse_event import InternalCallEvent
    from turia_chat.driving.ui.renderer import SSERenderer

    renderer = SSERenderer()
    event = InternalCallEvent(
        caller="compaction",
        model_id="claude-opus-4-6",
        input_tokens=2784,
        output_tokens=1099,
        cache_creation_tokens=0,
        cache_read_tokens=0,
        cost=0.041395,
    )

    # Should NOT raise 'bool' object is not callable (or anything else)
    try:
        renderer.render(event)
    except TypeError as e:
        if "not callable" in str(e):
            raise AssertionError(
                f"Renderer crashed with '{e}'. This is the exact bug from "
                f"v0.0.346 — someone is calling a @property as a method. "
                f"Check for spinner.is_running() vs spinner.is_running."
            ) from e
        raise


def test_extract_edit_summary():
    """_extract_edit_summary returns modified lines from edit_file output."""
    from turia_chat.driving.ui.tool_display import _extract_edit_summary

    # edit_file output with post-edit context
    output = (
        "Archivo editado: foo.py (+1/-0 lineas, 1 coincidencia(s))\n"
        "\n"
        "Contexto post-edit (foo.py):\n"
        "  (lineas 5-10 de 20, '>' marca las lineas modificadas)\n"
        " 5   x = 1\n"
        " 6   y = 2\n"
        " 7 > z = x + y\n"
        " 8 > print(z)\n"
        " 9   return\n"
    )
    result = _extract_edit_summary(output)
    assert len(result) == 2, f"Expected 2 modified lines, got {len(result)}: {result}"
    assert "z = x + y" in result[0]
    assert "print(z)" in result[1]

    # write_file output (no post-edit context, just header + nothing)
    output2 = "Archivo creado: bar.py (42 lineas)\n"
    result2 = _extract_edit_summary(output2)
    assert result2 == [], f"Expected empty for write_file without content, got {result2}"


if __name__ == "__main__":
    tests = [
        test_spinner_is_running_is_property,
        test_renderer_handle_internal_call_does_not_crash,
        test_extract_edit_summary,
    ]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"PASS: {t.__name__}")
        except (AssertionError, Exception) as e:
            print(f"FAIL: {t.__name__}\n      {e}")
            failures += 1
    print(f"\n{len(tests) - failures}/{len(tests)} passing")
    sys.exit(0 if failures == 0 else 1)
