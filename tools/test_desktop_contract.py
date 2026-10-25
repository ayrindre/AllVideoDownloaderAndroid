#!/usr/bin/env python3
"""Regression test — pywebview js_api introspection contract.

pywebview's `inject_pywebview` walks EVERY public (non-underscore) attribute of
the js_api object recursively (webview/util.py::get_functions) to build the JS
bridge. A public attribute that holds a window/native/CLR object graph makes it
descend into WinForms accessibility internals where `Rectangle.Empty` returns a
fresh instance per access — id()-based dedupe fails and the injection thread
drowns in `window.native.AccessibilityObject.Bounds.Empty…` recursion floods
(the frameless window then never receives `pywebview.api` and looks frozen).

So: js_api classes may only expose plain methods. This test enforces that.

Run:  python tools/test_desktop_contract.py
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BRIDGE = ROOT / "webfinder" / "desktop" / "window.py"


def test_no_public_data_attributes_via_ast() -> None:
    """Even without pywebview installed: the bridge must not *assign* any
    public instance attribute (self.<name> = …) — only self._private."""
    tree = ast.parse(BRIDGE.read_text(encoding="utf-8"))
    offenders: list[str] = []
    for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name.endswith("Bridge")):
        for node in ast.walk(cls):
            if isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if (isinstance(tgt, ast.Attribute) and isinstance(tgt.value, ast.Name)
                            and tgt.value.id == "self" and not tgt.attr.startswith("_")):
                        offenders.append(f"{cls.name}.{tgt.attr}")
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Attribute):
                t = node.target
                if (isinstance(t.value, ast.Name) and t.value.id == "self"
                        and not t.attr.startswith("_")):
                    offenders.append(f"{cls.name}.{t.attr}")
        # class-level public data attributes (methods are FunctionDef, fine)
        for stmt in cls.body:
            if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                tgts = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                for t in tgts:
                    if isinstance(t, ast.Name) and not t.id.startswith("_"):
                        offenders.append(f"{cls.name}.{t.id} (class-level)")
    assert not offenders, f"public attrs on js_api bridge would be scanned by pywebview: {offenders}"


def test_pywebview_scan_completes_cleanly() -> None:
    """With pywebview installed, run its REAL get_functions over our bridge."""
    try:
        import inspect
        import logging
        import textwrap

        import webview.util  # type: ignore
    except ImportError:
        print("  (pywebview not installed — skipped live scan)")
        return

    src = inspect.getsource(webview.util.inject_pywebview)
    tree = ast.parse(textwrap.dedent(src))
    fn = next(n for n in tree.body[0].body
              if isinstance(n, ast.FunctionDef) and n.name == "get_functions")
    code = textwrap.dedent(ast.get_source_segment(src, fn))

    errors: list[str] = []

    class Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            errors.append(record.getMessage())

    logger = logging.getLogger("contract-test")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(Collector())

    ns: dict = {"inspect": inspect, "logger": logger, "exposed_objects": [],
                "get_args": lambda f: list(inspect.getfullargspec(f).args)}
    exec(code, ns)

    from webfinder.desktop.window import DesktopBridge  # noqa: E402

    old_limit = sys.getrecursionlimit()
    sys.setrecursionlimit(1200)
    try:
        fns = ns["get_functions"](DesktopBridge())
    finally:
        sys.setrecursionlimit(old_limit)

    assert not errors, f"pywebview scan logged errors on the bridge: {errors[:3]}"
    assert sorted(fns) == ["close", "is_maximized", "minimize", "pick_folder",
                      "toggle_maximize"], fns


if __name__ == "__main__":
    test_no_public_data_attributes_via_ast()
    print("PASS · js_api bridge exposes no public data attributes")
    test_pywebview_scan_completes_cleanly()
    print("PASS · pywebview get_functions scan clean")
    print("OK")
