"""All Video Downloader — configuration & persistent settings.

Settings live in ~/.avd/settings.json so the packaged EXE stays portable.
The old WebFinder settings file is migrated once, on first launch, so an
upgrade keeps your download folder, proxy and cookie preferences.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import threading
from pathlib import Path
from typing import Any

APP_NAME = "All Video Downloader"
APP_VERSION = "2.0.0"
CONFIG_DIR = Path(os.environ.get("AVD_HOME") or os.environ.get("WEBFINDER_HOME")
                  or Path.home() / ".avd")
CONFIG_FILE = CONFIG_DIR / "settings.json"
_LEGACY_FILE = Path.home() / ".webfinder" / "settings.json"

DEFAULTS: dict[str, Any] = {
    # --- downloads -------------------------------------------------------
    "download_dir": str(Path.home() / "Downloads" / "All Video Downloader"),
    "max_concurrent": 3,
    "chunk_size_kb": 256,
    "simulate_on_network_error": True,   # graceful demo fallback
    "proxy": "",                         # optional http/socks proxy for all transfers
    # --- video / capture ---------------------------------------------------
    "default_container": "mp4",
    "default_quality": "1080",           # "best" | 2160 | 1440 | 1080 | 720 | 480
    "ffmpeg_path": "",                   # manual override if not on PATH
    "ytdlp_browser_cookies": "",         # ""|chrome|edge|firefox|brave|chromium — defeats paywall/bot walls
    # --- instagram checker (gallery-dl) ------------------------------------
    "instagram_include": "posts,reels",  # posts,reels,stories,highlights,tagged
    "instagram_limit": 30,               # newest N posts per tab (0 = everything)
    "instagram_delay": "",               # "" = gallery-dl's own rate limit (6-12 s/request)
    # --- appearance ----------------------------------------------------------
    "accent": "violet",                  # violet | azure | magenta | mint
    "ambient_effects": True,
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
        if raw is None and _LEGACY_FILE.exists():
            # one-shot migration from the old WebFinder data folder
            try:
                CONFIG_DIR.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(_LEGACY_FILE, CONFIG_FILE)
                raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            except OSError:
                raw = None
        if raw:
            merged = _deep_merge(DEFAULTS, raw)
            # keys of the retired search module must never resurrect
            for dead in ("engines", "result_limit", "safe_search", "resolve_pages",
                         "demo_mode", "vertical_mode", "file_types"):
                merged.pop(dead, None)
            with _lock:
                self._data = merged
        Path(self._data["download_dir"]).mkdir(parents=True, exist_ok=True)

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

    # -- runtime env overrides (used by the sandbox preview) -------------
    def apply_env_overrides(self) -> None:
        if os.environ.get("AVD_DL_DIR") or os.environ.get("WEBFINDER_DL_DIR"):
            self.update({"download_dir": os.environ.get("AVD_DL_DIR") or os.environ["WEBFINDER_DL_DIR"]})


settings = Settings()

IS_WINDOWS = sys.platform == "win32"
