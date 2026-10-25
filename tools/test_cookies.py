#!/usr/bin/env python3
"""All Video Downloader — cookie-source tests (yt-dlp CLI, module, downloader).

The wall these guard against is yt-dlp issue 7271: on Windows Chrome keeps its
cookie database locked (and 127+ App-Bound-encrypts it), so every attempt to
read cookies fails identically. The app must (a) prefer a cookies.txt when the
user supplies one, (b) forget the broken browser source after the FIRST failure
instead of retrying it for every extraction and download, and (c) still explain
what to fix.

Run:  python tools/test_cookies.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="avd-ck-"))
os.environ["AVD_HOME"] = str(TMP / "home")

from webfinder.config import CONFIG_DIR, settings            # noqa: E402
from webfinder.core import cookies as CK                    # noqa: E402
from webfinder.core import ytcli                            # noqa: E402
from webfinder.core import gallery as G                     # noqa: E402

BASE = {"ytdlp_browser_cookies": "", "cookies_file": "", "proxy": "", "default_container": "mp4"}
settings._data.update(BASE)


def reset(**kw):
    CK.reset()
    settings._data.update({**BASE, **kw})


# ═══ nothing configured → no flags, honest probe ═══════════════════════════
reset()
assert CK.ytdlp_flags() == [] and CK.gallery_flags() == [] and CK.module_opts() == {}
probe = CK.probe()
assert probe["ok"] is False and "logged out" in probe["message"]
assert CK.used_source() == "anonymous"
print("✓ default: no cookie source, anonymous flags, probe says so")

# ═══ browser source reaches every engine ══════════════════════════════════
reset(ytdlp_browser_cookies="firefox")
assert ytcli._cookie_flags() == ["--cookies-from-browser", "firefox"]
cmd = ytcli.download_cmd("https://x/y", outdir=str(TMP), outstem="v", fmt="bv*+ba/b",
                         container="mp4")
assert "--cookies-from-browser" in cmd and "firefox" in cmd
opts = __import__("webfinder.core.media", fromlist=["x"]).base_yt_opts()
assert opts["cookiesfrombrowser"] == ("firefox",)
print("✓ browser: yt-dlp CLI, yt-dlp module and the download command all use it")

# ═══ cookies.txt wins everywhere ═════════════════════════════════════════
jar = TMP / "cookies.txt"
jar.write_text("# Netscape HTTP Cookie File\n"
               ".instagram.com\tTRUE\t/\tTRUE\t1900000000\tsessionid\tabc\n"
               ".youtube.com\tTRUE\t/\tTRUE\t1900000000\tSID\txyz\n", encoding="utf-8")
reset(ytdlp_browser_cookies="firefox", cookies_file=str(jar))
assert CK.ytdlp_flags() == ["--cookies", str(jar)]
assert CK.gallery_flags() == ["--cookies", str(jar)]
assert CK.module_opts() == {"cookiefile": str(jar)}
cmd = ytcli.download_cmd("https://x/y", outdir=str(TMP), outstem="v", fmt="b", container="mp4")
assert "--cookies" in cmd and str(jar) in cmd and "--cookies-from-browser" not in cmd
assert CK.probe()["ok"] and CK.probe()["count"] == 2
assert "cookies.txt" in CK.used_source()
print("✓ cookies.txt: beats the browser for yt-dlp, the module, gallery-dl and downloads")

# ═══ a browser failure is remembered, not retried per request ════════════
reset(ytdlp_browser_cookies="chrome")
assert ytcli._cookie_flags() == ["--cookies-from-browser", "chrome"]
assert CK.mark_browser_failure("ERROR: Could not copy Chrome cookie database. See ...") is True
assert CK.browser_failure()
assert ytcli._cookie_flags() == []                       # second extraction: no read
cmd = ytcli.download_cmd("https://x/y", outdir=str(TMP), outstem="v", fmt="b", container="mp4")
assert "--cookies-from-browser" not in cmd              # downloads stop paying the timeout
assert CK.used_source().startswith("anonymous")
print("✓ failure memory: after ONE cookie-DB error nothing re-reads the browser")

# ...but a *different* message must not poison the source, and a new choice resets it
reset(ytdlp_browser_cookies="chrome")
assert CK.mark_browser_failure("HTTP Error 404: Not Found") is False
assert CK.browser_failure() == "" and ytcli._cookie_flags() == ["--cookies-from-browser", "chrome"]
CK.mark_browser_failure("Could not copy Chrome cookie database")
assert CK.browser_failure()
CK.reset()
assert ytcli._cookie_flags() == ["--cookies-from-browser", "chrome"]
print("✓ failure memory: unrelated errors ignored, changing the source clears it")

# ═══ anonymous retry drops BOTH sources, never the URL ═══════════════════
args = ["yt-dlp", "--no-warnings", "--cookies-from-browser", "chrome", "--cookies", "x.txt",
        "-f", "b", "https://site/watch?v=1"]
assert CK.strip_flags(args) == ["yt-dlp", "--no-warnings", "-f", "b", "https://site/watch?v=1"]
assert CK.strip_flags(["--cookies-file", "c.txt", "u"]) == ["u"]
print("✓ retry: cookie flags (and only those) are stripped for the anonymous pass")

# ═══ the probe explains each broken case ═════════════════════════════════
missing = TMP / "missing.txt"
reset(cookies_file=str(missing))
assert "not found" in CK.probe()["message"]
empty = TMP / "empty.txt"
empty.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
reset(cookies_file=str(empty))
assert "no cookie rows" in CK.probe()["message"]
reset(cookies_file=str(TMP))                  # a directory is not a cookies file
assert CK.file_usable() is False
print("✓ probe: missing / empty / not-a-file each get their own message")

from fastapi.testclient import TestClient                  # noqa: E402
from webfinder.app import app                               # noqa: E402

client = TestClient(app)

# ═══ "the user picked the wrong browser" — use one whose DB reads ════════
real_read = CK._read_browser
# chrome (configured) is locked; firefox has a live Instagram session
def fake_read(name):
    if name == "firefox":
        return True, 42, 3, "42 cookies readable from firefox."
    if name == "chrome":
        return False, 0, 0, CK.EXPLAIN
    return False, 0, 0, f"{name} has no cookie database on this machine"


CK._read_browser = fake_read
try:
    reset(ytdlp_browser_cookies="chrome")
    assert CK.ytdlp_flags() == ["--cookies-from-browser", "chrome"]

    # the first failure flips everything to the readable browser, automatically
    assert CK.mark_browser_failure("Could not copy Chrome cookie database")
    assert CK.auto_browser() == "firefox"
    assert CK.active_browser() == "firefox"
    assert CK.ytdlp_flags() == ["--cookies-from-browser", "firefox"]
    assert CK.gallery_flags() == ["--cookies-from-browser", "firefox"]
    assert CK.module_opts() == {"cookiesfrombrowser": ("firefox",)}
    src = CK.source()
    assert src["browser"] == "chrome" and src["active_browser"] == "firefox"
    assert src["mode"] == "browser" and src["browser_failed"] is True
    print("✓ fallback: a locked browser is replaced by the readable one automatically")

    # the probe offers the switch, and one call applies it
    pr = CK.probe()
    assert pr["ok"] is False and pr["suggest"] == "firefox", pr
    assert "firefox" in pr["message"]
    r = CK.use_best()
    assert r["ok"] and r["browser"] == "firefox"
    assert settings.get("ytdlp_browser_cookies") == "firefox"
    assert CK.browser_failure() == "" and CK.ytdlp_flags() == ["--cookies-from-browser", "firefox"]
    print("✓ fallback: probe suggests it, use_best() saves it (the one-click fix)")

    # a scan retries with that browser and says so
    settings._data.update({"ytdlp_browser_cookies": "chrome"})
    CK._browser_failure = ""
    calls = []
    real_dump = G.run_dump

    def fake_dump(url, **kw):
        calls.append(kw.get("cookies"))
        if len(calls) == 1:
            return {"items": [], "errors": ["Could not copy Chrome cookie database"],
                    "posts": [], "raw_error": "ERROR: Could not copy Chrome cookie database"}
        return {"items": [{"id": "1", "url": "https://cdn/x.jpg", "kind": "image", "ext": "jpg",
                           "filename": "x.jpg", "post": "P", "date": 1, "username": "u"}],
                "errors": [], "posts": [], "raw_error": ""}

    G.run_dump = fake_dump
    reset(ytdlp_browser_cookies="chrome")
    try:
        snap = G.start_scan("@nasa", include=["posts"], limit=3, cookie_source="chrome")
        for _ in range(200):
            body = G.get_scan(snap["id"])
            if body["status"] not in ("queued", "scanning"):
                break
            time.sleep(0.05)
    finally:
        G.run_dump = real_dump
    assert calls == ["chrome", "firefox"], calls
    assert body["status"] == "done" and body["counts"]["total"] == 1
    assert "firefox" in body["warnings"][0] and "readable" in body["warnings"][0]
    print("✓ fallback: the scan itself retries with firefox and explains why")

    # ...and the API exposes the one-click fix
    r = client.post("/api/cookies/use-best")
    assert r.status_code == 200 and r.json()["browser"] == "firefox", r.text
    assert settings.get("ytdlp_browser_cookies") == "firefox"
    print("✓ api: POST /cookies/use-best applies the readable browser")
finally:
    CK._read_browser = real_read

# ═══ readable cookies ≠ Instagram login (the tab was "broken" for this) ══
jar2 = TMP / "only-youtube.txt"
jar2.write_text("# Netscape HTTP Cookie File\n"
                ".youtube.com\tTRUE\t/\tTRUE\t1900000000\tSID\txyz\n", encoding="utf-8")
reset(cookies_file=str(jar2))
sess = CK.instagram_session()
assert sess["instagram"] is False and "cookies.txt" in sess["source"]
assert CK.probe()["ok"] is True                      # the file itself is fine

jar3 = TMP / "ig.txt"
jar3.write_text("# Netscape HTTP Cookie File\n"
                ".instagram.com\tTRUE\t/\tTRUE\t1900000000\tsessionid\tabc\n", encoding="utf-8")
reset(cookies_file=str(jar3))
assert CK.instagram_session()["instagram"] is True
print("✓ session: a readable source without an Instagram login is detected")

# a scan that finds nothing then explains exactly that
real_dump2 = G.run_dump
G.run_dump = lambda url, **kw: {"items": [], "errors": [], "posts": [], "raw_error": ""}
reset(cookies_file=str(jar2))
try:
    snap = G.start_scan("@nasa", include=["posts"], limit=3)
    for _ in range(200):
        body = G.get_scan(snap["id"])
        if body["status"] not in ("queued", "scanning"):
            break
        time.sleep(0.05)
finally:
    G.run_dump = real_dump2
assert body["warnings"] and "no Instagram login" in body["warnings"][0], body["warnings"]
print("✓ session: an empty scan says 'cookies are readable but have no Instagram login'")

# ═══ a site login wall is NOT a broken cookie source ═════════════════════
reset(ytdlp_browser_cookies="")
assert CK.mark_browser_failure("HttpError: '401 Unauthorized' (login required)") is False
assert CK.mark_browser_failure("ERROR: Could not copy Chrome cookie database") is False  # no source in use
assert CK.browser_failure() == ""
reset(ytdlp_browser_cookies="chrome")
assert CK.mark_browser_failure("HttpError: '401 Unauthorized' (login required)") is False
assert CK.browser_failure() == "" and CK.active_browser() == "chrome"
assert CK.mark_browser_failure("Could not copy Chrome cookie database") is True
print("✓ guard: 401s never masquerade as a broken browser cookie database")

# ── pasted session: the escape hatch when the browser's cookie DB is locked ──
# (sandbox-proven: mock Instagram returns 0 posts logged out, 4 files with a
#  pasted sessionid and nothing else changed)
def parse(raw):
    return CK.parse_cookie_input(raw)


assert parse("5123%3Aabc%3A9").get("cookies", {}).get("sessionid") == "5123%3Aabc%3A9"
hdr = parse("Cookie: sessionid=S1; csrftoken=C1; ds_user_id=42").get("cookies", {})
assert hdr.get("sessionid") == "S1" and hdr.get("csrftoken") == "C1", hdr
assert parse('{"sessionid": "S2"}').get("cookies", {}).get("sessionid") == "S2"
full = parse("# Netscape HTTP Cookie File\n.instagram.com\tTRUE\t/\tTRUE\t1999999999\tsessionid\tS3\n")
assert (full.get("cookiestxt") and "S3" in full["cookiestxt"]) or \
    full.get("cookies", {}).get("sessionid") == "S3", full
assert not parse("").get("cookies") and not parse("").get("cookiestxt")
assert parse("csrftoken=only").get("cookies", {}).get("csrftoken") == "only"
print("✓ session: bare value, cookie: header, JSON and a whole cookies.txt all parse")

sess_path = CK.instagram_cookie_path()
assert sess_path.endswith("instagram-cookies.txt") and str(CONFIG_DIR) in sess_path
r = CK.save_instagram_session("Cookie: sessionid=SESS%3A42; csrftoken=CSRF; ds_user_id=42")
assert r["ok"] and Path(sess_path).is_file(), r
rows = [x for x in Path(sess_path).read_text().splitlines() if x and not x.startswith("#")]
assert len(rows) == 3 and rows[0].split("\t")[5] == "sessionid", rows
assert oct(os.stat(sess_path).st_mode)[-3:] == "600"
assert str(settings.get("cookies_file") or "").endswith("instagram-cookies.txt"), settings.get("cookies_file")
assert sess_path in " ".join(CK.gallery_flags()) and sess_path in " ".join(CK.ytdlp_flags())
assert CK.count_netscape(sess_path) == 3
print("✓ session: written as a 600 cookies.txt and used by gallery-dl AND yt-dlp")

st = CK.instagram_session()
assert st.get("instagram") and "instagram-cookies.txt" in (st.get("source") or ""), st
print("✓ session: the status pill reports the imported session as the active source")

bad = CK.save_instagram_session("nothing=1")
assert bad["ok"] is False and "sessionid" in bad["message"], bad
assert "sessionid" in Path(sess_path).read_text()      # a failed paste keeps the good one
bad2 = CK.save_instagram_session("")
assert bad2["ok"] is False
print("✓ session: a paste without sessionid is refused and does not clobber the working one")

# the login wall must NOT be reported as a broken cookie database
assert not CK.is_cookie_error("Failed to load API data (KeyError: 'data')")
assert not CK.is_cookie_error("Expecting value: line 1 column 1 (char 0)")
assert CK.is_cookie_error("Unable to find Chrome cookies database in /x")
assert CK.is_cookie_error("SecurityError: Failed to decrypt with DPAPI")
wall = G.explain_error("Expecting value: line 1 column 1 (char 0)")
assert "session" in wall.lower() and "cookie database" not in wall.lower(), wall
print("✓ session: a login wall tells the user to paste a session, not to fix their cookie DB")

reset()
print("\nCOOKIE TESTS PASSED")
