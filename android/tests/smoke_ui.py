#!/usr/bin/env python3
"""Headless UI smoke test — build every screen with Kivy's mock window/GL
providers and exercise the main render paths. No display required.

Run:  PYTHONPATH=src KIVY_WINDOW=mock KIVY_GL_BACKEND=mock python tests/smoke_ui.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["KIVY_NO_ARGS"] = "1"
os.environ["KIVY_NO_CONSOLELOG"] = "1"
os.environ["AVD_HOME"] = "/tmp/avd-smoke"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import shutil  # noqa: E402

shutil.rmtree("/tmp/avd-smoke", ignore_errors=True)

import headless  # noqa: E402  — must precede any kivymd import

headless.install()

from avd.ui.app import AVDDownloaderApp  # noqa: E402
from avd.i18n import fa, t  # noqa: E402

app = AVDDownloaderApp()
root = app.build()
tab_names = [s.name for s in root.ids.tab_manager.screens]
print("✓ app built; tabs:", tab_names)
assert set(tab_names) == {"home", "downloads", "settings"}

home = app.screens["home"]
downloads = app.screens["downloads"]
settings = app.screens["settings"]
print("✓ three screens constructed")

# Persian shaping sanity
shaped = fa("بررسی لینک")
assert shaped and shaped != "بررسی لینک"
print("✓ Persian text shaping works")

# ── exercise every home-card renderer ─────────────────────────────────────
media_card = {
    "kind": "media", "url": "https://youtu.be/x", "title": "ویدیوی تست",
    "extractor": "youtube", "uploader": "کانال", "duration": 212,
    "view_count": 1000, "thumbnail": "", "ffmpeg": True,
    "formats": [{"height": 1080, "label": "1080p", "format": "137+140/best", "fps": 30},
                {"height": 720, "label": "720p", "format": "bv*[height<=720]+ba/best"},
                {"height": 0, "label": "Audio only", "format": "bestaudio/best"}],
    "formats_total": 3,
}
home._render(media_card)
assert home.selected_format["height"] == 1080
print("✓ media card renders, default quality chip selected")

hls_card = {
    "kind": "hls", "url": "https://x/a.m3u8", "title": "استریم زنده",
    "duration": 600, "ffmpeg": True, "bit_rate": 2_500_000,
    "formats": [{"height": 0, "label": "Best (auto)", "format": "bv*+ba/b", "url": ""},
                {"height": 720, "label": "720p · 2500 kbps", "format": "1/2/best", "url": "https://x/720.m3u8"}],
}
home._render(hls_card)
print("✓ hls card renders with variant ladder")

webmedia_card = {
    "kind": "webmedia", "url": "https://tube/x", "title": "تاپ تیوب",
    "site": "XVideos", "player": "html5player", "thumbnail": "",
    "referer": "https://tube/x", "found_on_page": "https://tube/x",
    "formats": [{"height": 1080, "label": "1080p", "format": "url",
                 "url": "https://cdn/1080.mp4", "ext": "mp4"},
                {"height": 480, "label": "480p", "format": "url",
                 "url": "https://cdn/480.mp4", "ext": "mp4"}],
}
home._render(webmedia_card)
print("✓ webmedia (player-config) card renders")

direct_card = {"kind": "direct", "url": "https://x/f.mp4", "title": "f.mp4",
               "file_type": "video", "size": 150_000_000,
               "content_type": "video/mp4", "accepts_ranges": "206"}
home._render(direct_card)
print("✓ direct file card renders")

page_card = {"kind": "page", "url": "https://x/p", "title": "صفحه", "site": "X",
             "candidates": [{"url": "https://x/a.mp4", "filename": "a.mp4",
                             "file_type": "video", "size_bytes": 9_000_000, "origin": "anchor"}]}
home._render(page_card)
print("✓ page card + candidate rows render")

error_card = {"kind": "media_error", "url": "https://x/y", "extractor": "youtube",
              "title": "بلاک", "error": "Sign in to confirm you're not a bot",
              "hints": ["<b>hint one</b> with markup", "plain hint"],
              "candidates": []}
home._render(error_card)
print("✓ media_error card renders, HTML stripped from hints")

magnet_card = {"kind": "magnet", "url": "magnet:?xt=urn:btih:abc&dn=movie",
               "title": "movie", "file_type": "magnet"}
home._render(magnet_card)
print("✓ magnet card renders (copy-only)")

home._show_idle()
home._show_loading()
print("✓ idle and loading stages render")

# ── downloads reconciliation with synthetic jobs ───────────────────────────
jobs = [
    {"id": "j1", "url": "https://x/a.mp4", "kind": "http", "filename": "a.mp4",
     "filepath": "/tmp/a.mp4", "title": "کار اول", "file_type": "video",
     "status": "downloading", "total": 100_000_000, "done": 42_000_000,
     "speed": 1_500_000, "eta": 38, "unit": "bytes", "error": "",
     "progress_pct": 42.0, "created_at": 0, "finished_at": 0, "meta": {}},
    {"id": "j2", "url": "https://x/b.m3u8", "kind": "hls", "filename": "b.mp4",
     "filepath": "/tmp/b.mp4", "title": "کار دوم", "file_type": "video",
     "status": "paused", "total": 600, "done": 120, "speed": 0, "eta": 0,
     "unit": "time", "error": "", "progress_pct": 20.0,
     "created_at": 0, "finished_at": 0, "meta": {}},
    {"id": "j3", "url": "https://x/c", "kind": "ytdlp", "filename": "c.mp4",
     "filepath": "/tmp/c.mp4", "title": "کار تمام", "file_type": "video",
     "status": "done", "total": 5_000_000, "done": 5_000_000, "speed": 0,
     "eta": 0, "unit": "bytes", "error": "", "progress_pct": 100.0,
     "created_at": 0, "finished_at": 1, "meta": {}},
]
downloads._reconcile(jobs)
assert set(downloads._cards) == {"j1", "j2", "j3"}
# second reconcile updates in place, no duplicate cards
jobs[0]["done"] = 80_000_000
jobs[0]["progress_pct"] = 80.0
downloads._reconcile(jobs)
assert len(downloads._cards) == 3
# removal path
downloads._reconcile(jobs[:2])
assert "j3" not in downloads._cards
print("✓ download cards reconcile (add / update / remove)")

# ── settings screen ─────────────────────────────────────────────────────────
assert settings.slider.value == 2
settings._on_slider(settings.slider, 4)
assert "۴" in settings.concurrent_val.text
print("✓ settings screen widgets live")

# ── theme switch rebuilds everything ────────────────────────────────────────
app.apply_theme("Light", "azure")
app.recolor_all()
assert app.pal["bg"] == "#F3F4FB" and app.accent == "azure"
app.apply_theme("Dark", "violet")
app.recolor_all()
home._render(media_card)
print("✓ theme/accent switch rebuilds all screens")

print("\nUI SMOKE TEST PASSED")
