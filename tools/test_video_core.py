#!/usr/bin/env python3
"""All Video Downloader — video-engine fixture tests.

Offline determinism: manifest parsing, magic sniffing, the quality-picker
builder and the download-plan routing are exercised against canned payloads.

Run:  python tools/test_video_core.py
"""
from __future__ import annotations

import asyncio
import json
import os
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
GALLERY = {"_type": "playlist", "playlist_count": 3, "title": "tube gallery",
           "entries": [{"title": "clip A", "url": "https://youtu.be/a", "duration": 120},
                       {"title": "clip B", "url": "https://youtu.be/b", "duration": 90},
                       {"title": "clip C", "url": "https://youtu.be/c", "duration": 60}]}
CALLS: list[dict] = []
class _YDL:
    def __init__(self, opts): self.opts = opts; CALLS.append(opts)
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def extract_info(self, url, download=False):
        if "gallery" in url:
            return GALLERY
        # only platform URLs answer; raw file URLs must fall through
        if "youtu" not in url:
            raise RuntimeError("ERROR: no suitable InfoExtractor for " + url)
        return INFO
fake_yt.YoutubeDL = _YDL
sys.modules["yt_dlp"] = fake_yt
media_obj, err = M._ytdlp_extract("https://youtu.be/x")
assert CALLS and "extractor_args" not in CALLS[0], \
    "first pass must be bare CLI defaults (that is the path users prove works)"
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

# ═══ playlist / gallery pages enumerate ALL entries (completeness) ══════════
CALLS.clear()
media_obj2, err2 = M._ytdlp_extract("https://tube.example/gallery/42")
assert media_obj2, err2
assert media_obj2["title"] == "t"                       # first entry, fully extracted
assert media_obj2["playlist"]["total"] == 3
assert [e["title"] for e in media_obj2["playlist"]["entries"]] == ["clip B", "clip C"]
assert media_obj2["playlist"]["entries"][0]["url"] == "https://youtu.be/b"
print("✓ gallery: first entry becomes the card, the rest ride along as a list")

# ═══ page recursion stamps referer (hotlink-guarded CDNs) ════════════════════
import httpx
_orig = httpx.AsyncClient
httpx.AsyncClient = Client
try:
    out2 = asyncio.run(M.analyze("https://blog.example/page"))
finally:
    httpx.AsyncClient = _orig
assert out2.get("referer") == "https://blog.example/page"
assert out2.get("found_on_page") == "https://blog.example/page"
print("✓ page→file: job meta will carry the page as Referer")

# ═══ no header poisoning in yt-dlp opts anymore ══════════════════════════════
from webfinder.config import DEFAULTS, APP_NAME
assert "http_headers" not in M.base_yt_opts(), "custom UA would break player clients"
assert "skip_download" in M.base_yt_opts({"skip_download": True, "extract_flat": "in_playlist"})
print("✓ base_yt_opts: CLI-clean (no forced UA), cookies/proxy only when set")

# ═══ cookie-DB failure must NOT brick every site: retry without cookies ═════
from webfinder.config import settings as _st
from webfinder.core import ytcli as YT
assert YT._vparse("2026.10.21") > YT._vparse("2024.08.06")
assert YT._vparse("2026.3.5") > YT._vparse("2026.3.4")
print("✓ version compare: dot-date releases ordered numerically")

_orig_st = _st.get("ytdlp_browser_cookies")
_st.update({"ytdlp_browser_cookies": "chrome"})
_seen_opts: list[dict] = []
class CookieYDL:
    def __init__(self, opts):
        _seen_opts.append(opts)
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def extract_info(self, url, download=False):
        if self.opts_key():
            raise RuntimeError("ERROR: [youtube] Could not copy Chrome cookie database. "
                               "See https://github.com/yt-dlp/yt-dlp/issues/7271")
        return INFO
    def opts_key(self):
        return _seen_opts[-1].get("cookiesfrombrowser")
fake_yt.YoutubeDL = CookieYDL
got, gerr, gwin = M._module_attempt("https://youtu.be/x", {"skip_download": True})
assert got is None                      # ALL passes poisoned by the cookie read
info2, err2, _ = M._attempt_extract("https://youtu.be/x", {"skip_download": True})
assert info2 and info2.get("formats"), (err2, info2)
assert any(o.get("cookiesfrombrowser") is None for o in _seen_opts[-3:]), _seen_opts[-3:]
_st.update({"ytdlp_browser_cookies": _orig_st})
fake_yt.YoutubeDL = _YDL                 # restore the sane stub for later tests
print("✓ cookie-DB wall: analyzer auto-retries anonymously (every site not bricked)")

# ═══ newer system CLI ⇒ extraction routes to the binary, not the stale module ═
_calls: list[dict] = []
def fake_extract(url, **kw):
    _calls.append({"url": url, **kw})
    return (INFO if len(_calls) == 1 else None), "nope"
_orig_use, _orig_ext = YT.use_cli, YT.extract
YT.use_cli = lambda: True
YT.extract = fake_extract
try:
    media_cli, _ = M._ytdlp_extract("https://youtu.be/cli")
finally:
    YT.use_cli, YT.extract = _orig_use, _orig_ext
assert media_cli and media_cli["formats"], media_cli
assert _calls and _calls[0]["flat"] is True and _calls[0]["noplaylist"] is False
print("✓ system-CLI engine: extraction routes through the fresh binary (flags mapped)")

# ═══ iframe-players on embed pages become hop targets ═══════════════════════
EMBED_HTML = """<html><body>
<iframe src="//players.example.io/embed/video/9x8q" width=640 height=360></iframe>
</body></html>"""
_resp_cache = {}
class EmbedResp(Resp):
    def __init__(self, url): super().__init__(EMBED_HTML, url="https://tube.example/watch/1")
class EmbedClient(Client):
    def _r(self, url):
        if "players.example" in url:      # the embed resolves to a real mp4 host
            return _done(Resp("", url=url, headers={"content-type": "video/mp4",
                                                     "content-length": "50000000"}))
        return _done(EmbedResp(url))
    def head(self, url, **k): return self._r(url)
    def get(self, url, headers=None, **k): return self._r(url)
httpx.AsyncClient = EmbedClient
try:
    out3 = asyncio.run(M.analyze("https://tube.example/watch/1"))
finally:
    httpx.AsyncClient = _orig
assert out3["kind"] == "direct" and "players.example" in out3["url"], out3
assert out3.get("found_on_page") == "https://tube.example/watch/1"
print("✓ embed hop: iframe player resolved → real file card with page provenance")

# ═══ CLI download command mirrors the analysis recipe ════════════════════════
YT.detect.cache_clear()
os.environ["AVD_YTDLP_BIN"] = "yt-dlp"
args = YT.download_cmd("https://youtu.be/x", outdir="/d", outstem="t",
                       fmt="137+140/bestvideo[height<=1080]", container="mp4",
                       referer="https://page.example/v", client={"player_client": ["android", "tv"]})
blob = " ".join(args)
assert "-f 137+140/bestvideo[height<=1080] --merge-output-format mp4" in blob
assert "--referer https://page.example/v" in blob
assert "youtube:player_client=android,tv" in blob
assert "--progress-template" in blob and "AVDPROG" in blob
del os.environ["AVD_YTDLP_BIN"]
print("✓ download_cmd: fmt/referer/client/progress-template all wired")

print("\nALL VIDEO-CORE FIXTURE TESTS PASSED")
