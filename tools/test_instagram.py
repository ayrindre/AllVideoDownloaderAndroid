#!/usr/bin/env python3
"""All Video Downloader — Instagram checker (gallery-dl bridge) tests.

Fully offline: a stub "gallery-dl" is generated in a temp dir and driven through
the real bridge — command construction, JSON parsing (all dump shapes), source
normalisation, the scan task lifecycle, error mapping and the download hand-off.
The FastAPI routes are exercised in-process with TestClient.

Run:  python tools/test_instagram.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="avd-ig-"))
os.environ["AVD_HOME"] = str(TMP / "home")

from webfinder.config import settings
from webfinder.core import gallery as G  # noqa: E402

# ═══ stub engine: behaves like gallery-dl for the shapes we care about ══════
STUB = TMP / "fake_gallery_dl.py"
STUB.write_text(r'''
import json, sys
args = sys.argv[1:]
if "--version" in args:
    print("9.9.9"); raise SystemExit(0)
url = args[-1]
mode = "line" if "--line-mode" in open(__file__).read() else "array"
if "boom" in url:
    sys.stderr.write("[instagram][error] HttpError: '401 Unauthorized' (login required)\n")
    print("[]"); raise SystemExit(1)
if "empty" in url:
    print("[]"); raise SystemExit(0)

def post(code, user, day):
    return {"post_shortcode": code, "post_url": f"https://www.instagram.com/p/{code}/",
            "post_id": "1", "username": user, "fullname": "Test Account",
            "description": f"caption {code}", "date": day, "likes": 7, "type": "post", "count": 2}

def media(code, user, day):
    base = post(code, user, day)
    return [
        [3, f"https://cdn.example/{code}_1.jpg?x=1",
         {**base, "media_id": code + "1", "num": 1, "count": 2, "extension": "jpg",
          "filename": f"{code}_1", "display_url": f"https://cdn.example/{code}_1.jpg?x=1",
          "width": 1080, "height": 1350}],
        [3, f"https://cdn.example/{code}_2.mp4?x=1",
         {**base, "media_id": code + "2", "num": 2, "count": 2, "extension": "mp4",
          "filename": f"{code}_2", "display_url": f"https://cdn.example/{code}_2.jpg?x=1",
          "width": 1080, "height": 1920, "video_url": "v"}],
    ]

msgs = []
if "/reels/" in url:
    msgs += [[2, "", post("REEL1", "someone", 1000)]] + media("REEL1", "someone", 1000)
elif "/stories/" in url:
    msgs += [[2, "", post("STORY1", "someone", 2000)]] + media("STORY1", "someone", 2000)
elif "/highlights/" in url:
    msgs += [[2, "", post("HL1", "someone", 500)]] + media("HL1", "someone", 500)
elif "/tagged/" in url or "empty" in url:
    pass
elif "/p/" in url or "/reel/" in url:
    msgs += [[2, "", post("POST9", "someone", 3000)]] + media("POST9", "someone", 3000)
else:
    msgs += [[2, "", post("POST1", "someone", 900)]] + media("POST1", "someone", 900)
    msgs += [[2, "", post("POST2", "someone", 800)]] + media("POST2", "someone", 800)
msgs.append([6, "https://www.instagram.com/someone/tagged/", {"_extractor": None}])
if "--line-mode" in args:
    for m in msgs:
        print(json.dumps(m))
else:
    print(json.dumps(msgs, indent=2))
''', encoding="utf-8")

os.environ["AVD_GALLERYDL_BIN"] = f"{sys.executable} {STUB}"
G.detect.cache_clear()

# ═══ engine detection reads the override command line ══════════════════════
d = G.detect()
assert d["available"] and d["version"] == "9.9.9", d
assert d["cmd"][0] == sys.executable and d["cmd"][-1].endswith("fake_gallery_dl.py"), d["cmd"]
print("✓ engine: AVD_GALLERYDL_BIN accepts a binary OR a full command line")

# ═══ source normalisation: handles, profile/post/story URLs, foreign sites ══
assert G.parse_source("@nasa")["username"] == "nasa"
assert G.parse_source("nasa")["username"] == "nasa"
assert G.parse_source("https://www.instagram.com/nasa/")["url"] == "https://www.instagram.com/nasa/"
assert G.parse_source("instagram.com/nasa")["kind"] == "profile"
post_src = G.parse_source("https://www.instagram.com/p/CxYz123/")
assert post_src["kind"] == "post" and post_src["code"] == "CxYz123"
story_src = G.parse_source("https://www.instagram.com/stories/nasa/987/")
assert story_src["kind"] == "story" and story_src["username"] == "nasa"
scoped = G.parse_source("https://www.instagram.com/nasa/reels/")
assert scoped["kind"] == "profile" and scoped["scoped"] == "reels"
other = G.parse_source("https://example.org/gallery/42")
assert other["kind"] == "url" and other["url"].endswith("/gallery/42"), other
for bad in ("", "   ", "not a url at all"):
    try:
        G.parse_source(bad)
        raise AssertionError(f"{bad!r} should be rejected")
    except ValueError:
        pass
print("✓ source: @handle / handle / profile / post / story / scoped tab / other site")

# ═══ targets: validation + saved defaults ══════════════════════════════════
assert G.clean_targets(["posts", "junk", "reels"]) == ["posts", "reels"]
assert G.clean_targets("posts, stories") == ["posts", "stories"]
assert G.clean_targets([]) == ["posts", "reels"]           # DEFAULTS
assert set(G.clean_targets(["tagged"])) == {"tagged"}
print("✓ targets: invalid keys dropped, empty list falls back to saved defaults")

# ═══ command line: merged video, no silent DASH, cookies, proxy, range ═════
cmd = G.build_cmd("https://www.instagram.com/nasa/posts/", cookies="chrome",
                  proxy="socks5://127.0.0.1:1080", limit=25, delay="3-6")
blob = " ".join(cmd)
assert "-j" in cmd and not any(a in cmd for a in ("--simulate", "download")), cmd
assert "extractor.instagram.videos=merged" in blob, "progressive (audio-muxed) video is required"
assert "extractor.instagram.audio=false" in blob and "extractor.instagram.previews=false" in blob
assert "--post-range 1-25" in blob and "--cookies-from-browser chrome" in blob
assert "--proxy socks5://127.0.0.1:1080" in blob and "--sleep-request 3-6" in blob
assert cmd[-1] == "https://www.instagram.com/nasa/posts/"
plain = " ".join(G.build_cmd("https://www.instagram.com/nasa/posts/"))
assert "--cookies-from-browser" not in plain and "--post-range" not in plain
print("✓ cmd: -j dump, merged video, no previews/audio, cookies/proxy/range wired")

# ═══ dump parsing: array, JSON-lines, errors, ytdl placeholders ════════════
DUMP = json.dumps([
    [2, "", {"post_shortcode": "ABC", "post_url": "https://www.instagram.com/p/ABC/",
             "username": "nasa", "fullname": "NASA", "description": "moon\n#space",
             "date": 1700000000, "likes": 12, "type": "reel", "count": 2}],
    [3, "https://cdn.example/ABC_1.mp4?token=1",
     {"post_shortcode": "ABC", "username": "nasa", "fullname": "NASA", "media_id": "111",
      "num": 1, "count": 2, "extension": "mp4", "display_url": "https://cdn.example/p.jpg",
      "width": 1080, "height": 1920, "video_url": "x", "date": 1700000000}],
    [3, "https://cdn.example/ABC_2.jpg?token=2",
     {"post_shortcode": "ABC", "username": "nasa", "media_id": "222", "num": 2, "count": 2,
      "extension": "jpg", "display_url": "https://cdn.example/ABC_2.jpg?token=2",
      "date": 1700000000}],
    [3, "ytdl:https://www.instagram.com/p/ABC/3.mp4", {"media_id": "333", "extension": "mp4"}],
    [6, "https://www.instagram.com/nasa/tagged/", {}],
    [-1, {"error": "HttpError", "message": "401 Unauthorized"}],
], indent=2)
parsed = G.parse_dump(DUMP)
assert len(parsed["items"]) == 2, parsed["items"]      # ytdl placeholder dropped
vid, img = parsed["items"]
assert vid["kind"] == "video" and vid["ext"] == "mp4" and vid["filename"] == "nasa_ABC_1.mp4"
assert img["kind"] == "image" and img["filename"] == "nasa_ABC_2.jpg"
assert vid["caption"] == "moon #space" and vid["date"] == 1700000000 and vid["likes"] == 12
assert vid["thumbnail"].endswith("p.jpg") and img["thumbnail"] == img["url"]
assert parsed["posts"][0]["post"] == "ABC" and parsed["posts"][0]["type"] == "reel"
assert parsed["errors"] == ["401 Unauthorized"] and parsed["queues"]
print("✓ parse: items normalized (video/photo, filename, caption, poster), post metadata kept")

# JSON-lines shape (output.jsonl) must parse too
lines = "\n".join(json.dumps(m) for m in json.loads(DUMP))
assert len(G.parse_dump(lines)["items"]) == 2
# garbage / empty dumps never raise
assert G.parse_dump("")["items"] == []
assert G.parse_dump("[garbage")["items"] == []
assert G.parse_dump('[{"url": "https://x/y.mp4", "extension": "mp4"}]')["items"][0]["ext"] == "mp4"
print("✓ parse: JSON-lines + bare objects + malformed output all handled")

# ═══ full scan lifecycle through the real bridge ═══════════════════════════
def wait(scan_id, limit=30.0):
    t0 = time.time()
    while time.time() - t0 < limit:
        snap = G.get_scan(scan_id)
        if snap and snap["status"] not in ("queued", "scanning"):
            return snap
        time.sleep(0.1)
    raise AssertionError("scan did not finish")

snap = G.start_scan("https://www.instagram.com/nasa/",
                    include=["posts", "reels", "tagged"], limit=20)
assert snap["status"] in ("queued", "scanning")
final = wait(snap["id"])
assert final["status"] == "done", final["errors"]
assert [t["key"] for t in final["targets"]] == ["posts", "reels", "tagged"]
tab = {t["key"]: t["status"] for t in final["targets"]}
assert tab == {"posts": "done", "reels": "done", "tagged": "empty"}, tab
assert final["counts"] == {"total": 6, "videos": 3, "images": 3, "posts": 3}, final["counts"]
names = {i["filename"] for i in final["items"]}
assert {"someone_POST1_1.jpg", "someone_POST1_2.mp4",
        "someone_REEL1_1.jpg"} <= names, names
assert {i["target"] for i in final["items"]} == {"posts", "reels"}
assert final["items"] == sorted(final["items"], key=lambda i: -(i["date"] or 0)), "newest first"
assert final["progress"]["done"] == 3 and final["username"] == "nasa"
print("✓ scan: per-tab status (done/empty), counts, newest-first, username")

# single post + story URLs take one target each
one = wait(G.start_scan("https://www.instagram.com/p/POST9/")["id"])
assert len(one["targets"]) == 1 and one["targets"][0]["key"] == "post"
assert one["counts"]["total"] == 2
story = wait(G.start_scan("https://www.instagram.com/stories/nasa/1/")["id"])
assert story["targets"][0]["key"] == "story" and story["counts"]["total"] == 2
print("✓ scan: post/story links are single-target scans")

# ═══ failures are honest: 401 → cookie hint, no crash ══════════════════════
bad = wait(G.start_scan("https://www.instagram.com/boom/", include=["posts"])["id"])
assert bad["status"] == "error" and bad["items"] == []
assert any("Browser cookies source" in e for e in bad["errors"]), bad["errors"]
print("✓ error: 401 mapped to the cookie-source fix (not a dead end)")

# a raw gallery-dl crash (blocked connection, changed layout) gets an actionable wrap
assert "gallery-dl could not read the page" in G.explain_error(
    "cannot access local variable 'page' where it is not associated with a value")
assert "Network proxy" in G.explain_error("Failed to resolve 'instagram.com'")
assert "Browser cookies source" in G.explain_error("HttpError: '401 Unauthorized'")
clean = G._friendly_stderr('Traceback (most recent call last):\n  File "x.py", line 3\n'
                           'UnboundLocalError: boom\n')
assert clean == "boom", clean            # traceback frames never reach the UI
print("✓ errors: tracebacks trimmed, crash/login/network each get the right fix hint")

# nothing found → explicit explanation instead of a silent empty screen
nothing = wait(G.start_scan("https://www.instagram.com/empty/", include=["posts"])["id"])
assert nothing["status"] == "error" and any("No media found" in e for e in nothing["errors"])
print("✓ empty: tells the user why (private/empty/no session) instead of nothing")

# ═══ cancel stops a running scan ═══════════════════════════════════════════
slow = G.start_scan("https://www.instagram.com/nasa/", include=["posts", "reels", "tagged"])
assert G.cancel_scan(slow["id"]) is True
cancelled = G.get_scan(slow["id"])
assert cancelled["status"] in ("cancelled", "done"), cancelled["status"]
assert G.cancel_scan("nope") is False
print("✓ cancel: running scan stops, unknown id returns False")

# ═══ job hand-off carries Instagram headers + a sane filename ══════════════
job = G.to_job(final["items"][0])
assert job["kind"] == "http" and job["url"].startswith("https://cdn.example/")
assert job["filename"].endswith((".mp4", ".jpg")) and job["file_type"] in ("video", "image")
assert job["meta"]["referer"] == "https://www.instagram.com/"
assert job["meta"]["headers"]["Referer"] == "https://www.instagram.com/"
print("✓ job: http worker + Instagram Referer, filename/type derived from the item")

# ═══ engine info for the UI ════════════════════════════════════════════════
info = G.gallery_engine_info()
assert info["available"] and info["version"] == "9.9.9"
assert [t["key"] for t in info["targets"]] == ["posts", "reels", "stories", "highlights", "tagged"]
assert info["defaults"]["include"] and info["defaults"]["limit"] == 30
print("✓ engine info: tabs, defaults and version for the UI badge")

# ═══ HTTP API: engine, scan→poll, cancel, download enqueue ═════════════════
from fastapi.testclient import TestClient  # noqa: E402
from webfinder.app import app  # noqa: E402

client = TestClient(app)
r = client.get("/api/gallery/engine")
assert r.status_code == 200 and r.json()["available"] is True
assert client.get("/api/gallery/scan/unknown").status_code == 404

r = client.post("/api/gallery/scan", json={"url": "@nasa", "include": ["posts"], "limit": 5})
assert r.status_code == 200, r.text
sid = r.json()["scan"]["id"]
for _ in range(200):
    body = client.get(f"/api/gallery/scan/{sid}").json()["scan"]
    if body["status"] not in ("queued", "scanning"):
        break
    time.sleep(0.05)
assert body["status"] == "done" and body["counts"]["total"] == 4, body
assert client.get("/api/gallery/scans").json()["scans"]

assert client.post("/api/gallery/scan", json={"url": "  "}).status_code == 400

queued = []
import webfinder.api as api_mod  # noqa: E402


class _FakeJob:
    id = "fake"


def _fake_enqueue(**kw):
    queued.append(kw)
    return _FakeJob()


orig_enqueue = api_mod.manager.enqueue
api_mod.manager.enqueue = _fake_enqueue
try:
    r = client.post("/api/gallery/download", json={"items": [
        {"url": "https://cdn.example/a.mp4", "filename": "a.mp4", "kind": "video"},
        {"url": "notaurl", "filename": "nope"},
        {"url": "https://cdn.example/b.jpg", "filename": "b.jpg", "kind": "image"}]})
finally:
    api_mod.manager.enqueue = orig_enqueue
assert r.status_code == 200 and r.json()["queued"] == 2, r.text
assert [q["kind"] for q in queued] == ["http", "http"]
assert queued[0]["meta"]["referer"] == "https://www.instagram.com/"
assert client.post("/api/gallery/download", json={"items": []}).status_code == 400
print("✓ api: /gallery/{engine,scan,scans,download} wired, junk items skipped, empty → 400")

# ═══ cookies: cookies.txt wins, a broken browser DB is remembered ═════════
from webfinder.core import cookies as CK  # noqa: E402

tmp = Path(tempfile.mkdtemp())
jar = tmp / "cookies.txt"
jar.write_text("# Netscape HTTP Cookie File\n"
               ".instagram.com\tTRUE\t/\tTRUE\t1900000000\tsessionid\tabc\n"
               ".youtube.com\tTRUE\t/\tTRUE\t1900000000\tSID\txyz\n", encoding="utf-8")
empty = tmp / "empty.txt"
empty.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")

cfg = {"ytdlp_browser_cookies": "", "cookies_file": "", "proxy": "", "instagram_include": "posts,reels",
       "instagram_limit": 30, "instagram_delay": ""}
settings._data.update(cfg)
CK.reset()
assert CK.probe()["ok"] is False and "logged out" in CK.probe()["message"]

settings._data.update({"ytdlp_browser_cookies": "chrome"})
assert CK.ytdlp_flags() == ["--cookies-from-browser", "chrome"]
assert CK.gallery_flags() == ["--cookies-from-browser", "chrome"]
assert CK.module_opts() == {"cookiesfrombrowser": ("chrome",)}
print("✓ cookies: browser source reaches yt-dlp (CLI + module) and gallery-dl")

# a cookies.txt beats the browser, and a bad file is reported, not silently used
settings._data.update({"cookies_file": str(jar)})
assert CK.ytdlp_flags() == ["--cookies", str(jar)]
assert CK.gallery_flags() == ["--cookies", str(jar)]
assert CK.module_opts() == {"cookiefile": str(jar)}
assert CK.probe()["ok"] and CK.probe()["count"] == 2
settings._data.update({"cookies_file": str(empty)})
assert CK.probe()["ok"] is False and "no cookie rows" in CK.probe()["message"]
settings._data.update({"cookies_file": str(tmp / "nope.txt")})
assert CK.probe()["ok"] is False and "not found" in CK.probe()["message"]
settings._data.update({"cookies_file": ""})
print("✓ cookies: cookies.txt wins over the browser, empty/missing file explained")

# the Chrome wall: remembered once, then skipped — and the flag is gone
assert CK.mark_browser_failure("ERROR: Could not copy Chrome cookie database") is True
assert CK.browser_failure() and CK.ytdlp_flags() == [] and CK.gallery_flags() == [] and CK.module_opts() == {}
assert "unreadable" in CK.used_source()
CK.reset()
assert CK.ytdlp_flags() == ["--cookies-from-browser", "chrome"]      # a new source is retried
print("✓ cookies: one unreadable-DB failure is remembered instead of retried forever")

# a scan that hits the wall retries anonymously and SAYS so
calls = []
real_dump = G.run_dump


def fake_dump(url, **kw):
    calls.append(kw.get("cookies"))
    if len(calls) == 1:
        return {"items": [], "errors": ["Could not copy Chrome cookie database"], "posts": [],
                "raw_error": "ERROR: Could not copy Chrome cookie database"}
    return {"items": [{"id": "1", "url": "https://cdn/x.jpg", "kind": "image", "ext": "jpg",
                       "filename": "x.jpg", "post": "P", "date": 1, "username": "u"}],
            "errors": [], "posts": [], "raw_error": ""}


G.run_dump = fake_dump
CK.reset()
try:
    snap = G.start_scan("@nasa", include=["posts"], limit=3, cookie_source="chrome")
    for _ in range(200):
        body = G.get_scan(snap["id"])
        if body["status"] not in ("queued", "scanning"):
            break
        time.sleep(0.05)
finally:
    G.run_dump = real_dump

assert calls == ["chrome", ""], calls            # retried logged out
assert body["status"] == "done" and body["counts"]["total"] == 1
assert body["warnings"] and "logged out" in body["warnings"][0]
assert body["cookies"]["browser_failed"] is True
print("✓ cookies: a 401/DB wall retries anonymously and warns instead of dying")

# the API exposes the probe so the UI can offer a "Check cookies" button
r = client.get("/api/cookies/status")
assert r.status_code == 200 and "mode" in r.json()
CK.reset()
r = client.get("/api/cookies/probe")
assert r.status_code == 200 and r.json()["ok"] is False
assert "cookies" in client.get("/api/meta").json()["system"]
print("✓ api: /cookies/{status,probe} + meta.cookies for the settings button")

settings._data.update(cfg)
CK.reset()

print("\nINSTAGRAM CHECKER TESTS PASSED")
