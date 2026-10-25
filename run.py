#!/usr/bin/env python3
"""WebFinder — entry point.

    python run.py                # native frameless window (needs pywebview),
                                 # falls back to the default browser
    python run.py --browser      # force browser mode (UI/UX development)
    python run.py --port 8080    # custom port

Windows users: double-click run.bat instead — it manages the venv for you.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _deps_missing() -> str:
    try:
        import fastapi   # noqa: F401
        import uvicorn    # noqa: F401
        import httpx      # noqa: F401
    except ImportError as exc:
        return exc.name or str(exc)
    return ""


_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _server_alive(url: str) -> bool:
    """Probe localhost WITHOUT the system proxy — proxy-everything setups would
    otherwise hang/not see their own server."""
    try:
        with _NO_PROXY.open(url.rstrip("/") + "/api/meta", timeout=2) as r:
            return r.status == 200
    except OSError:
        return False


def _hold_open() -> None:
    """Keep a process alive while a background thread serves the app."""
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="WebFinder — smart file search & downloader")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--browser", action="store_true",
                        help="serve + open default browser instead of the pywebview window")
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()

    missing = _deps_missing()
    if missing:
        print(f"[webfinder] Python package '{missing}' is not installed for THIS interpreter.")
        print("            You are probably running with the system Python instead of the project venv.")
        print()
        print("  Windows : double-click  run.bat   (creates .venv + installs everything)")
        print("  manual  :  python -m venv .venv")
        print("             .venv\\Scripts\\python.exe -m pip install -r requirements.txt")
        print("             .venv\\Scripts\\python.exe run.py")
        if sys.platform == "win32":
            input("\nPress Enter to exit…")
        sys.exit(1)

    # FFmpeg bootstrap (HLS/DASH capture): the console the launcher owns shows
    # the progress; failures are strictly non-fatal (ffmpeg_tools retries once
    # per stream job anyway). WEBFINDER_NO_FFMPEG_INSTALL=1 opts out.
    try:
        import shutil as _sh
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from webfinder.core import ffmpeg_setup
        bin_dir = Path(__file__).resolve().parent / "bin"
        suf = ".exe" if os.name == "nt" else ""
        on_path = (bool(_sh.which("ffmpeg") and _sh.which("ffprobe"))
                   or bool(_sh.which("ffmpeg.exe") and _sh.which("ffprobe.exe")))
        local = (bin_dir / f"ffmpeg{suf}").exists() and (bin_dir / f"ffprobe{suf}").exists()
        if not (on_path or local):
            if os.environ.get("WEBFINDER_NO_FFMPEG_INSTALL"):
                print("[webfinder] FFmpeg unavailable and auto-install disabled — HLS/DASH capture stays off.")
            else:
                print("[webfinder] FFmpeg missing: auto-installing into the app's bin/ folder "
                      "(opt out with WEBFINDER_NO_FFMPEG_INSTALL=1)…")
                ffmpeg_setup.ensure_ffmpeg(progress=lambda m: print(f"[webfinder]   {m}"))
    except Exception as exc:  # noqa: BLE001 — never let the helper break launch
        print(f"[webfinder] ffmpeg bootstrap skipped: {exc}")

    # Keep yt-dlp fresh: YouTube rewrites its anti-bot rules weekly and a stale
    # local copy is the #1 cause of "only 480p offered" / "Sign in to confirm
    # you're not a bot". One silent pip upgrade per day, in the background.
    if not os.environ.get("WEBFINDER_NO_SELFUPDATE"):
        import threading

        def _selfupdate() -> None:
            try:
                stamp = Path(__file__).resolve().parent / ".wf-ytdlp-updated"
                if stamp.exists() and time.time() - stamp.stat().st_mtime < 86400:
                    return
                import subprocess as _sp
                r = _sp.run([sys.executable, "-m", "pip", "install", "-U", "--quiet",
                             "--disable-pip-version-check", "yt-dlp"],
                            capture_output=True, text=True, timeout=240)
                if r.returncode == 0:
                    stamp.touch()
                    print("[webfinder] yt-dlp refreshed — restart the app to load the new version.")
                else:
                    print("[webfinder] yt-dlp self-update skipped (offline or pip unavailable).")
            except Exception:  # noqa: BLE001 — pure nicety
                pass

        threading.Thread(target=_selfupdate, daemon=True).start()

    if os.environ.get("WEBFINDER_PORT_TAKEOVER"):        # launched by run.bat wrapper
        args.port = int(os.environ["WEBFINDER_PORT_TAKEOVER"])

    url = f"http://127.0.0.1:{args.port}"

    # A WebFinder backend is already answering on this port → don't double-bind.
    if _server_alive(url):
        print(f"[webfinder] A WebFinder backend is already running on {url} — opening it.")
        if not args.no_open:
            webbrowser.open(url)
        _hold_open()
        return

    if not args.browser:
        from webfinder.desktop.window import launch
        os.environ["WEBFINDER_DESKTOP"] = "1"
        try:
            if launch(args.port, args.host):
                return
            print("[webfinder] pywebview not installed — falling back to browser mode.")
            print("[webfinder] install the desktop shell with:  pip install pywebview")
        except Exception as exc:  # noqa: BLE001 — the shell can fail for many GUI reasons
            print(f"[webfinder] desktop shell failed ({exc}) — falling back to browser mode.")
            if _server_alive(url):
                # backend thread is already serving; just open the browser on it.
                if not args.no_open:
                    webbrowser.open(url)
                print(f"[webfinder] WebFinder is running at {url} (browser mode). Ctrl+C to stop.")
                _hold_open()
                return

    import uvicorn
    from webfinder.app import app

    if not args.no_open:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001 — headless environments have no browser
            pass
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
