"""All Video Downloader — gallery-dl bridge (Instagram checker).

`gallery-dl` is the right tool for *profiles*: yt-dlp downloads one video per
URL, while gallery-dl walks a whole account — posts, reels, stories, highlights,
tagged — and reports every media file it finds as JSON. This module drives that
binary (or the installed module) and turns its dump into the app's own items:

    profile URL / @handle
        → one gallery-dl run per target (posts, reels, stories, highlights)
          with `-j` (JSON, no download), merged and de-duplicated
        → normalized items (video/image, filename, post, caption, date…)
        → the UI picks some, the Download Manager streams them (http worker)

Why one run per target: failures stay isolated (a private "tagged" tab must not
kill the "posts" results), each target reports its own status/count, and the
scan can stream partial results to the UI while Instagram's rate limiter sleeps
between pages.

Design notes
------------
* Nothing here is Instagram-*only*: any URL gallery-dl supports (a Reddit or
  Pinterest profile, a DeviantArt gallery…) goes through the same path. The tab
  is named for the job most people want done; ``POST /api/gallery/scan`` is the
  generic entry point.
* No downloads happen during a scan (`-j` = extract + print JSON). The chosen
  items are enqueued into the normal Download Manager, so pause/resume/progress
  work exactly like every other transfer.
* Credentials are the app's existing "Browser cookies source" setting, shared
  with yt-dlp: ``--cookies-from-browser chrome`` is what makes a logged-out
  Instagram scan work at all.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from ..config import settings
from . import cookies as cookie_state

# ---------------------------------------------------------------------------
# What a profile is made of — one gallery-dl URL pattern per target
# ---------------------------------------------------------------------------
TARGETS: dict[str, dict] = {
    "posts": {"label": "Posts", "url": "https://www.instagram.com/{u}/posts/",
              "icon": "image", "about": "everything on the grid"},
    "reels": {"label": "Reels", "url": "https://www.instagram.com/{u}/reels/",
              "icon": "film", "about": "short vertical videos"},
    "stories": {"label": "Stories", "url": "https://www.instagram.com/stories/{u}/",
                "icon": "clock", "about": "live 24 h, needs a login"},
    "highlights": {"label": "Highlights", "url": "https://www.instagram.com/{u}/highlights/",
                   "icon": "book", "about": "saved story collections"},
    "tagged": {"label": "Tagged", "url": "https://www.instagram.com/{u}/tagged/",
               "icon": "search", "about": "posts the account is tagged in"},
}
DEFAULT_TARGETS = ("posts", "reels")

VIDEO_EXTS = {"mp4", "mkv", "webm", "mov", "m4v", "ts", "gif"}
AUDIO_EXTS = {"mp3", "m4a", "aac", "ogg", "opus", "wav"}
_HANDLE_RE = re.compile(r"^[A-Za-z0-9._]{1,40}$")
_PER_TARGET_TIMEOUT = int(os.environ.get("AVD_GALLERYDL_TIMEOUT") or 420)


# ---------------------------------------------------------------------------
# Engine detection
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def detect() -> dict:
    """Find gallery-dl: env override → PATH binary → importable module."""
    # AVD_GALLERYDL_BIN may be a path OR a full command line
    # ("C:\\Python\\python.exe C:\\tools\\gallery_dl.py", "python -m gallery_dl")
    override = (os.environ.get("AVD_GALLERYDL_BIN") or "").strip()
    exe = ""
    cmd: list[str] = []
    if override:
        cmd = shlex.split(override, posix=(os.name != "nt"))
        exe = " ".join(cmd)
    else:
        exe = shutil.which("gallery-dl") or shutil.which("gallery-dl.exe") or ""
        if exe:
            cmd = [exe]

    module_version = ""
    try:
        from gallery_dl.version import __version__ as module_version  # noqa: N813
    except Exception:  # noqa: BLE001 — not installed
        module_version = ""

    version = ""
    if cmd:
        try:
            r = subprocess.run([*cmd, "--version"], capture_output=True, text=True,
                               encoding="utf-8", errors="ignore", timeout=30)
            version = (r.stdout or "").strip().splitlines()[-1] if r.stdout else ""
        except Exception:  # noqa: BLE001
            version = ""
    elif module_version:
        cmd = [sys.executable, "-m", "gallery_dl"]
        version = module_version

    return {"available": bool(cmd), "cmd": cmd, "exe": exe,
            "version": version or module_version, "module_version": module_version,
            "install_hint": ("" if cmd else
                             "pip install gallery-dl  (or install it from github.com/mikf/gallery-dl "
                             "and make sure `gallery-dl` is on PATH)")}


def available() -> bool:
    try:
        return bool(detect()["available"])
    except Exception:  # noqa: BLE001 — detection must never break the API
        return False


# ---------------------------------------------------------------------------
# Input normalisation
# ---------------------------------------------------------------------------
def parse_source(raw: str) -> dict:
    """Accept a profile URL, a post/reel/story URL, ``@handle`` or a bare handle."""
    text = (raw or "").strip()
    if not text:
        raise ValueError("Paste an Instagram profile link (or a @handle).")
    if text.startswith("@"):
        text = text[1:].strip()

    if not re.match(r"^[a-z]+://", text, re.I):
        if "." in text and "/" not in text.split("/")[0] and "instagram" in text.lower():
            text = "https://" + text
        elif _HANDLE_RE.match(text):
            return {"kind": "profile", "username": text, "url": f"https://www.instagram.com/{text}/"}
        else:
            text = "https://" + text

    from urllib.parse import urlparse
    try:
        parts = urlparse(text)
    except ValueError as exc:
        raise ValueError("That does not look like a URL.") from exc
    host = (parts.netloc or "").lower().split(":")[0]
    segments = [s for s in (parts.path or "").split("/") if s]

    # Not Instagram? gallery-dl handles hundreds of galleries — scan it as-is
    # instead of inventing an instagram.com URL out of its path.
    if not (host == "instagram.com" or host.endswith((".instagram.com", ".instagr.am"))):
        if not host or "." not in host:
            raise ValueError("That does not look like a link — paste a profile URL or @handle.")
        return {"kind": "url", "username": "", "url": text, "host": host}

    if not segments:
        raise ValueError("That Instagram link has no profile name in it.")

    # /p/<code>/, /reel/<code>/, /tv/<code>/ → a single post
    if segments[0] in ("p", "reel", "reels", "tv") and len(segments) >= 2:
        return {"kind": "post", "username": "", "url": f"https://{host}/{segments[0]}/{segments[1]}/",
                "code": segments[1]}
    # /stories/<user>/<id>/ → one story item
    if segments[0] == "stories" and len(segments) >= 2:
        return {"kind": "story", "username": segments[1],
                "url": f"https://{host}/stories/{segments[1]}/" + (f"{segments[2]}/" if len(segments) > 2 else "")}

    username = segments[0]
    if not _HANDLE_RE.match(username):
        raise ValueError(f"'{username}' is not a valid Instagram username.")
    # a scoped profile URL (/user/reels/) keeps only that tab
    scoped = segments[1] if len(segments) > 1 else ""
    return {"kind": "profile", "username": username,
            "url": f"https://www.instagram.com/{username}/",
            "scoped": scoped if scoped in TARGETS else ""}


def clean_targets(requested) -> list[str]:
    """Validate a target list (``[]`` → the user's saved default)."""
    if isinstance(requested, str):
        requested = requested.replace(" ", "").split(",")
    keys = [k for k in (requested or []) if k in TARGETS]
    if not keys:
        saved = str(settings.get("instagram_include") or "posts,reels")
        keys = [k for k in saved.replace(" ", "").split(",") if k in TARGETS] or list(DEFAULT_TARGETS)
    return list(dict.fromkeys(keys))


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------
def build_cmd(url: str, *, cookies: str = "", proxy: str = "", limit: int = 0,
              delay: str = "", cookie_file: str = "") -> list[str]:
    """`gallery-dl -j` for one URL, with the app's settings folded in."""
    d = detect()
    cmd = list(d["cmd"]) + [
        "-j",                                     # JSON on stdout, never download
        # Instagram offers progressive (audio muxed) and DASH (higher quality but
        # silent) variants; a downloader that hands the user a silent file is
        # broken, so ask for the merged stream and skip audio-only sidecars.
        "-o", "extractor.instagram.videos=merged",
        "-o", "extractor.instagram.audio=false",
        "-o", "extractor.instagram.previews=false",
        "-o", "output.private=false",
    ]
    if limit and limit > 0:
        cmd += ["--post-range", f"1-{int(limit)}"]
    if delay:
        cmd += ["--sleep-request", str(delay)]
    if proxy:
        cmd += ["--proxy", proxy]
    # A cookies.txt file always wins: it is the only source that keeps working
    # when the browser holds (or encrypts) its own database.
    file_path = (cookie_file or cookie_state.cookie_file()).strip()
    browser = (cookies or "").strip()
    if file_path and os.path.isfile(file_path):
        cmd += ["--cookies", file_path]
    elif browser and not cookie_state.browser_failure():
        cmd += ["--cookies-from-browser", browser]
    cmd.append(url)
    return cmd


_ERROR_RE = re.compile(r"^\[[\w-]+\]\[(?:error|warning)\]\s*(.*)$")
_EXC_RE = re.compile(r"^[A-Za-z_][\w.]*(?:Error|Exception|Warning):\s*(.+)$")
_LOGIN_RE = re.compile(r"401|403|login|login_required|cookie|unauthori[sz]ed|not logged in|sessionid"
                       r"|checkpoint|challenge", re.I)
_NET_RE = re.compile(r"name resolution|failed to resolve|connection|timed out|timeout|unreachable"
                     r"|newconnectionerror|proxy|ssl|temporary failure|network", re.I)
_INTERNAL_RE = re.compile(
    r"unboundlocal|attributeerror|typeerror|keyerror|nameerror|indexerror|valueerror|traceback"
    r"|cannot access local variable|referenced before assignment|has no attribute"
    r"|not subscriptable|is not callable|expected .* got|takes \d+ positional"
    r"|missing \d+ required", re.I)


def _friendly_stderr(text: str) -> str:
    """gallery-dl logs into stderr; keep the human line, drop traceback frames."""
    lines: list[str] = []
    for line in (text or "").splitlines():
        raw = line.rstrip()
        if not raw.strip() or raw.strip().startswith(("Traceback (most recent call last)",
                                                      "File \"", "^")):
            continue
        if raw.startswith(("  ", "\t")):              # traceback frame / source echo
            continue
        m = _ERROR_RE.match(raw.strip())
        if m:
            lines.append(m.group(1))
            continue
        m = _EXC_RE.match(raw.strip())
        if m:
            lines.append(m.group(1))
    out = " · ".join(dict.fromkeys(lines[-3:]))
    return out[:400]


_MISSING_RE = re.compile(r"user .{0,40}could not be found|user not found|account .{0,20}not found"
                          r"|requested user|no such user|404 not found", re.I)


def explain_error(msg: str) -> str:
    """Turn a raw gallery-dl failure into something a user can act on."""
    text = (msg or "").strip()
    low = text.lower()
    if cookie_state.is_cookie_error(text):
        return f"{text} — {cookie_state.EXPLAIN}"
    if _MISSING_RE.search(low):
        return (f"{text} — Instagram only answers this for accounts it can see: it is the reply "
                "for a typo/renamed handle, for a private account, and (most often) for a "
                "logged-out request to a profile it will not serve anonymously. Set Settings → "
                "Video & capture → Browser cookies source (or a cookies.txt file) and try again.")
    if _LOGIN_RE.search(low):
        return (text + " — Instagram needs a logged-in session: set Settings → Video & capture → "
                "Browser cookies source (chrome/edge/firefox), close that browser fully, then scan again.")
    if _NET_RE.search(low):
        return (text + " — the request never reached Instagram: check the connection, or set "
                "Settings → Downloads → Network proxy (a blocked/datacenter IP gets refused).")
    if _INTERNAL_RE.search(low) or not text:
        return (f"gallery-dl could not read the page ({text or 'no output'}) — that is usually a blocked "
                "connection, a changed Instagram layout, or an outdated gallery-dl "
                "(run: pip install -U gallery-dl).")
    return text


def run_dump(url: str, *, cookies: str = "", proxy: str = "", limit: int = 0,
             delay: str = "", timeout: int = _PER_TARGET_TIMEOUT,
             cancel: threading.Event | None = None,
             on_proc=None, cookie_file: str = "") -> dict:
    """Run one gallery-dl dump. Returns ``{items, errors, raw_error, rc}``."""
    cmd = build_cmd(url, cookies=cookies, proxy=proxy, limit=limit, delay=delay,
                    cookie_file=cookie_file)
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8", errors="ignore")
    except OSError as exc:
        return {"items": [], "errors": [f"gallery-dl could not start: {exc}"], "raw_error": "", "rc": -1}
    if on_proc:
        on_proc(proc)

    deadline = time.time() + timeout
    while True:
        if cancel is not None and cancel.is_set():
            _kill(proc)
            return {"items": [], "errors": ["scan cancelled"], "raw_error": "", "rc": -2}
        if proc.poll() is not None:
            break
        if time.time() > deadline:
            _kill(proc)
            return {"items": [], "errors": [f"gallery-dl timed out after {timeout}s — "
                                            "try a smaller post limit"], "raw_error": "", "rc": -3}
        time.sleep(0.25)

    out, err = proc.communicate()
    parsed = parse_dump(out or "")
    parsed["rc"] = proc.returncode
    parsed["raw_error"] = _friendly_stderr(err or "")
    if proc.returncode not in (0, None) and not parsed["items"]:
        raw = " · ".join(dict.fromkeys((parsed["raw_error"] or "", *(parsed["errors"] or []))))
        parsed["errors"] = [explain_error(raw or f"gallery-dl exited {proc.returncode}")]
    elif not parsed["items"] and parsed["errors"]:
        parsed["errors"] = [explain_error(e) for e in parsed["errors"]]
    return parsed


def _kill(proc: subprocess.Popen) -> None:
    try:
        proc.terminate()
        proc.wait(timeout=8)
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# JSON dump → normalized items
# ---------------------------------------------------------------------------
_MSG_URL, _MSG_DIR, _MSG_QUEUE = 3, 2, 6


def _iter_messages(text: str):
    """Yield gallery-dl messages from any of its dump shapes.

    Supports the default pretty-printed array, ``output.jsonl`` line mode and a
    bare ``{...}`` object, because the user's own gallery-dl config may switch
    the format.
    """
    body = (text or "").strip()
    if not body:
        return
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        for line in body.splitlines():
            line = line.strip().rstrip(",")
            if not line or line in ("[", "]", "{", "}"):
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue
        return
    if isinstance(data, dict):
        yield data
    elif isinstance(data, list):
        for entry in data:
            yield entry


def _ext_of(url: str, kw: dict) -> str:
    ext = str(kw.get("extension") or "").lower().lstrip(".")
    if ext:
        return ext
    m = re.search(r"\.([A-Za-z0-9]{2,5})(?:\?|$)", url or "")
    return m.group(1).lower() if m else "jpg"


def _kind_of(url: str, ext: str, kw: dict) -> str:
    if kw.get("video_url") or ext in VIDEO_EXTS:
        return "video"
    if ext in AUDIO_EXTS:
        return "audio"
    return "image"


def _item(kw: dict, url: str, target: str) -> dict | None:
    if not isinstance(kw, dict) or not url:
        return None
    url = str(url)
    if url.startswith("ytdl:") or not url.startswith("http"):
        return None                      # gallery-dl placeholder (DASH muxing) — not a file
    ext = _ext_of(url, kw)
    kind = _kind_of(url, ext, kw)
    user = str(kw.get("username") or kw.get("fullname") or "").strip()
    code = str(kw.get("post_shortcode") or kw.get("sidecar_shortcode") or "").strip()
    num = int(kw.get("num") or 0)
    count = int(kw.get("count") or 0)
    media_id = str(kw.get("media_id") or "").strip()
    stem = "_".join(x for x in (user or "instagram", code or media_id or f"{num}") if x)
    if count > 1 and num:
        stem = f"{stem}_{num}"
    filename = re.sub(r"[^\w.\-]+", "_", f"{stem}.{ext}")[:150]

    caption = str(kw.get("description") or "").strip().replace("\n", " ")
    thumb = str(kw.get("display_url") or "")
    if thumb == url or thumb.startswith("ytdl:"):
        thumb = "" if kind == "video" else url

    return {
        "id": media_id or url,
        "url": url,
        "kind": kind,
        "ext": ext,
        "filename": filename,
        "thumbnail": thumb,
        "post": code,
        "post_url": str(kw.get("post_url") or ""),
        "type": str(kw.get("type") or ("reel" if kind == "video" else "post")),
        "target": target,
        "username": user,
        "fullname": str(kw.get("fullname") or ""),
        "caption": caption[:240],
        "date": int(kw.get("date") or kw.get("post_date") or 0),
        "likes": int(kw.get("likes") or 0),
        "width": int(kw.get("width") or 0),
        "height": int(kw.get("height") or 0),
    }


def parse_dump(text: str) -> dict:
    """Parse a gallery-dl ``-j`` dump into ``{items, posts, errors, queues}``."""
    items: dict[str, dict] = {}
    posts: dict[str, dict] = {}
    errors: list[str] = []
    queues: list[str] = []

    for msg in _iter_messages(text):
        # a bare item object (custom configs / future dump shapes)
        if isinstance(msg, dict):
            if msg.get("url"):
                it = _item(msg, str(msg["url"]), "")
                if it:
                    items.setdefault(it["id"], it)
            continue
        if not isinstance(msg, (list, tuple)) or not msg:
            continue
        head = msg[0]
        if not isinstance(head, int):
            continue                                  # not a message tuple
        if head == -1:
            payload = msg[1] if len(msg) > 1 and isinstance(msg[1], dict) else {}
            errors.append(str(payload.get("message") or payload.get("error") or "gallery-dl error")[:300])
        elif head == _MSG_URL and len(msg) >= 3:
            it = _item(msg[2], str(msg[1]), "")
            if it:
                items.setdefault(it["id"], it)
        elif head == _MSG_DIR:
            # (Message.Directory, "", kwdict) — the payload is the LAST dict
            post = next((m for m in reversed(msg[1:]) if isinstance(m, dict)), None)
            if post is None:
                continue
            code = str(post.get("post_shortcode") or post.get("sidecar_shortcode") or "")
            if code:
                posts[code] = {
                    "post": code,
                    "post_url": str(post.get("post_url") or ""),
                    "type": str(post.get("type") or "post"),
                    "caption": str(post.get("description") or "").replace("\n", " ")[:240],
                    "date": int(post.get("date") or 0),
                    "likes": int(post.get("likes") or 0),
                    "username": str(post.get("username") or ""),
                    "fullname": str(post.get("fullname") or ""),
                }
        elif head == _MSG_QUEUE and len(msg) >= 2:
            queues.append(str(msg[1]))

    # gallery-dl merges post metadata into every file dict, but older versions
    # (and some extractors) only report it on the Directory message — fill the
    # gaps so captions/dates/likes are never missing on the card.
    for it in items.values():
        meta = posts.get(it.get("post") or "")
        if not meta:
            continue
        for key, src in (("caption", "caption"), ("date", "date"), ("likes", "likes"),
                         ("post_url", "post_url"), ("username", "username"),
                         ("fullname", "fullname")):
            if not it.get(key) and meta.get(src):
                it[key] = meta[src]

    return {"items": list(items.values()), "posts": list(posts.values()),
            "errors": errors, "queues": queues}


# ---------------------------------------------------------------------------
# Scan tasks — one thread per scan, polled by the UI
# ---------------------------------------------------------------------------
@dataclass
class ScanTask:
    id: str
    source: dict
    targets: list[dict]
    limit: int
    cookie_source: str
    status: str = "queued"                 # queued | scanning | done | error | cancelled
    items: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)   # worked, but not as asked
    started: float = field(default_factory=time.time)
    finished: float = 0.0
    current: str = ""
    engine: dict = field(default_factory=dict)
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)
    _proc: subprocess.Popen | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def to_dict(self) -> dict:
        with self._lock:
            done_targets = [t for t in self.targets if t["status"] in ("done", "empty", "error")]
            videos = sum(1 for i in self.items if i["kind"] == "video")
            return {
                "id": self.id,
                "status": self.status,
                "source": self.source,
                "username": self.source.get("username", ""),
                "fullname": next((i["fullname"] for i in self.items if i.get("fullname")), ""),
                "avatar_hint": next((i["thumbnail"] for i in self.items
                                     if i.get("thumbnail") and i["kind"] == "video"), ""),
                "targets": [dict(t) for t in self.targets],
                "progress": {"done": len(done_targets), "total": len(self.targets),
                             "current": self.current},
                "limit": self.limit,
                "cookie_source": self.cookie_source,
                "items": list(self.items),
                "counts": {"total": len(self.items), "videos": videos,
                           "images": len(self.items) - videos,
                           "posts": len({i["post"] for i in self.items if i.get("post")})},
                "errors": list(self.errors),
                "warnings": list(self.warnings),
                "cookies": cookie_state.source(),
                "engine": dict(self.engine),
                "started": self.started,
                "finished": self.finished,
                "elapsed": round((self.finished or time.time()) - self.started, 1),
            }


SCANS: dict[str, ScanTask] = {}
_SCANS_LOCK = threading.Lock()
_MAX_SCANS = 12


def get_scan(scan_id: str) -> dict | None:
    with _SCANS_LOCK:
        task = SCANS.get(scan_id)
    return task.to_dict() if task else None


def list_scans() -> list[dict]:
    with _SCANS_LOCK:
        tasks = list(SCANS.values())
    return [t.to_dict() for t in sorted(tasks, key=lambda t: -t.started)[:10]]


def cancel_scan(scan_id: str) -> bool:
    with _SCANS_LOCK:
        task = SCANS.get(scan_id)
    if not task:
        return False
    task._cancel.set()
    proc = task._proc
    if proc is not None:
        _kill(proc)
    with task._lock:
        task.status = "cancelled"
        task.finished = task.finished or time.time()
    return True


def start_scan(raw_source: str, *, include=None, limit: int = 0,
               cookie_source: str = "") -> dict:
    """Kick off a scan in a background thread and return the task snapshot."""
    d = detect()
    if not d["available"]:
        raise RuntimeError(f"gallery-dl is not installed — {d['install_hint']}")

    source = parse_source(raw_source)
    keys = clean_targets(include)
    if source["kind"] == "profile" and source.get("scoped"):
        keys = [source["scoped"]]
    try:
        limit = int(limit or settings.get("instagram_limit") or 30)
    except (TypeError, ValueError):
        limit = 30
    cookie_source = (cookie_source or settings.get("ytdlp_browser_cookies") or "").strip()

    if source["kind"] == "profile":
        targets = [{"key": k, "label": TARGETS[k]["label"], "url": TARGETS[k]["url"].format(u=source["username"]),
                    "status": "queued", "count": 0, "error": ""} for k in keys]
    else:
        label = {"post": "Post", "story": "Story"}.get(source["kind"], "Gallery")
        targets = [{"key": source["kind"], "label": label, "url": source["url"],
                    "status": "queued", "count": 0, "error": ""}]

    task = ScanTask(id=uuid.uuid4().hex[:12], source=source, targets=targets,
                    limit=limit, cookie_source=cookie_source, engine=d,
                    current=targets[0]["key"] if targets else "")
    with _SCANS_LOCK:
        SCANS[task.id] = task
        while len(SCANS) > _MAX_SCANS:            # keep memory bounded
            oldest = min(SCANS.values(), key=lambda t: t.started)
            if oldest.id == task.id:
                break
            SCANS.pop(oldest.id, None)

    threading.Thread(target=_run_scan, args=(task,), daemon=True,
                     name=f"gallery-scan-{task.id}").start()
    return task.to_dict()


def _cookie_warning() -> str:
    """One clear line about cookies — the failure is a setup issue, not a job error."""
    return (cookie_state.browser_failure()
            or "Browser cookies could not be read")


def _scan_dump(task: ScanTask, target: dict, proxy: str, delay: str) -> dict:
    """Run one target, and if the cookie source is the reason it failed, retry it
    anonymously so public media still appears (and say so)."""
    file_path = cookie_state.cookie_file()
    result = run_dump(target["url"], cookies=task.cookie_source, proxy=proxy,
                      limit=task.limit, delay=delay, cancel=task._cancel,
                      on_proc=lambda p: setattr(task, "_proc", p),
                      cookie_file=file_path)
    blob = " · ".join([result.get("raw_error") or ""] + (result.get("errors") or []))
    # a broken cookie SOURCE (locked/encrypted DB) is not a site login wall
    if not cookie_state.mark_browser_failure(blob):
        return result
    # remember it for the whole session: every later run skips the dead source
    # ...but the user may simply have picked the wrong browser: another one on
    # this machine can still be readable (Firefox never locks its database).
    alt = cookie_state.auto_browser()
    task.cookie_source = alt
    retry = run_dump(target["url"], cookies=alt, proxy=proxy, limit=task.limit,
                     delay=delay, cancel=task._cancel,
                     on_proc=lambda p: setattr(task, "_proc", p), cookie_file=file_path)
    with task._lock:
        if alt:
            warning = (f"{cookie_state.browser() or 'Browser'} cookies could not be read, so this "
                       f"scan used {alt} instead (its cookie database is readable). If Instagram "
                       f"asks for a login, open {alt}, sign in, then scan again — or export a "
                       "cookies.txt (Settings → Cookies file).")
        else:
            warning = (f"Browser cookies could not be read ({cookie_state.EXPLAIN}) — this scan ran "
                       "logged out, so only public media appeared.")
        if warning not in task.warnings:
            task.warnings.append(warning)
    return retry


def _run_scan(task: ScanTask) -> None:
    proxy = (settings.get("proxy") or "").strip()
    delay = str(settings.get("instagram_delay") or "")
    with task._lock:
        task.status = "scanning"
        if cookie_state.browser_failure() and not cookie_state.file_usable():
            task.warnings.append(
                "Browser cookies could not be read earlier in this session, so this scan runs "
                "logged out. " + cookie_state.EXPLAIN)

    seen: set[str] = set()
    for target in task.targets:
        if task._cancel.is_set():
            break
        with task._lock:
            target["status"] = "scanning"
            task.current = target["key"]
        try:
            result = _scan_dump(task, target, proxy, delay)
        except Exception as exc:  # noqa: BLE001 — one target must never kill the scan
            result = {"items": [], "errors": [str(exc)[:200]], "posts": []}
        finally:
            task._proc = None

        added = 0
        with task._lock:
            for it in result.get("items") or []:
                it["target"] = target["key"]
                if it["id"] in seen:
                    continue
                seen.add(it["id"])
                task.items.append(it)
                added += 1
            for msg in result.get("errors") or []:
                if msg and msg not in task.errors:
                    task.errors.append(msg)
            target["count"] = added
            target["status"] = ("done" if added else
                                ("error" if result.get("errors") else "empty"))
            if result.get("errors"):
                target["error"] = (result["errors"][0] or "")[:220]

    # newest first — Instagram returns oldest→newest inside each target
    with task._lock:
        task.items.sort(key=lambda i: -(i.get("date") or 0))
        task.current = ""
        if task.status != "cancelled":
            task.status = "done" if task.items else "error"
            if not task.items and not task.errors:
                task.errors.append("No media found — the account may be private, empty, or "
                                   "require a logged-in session (Settings → Browser cookies source).")
            if not task.items and not task.warnings:
                # the cookies were readable — but were they *Instagram* cookies?
                try:
                    sess = cookie_state.instagram_session()
                except Exception:  # noqa: BLE001 — diagnostics never break a scan
                    sess = {}
                if sess.get("source") and not sess.get("instagram"):
                    task.warnings.append(
                        f"{sess['source']} is readable, but it has no Instagram login, so "
                        "Instagram answers every request as a visitor. Open instagram.com in "
                        "that browser, sign in, then scan again — or export a cookies.txt from "
                        "the logged-in session (Settings → Video & capture → Cookies file).")
        elif not task.errors:
            task.errors.append("scan cancelled")
        task.finished = time.time()


# ---------------------------------------------------------------------------
# Download hand-off — the normal manager does the actual transfer
# ---------------------------------------------------------------------------
def to_job(item: dict) -> dict:
    """Enqueue kwargs for one scanned item (http worker + Instagram headers)."""
    kind = item.get("kind") or "image"
    headers = {
        "Referer": "https://www.instagram.com/",
        "Accept": "*/*",
    }
    return {
        "url": item.get("url", ""),
        "kind": "http",
        "title": (item.get("caption") or item.get("filename") or "instagram")[:150],
        "filename": item.get("filename") or "",
        "file_type": "video" if kind == "video" else ("audio" if kind == "audio" else "image"),
        "meta": {"referer": "https://www.instagram.com/", "headers": headers,
                 "source": "instagram", "post": item.get("post", "")},
    }


def gallery_engine_info() -> dict:
    d = detect()
    return {"available": d["available"], "version": d["version"],
            "exe": d["exe"], "install_hint": d["install_hint"],
            "targets": [{"key": k, **{f: v[f] for f in ("label", "about", "icon")}}
                        for k, v in TARGETS.items()],
            "defaults": {"include": clean_targets(None),
                         "limit": int(settings.get("instagram_limit") or 30)}}
