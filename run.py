#!/usr/bin/env python3
"""WebFinder — entry point.

    python run.py                # native frameless window (needs pywebview),
                                 # falls back to the default browser otherwise
    python run.py --browser      # force browser mode (UI/UX development)
    python run.py --port 8080    # custom port
"""
from __future__ import annotations

import argparse
import os
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main() -> None:
    parser = argparse.ArgumentParser(description="WebFinder — smart file search & downloader")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--browser", action="store_true", help="serve + open default browser instead of pywebview")
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()

    if not args.browser:
        from webfinder.desktop.window import launch
        os.environ["WEBFINDER_DESKTOP"] = "1"
        try:
            if launch(args.port, args.host):
                return
            print("[webfinder] pywebview not installed — falling back to browser mode.")
            print("[webfinder] install the desktop shell with:  pip install pywebview")
        except Exception as exc:  # noqa: BLE001
            print(f"[webfinder] desktop shell failed ({exc}) — falling back to browser mode.")

    import uvicorn
    from webfinder.app import app

    url = f"http://127.0.0.1:{args.port}"
    if not args.no_open:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001 — headless environments have no browser
            pass
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
