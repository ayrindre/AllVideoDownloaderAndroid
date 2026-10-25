"""All Video Downloader — one answer to "which cookies does this run use?".

Two sources, in this order:

1. **A cookies.txt file** (Settings → Video & capture → *Cookies file*). This is
   the reliable path: a browser can keep its database locked or App-Bound
   encrypted (Chrome 127+ on Windows, yt-dlp issue #7271), while an exported
   Netscape cookie file always reads.
2. **A browser profile** (chrome/edge/firefox/…), read by yt-dlp and gallery-dl.

A browser read that fails once is remembered for the whole session. That matters:
the failure mode is "the file is locked", which repeats identically for every
request, so without this the log fills with the same ERROR line for every single
extraction and download attempt. Once we know the DB is unreadable we go
straight to the anonymous path and tell the user exactly what to fix.
"""
from __future__ import annotations

import re
import threading
from pathlib import Path

from ..config import settings

# yt-dlp / gallery-dl / our own wording for "the cookie source did not work"
_COOKIE_ERR = re.compile(
    r"could not copy|cookie database|browser cookies|unable to (?:read|load|decrypt)"
    r"|failed to (?:read|load|decrypt)|cookie(?:s)? (?:file|not found|is empty)"
    r"|app[- ]bound|decrypt(?:ion)? (?:failed|key)|permission denied.*cookie",
    re.I)

# a message we never want to show twice: it is a *setup* problem, not a job error
EXPLAIN = ("The browser's cookie database could not be read — Chrome holds it open while "
           "running, and Chrome 127+ on Windows also App-Bound-encrypts it. Fully quit the "
           "browser (tray icon too), pick Firefox, or export a cookies.txt and set "
           "Settings → Video & capture → Cookies file. Until then the app runs logged out.")

_lock = threading.Lock()
_browser_failure = ""          # first failure message in this process


# ---------------------------------------------------------------------------
# Settings accessors
# ---------------------------------------------------------------------------
def browser() -> str:
    """Configured browser name ('' = no browser source)."""
    return str(settings.get("ytdlp_browser_cookies") or "").strip().lower()


def cookie_file() -> str:
    """Configured cookies.txt path, or '' when unset (existence is checked)."""
    raw = str(settings.get("cookies_file") or "").strip().strip('"')
    if not raw:
        return ""
    return str(Path(raw).expanduser())


def file_usable() -> bool:
    path = cookie_file()
    return bool(path) and Path(path).is_file()


def source() -> dict:
    """What the engines would use right now — handy for the UI/meta payload."""
    path = cookie_file()
    failed = browser_failure()
    return {
        "browser": browser(),
        "file": path,
        "file_ok": file_usable(),
        "mode": "file" if file_usable() else ("browser" if browser() and not failed else ""),
        "browser_failed": bool(failed),
        "error": failed,
    }


# ---------------------------------------------------------------------------
# Session memory of a broken browser source
# ---------------------------------------------------------------------------
def browser_failure() -> str:
    with _lock:
        return _browser_failure


def is_cookie_error(msg: str) -> bool:
    return bool(_COOKIE_ERR.search(msg or ""))


def mark_browser_failure(msg: str = "") -> bool:
    """Remember that the browser DB is unreadable. True when it *was* that kind
    of failure (so callers can retry anonymously instead of surfacing it)."""
    global _browser_failure
    if not is_cookie_error(msg):
        return False
    with _lock:
        if not _browser_failure:
            _browser_failure = (msg or EXPLAIN).strip()[:300]
    return True


def reset() -> None:
    """Forget the failure (settings changed / tests)."""
    global _browser_failure
    with _lock:
        _browser_failure = ""


# ---------------------------------------------------------------------------
# Flags for the two engines
# ---------------------------------------------------------------------------
def ytdlp_flags() -> list[str]:
    """Extra CLI flags for the system yt-dlp binary."""
    if file_usable():
        return ["--cookies", cookie_file()]
    name = browser()
    if name and not browser_failure():
        return ["--cookies-from-browser", name]
    return []


def gallery_flags() -> list[str]:
    """Extra CLI flags for gallery-dl."""
    if file_usable():
        return ["--cookies", cookie_file()]
    name = browser()
    if name and not browser_failure():
        return ["--cookies-from-browser", name]
    return []


def module_opts() -> dict:
    """Fragment for a ``yt_dlp.YoutubeDL`` options dict."""
    if file_usable():
        return {"cookiefile": cookie_file()}
    name = browser()
    if name and not browser_failure():
        return {"cookiesfrombrowser": (name,)}
    return {}


_FLAG_WITH_VALUE = ("--cookies-from-browser", "--cookies", "--cookies-file")


def strip_flags(args: list[str]) -> list[str]:
    """Remove every cookie flag (and its value) — the anonymous retry."""
    out: list[str] = []
    skip = False
    for a in args:
        if skip:
            skip = False
            continue
        if a in _FLAG_WITH_VALUE:
            skip = True
            continue
        out.append(a)
    return out


def used_source() -> str:
    """Human label of what a run actually uses (for logs / job meta)."""
    if file_usable():
        return f"cookies.txt ({Path(cookie_file()).name})"
    if browser() and not browser_failure():
        return f"{browser()} cookies"
    if browser_failure():
        return "anonymous (browser cookies unreadable)"
    return "anonymous"


# ---------------------------------------------------------------------------
# Diagnostics — the "Check cookies" button
# ---------------------------------------------------------------------------
def count_netscape(path: str) -> int:
    """Number of real cookie rows in a Netscape cookies.txt (0 = empty/invalid)."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return 0
    n = 0
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") and not line.startswith("#HttpOnly_"):
            continue
        if len(line.split("\t")) >= 7:
            n += 1
    return n


def _probe_browser(name: str) -> tuple[bool, int, str]:
    """Read the browser's cookies *locally* (no network) and report what broke."""
    try:
        from yt_dlp.cookies import extract_cookies_from_browser  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001 — yt-dlp missing
        return False, 0, f"yt-dlp is not available to read cookies ({exc})"
    try:
        jar = extract_cookies_from_browser(name)
        n = len(jar)
    except Exception as exc:  # noqa: BLE001 — every failure is a user-facing message
        raw = str(exc) or exc.__class__.__name__
        if is_cookie_error(raw):
            mark_browser_failure(raw)
            return False, 0, EXPLAIN
        if "could not find" in raw.lower() or "no such file" in raw.lower():
            return False, 0, (f"{name} has no cookie database on this machine ({raw[:150]}) — "
                              f"is it installed and signed in? Firefox is the most reliable "
                              "source, or point “Cookies file” at an exported cookies.txt.")
        return False, 0, f"Could not read {name} cookies: {raw[:220]}"
    if not n:
        return False, 0, (f"{name} answered but returned no cookies — open {name}, log in to the "
                          "site you need, then check again.")
    return True, n, f"{n} cookies readable from {name}."


def probe() -> dict:
    """Check whatever cookie source is configured. Never raises."""
    path = cookie_file()
    if path:
        if not Path(path).is_file():
            return {"ok": False, "mode": "file", "source": path, "count": 0,
                    "message": f"Cookies file not found: {path}"}
        n = count_netscape(path)
        if not n:
            return {"ok": False, "mode": "file", "source": path, "count": 0,
                    "message": ("That file has no cookie rows — export it in Netscape/"
                                "cookies.txt format (a “Get cookies.txt LOCALLY” style "
                                "extension writes exactly that).")}
        ok = True
        return {"ok": ok, "mode": "file", "source": path, "count": n,
                "message": f"{n} cookies loaded from {Path(path).name}."}
    name = browser()
    if not name:
        return {"ok": False, "mode": "", "source": "", "count": 0,
                "message": ("No cookie source configured — every request runs logged out. "
                            "Pick a browser above (Firefox is the most reliable) or point "
                            "“Cookies file” at an exported cookies.txt.")}
    ok, n, msg = _probe_browser(name)
    if ok:
        reset()          # the user fixed it (closed Chrome / logged in) — try again
    return {"ok": ok, "mode": "browser", "source": name, "count": n, "message": msg}


def explain(msg: str) -> str:
    """Friendly replacement for a raw cookie failure, or '' if not ours."""
    return EXPLAIN if is_cookie_error(msg) else ""
