"""WebFinder — pywebview desktop host for Windows.

Creates a borderless, hardware-accelerated (WebView2/Chromium) window with
custom traffic-light controls, and exposes a tiny JS API for window control
and native folder picking. Falls back to "open in browser" when pywebview is
not installed, so `python run.py` always works.
"""
from __future__ import annotations

import threading
import time
import urllib.request


class DesktopBridge:
    """Methods reachable from JS as `window.pywebview.api.<name>`.

    ⚠ CRITICAL pywebview contract: pywebview recursively introspects EVERY
    public (non-underscore) attribute of the js_api object to build the JS
    bridge (`webview.util.scan`).  A public attribute holding the native
    window → it walks into the WinForms/COM object graph →
    `window.native.AccessibilityObject.Bounds.Empty.Empty…` → WinForms
    returns a fresh `Rectangle.Empty` instance per access, pywebview's id()
    dedupe fails → infinite recursion → the JS-injection thread dies,
    `_pywebviewready` never fires and the window appears frozen.
    So: the window reference MUST stay private (`_window`). Only expose
    plain methods here — never window/browser/state objects.
    """

    def __init__(self) -> None:
        self._window = None  # MUST be private — see class docstring

    # -- window controls ----------------------------------------------------
    def minimize(self):
        self._window.minimize()

    def toggle_maximize(self):
        if self._window.maximized:
            self._window.restore()
        else:
            self._window.maximize()

    def close(self):
        self._window.destroy()

    # -- native dialogs -------------------------------------------------------
    def pick_folder(self):
        import webview
        selection = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        return selection[0] if selection else ""


_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def wait_for_server(port: int, timeout: float = 15.0) -> bool:
    """Poll /api/meta WITHOUT system proxy — machines that route everything
    through a local proxy would otherwise never see their own localhost."""
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}/api/meta"
    while time.time() < deadline:
        try:
            with _NO_PROXY.open(url, timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except OSError:
            time.sleep(0.15)
    return False


def launch(port: int, host: str) -> bool:
    """Start the uvicorn server in a thread and open the native window.

    Returns False if pywebview is unavailable (caller falls back to browser).
    """
    try:
        import webview  # type: ignore
    except ImportError:
        return False

    import uvicorn
    from ..app import app

    t = threading.Thread(
        target=lambda: uvicorn.run(app, host="127.0.0.1", port=port,
                                   log_level="warning", access_log=False),
        daemon=True,
    )
    t.start()
    if not wait_for_server(port):
        raise RuntimeError("Backend did not come up in time.")

    bridge = DesktopBridge()
    window = webview.create_window(
        title="WebFinder",
        url=f"http://127.0.0.1:{port}",
        js_api=bridge,
        width=1280,
        height=820,
        min_size=(980, 620),
        frameless=True,          # custom titlebar lives in the frontend
        easy_drag=False,         # drag handled by -webkit-app-region CSS
        background_color="#0e0e13",
    )
    bridge._window = window
    # 60fps, no resize flashing on Windows
    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.start(debug=False, gui="edgechromium")
    return True
