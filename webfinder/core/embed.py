"""All Video Downloader — media extraction from page source & player configs.

Most video sites do not expose an ``og:video`` tag or a plain file anchor.
What they expose is a **player configuration** somewhere in the HTML:

* ``html5player.setVideoUrlHigh('/videos/....mp4')``      (xvideos, xnxx…)
* ``video_url: 'https://.../video.mp4'``                  (kt_player / porntrex…)
* ``{"hlsUrl": "https:\\/\\/cdn...\\/master.m3u8"}``      (JSON, escaped slashes)
* ``sources: [{file: "..."}]``                            (jwplayer, video.js…)
* ``__NEXT_DATA__`` / ``__NUXT__`` blobs                  (modern tube front-ends)
* ``"contentUrl": "..."``                                 (JSON-LD schema.org)

This module turns any of those into plain candidate URLs — no per-site code
required — and scores them so the real 1080p stream outranks ads, sprites,
posters and tracking pixels. :mod:`webfinder.core.sites` adds per-site labels
on top of this generic layer.
"""
from __future__ import annotations

import re
from urllib.parse import unquote, urljoin, urlparse

from . import filekind as fk

# ---------------------------------------------------------------------------
# URL shapes worth pulling out of a document
# ---------------------------------------------------------------------------
_EXTS = (r"mp4|m3u8|mpd|webm|mkv|mov|m4v|flv|f4v|ts|m2ts|3gp|ogv"
         r"|mp3|m4a|aac|ogg|opus|wav|flac")

_ABS_URL = rf"(?:https?:)?//[^\s\"'<>\\`{{}}|^]+?\.(?:{_EXTS})(?:\?[^\s\"'<>\\`{{}}|^]*)?"
_REL_URL = rf"(?<![\w:/])(?:/[^\s\"'<>\\`{{}}|^]+?\.(?:{_EXTS}))(?:\?[^\s\"'<>\\`{{}}|^]*)?"

# any media file URL, absolute, protocol-relative or rooted
MEDIA_URL_RE = re.compile(rf"(?P<url>{_ABS_URL}|{_REL_URL})", re.I)

# media served through a query parameter (no extension in the path)
QUERY_EXT_RE = re.compile(
    rf"""(?P<url>(?:https?:)?//[^\s"'<>\\]{{10,}}?[?&](?:type|format|ext|mime|filetype)="""
    rf"""(?:video%2F|audio%2F)?(?:{_EXTS})\b[^\s"'<>\\]*)""", re.I)

# key/value pairs from JS object literals or JSON
_KV_RE = re.compile(
    r"""(?P<k>[A-Za-z_$][\w$.\-]{0,40}?)\s*(?::|=>|=)\s*"""
    r"""(?P<q>["'])(?P<v>[^"'\s<>\\]{6,900})(?P=q)""")
_VIDEO_KEY_RE = re.compile(r"video|hls|dash|stream|media|playback|movie|clip|source|file|mp4|m3u8|mpd", re.I)

_ASSET_EXT_RE = re.compile(
    r"\.(?:jpe?g|png|gif|webp|avif|svg|ico|bmp|tiff|css|js|mjs|jsx|json|xml|txt|html?|woff2?|ttf|eot|map|vtt|srt)(?:$|[?#])",
    re.I)

_AD_HOST_RE = re.compile(
    r"(?:^|\.)(?:doubleclick|googlesyndication|googleadservices|adservice|adsystem"
    r"|adnxs|exoclick|exosrv|juicyads|trafficjunky|trafficfactory|popads|popcash"
    r"|propellerads|adsterra|tsyndicate|realsrv|adspy|clickadu|hilltopads|adcash"
    r"|zergnet|outbrain|taboola|mgid|revcontent|adroll|smartadserver)\.", re.I)

# paths that are almost never the feature video
_LOW_VALUE_RE = re.compile(r"thumb|poster|sprite|preview|trailer|sample|placeholder|logo|banner", re.I)
# A URL sitting in a tag attribute is a *link*, not a player-config URL: the
# caller classifies those itself (anchor / <video> / og:), so never double-label
# a directory listing as "qualities of one video".
_ATTR_PREFIX_RE = re.compile(r"""(?:href|src|poster|action)\s*=\s*["']\s*$""", re.I)

_HEIGHT_RE = re.compile(r"(?<![0-9A-Za-z])(2160|1440|1080|720|540|480|360|270|240|180|144)(?:p)?(?![0-9A-Za-z])", re.I)
_DIM_RE = re.compile(r"(?<!\d)(\d{3,4})\s*x\s*(2160|1440|1080|720|540|480|360|240)(?!\d)", re.I)
_WORD_QUALITY = (
    (re.compile(r"(?<![a-z])4k(?![a-z])|uhd", re.I), 2160),
    (re.compile(r"(?<![a-z])qhd(?![a-z])", re.I), 1440),
    (re.compile(r"(?<![a-z])fhd(?![a-z])", re.I), 1080),
    (re.compile(r"(?<![a-z])hd(?![a-z])", re.I), 720),
    (re.compile(r"(?<![a-z])sd(?![a-z])", re.I), 480),
)

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_OG_TITLE_RE = re.compile(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', re.I)
_OG_IMAGE_RE = re.compile(r'<meta[^>]+property=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)', re.I)


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------
_ESCAPES = (
    (re.compile(r"\\/"), "/"),
    (re.compile(r"\\u002[fF]"), "/"),
    (re.compile(r"\\u003[aA]"), ":"),
    (re.compile(r"\\u0026"), "&"),
    (re.compile(r"\\u003[dD]"), "="),
    (re.compile(r"&#x2[fF];|&#47;"), "/"),
    (re.compile(r"&#x3[aA];|&#58;"), ":"),
    (re.compile(r"&amp;"), "&"),
)


def normalize(text: str) -> str:
    """Undo the escaping layers sites hide URLs behind (``\\/``, ``\\u002F``…)."""
    out = text or ""
    for pat, repl in _ESCAPES:
        out = pat.sub(repl, out)
    return out


def quality_of(url: str, label: str = "") -> tuple[int, str]:
    """Best-effort ``(height, human label)`` for a media URL."""
    blob = unquote(f"{label} {url}")
    path = ""
    try:
        path = unquote(urlparse(url).path)
    except ValueError:
        path = ""
    hay = f"{path} {url}"
    for m in _DIM_RE.finditer(hay):
        try:
            return int(m.group(2)), f"{int(m.group(2))}p"
        except ValueError:
            continue
    m = _HEIGHT_RE.search(hay)
    if m:
        h = int(m.group(1))
        return h, f"{h}p"
    for pat, h in _WORD_QUALITY:
        if pat.search(blob) and not _HEIGHT_RE.search(hay):
            return h, ("2160p" if h >= 2160 else f"{h}p")
    if label:
        return 0, label
    return 0, ""


def _ext(url: str) -> str:
    """Lower-case extension without the dot (``m3u8``, ``mp4``…)."""
    try:
        ext = fk.url_extension(urlparse(url).path) or fk.url_extension(url)
    except ValueError:
        return ""
    return ext.lstrip(".").lower()


def _reject(url: str) -> bool:
    low = url.lower()
    if not low.startswith(("http://", "https://")):
        return True
    if _ASSET_EXT_RE.search(low):
        return True
    try:
        host = urlparse(url).netloc
    except ValueError:
        return True
    return bool(_AD_HOST_RE.search(host))


def _score(url: str, origin: str, label: str = "") -> int:
    ext = _ext(url)
    base = {"m3u8": 62, "mpd": 58, "mp4": 52, "webm": 46, "mkv": 44,
            "mov": 40, "m4v": 40, "f4v": 36, "flv": 34, "ts": 20,
            "mp3": 30, "m4a": 30}.get(ext, 26)
    height, _ = quality_of(url, label)
    score = base + height // 100               # 1080p ≈ +10
    if _LOW_VALUE_RE.search(url):
        score -= 12
    try:
        if urlparse(url).scheme == "http":
            score -= 2
    except ValueError:
        pass
    score += {"recipe": 8, "embed": 4, "og": 10, "video": 10}.get(origin, 0)
    return score


def candidate(url: str, base_url: str, origin: str = "embed", label: str = "") -> dict | None:
    """Turn a raw URL found in a document into an analyzer candidate."""
    raw = (url or "").strip().strip('"\'')
    if not raw or len(raw) < 8:
        return None
    if raw.startswith(("data:", "blob:", "javascript:", "mailto:", "#")):
        return None
    full = urljoin(base_url, raw)
    if _reject(full):
        return None
    height, qlabel = quality_of(full, label)
    if not qlabel and label:
        qlabel = label
    ext = _ext(full)
    if not qlabel and ext in ("m3u8", "mpd"):
        qlabel = "HLS (auto)" if ext == "m3u8" else "DASH (auto)"
    kind = ("audio" if fk.classify(full) == "audio"
            else "video")
    name = unquote(fk.guess_filename(full, f"video.{ext or 'mp4'}"))
    if "." not in name and ext:
        name = f"{name}.{ext}"
    return {"url": full, "filename": name, "file_type": kind,
            "size_bytes": None, "height": height, "quality": qlabel,
            "source": origin, "score": _score(full, origin, label),
            "ext": ext}


def extract(text: str, base_url: str, *, limit: int = 48,
            origin: str = "embed") -> list[dict]:
    """All media URLs in a document, de-duplicated and best-first."""
    norm = normalize(text)
    found: dict[str, dict] = {}

    def add(url: str, origin_: str = origin, label: str = "") -> None:
        c = candidate(url, base_url, origin_, label)
        if not c:
            return
        old = found.get(c["url"])
        if old is None or c["score"] > old["score"]:
            found[c["url"]] = c

    for pat in (MEDIA_URL_RE, QUERY_EXT_RE):
        for m in pat.finditer(norm):
            if _ATTR_PREFIX_RE.search(norm[max(0, m.start() - 24):m.start()]):
                continue
            add(m.group("url"))
    for m in _KV_RE.finditer(norm):
        key, val = m.group("k") or "", m.group("v") or ""
        if not _VIDEO_KEY_RE.search(key) or _ASSET_EXT_RE.search(val.lower()):
            continue
        # a URL-shaped value only: extension, or a rooted/absolute path
        if not (re.search(rf"\.(?:{_EXTS})(?:$|[?#])", val, re.I)
                or val.startswith(("http", "//", "/"))):
            continue
        add(val, origin, "")

    out = sorted(found.values(), key=lambda c: -c["score"])
    return out[:limit]


# ---------------------------------------------------------------------------
# Page metadata (title / poster) — small helper used by the analyzer
# ---------------------------------------------------------------------------
def page_meta(html: str, base_url: str) -> dict:
    text = html or ""
    title = ""
    m = _OG_TITLE_RE.search(text)
    if m:
        title = m.group(1)
    if not title:
        m = _TITLE_RE.search(text)
        if m:
            title = re.sub(r"\s+", " ", m.group(1))
    title = (title or "").strip()[:180]
    thumb = ""
    m = _OG_IMAGE_RE.search(text)
    if m:
        try:
            thumb = urljoin(base_url, m.group(1).strip())
        except ValueError:
            thumb = ""
    return {"title": _clean_title(title), "thumbnail": thumb}


_SITE_SUFFIX_RE = re.compile(
    r"\s*[|\-–—·:]\s*(?:watch|free|hd|official|home|video|videos|tube|porn|sex|xxx)\b.*$", re.I)


def _clean_title(title: str) -> str:
    """Drop the trailing ' - SiteName / Free HD Porn' noise from <title>."""
    t = re.sub(r"\s+", " ", title or "").strip()
    if not t:
        return ""
    for sep in (" | ", " – ", " — ", " - ", " · "):
        if sep in t:
            first = t.split(sep)[0].strip()
            if len(first) >= 6:
                return first[:180]
    return t[:180]
