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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="avd-ck-"))
os.environ["AVD_HOME"] = str(TMP / "home")

from webfinder.config import settings                      # noqa: E402
from webfinder.core import cookies as CK                    # noqa: E402
from webfinder.core import ytcli                            # noqa: E402

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

reset()
print("\nCOOKIE TESTS PASSED")
