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

import os
import re
import threading
import time
from pathlib import Path

from ..config import CONFIG_DIR, settings

# yt-dlp / gallery-dl / our own wording for "the cookie source did not work"
_COOKIE_ERR = re.compile(
    # the classic ones (yt-dlp + gallery-dl wording)
    r"could not copy|cookie database|app[- ]bound|permission denied.*cookie"
    r"|cookie.*(?:locked|in use)"
    # gallery-dl: "Unable to find Chrome cookies database in …"
    r"|unable to find .{0,30}cookies database|unable to find .{0,20}cookies"
    # "could not be decrypted" (App-Bound Encryption)
    r"|cookies .{0,40}could not be decrypted|could not decrypt .{0,20}cookies"
    r"|failed to decrypt with|dpapi"
    # explicit read/load failures, but only when cookies are named
    r"|(?:could not|unable to|failed to) (?:read|load|extract|decrypt) (?:the )?cookies?"
    r"|cookies? (?:file (?:is )?(?:empty|invalid)|not found|is empty)"
    r"|invalid netscape cookies\.txt",
    re.I)

# a message we never want to show twice: it is a *setup* problem, not a job error
EXPLAIN = ("The browser's cookie database could not be read — Chrome holds it open while "
           "running, and Chrome 127+ on Windows also App-Bound-encrypts it. Fully quit the "
           "browser (tray icon too), pick Firefox, or export a cookies.txt and set "
           "Settings → Video & capture → Cookies file. Until then the app runs logged out.")

# Browsers we can read from, best-effort order. Firefox is first because its
# cookie store is a plain SQLite file nobody locks — the one that survives the
# Chrome wall on Windows.
CANDIDATES = ("firefox", "edge", "brave", "chromium", "vivaldi", "opera", "chrome", "safari")

_lock = threading.Lock()
_browser_failure = ""          # first failure message in this process
_alt_browser = None            # None = not scanned yet; "" = nothing readable
_alt_meta: dict = {}
_ig_cache: dict = {}           # source signature → does it hold an Instagram login?


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
    active = active_browser()
    return {
        "browser": browser(),
        "active_browser": active,
        "file": path,
        "file_ok": file_usable(),
        "mode": "file" if file_usable() else ("browser" if active else ""),
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
    of failure (so callers can retry anonymously instead of surfacing it).

    Only called a failure when a browser source is actually in use: a site that
    answers 401 is a login wall (Instagram, YouTube), not a broken cookie store,
    and must not poison the session with "cookies unreadable".
    """
    global _browser_failure
    if not browser() or not is_cookie_error(msg):
        return False
    with _lock:
        if not _browser_failure:
            _browser_failure = (msg or EXPLAIN).strip()[:300]
    return True


def reset() -> None:
    """Forget the failure (settings changed / tests)."""
    global _browser_failure, _alt_browser
    with _lock:
        _browser_failure = ""
        _alt_browser = None
        _alt_meta.clear()
        _ig_cache.clear()


# ---------------------------------------------------------------------------
# Flags for the two engines
# ---------------------------------------------------------------------------
def ytdlp_flags() -> list[str]:
    """Extra CLI flags for the system yt-dlp binary."""
    if file_usable():
        return ["--cookies", cookie_file()]
    name = active_browser()
    return ["--cookies-from-browser", name] if name else []


def gallery_flags() -> list[str]:
    """Extra CLI flags for gallery-dl."""
    if file_usable():
        return ["--cookies", cookie_file()]
    name = active_browser()
    return ["--cookies-from-browser", name] if name else []


def module_opts() -> dict:
    """Fragment for a ``yt_dlp.YoutubeDL`` options dict."""
    if file_usable():
        return {"cookiefile": cookie_file()}
    name = active_browser()
    return {"cookiesfrombrowser": (name,)} if name else {}


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
        alt = auto_browser()
        return f"{alt} cookies (fallback)" if alt else "anonymous (browser cookies unreadable)"
    return "anonymous"


# ---------------------------------------------------------------------------
# Instagram session import — paste a cookie, get a cookies.txt
# ---------------------------------------------------------------------------
IG_DOMAIN = ".instagram.com"
IG_NAMES = ("sessionid", "csrftoken", "ds_user_id", "mid", "datr", "ig_did", "rur")
_PAIR_RE = re.compile(r"([A-Za-z0-9_\-]+)=([^;,\s]+)")


def instagram_cookie_path() -> str:
    """Where an imported session lives (next to settings.json, not in a temp dir)."""
    return str(Path(CONFIG_DIR) / "instagram-cookies.txt")


def parse_cookie_input(raw: str) -> dict:
    """Understand everything a user might paste into a "session" box.

    Accepted: the bare `sessionid` value, `a=1; b=2`, a `Cookie:` header line, a
    JSON `{"sessionid": ...}` blob, or the whole content of a Netscape
    `cookies.txt`. Returns `{"cookies": {...}}` or `{"cookiestxt": "<text>"}`.
    """
    text = (raw or "").strip().strip('"\'')
    if not text:
        return {}
    # a cookies.txt (tab separated, ≥7 columns) is passed through untouched
    if any(line.count("\t") >= 6 for line in text.splitlines()):
        return {"cookiestxt": text, "cookies": {}}
    if text[0] in "{[":
        try:
            import json
            data = json.loads(text)
            items = data if isinstance(data, list) else [
                {"name": k, "value": v} for k, v in data.items()]
            cookies = {}
            for entry in items:
                if isinstance(entry, dict) and entry.get("name"):
                    cookies[str(entry["name"])] = str(entry.get("value") or "")
            if cookies:
                return {"cookies": cookies}
        except Exception:  # noqa: BLE001 — not JSON, keep going
            pass
    text = re.sub(r"^\s*cookie\s*:\s*", "", text, flags=re.I)
    if "=" not in text:
        # a bare value: sessionid is the only one this makes sense for
        return {"cookies": {"sessionid": text}} if len(text) > 12 else {}
    pairs = dict(_PAIR_RE.findall(text))
    known = {k: v for k, v in pairs.items() if k in IG_NAMES}
    # keep the unknown names too when nothing useful was recognised, so the error
    # can say "there is no sessionid here" instead of "nothing usable"
    return {"cookies": known or pairs} if pairs else {}


def save_instagram_session(raw: str) -> dict:
    """Store the pasted session as a cookies.txt the engines already understand."""
    parsed = parse_cookie_input(raw)
    if not parsed:
        return {"ok": False, "message": ("Nothing usable in that paste — it should contain "
                                         "sessionid=… (or the whole cookies.txt content).")}

    path = Path(instagram_cookie_path())
    path.parent.mkdir(parents=True, exist_ok=True)

    if parsed.get("cookiestxt"):
        text = parsed["cookiestxt"]
        path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
        count = count_netscape(str(path))
        if not count:
            path.unlink(missing_ok=True)
            return {"ok": False, "message": "That cookies.txt has no cookie rows in it."}
    else:
        cookies = parsed.get("cookies") or {}
        if not cookies.get("sessionid"):
            return {"ok": False, "message": (
                "That paste has no sessionid — open instagram.com → DevTools → Application → "
                "Cookies → https://www.instagram.com and copy the value of the sessionid row "
                "(or use “copy as cURL” and paste the whole cookie line).")}
        expires = int(time.time()) + 365 * 86400
        lines = ["# Netscape HTTP Cookie File",
                 "# written by All Video Downloader — an Instagram login session"]
        for name, value in cookies.items():
            lines.append(f"{IG_DOMAIN}\tTRUE\t/\tTRUE\t{expires}\t{name}\t{value}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        count = len(cookies)

    try:
        os.chmod(path, 0o600)          # it is a login credential
    except OSError:
        pass

    settings.update({"cookies_file": str(path)})
    reset()                            # a fresh source must be tried, not skipped
    names = ", ".join(sorted(parsed.get("cookies") or {})) or f"{count} cookies"
    return {"ok": True, "path": str(path), "count": count, "names": names,
            "instagram": True,
            "message": (f"Instagram session saved ({names}). Scan again — the checker now "
                        "reads it instead of your browser's locked cookie database.")}


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


def _read_browser(name: str) -> tuple[bool, int, int, str]:
    """Read a browser's cookies *locally* (no network).

    Returns ``(ok, cookie_count, instagram_count, message)`` and never raises —
    every failure mode here is something the user can be told about.
    """
    try:
        from yt_dlp.cookies import extract_cookies_from_browser  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001 — yt-dlp missing
        return False, 0, 0, f"yt-dlp is not available to read cookies ({exc})"
    try:
        jar = extract_cookies_from_browser(name)
    except Exception as exc:  # noqa: BLE001 — every failure is a user-facing message
        raw = str(exc) or exc.__class__.__name__
        if is_cookie_error(raw):
            return False, 0, 0, EXPLAIN
        if "could not find" in raw.lower() or "no such file" in raw.lower():
            return False, 0, 0, (f"{name} has no cookie database on this machine ({raw[:150]}) — "
                                 "is it installed and signed in?")
        return False, 0, 0, f"Could not read {name} cookies: {raw[:220]}"
    try:
        ig = sum(1 for c in jar if "instagram" in str(getattr(c, "domain", "")).lower())
    except Exception:  # noqa: BLE001
        ig = 0
    n = len(jar)
    if not n:
        return False, 0, 0, (f"{name} answered but returned no cookies — open {name}, log in to "
                             "the site you need, then check again.")
    return True, n, ig, f"{n} cookies readable from {name}."


def _probe_browser(name: str) -> tuple[bool, int, str]:
    """_read_browser, and remember the failure of the *configured* source."""
    ok, n, _ig, msg = _read_browser(name)
    if not ok and is_cookie_error(msg):
        mark_browser_failure(msg)
    return ok, n, msg


def scan_browsers(exclude: str = "") -> list[dict]:
    """Every readable browser on this machine, Instagram-capable ones first."""
    found: list[dict] = []
    for name in CANDIDATES:
        if name == (exclude or "").lower():
            continue
        ok, n, ig, _msg = _read_browser(name)
        if ok:
            found.append({"browser": name, "count": n, "instagram": ig})
    found.sort(key=lambda b: (-b["instagram"], -b["count"]))
    return found


def auto_browser() -> str:
    """A browser whose cookies *can* be read, used when the chosen one cannot.

    Cached for the session: the answer only changes when the user changes
    settings (``reset()``) — it never becomes readable mid-session on its own.
    """
    global _alt_browser
    with _lock:
        if _alt_browser is not None:
            return _alt_browser
    found = scan_browsers(exclude=browser())
    name = found[0]["browser"] if found else ""
    with _lock:
        _alt_browser = name
        _alt_meta.clear()
        _alt_meta.update(found[0] if found else {})
    return name


def active_browser() -> str:
    """The browser the engines should actually use right now ('' = none)."""
    name = browser()
    if not name:
        return ""
    if not browser_failure():
        return name
    return auto_browser()


def instagram_session() -> dict:
    """Does the cookie source in effect actually hold an Instagram login?

    A readable Chrome profile with no `sessionid` for instagram.com is the most
    confusing state of all: gallery-dl works, Instagram answers 404, and the tab
    looks broken. Cached per session (``reset()`` clears it).
    """
    if file_usable():
        sig = f"file:{cookie_file()}"
        if sig in _ig_cache:
            return _ig_cache[sig]
        try:
            text = Path(cookie_file()).read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            text = ""
        res = {"source": f"cookies.txt ({Path(cookie_file()).name})",
               "instagram": "instagram" in text, "count": count_netscape(cookie_file())}
        _ig_cache[sig] = res
        return res
    name = active_browser()
    if not name:
        return {"source": "", "instagram": False, "count": 0}
    sig = f"browser:{name}"
    if sig in _ig_cache:
        return _ig_cache[sig]
    ok, n, ig, _msg = _read_browser(name)
    res = {"source": f"{name} cookies" if ok else "", "instagram": bool(ig),
           "count": ig, "readable": ok}
    _ig_cache[sig] = res
    return res


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
        alts = scan_browsers()
        res = {"ok": False, "mode": "", "source": "", "count": 0,
               "alternatives": alts, "suggest": alts[0]["browser"] if alts else "",
               "message": ("No cookie source configured — every request runs logged out. "
                           "Pick a browser above (Firefox is the most reliable) or point "
                           "“Cookies file” at an exported cookies.txt.")}
        if alts:
            res["message"] += f" {alts[0]['browser']} is readable on this machine."
        return res
    ok, n, msg = _probe_browser(name)
    if ok:
        reset()          # the user fixed it (closed Chrome / logged in) — try again
        sess = instagram_session()
        if not sess.get("instagram"):
            msg += (" …but there is no Instagram login in it: open instagram.com in "
                    f"{name}, sign in, then check again.")
        return {"ok": True, "mode": "browser", "source": name, "count": n,
                "instagram": bool(sess.get("instagram")),
                "alternatives": [], "suggest": "", "message": msg}
    # the chosen browser cannot be read — who else has cookies on this machine?
    alts = scan_browsers(exclude=name)
    if alts:
        best = alts[0]
        msg += (f" {best['browser']} IS readable here ({best['count']} cookies"
                + (", Instagram session included" if best["instagram"] else "")
                + ") — switching to it makes the scan work.")
    return {"ok": False, "mode": "browser", "source": name, "count": 0,
            "alternatives": alts, "suggest": alts[0]["browser"] if alts else "",
            "message": msg}


def use_best() -> dict:
    """Save the best readable browser as the source — the one-click fix."""
    alts = scan_browsers()
    if not alts:
        return {"ok": False, "browser": "", "count": 0,
                "message": ("None of the browsers on this machine gave up readable cookies. "
                            "Close the browser completely before the scan, or export a "
                            "cookies.txt and set Settings → Video & capture → Cookies file.")}
    best = alts[0]
    settings.update({"ytdlp_browser_cookies": best["browser"]})
    reset()
    return {"ok": True, "browser": best["browser"], "count": best["count"],
            "instagram": best["instagram"],
            "message": (f"Using {best['browser']} cookies now ({best['count']} readable"
                        + (", Instagram session included" if best["instagram"] else "")
                        + "). Scan again.")}


def explain(msg: str) -> str:
    """Friendly replacement for a raw cookie failure, or '' if not ours."""
    return EXPLAIN if is_cookie_error(msg) else ""
