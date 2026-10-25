"""WebFinder — configuration & persistent settings.

Settings live in ~/.webfinder/settings.json so the packaged EXE stays portable.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from typing import Any

APP_NAME = "WebFinder"
APP_VERSION = "1.0.0"
CONFIG_DIR = Path(os.environ.get("WEBFINDER_HOME", Path.home() / ".webfinder"))
CONFIG_FILE = CONFIG_DIR / "settings.json"

DEFAULTS: dict[str, Any] = {
    # --- downloads -------------------------------------------------------
    "download_dir": str(Path.home() / "Downloads" / "WebFinder"),
    "max_concurrent": 3,
    "chunk_size_kb": 256,
    "simulate_on_network_error": True,   # graceful demo fallback
    # --- search ----------------------------------------------------------
    "engines": {
        "google": True,
        "bing": True,
        "duckduckgo": True,
        "yandex": False,
        "mojeek": True,
    },
    "result_limit": 60,
    "safe_search": False,
    "proxy": "",                         # optional http/socks proxy for scraping
    "resolve_pages": True,               # crawl result pages for direct file links
    # --- media -----------------------------------------------------------
    "default_container": "mp4",
    "default_quality": "1080",           # "best" | 2160 | 1440 | 1080 | 720 | 480
    "ffmpeg_path": "",                   # manual override if not on PATH
    # --- appearance / misc ------------------------------------------------
    "accent": "violet",                  # violet | azure | magenta | mint
    "ambient_effects": True,
    "demo_mode": False,                  # force synthetic data (UI preview / offline)
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
            with _lock:
                self._data = _deep_merge(DEFAULTS, raw)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass
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
        if os.environ.get("WEBFINDER_DEMO") == "1":
            self.update({"demo_mode": True})
        if os.environ.get("WEBFINDER_DL_DIR"):
            self.update({"download_dir": os.environ["WEBFINDER_DL_DIR"]})


settings = Settings()

IS_WINDOWS = sys.platform == "win32"
