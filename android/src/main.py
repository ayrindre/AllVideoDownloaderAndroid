"""All Video Downloader (Android) — application entry point.

Buildozer/p4a launches this module; it only wires the KivyMD shell. The
download engine runs on a background asyncio thread (see avd/engine.py).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# make the `avd` package importable both in the p4a bundle and on desktop
sys.path.insert(0, str(Path(__file__).resolve().parent))

from avd.ui.app import AVDDownloaderApp  # noqa: E402


def main() -> None:
    # Kivy config must be set before window creation
    os.environ.setdefault("KIVY_NO_CONSOLELOG", "1")
    AVDDownloaderApp().run()


if __name__ == "__main__":
    main()
