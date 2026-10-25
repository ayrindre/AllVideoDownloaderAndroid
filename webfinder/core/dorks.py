"""WebFinder — file-type taxonomy + smart search dorks.

Every file-type chip the user toggles translates into a *dork* string that
gets appended to the raw query, plus a set of extension heuristics the
backend uses to classify URLs that come back from the engines.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse, unquote

# --------------------------------------------------------------------------- 
# File type catalogue
# ---------------------------------------------------------------------------
FILE_TYPES: dict[str, dict] = {
    "video": {
        "label": "Video",
        "icon": "video",
        "color": "#a855f7",
        "dorks": ['(filetype:mp4 OR filetype:mkv OR filetype:avi OR filetype:mov OR filetype:webm OR inurl:".mp4" OR inurl:".mkv")'],
        "exts": {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".m4v", ".ts", ".m2ts", ".wmv", ".m3u8"},
    },
    "image": {
        "label": "Image",
        "icon": "image",
        "color": "#38bdf8",
        "dorks": ['(filetype:jpg OR filetype:jpeg OR filetype:png OR filetype:webp OR filetype:gif OR filetype:svg OR filetype:tiff)'],
        "exts": {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg", ".bmp", ".tiff", ".heic", ".raw"},
    },
    "torrent": {
        # Magnet search is part of Torrent now — one chip, both file kinds.
        "label": "Torrent",
        "icon": "torrent",
        "color": "#22c55e",
        "dorks": ['(filetype:torrent OR inurl:".torrent" OR inurl:magnet "xt=urn:btih")'],
        "exts": {".torrent"},
        "keywords": ["torrent", "magnet", "btih", "seeders", "tracker"],
    },
    "software": {
        "label": "Software",
        "icon": "app",
        "color": "#4f7cff",
        "dorks": ['(filetype:exe OR filetype:msi OR filetype:appimage OR (setup OR installer OR portable download))'],
        "exts": {".exe", ".msi", ".appimage", ".msix", ".bat", ".apk", ".dmg"},
    },
    "archive": {
        "label": "Archive",
        "icon": "archive",
        "color": "#eab308",
        "dorks": ['(filetype:zip OR filetype:rar OR filetype:7z OR filetype:tar OR filetype:gz)',
                  'intitle:"index of" (zip OR rar OR 7z OR tar)'],
        "exts": {".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".iso"},
    },
    "audio": {
        "label": "Audio",
        "icon": "audio",
        "color": "#ec4899",
        "dorks": ['(filetype:mp3 OR filetype:flac OR filetype:m4a OR filetype:opus OR filetype:wav)'],
        "exts": {".mp3", ".flac", ".m4a", ".opus", ".wav", ".aac", ".ogg"},
    },
    "ebook": {
        "label": "E-Book",
        "icon": "book",
        "color": "#14b8a6",
        "dorks": ['(filetype:pdf OR filetype:epub OR filetype:mobi) (book OR ebook OR "read online")'],
        "exts": {".pdf", ".epub", ".mobi", ".azw3", ".djvu", ".fb2"},
    },
}

STREAM_EXTS = {".m3u8", ".mpd"}
TORRENT_RE = re.compile(r"[?&]([^=]*)\.torrent|\.torrent(?:$|[?#])", re.I)
MAGNET_RE = re.compile(r"^magnet:\?|xt=urn:btih", re.I)
# "42 MB", "1.4 GB", "350kb" — engines love leaking sizes in snippets.
SIZE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s?(KB|MB|GB|TB|KiB|MiB|GiB|TiB|kB|kb)\b", re.I)
SIZE_MULT = {"k": 1024, "m": 1024**2, "g": 1024**3, "t": 1024**4}


def build_query(raw_query: str, selected_types: list[str]) -> str:
    """Append per-type dorks (OR-joined) to the user query."""
    q = raw_query.strip()
    dorks: list[str] = []
    for t in selected_types:
        spec = FILE_TYPES.get(t)
        if not spec:
            continue
        for d in spec["dorks"]:
            if d not in dorks:
                dorks.append(d)
    if not dorks:
        return q
    if len(dorks) == 1:
        return f"{q} {dorks[0]}"
    return f"{q} ( " + " OR ".join(dorks) + " )"


def url_extension(url: str) -> str:
    try:
        path = unquote(urlparse(url).path)
    except ValueError:
        return ""
    m = re.search(r"(\.[A-Za-z0-9]{1,6})$", path)
    return m.group(1).lower() if m else ""


def classify(url: str, snippet: str = "", title: str = "") -> str:
    """Return the best-matching file-type key for a result (or 'link')."""
    if MAGNET_RE.search(url):
        return "magnet"
    ext = url_extension(url)
    hay = f"{title} {snippet}".lower()
    if ext in STREAM_EXTS or ".m3u8" in hay or ".mpd" in hay:
        return "video"
    for key, spec in FILE_TYPES.items():
        if ext and ext in spec["exts"]:
            return key
    if TORRENT_RE.search(url) or "torrent" in ext:
        return "torrent"
    if any(k in hay for k in ("magnet link", "xt=urn:btih")):
        return "magnet"
    if ".torrent" in hay:
        return "torrent"
    return "link"


def guess_filename(url: str, fallback: str = "download") -> str:
    try:
        name = unquote(urlparse(url).path.rstrip("/").split("/")[-1])
    except ValueError:
        name = ""
    name = re.sub(r"[^\w.\-()+ ]", "_", name).strip(".")
    return name or fallback


def extract_size_hint(text: str) -> int | None:
    m = SIZE_RE.search(text or "")
    if not m:
        return None
    value = float(m.group(1).replace(",", "."))
    unit = m.group(2)[0].lower()
    size = int(value * SIZE_MULT[unit])
    # sanity: ignore < 1 KB or > 20 TB noise
    return size if 1024 <= size <= 20 * 1024**4 else None
