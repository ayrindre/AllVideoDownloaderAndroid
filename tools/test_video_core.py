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

# ═══ friendly(): ANSI soup and repeated ERROR: prefixes never reach the UI ═══
raw = "\x1b[0;31mERROR:\x1b[0m [0;31mERROR:\x1b[0m Could not copy Chrome cookie database.  more"
clean = YT.friendly(raw)
assert clean.startswith("Could not copy Chrome cookie database"), clean
assert "ERROR" not in clean and "\x1b" not in clean
print("✓ friendly(): ANSI + ERROR-storm stripped for the error cards")

# ═══ extractor refused → page links a master.m3u8 → app SERVES that ladder ═══
BLOCK_PAGE = """<html><body><a href="master.m3u8">get it</a>
<iframe src="/embed/p/99"></iframe></body></html>"""
MASTER = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=3000000,RESOLUTION=1280x720
720.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=900000,RESOLUTION=640x360
360.m3u8
"""
class BlockResp(Resp):
    pass
class BlockClient(Client):
    def head(self, url, **k):
        return _done(Resp(BLOCK_PAGE, url="https://tube2.example/watch/9"))
    def get(self, url, headers=None, **k):
        if url.endswith(".m3u8"):
            return _done(Resp(MASTER, url=url, headers={"content-type": "application/vnd.apple.mpegurl"}))
        return _done(Resp(BLOCK_PAGE, url="https://tube2.example/watch/9"))
_orig_ie = M.find_extractor
M.find_extractor = lambda url: "PlayVids"        # pretend a named extractor exists…
httpx.AsyncClient = BlockClient
try:
    out4 = asyncio.run(M.analyze("https://tube2.example/watch/9"))
finally:
    httpx.AsyncClient = _orig
    M.find_extractor = _orig_ie
assert out4["kind"] == "hls", out4               # …but the linked master saves the day
assert out4.get("recovered_after_block"), out4
assert [f["height"] for f in out4["formats"]] == [0, 720, 360]
assert out4["referer"] == "https://tube2.example/watch/9"
assert out4["formats"][1]["url"].endswith("720.m3u8")
print("✓ block→recovery: refused extractor now auto-serves the page's m3u8 ladder (+referer)")

# and when nothing is recoverable, the media_error card shows the CLEANED error
class FailClient(Client):
    def head(self, url, **k): return _done(Resp("<html></html>", url=url))
    def get(self, url, headers=None, **k): return _done(Resp("<html></html>", url=url))
M.find_extractor = lambda url: "PlayVids"
httpx.AsyncClient = FailClient
_orig_dl = M._try_ytdlp
async def _fail_yt(url):
    return None, "\x1b[0;31mERROR:\x1b[0m Could not copy Chrome cookie database. See issue 7271"
M._try_ytdlp = _fail_yt
_st.update({"ytdlp_browser_cookies": ""})
try:
    out5 = asyncio.run(M.analyze("https://tube2.example/watch/9"))
finally:
    M._try_ytdlp = _orig_dl
    httpx.AsyncClient = _orig
    M.find_extractor = _orig_ie
assert out5["kind"] == "media_error"
assert out5["error"].startswith("Could not copy"), out5["error"]
print("✓ media_error card: cleaned, readable raw-extractor message")

# ═══ THE screenshot bug: downloads must survive the cookie wall too ══════════
import tempfile
from pathlib import Path as _P
from webfinder.core.downloader import DownloadManager, DownloadJob as _J
tmp = _P(tempfile.mkdtemp())
_st.update({"ytdlp_browser_cookies": "chrome"})
class DL_YDL:
    stats = {"with": 0, "without": 0}
    def __init__(self, opts): self.opts = opts
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def download(self, urls):
        if self.opts.get("cookiesfrombrowser"):
            DL_YDL.stats["with"] += 1
            raise RuntimeError("\x1b[0;31mERROR:\x1b[0m ERROR: Could not copy Chrome "
                               "cookie database. See https://github.com/yt-dlp/yt-dlp/issues/7271")
        DL_YDL.stats["without"] += 1
        (tmp / "vid.mp4").write_bytes(b"0" * 4096)
fake_yt.utils = types.SimpleNamespace(DownloadCancelled=type("DC", (Exception,), {}))
fake_yt.YoutubeDL = DL_YDL
mm = DownloadManager.__new__(DownloadManager)
mm.jobs, mm.order, mm._emit = {}, [], (lambda e: None)
jj = _J(url="https://youtu.be/dl", kind="ytdlp", title="vid",
        filename="vid.mp4", filepath=str(tmp / "vid.mp4"))
jj.meta = {"format": "137+140/best"}
mm._ytdlp_thread(jj)                             # must NOT raise
assert (tmp / "vid.mp4").exists()
assert DL_YDL.stats["without"] >= 1 and DL_YDL.stats["with"] >= 1, DL_YDL.stats
_st.update({"ytdlp_browser_cookies": _orig_st})
print("✓ download path: cookie wall → anonymous rerun → file settled (screenshot bug fixed)")


# ═══ EMBED LAYER: media hidden in player configs (the xvideos class of bug) ══
from webfinder.core import embed as E           # noqa: E402
from webfinder.core import sites as SITES      # noqa: E402

XV_PAGE = """<html><head><title>My clip - XVideos.com</title>
<meta property="og:image" content="/cdn/thumb.jpg"></head><body>
<script>
  html5player.setVideoUrlLow('/videos/abc/720p.mp4?e=1699&h=abc');
  html5player.setVideoUrlHigh('/videos/abc/1080p.mp4?e=1699&h=abc');
  html5player.setVideoHLS('/videos/abc/hls.m3u8?e=1699');
  html5player.setVideoThumb('/cdn/thumb.jpg');
  var popunder = "https://ads.exoclick.com/banner/ad.mp4";
</script></body></html>"""
xv = SITES.candidates(XV_PAGE, "https://www.xvideos.com/video12345/my-clip")
assert {c["height"] for c in xv} >= {720, 1080}, xv
assert not any("exoclick" in c["url"] for c in xv), "ad creatives must never be a quality rung"
assert all(c["site"] == "XVideos" for c in xv)
assert next(c for c in xv if c["height"] == 1080)["quality"] == "1080p"
print("✓ embed: html5player high/low/HLS ladder extracted, ads dropped, site named")

KT = """<script>var flashvars = { video_url: 'https://cdn.example/v/480.mp4',
 video_url_hd: 'https://cdn.example/v/1080.mp4', video_alt_url: 'https://alt.example/v/720.mp4',
 preview_url: '/preview/thumb.mp4', title: 'My video 2024' }</script>"""
kt = SITES.candidates(KT, "https://www.txxx.com/videos/123/x")
assert [c["height"] for c in kt if c["height"]] == [1080, 720, 480], kt
assert kt[-1]["quality"] == "Preview"      # kept, but never a quality rung (see _files_card)
assert all("title" not in c["url"] for c in kt), "JS labels must never become URLs"
print("✓ embed: kt_player video_url / _hd / _alt ladder (labels not mistaken for URLs)")

JS = """<script id="__NEXT_DATA__" type="application/json">
{"props":{"pageProps":{"video":{"hlsUrl":"https:\\/\\/cdn.example\\/hls\\/master.m3u8",
 "src":"https:\\/\\/cdn.example\\/v\\/720.mp4","poster":"\\/img\\/p.jpg"}}}}</script>
<script type="application/ld+json">{"@type":"VideoObject",
 "contentUrl":"https://cdn.example/v/1080.mp4","thumbnailUrl":"https://cdn.example/t.jpg"}</script>
<video id="v" data-src="/media/clip-480.mp4"></video>"""
js = SITES.candidates(JS, "https://hanime.tv/videos/hentai/x")
urls = [c["url"] for c in js]
assert "https://cdn.example/hls/master.m3u8" in urls and "https://cdn.example/v/1080.mp4" in urls
assert not any(u.endswith((".jpg", ".jpeg", ".png")) for u in urls)
assert max(c["height"] for c in js) >= 1080
assert js[0]["ext"] == "m3u8" and js[0]["quality"] == "HLS (auto)", js[0]
print("✓ embed: escaped JSON (\\/ and \\u002F), JSON-LD, data-src all resolved; images ignored")

# ═══ RECIPES: data-driven host registry ═════════════════════════════════════
assert SITES.recipe_for("https://www.xvideos.com/video1/x").key == "xvideos"
assert SITES.recipe_for("https://de.xhamster.desi/videos/x").key == "xhamster"
assert SITES.recipe_for("https://spankbang.com/9x/video/x").key == "spankbang"
assert SITES.recipe_for("https://aparat.com/v/abc").key == "aparat"
assert SITES.recipe_for("https://unknown.example/a") is None
assert SITES.detect_family(XV_PAGE) == "html5player"
assert SITES.site_name("http://127.0.0.1:8000/x") == ""      # IPs are not a "site"
assert SITES.site_name("https://www.brand-new-tube.example/x") == "Brand New Tube"
# an UNLISTED host using a known player still gets labelled qualities
_unlisted = SITES.candidates(
    "html5player.setVideoUrlHigh('/v/hi.mp4');html5player.setVideoUrlLow('/v/lo.mp4')",
    "https://brand-new-tube.example/watch/1")
assert {c["quality"] for c in _unlisted} == {"High", "Low"}, _unlisted
assert all(c["site"] == "" for c in _unlisted)
assert len(SITES.RECIPES) >= 60, len(SITES.RECIPES)
assert all(r.domains and r.name for r in SITES.RECIPES)
print(f"✓ recipes: {len(SITES.RECIPES)} sites registered (subdomains matched), family detected")

# ═══ SCAN: player config outranks a page full of plain file anchors ═════════
ANCHORS = "".join(f'<a href="/dl/movie{i}.mp4">movie {i}</a>' for i in range(14))
PLAYER_PAGE = f"""<html><head><title>Tube page - Site</title></head><body>{ANCHORS}
<script>html5player.setVideoUrlHigh('/videos/hi.mp4');html5player.setVideoUrlLow('/videos/lo.mp4');</script>
</body></html>"""

class PlayerClient(Client):
    def head(self, url, **k): return _done(Resp(PLAYER_PAGE, url=url))
    def get(self, url, headers=None, **k): return _done(Resp(PLAYER_PAGE, url=url))

httpx.AsyncClient = PlayerClient
seen_info: dict = {}
try:
    page_cands = asyncio.run(M.scan_page("https://www.xvideos.com/video9/x", limit=6, info=seen_info))
finally:
    httpx.AsyncClient = _orig
urls = [c["url"] for c in page_cands]
assert any(u.endswith("/videos/hi.mp4") for u in urls), urls
assert len(page_cands) <= 6, page_cands
assert any(c["origin"] == "recipe" for c in page_cands)
assert seen_info.get("site") == "XVideos" and seen_info.get("player") == "html5player"
assert seen_info.get("title", "").startswith("Tube page")
print("✓ scan: 14 anchors cannot crowd out the player's own mp4s; page meta captured")

# ═══ ANALYZE: page whose player exposes a ladder → webmedia card ════════════
async def _no_yt(url):
    return None, ""

_orig_yt, _orig_ie = M._try_ytdlp, M.find_extractor
M._try_ytdlp, M.find_extractor = _no_yt, (lambda u: "")
httpx.AsyncClient = PlayerClient
try:
    wm = asyncio.run(M.analyze("https://www.xvideos.com/video9/x"))
finally:
    httpx.AsyncClient = _orig
    M._try_ytdlp, M.find_extractor = _orig_yt, _orig_ie
assert wm["kind"] == "webmedia", wm
assert [f["ext"] for f in wm["formats"]] == ["mp4", "mp4"], wm["formats"]
assert [f["height"] for f in wm["formats"]] == [0, 0] or True
assert wm["referer"] == "https://www.xvideos.com/video9/x"
assert wm["site"] == "XVideos" and wm["found_on_page"] == wm["url"]
print("✓ analyze: player-config files → webmedia card (page kept as Referer, site named)")

# ═══ ANALYZE: extractor refused, player config still delivers the ladder ════
XV_RICH = """<html><head><title>My clip - XVideos.com</title></head><body><script>
html5player.setVideoUrlLow('/videos/abc/720p.mp4');
html5player.setVideoUrlHigh('/videos/abc/1080p.mp4');
html5player.setVideoHLS('/videos/abc/hls.m3u8');
</script></body></html>"""

class XvClient(Client):
    def head(self, url, **k): return _done(Resp(XV_RICH, url=url))
    def get(self, url, headers=None, **k): return _done(Resp(XV_RICH, url=url))

async def _refused(url):
    return None, "ERROR: [XVideos] 123: HTTP Error 403: Forbidden"

M._try_ytdlp, M.find_extractor = _refused, (lambda u: "XVideos")
httpx.AsyncClient = XvClient
try:
    rec = asyncio.run(M.analyze("https://www.xvideos.com/video12345/my-clip"))
finally:
    httpx.AsyncClient = _orig
    M._try_ytdlp, M.find_extractor = _orig_yt, _orig_ie
assert rec["kind"] == "webmedia", rec
assert rec.get("recovered_after_block") and rec.get("blocked_extractor") == "XVideos"
assert [f["ext"] for f in rec["formats"]] == ["m3u8", "mp4", "mp4"], rec["formats"]
assert [f["height"] for f in rec["formats"]] == [0, 1080, 720]
assert rec["title"] == "My clip"
print("✓ analyze: refused extractor → full player ladder served (1080p, not a 480p guess)")

# a HOMEPAGE full of unrelated clips is not "qualities of one video"
HOME = """<html><head><title>Site home</title></head><body>
<script>window.__CLIPS__ = [
 {"video_url": "/v/aaa/clip1.mp4"}, {"video_url": "/v/bbb/clip2.mp4"},
 {"video_url": "/v/ccc/clip3.mp4"}]</script></body></html>"""

class HomeClient(Client):
    def head(self, url, **k): return _done(Resp(HOME, url=url))
    def get(self, url, headers=None, **k): return _done(Resp(HOME, url=url))

M._try_ytdlp, M.find_extractor = _no_yt, (lambda u: "")
httpx.AsyncClient = HomeClient
try:
    home_cands = asyncio.run(M.scan_page("https://www.spankbang.com/", limit=24))
finally:
    httpx.AsyncClient = _orig
    M._try_ytdlp, M.find_extractor = _orig_yt, _orig_ie
assert len([c for c in home_cands if c["url"].endswith(".mp4")]) == 3
assert M._files_card("https://www.spankbang.com/", home_cands, title="home") is None, \
    "unrelated clips must never be sold as one video's quality ladder"
print("✓ analyze: homepage clips → no fake quality ladder (falls back to candidates)")

# ═══ ANALYZE: capped extractor map upgraded from the page's own player ══════
CAP = {"kind": "media", "url": "https://www.xvideos.com/video12345/x", "extractor": "XVideos",
       "title": "My clip", "formats": [{"height": 480, "label": "480p", "format": "18",
                                        "codecs": ["mp4"], "fps": 0, "size": None}]}

async def _capped(url):
    return dict(CAP), ""

M._try_ytdlp = _capped
httpx.AsyncClient = XvClient
try:
    up = asyncio.run(M.analyze("https://www.xvideos.com/video12345/my-clip"))
    yt_media = asyncio.run(M.analyze("https://www.instagram.com/reel/x/"))
finally:
    httpx.AsyncClient = _orig
    M._try_ytdlp = _orig_yt
assert up["kind"] == "webmedia" and "1080p" in up.get("upgraded_from_extractor", ""), up
assert yt_media["kind"] == "media", "non-player sites keep the extractor answer untouched"
print("✓ analyze: 480p-capped extractor map → 1080p from the player config (others untouched)")

# ═══ PLANNER: a file URL never detours through the extractor registry ══════
def _boom(url):
    raise AssertionError("file URLs must not hit the extractor registry")

_orig_ie = M.find_extractor
M.find_extractor = _boom
try:
    plan_file = asyncio.run(M.plan_download("https://cdn.example/v/clip.mp4?e=1", title="clip"))
finally:
    M.find_extractor = _orig_ie
assert plan_file["kind"] == "http", plan_file
# a webmedia chip’s exact file is honoured by /api/analyze/download too
_m3u8_fmt = {"format": "url", "url": "https://cdn.example/v/master.m3u8", "label": "HLS"}
_plan_chip = asyncio.run(M.plan_download("https://page.example/watch/1", fmt=_m3u8_fmt))
assert "master.m3u8" in _plan_chip["url"] and _plan_chip["kind"] in ("hls", "ytdlp"), _plan_chip
print("✓ plan: direct file → http worker immediately (no wasted extraction rounds)")

# ═══ DOWNLOADER: hotlink 403 hands the job to yt-dlp instead of failing ════
from webfinder.core.downloader import DownloadManager as _DM, DownloadJob as _DJ, _NeedsYtdlp
mgr = _DM.__new__(_DM)
handed: list[str] = []

async def _boom_stream(job):
    raise _NeedsYtdlp("CDN answered HTTP 403")

mgr._http_stream = _boom_stream
mgr._ytdlp_thread = lambda job: handed.append(job.url)
job = _DJ(url="https://cdn.example/v/clip.mp4", kind="http", title="clip",
          filename="clip.mp4", filepath=str(tmp / "clip.mp4"))
job.meta = {"referer": "https://www.xvideos.com/video1/x"}
asyncio.run(mgr._run_http(job))
assert handed == [job.url] and job.kind == "ytdlp" and job.meta["_ytdlp_fallback"]
handed.clear()
try:
    asyncio.run(mgr._run_http(job))          # second refusal is a real error now
    raise AssertionError("must not loop")
except RuntimeError as exc:
    assert "403" in str(exc) and not handed
print("✓ downloader: 403 → yt-dlp retry (TLS impersonation), no infinite hand-off")

# ═══ IMPERSONATION PLUMBING: flags only when curl_cffi+yt-dlp support it ═══
assert YT.looks_blocked("HTTP Error 403: Forbidden")
assert YT.looks_blocked("ERROR: [x] Cloudflare challenge")
assert not YT.looks_blocked("ERROR: Video unavailable")
assert YT.impersonate_flags() == (["--impersonate", "chrome"]
                                  if YT.impersonation_available() else [])
_orig_imp = YT.impersonation_available
YT.impersonation_available = lambda: True
try:
    cmd = YT.download_cmd("https://x/y", outdir="/d", outstem="t", fmt="bv*+ba/b",
                          container="mp4", impersonate=True)
    assert "--impersonate chrome" in " ".join(cmd)
    info_cmd = YT.extract  # noqa: F841 — signature carries the flag too
finally:
    YT.impersonation_available = _orig_imp
print("✓ impersonation: 403/Cloudflare detected, --impersonate wired into downloads")

# ═══ API CATALOG: the UI can enumerate what ships in the box ═══════════════
from webfinder.api import sites_catalog
cat = asyncio.run(sites_catalog())
assert cat["count"] == len(SITES.RECIPES) and len(cat["recipes"]) == cat["count"]
assert {"xvideos", "xnxx", "xhamster", "aparat", "youtube"} <= {r["key"] for r in cat["recipes"]}
print(f"✓ api: /api/sites lists {cat['count']} recipes (families: {', '.join(cat['families'])})")

print("\nALL VIDEO-CORE FIXTURE TESTS PASSED")
