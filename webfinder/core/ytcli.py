"""All Video Downloader — system yt-dlp CLI bridge.

When the user's own `yt-dlp` (on PATH) is NEWER than the app's pip copy — the
normal state when PyPI is unreachable from the user's network — we drive the
system binary via subprocess instead of the stale module. "The CLI works" then
literally means the app runs the CLI: same clients, same freshness, same PO
token machinery.

Also: every cookie-reading attempt that dies with Chrome's infamous
"Could not copy Chrome cookie database" (issue 7271 — locked DB / App-Bound
Encryption) is automatically retried WITHOUT cookies, so one browser quirk
never bricks analysis of every other site again.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from functools import lru_cache

from ..config import settings

_ERR_MARKERS = re.compile(r"could not copy|cookie database|browser cookies", re.I)
# "the site refused us as a non-browser" — the case TLS impersonation fixes
_BLOCK_MARKERS = re.compile(
    r"\b403\b|\b429\b|forbidden|cloudflare|just a moment|attention required"
    r"|access denied|captcha|ddos|unusual traffic|blocked by|request blocked"
    r"|sign in to confirm", re.I)
_IMPERSONATE_TARGET = "chrome"
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m|\[[0-9;]*m")
_ERR_PREFIX_RE = re.compile(r"^(?:\s*ERROR:\s*)+", re.I)


def friendly(msg: str) -> str:
    """Strip yt-dlp's ANSI colors and its habit of repeating 'ERROR: ERROR:' —
    raw escape-sequence soup in the UI reads like the app itself is broken."""
    if not msg:
        return ""
    out = _ANSI_RE.sub("", str(msg))
    prev = None
    while prev != out:
        prev = out
        out = _ERR_PREFIX_RE.sub("", out.strip()).strip()
    out = re.sub(r"(?:\[Errno \d+\]\s*)+", "", out)
    return re.sub(r"\s+", " ", out).strip()


def _vparse(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", v or "")
    if not nums:
        return ()
    parts = [int(n) for n in nums[:4]]
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts)


@lru_cache(maxsize=1)
def detect() -> dict:
    """Compare app-module vs system-CLI yt-dlp once per process."""
    mod_ver = ""
    try:
        from yt_dlp.version import __version__ as mod_ver
    except Exception:  # noqa: BLE001
        pass
    exe = (os.environ.get("AVD_YTDLP_BIN")
           or shutil.which("yt-dlp") or shutil.which("yt-dlp.exe") or "")
    cli_ver = ""
    if exe:
        try:
            r = subprocess.run([exe, "--version"], capture_output=True, text=True,
                               encoding="utf-8", errors="ignore", timeout=15)
            cli_ver = (r.stdout or "").strip()
        except Exception:  # noqa: BLE001
            cli_ver = ""
    newer = bool(cli_ver) and _vparse(cli_ver) > _vparse(mod_ver)
    forced = os.environ.get("AVD_FORCE_SYSTEM_YTDLP") == "1" and bool(exe)
    use = bool(exe) and (newer or forced)
    return {"exe": exe, "module_version": mod_ver, "cli_version": cli_ver,
            "use_cli": use,
            "label": (f"system CLI {cli_ver} (active)" if use else f"module {mod_ver}")}


def use_cli() -> bool:
    try:
        return bool(detect()["use_cli"])
    except Exception:  # noqa: BLE001 — detection must never break downloads
        return False


def _cookie_flags() -> list[str]:
    b = (settings.get("ytdlp_browser_cookies") or "").strip()
    return ["--cookies-from-browser", b] if b else []


@lru_cache(maxsize=1)
def impersonation_available() -> bool:
    """yt-dlp can impersonate a browser's TLS fingerprint (needs curl_cffi)."""
    try:
        import curl_cffi  # noqa: F401
    except Exception:  # noqa: BLE001 — optional dependency
        return False
    try:
        from yt_dlp.networking.impersonate import ImpersonateTarget  # noqa: F401
    except Exception:  # noqa: BLE001 — older yt-dlp
        return False
    return True


def impersonate_target():
    """Value for yt-dlp's ``impersonate`` option, or None when unavailable."""
    if not impersonation_available():
        return None
    try:
        from yt_dlp.networking.impersonate import ImpersonateTarget
        return ImpersonateTarget.from_str(_IMPERSONATE_TARGET)
    except Exception:  # noqa: BLE001
        return _IMPERSONATE_TARGET


def impersonate_flags() -> list[str]:
    return ["--impersonate", _IMPERSONATE_TARGET] if impersonation_available() else []


def looks_blocked(msg: str) -> bool:
    return bool(_BLOCK_MARKERS.search(msg or ""))


def common_flags(*, referer: str = "", client: dict | None = None) -> list[str]:
    flags = ["--no-warnings", "--no-check-certificates",
             "--socket-timeout", "30", "--retries", "3"]
    px = (settings.get("proxy") or "").strip()
    if px:
        flags += ["--proxy", px]
    if referer:
        flags += ["--referer", referer]
    pc = (client or {}).get("player_client")
    if pc:
        flags += ["--extractor-args", "youtube:player_client=" + ",".join(pc)]
    return flags


def extract(url: str, *, flat: bool = False, playlist_items: str | None = None,
             noplaylist: bool = True, client: dict | None = None,
             referer: str = "", impersonate: bool = False) -> tuple[dict | None, str]:
    """`yt-dlp -J` — returns (info, error) with the cookie-failure retry."""
    d = detect()
    args = [d["exe"], "-J"] + common_flags(referer=referer, client=client)
    if impersonate:
        args += impersonate_flags()
    if flat:
        args += ["--flat-playlist"]
    if playlist_items:
        args += ["--playlist-items", playlist_items]
    if noplaylist:
        args += ["--no-playlist"]
    cookies = _cookie_flags()
    for attempt in range(2):
        p = args + ([] if attempt else cookies) + [url]
        try:
            r = subprocess.run(p, capture_output=True, text=True,
                               encoding="utf-8", errors="ignore", timeout=180)
        except subprocess.TimeoutExpired:
            return None, "yt-dlp CLI timed out (180 s)"
        except OSError as exc:
            return None, f"yt-dlp CLI could not run: {exc}"
        if r.returncode == 0 and (r.stdout or "").strip():
            try:
                return json.loads(r.stdout), ""
            except json.JSONDecodeError:
                return None, "yt-dlp CLI emitted non-JSON output"
        err = (r.stderr or "").strip().splitlines()
        err = friendly(err[-1])[:260] if err else f"yt-dlp CLI exited {r.returncode}"
        if attempt == 0 and cookies and _ERR_MARKERS.search(err):
            continue                       # retry once, without cookie reading
        return None, err
    return None, "unreachable"


PROGRESS_TEMPLATE = ("AVDPROG %(progress._percent_str)s %(progress.downloaded_bytes)s "
                     "%(progress.total_bytes)s %(progress.total_bytes_estimate)s %(progress.speed)s")


def download_cmd(url: str, *, outdir: str, outstem: str, fmt: str, container: str,
                 referer: str = "", client: dict | None = None,
                 playlist: bool = False, impersonate: bool = False) -> list[str]:
    d = detect()
    args = [d["exe"], "--newline", "--progress-template", f"download:{PROGRESS_TEMPLATE}",
            "-f", fmt, "--merge-output-format", container,
            "--concurrent-fragments", "4", "--windows-filenames",
            "-P", outdir, "-o", outstem + ".%(ext)s"]
    args += common_flags(referer=referer, client=client)
    if impersonate:
        args += impersonate_flags()
    if not playlist:
        args += ["--no-playlist"]
    cookies = _cookie_flags()
    if cookies:
        args += cookies
    args.append(url)
    return args
