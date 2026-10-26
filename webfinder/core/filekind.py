"""All Video Downloader — URL → file-kind taxonomy helpers.

Slimmed descendant of the old search `dorks` module: no query building, no
engine anything — just the classification the downloader still relies on.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse, unquote

VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".m4v", ".ts", ".m2ts", ".wmv", ".3gp", ".mpg", ".mpeg"}
ARCHIVE_EXTS = {".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".iso"}
AUDIO_EXTS = {".mp3", ".flac", ".m4a", ".opus", ".wav", ".aac", ".ogg"}
STREAM_EXTS = {".m3u8", ".mpd"}
EXT_KIND: dict[str, str] = {}
for _e in VIDEO_EXTS: EXT_KIND[_e] = "video"
for _e in AUDIO_EXTS: EXT_KIND[_e] = "audio"
for _e in ARCHIVE_EXTS: EXT_KIND[_e] = "archive"
EXT_KIND[".torrent"] = "torrent"

TORRENT_RE = re.compile(r"[?&]([^=]*)\.torrent|\.torrent(?:$|[?#])", re.I)
MAGNET_RE = re.compile(r"^magnet:\?|xt=urn:btih", re.I)


def url_extension(url: str) -> str:
    """Last path extension, tolerating file-host decorative suffixes.

    ``/get_file/9/<hash>/…/clip_720m.mp4/?download=true`` is still an mp4 — the
    trailing slash and query are KVS/hotlink-guard noise, not part of the name.
    """
    try:
        path = unquote(urlparse(url).path).rstrip("/;")
    except ValueError:
        return ""
    m = re.search(r"(\.[A-Za-z0-9]{1,6})$", path)
    return m.group(1).lower() if m else ""


def classify(url: str, snippet: str = "", title: str = "") -> str:
    """Return the best-matching file-type key for a URL (or 'link')."""
    if MAGNET_RE.search(url):
        return "magnet"
    ext = url_extension(url)
    hay = f"{title} {snippet}".lower()
    if ext in STREAM_EXTS or ".m3u8" in hay or ".mpd" in hay:
        return "video"
    if ext in EXT_KIND:
        return EXT_KIND[ext]
    if TORRENT_RE.search(url) or "torrent" in ext:
        return "torrent"
    if any(k in hay for k in ("magnet link", "xt=urn:btih")):
        return "magnet"
    return "link"


def is_video_url(url: str) -> bool:
    ext = url_extension(url)
    return ext in VIDEO_EXTS or ext in STREAM_EXTS


def guess_filename(url: str, fallback: str = "download") -> str:
    try:
        name = unquote(urlparse(url).path.rstrip("/").split("/")[-1])
    except ValueError:
        name = ""
    name = re.sub(r"[^\w.\-()+ ]", "_", name).strip(".")
    return name or fallback
