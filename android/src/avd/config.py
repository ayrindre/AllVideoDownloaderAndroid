"""All Video Downloader (Android) — persistent settings.

Same settings contract as the desktop app (``webfinder/config.py``) so the
reused engine modules work untouched, but storage lives in app-private
internal storage and the default download folder points at the app-specific
external volume — no runtime storage permission required.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from .platform import runtime

APP_NAME = "All Video Downloader"
APP_VERSION = "3.0.0"
APP_EDITION = "Android"

CONFIG_DIR = runtime.config_dir()
CONFIG_FILE = CONFIG_DIR / "settings.json"

DEFAULTS: dict[str, Any] = {
    # --- downloads -------------------------------------------------------
    "download_dir": str(runtime.downloads_dir()),
    "max_concurrent": 2,
    "chunk_size_kb": 256,
    "simulate_on_network_error": False,   # no fake downloads on a real phone
    "proxy": "",                          # optional http/socks proxy for all transfers
    # --- video / capture ---------------------------------------------------
    "default_container": "mp4",
    "default_quality": "1080",            # "best" | 2160 | 1440 | 1080 | 720 | 480
    "ffmpeg_path": "",                    # manual override (folder or binary)
    "ytdlp_browser_cookies": "",          # kept for engine parity; unused on Android
    "cookies_file": "",                   # Netscape cookies.txt — auto-detected in external dir
    # --- appearance ----------------------------------------------------------
    "accent": "violet",                   # violet | azure | magenta | mint
    "ambient_effects": True,
    "theme_style": "Dark",                # Dark | Light
}

_lock = threading.Lock()


def _deep_merge(base: dict, patch: dict) -> dict:
    out = dict(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Settings:
    """Thread-safe settings object backed by a JSON file."""

    def __init__(self) -> None:
        self._data = dict(DEFAULTS)
        self.load()

    # -- persistence ------------------------------------------------------
    def load(self) -> None:
        try:
            raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            raw = None
        if raw:
            merged = _deep_merge(DEFAULTS, raw)
            for dead in ("engines", "result_limit", "safe_search", "resolve_pages",
                         "demo_mode", "vertical_mode", "file_types",
                         "instagram_include", "instagram_limit", "instagram_delay"):
                merged.pop(dead, None)
            with _lock:
                self._data = merged
        Path(self._data["download_dir"]).mkdir(parents=True, exist_ok=True)
        self._autodetect_cookies()

    def _autodetect_cookies(self) -> None:
        """A cookies.txt dropped into the app's external folder is picked up
        automatically — the Android equivalent of the desktop file picker."""
        jar = runtime.cookies_path()
        if jar.is_file() and jar.stat().st_size > 0:
            self._data["cookies_file"] = str(jar)

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with _lock:
            tmp = CONFIG_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
            os.replace(tmp, CONFIG_FILE)

    # -- access -----------------------------------------------------------
    def snapshot(self) -> dict:
        with _lock:
            return json.loads(json.dumps(self._data))

    def update(self, patch: dict) -> dict:
        with _lock:
            self._data = _deep_merge(self._data, patch)
            merged = dict(self._data)
        Path(merged["download_dir"]).mkdir(parents=True, exist_ok=True)
        self.save()
        return merged

    def get(self, key: str, fallback: Any = None) -> Any:
        with _lock:
            return self._data.get(key, fallback)

    def apply_env_overrides(self) -> None:
        if os.environ.get("AVD_DL_DIR"):
            self.update({"download_dir": os.environ["AVD_DL_DIR"]})


settings = Settings()

IS_ANDROID = runtime.IS_ANDROID
