#!/usr/bin/env python3
"""All Video Downloader — video-engine fixture tests.

Offline determinism: manifest parsing, magic sniffing, the quality-picker
builder and the download-plan routing are exercised against canned payloads.

Run:  python tools/test_video_core.py
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from webfinder.core import media as M  # noqa: E402

# ═══ HLS master playlist → variant ladder, tallest first ════════════════════
M3U8 = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=5500000,AVERAGE-BANDWIDTH=5000000,RESOLUTION=1920x1080,CODECS="avc1.640028,mp4a.40.2"
1080p/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=2800000,RESOLUTION=1280x720
720p/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=1200000,RESOLUTION=640x360
360p/index.m3u8
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aac",NAME="English",DEFAULT=YES,URI="audio/en.m3u8"
"""
ladder = M.parse_m3u8_master(M3U8, "https://cdn.example.io/show/master.m3u8")
assert [v["height"] for v in ladder] == [1080, 720, 360], ladder
assert ladder[0]["url"] == "https://cdn.example.io/show/1080p/index.m3u8"
assert ladder[0]["bandwidth"] == 5_500_000
print("✓ m3u8 master: ladder parsed, sorted by height, absolute URLs")

forms = M.stream_formats(ladder)
assert forms[0]["label"] == "Best (auto)"
assert forms[1]["label"].startswith("1080p") and "5500" in forms[1]["label"]
assert forms[1]["format"].startswith("0/1/") and "height<=1080" in forms[1]["format"]  # idx = position in the master
print("✓ picker: auto + one chip per rung, yt-dlp selector chain built")

# ═══ DASH MPD → representations with real ids ══════════════════════════════
MPD = """<?xml version="1.0"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static">
 <Period>
  <AdaptationSet contentType="video" mimeType="video/mp4">
   <Representation id="v1080" bandwidth="4500000" width="1920" height="1080"><BaseURL>vid/1080.m3u8</BaseURL></Representation>
   <Representation id="v720" bandwidth="2300000" width="1280" height="720"><BaseURL>vid/720.m3u8</BaseURL></Representation>
  </AdaptationSet>
  <AdaptationSet contentType="audio" mimeType="audio/mp4">
   <Representation id="a128" bandwidth="128000"><BaseURL>aud/en.m3u8</BaseURL></Representation>
  </AdaptationSet>
 </Period>
</MPD>"""
lad2 = M.parse_mpd_master(MPD, "https://cdn.example.io/dash/manifest.mpd")
assert [v["height"] for v in lad2] == [1080, 720] and lad2[0]["rep_id"] == "v1080"
assert lad2[0]["url"].endswith("vid/1080.m3u8")
f2 = M.stream_formats(lad2)
assert f2[1]["format"].startswith("v1080/"), f2[1]      # rep id rides the selector
print("✓ mpd: video reps only (audio set skipped), representation ids kept")

# ═══ container sniffing beats lying headers ═════════════════════════════════
ftyp = b"\x00\x00\x00\x20ftypisom" + b"\x00" * 52
ebml = b"\x1a\x45\xdf\xa3\x01\x00\x00\x00" + b"\x00" * 56
flv = b"FLV\x01\x05" + b"\x00" * 59
assert M.sniff_container(ftyp) == "mp4"
assert M.sniff_container(ebml) == "mkv"
assert M.sniff_container(flv) == "flv"
assert M.sniff_container(b"<!DOCTYPE html><html>") == ""
print("✓ magic bytes: ftyp/EBML/FLV recognized, HTML rejected")

# ═══ plan_download routes a picked variant through yt-dlp (audio muxing) ════
plan = asyncio.run(M.plan_download("https://cdn.example.io/show/master.m3u8",
                                   fmt=forms[1]))
assert plan["kind"] in ("ytdlp", "hls")          # yt-dlp present in this venv
if plan["kind"] == "ytdlp":
    assert plan["meta"]["format"] == forms[1]["format"]
else:
    assert plan["meta"]["variant_url"] == ladder[0]["url"]
assert plan["file_type"] == "video"
plan_auto = asyncio.run(M.plan_download("https://cdn.example.io/show/master.m3u8"))
assert plan_auto["kind"] in ("ytdlp", "hls")
print("✓ plan: variant →", plan["kind"], "| auto →", plan_auto["kind"])

# ═══ yt-dlp picker carries REAL format ids (quality is a promise, not a hope) ═
fake_yt = types.ModuleType("yt_dlp")
INFO = {"title": "t", "extractor_key": "Youtube", "formats": [
    {"format_id": "399", "ext": "mp4", "vcodec": "av01.0.19M.08", "acodec": "none", "height": 2160, "tbr": 9000, "fps": 60},
    {"format_id": "299", "ext": "mp4", "vcodec": "avc1.640028", "acodec": "none", "height": 1080, "tbr": 4000},
    {"format_id": "137", "ext": "mp4", "vcodec": "avc1.640028", "acodec": "none", "height": 1080, "tbr": 6500},
    {"format_id": "140", "ext": "m4a", "vcodec": "none", "acodec": "mp4a.40.2", "abr": 129},
    {"format_id": "18", "ext": "mp4", "vcodec": "avc1.42001E", "acodec": "mp4a.40.2", "height": 360, "tbr": 600},
]}
class _YDL:
    def __init__(self, opts): self.opts = opts
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def extract_info(self, url, download=False):
        # only the platform URL answers; raw file URLs must fall through
        if "youtu" not in url:
            raise RuntimeError("ERROR: no suitable InfoExtractor for " + url)
        # first client pass (android/tv) returns the rich map
        assert "player_client" in str(self.opts.get("extractor_args", {}))
        return INFO
fake_yt.YoutubeDL = _YDL
sys.modules["yt_dlp"] = fake_yt
media_obj, err = M._ytdlp_extract("https://youtu.be/x")
sel = {f["height"]: f["format"] for f in media_obj["formats"]}
assert sel[1080].startswith("137+140/"), sel[1080]
assert "399+140" in sel[2160], sel[2160]
assert media_obj["formats_total"] == 5
print("✓ picker ids: 1080p →", sel[1080].split("/")[0], "| 4K →", sel[2160].split("/")[0])

# ═══ page deep-scan upgrade: analyze() re-analyzes the hidden video ══════════
PAGE = """<html><head><meta property="og:video" content="/media/clip.mp4"></head>
<body><a href="notes.txt">t</a><video src="/players/late.js"></video></body></html>"""

class Resp:
    def __init__(self, text="", status=200, headers=None, url=""):
        self.text, self.status_code = text, status
        self.headers = headers or {"content-type": "text/html"}
        self.url = url or "https://blog.example/page"
        self.content = text.encode()
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError("HTTP")

class Client:
    def __init__(self, *a, **k): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    def get(self, url, headers=None, **k):
        if "clip.mp4" in url:
            return _done(Resp("", url=url, headers={"content-type": "video/mp4",
                                                     "content-length": "90000000"}))
        return _done(Resp(PAGE, url="https://blog.example/page"))
    def head(self, url, **k):
        if "clip.mp4" in url:
            return _done(Resp("", url=url, headers={"content-type": "video/mp4",
                                                    "content-length": "90000000"}))
        return _done(Resp(PAGE, url="https://blog.example/page"))
def _done(r):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    f = loop.create_future(); f.set_result(r); return f

import httpx
_orig = httpx.AsyncClient
httpx.AsyncClient = Client
try:
    out = asyncio.run(M.analyze("https://blog.example/page"))
finally:
    httpx.AsyncClient = _orig
assert out["kind"] == "direct" and out["url"].endswith("clip.mp4"), out
assert out.get("found_on_page") == "https://blog.example/page"
print("✓ page scan: og:video discovered → re-analyzed → direct-download card")

# ═══ cancel removes the job; a removed job can never republish ══════════════
from webfinder.core.downloader import DownloadManager, DownloadJob
events = []
m = DownloadManager.__new__(DownloadManager)
m.jobs, m.order, m._emit = {}, [], (lambda evt: events.append(evt))
j = DownloadJob(url="https://x/a.mp4", kind="sim", title="a"); j.id = "j1"
m.jobs["j1"] = j; m.order.append("j1")
assert m.cancel("j1") is True
assert "j1" not in m.jobs, "cancelled job must leave the list"
m.publish(j)                                     # zombie publish → silent
assert not any(e["type"] == "job.update" for e in events[1:])
print("✓ cancel semantics: row removed, worker muted")

# ═══ meta: the app exposes no search surface any more ════════════════════════
from webfinder.config import DEFAULTS, APP_NAME
assert APP_NAME == "All Video Downloader"
assert not {"engines", "result_limit", "safe_search", "resolve_pages", "demo_mode"} & set(DEFAULTS)
assert "proxy" in DEFAULTS and "default_quality" in DEFAULTS
print("✓ config: search-era keys gone, download keys kept")

print("\nALL VIDEO-CORE FIXTURE TESTS PASSED")
