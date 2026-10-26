"""All Video Downloader — media extraction from page source & player configs.

Most video sites do not expose an ``og:video`` tag or a plain file anchor.
What they expose is a **player configuration** somewhere in the HTML:

* ``html5player.setVideoUrlHigh('/videos/....mp4')``      (xvideos, xnxx…)
* ``video_url: 'https://.../video.mp4'``                  (kt_player / porntrex…)
* ``flashvars = { video_url: 'function/0/https://…' }``  (KVS tubes: hashed)
* ``{"hlsUrl": "https:\\\\/\\\\/cdn...\\\\/master.m3u8"}``      (JSON, escaped slashes)
* ``sources: [{file: "...", label: "1080p"}]``            (jwplayer, video.js…)
* ``player.src({type: "application/x-mpegURL", src})``   (video.js, plyr, clappr)
* ``manifestUri: "..."``                                 (Shaka player)
* ``__NEXT_DATA__`` / ``__NUXT__`` blobs                  (modern tube front-ends)
* ``"contentUrl": "..."``                                 (JSON-LD schema.org)
* ``eval(function(p,a,c,k,e,d){…})``                      (packed/obfuscated players)

This module turns any of those into plain candidate URLs — no per-site code
required — and scores them so the real 1080p stream outranks ads, sprites,
posters and tracking pixels. :mod:`webfinder.core.sites` adds per-site labels
on top of this generic layer.
"""
from __future__ import annotations

import re
from urllib.parse import unquote, urljoin, urlparse, urlunparse

from . import filekind as fk

# ---------------------------------------------------------------------------
# URL shapes worth pulling out of a document
# ---------------------------------------------------------------------------
_EXTS = (r"mp4|m3u8|mpd|webm|mkv|mov|m4v|flv|f4v|m4s|ts|m2ts|3gp|ogv"
         r"|mp3|m4a|aac|ogg|opus|wav|flac")

_TRAIL = r"""[^\s"'<>\\`{}|^]"""
_ABS_URL = (rf"(?:https?:)?//{_TRAIL}+?\.(?:{_EXTS})"
            rf"(?:/{_TRAIL}*)?(?:\?{_TRAIL}*)?")
_REL_URL = (rf"(?<![\w:/])(?:/{_TRAIL}+?\.(?:{_EXTS}))"
            rf"(?:/{_TRAIL}*)?(?:\?{_TRAIL}*)?")

# any media file URL, absolute, protocol-relative or rooted
MEDIA_URL_RE = re.compile(rf"(?P<url>{_ABS_URL}|{_REL_URL})", re.I)

# media served through a query parameter (no extension in the path)
QUERY_EXT_RE = re.compile(
    rf"""(?P<url>(?:https?:)?//[^\s"'<>\\]{{10,}}?[?&](?:type|format|ext|mime|filetype)="""
    rf"""(?:video%2F|audio%2F)?(?:{_EXTS})\b[^\s"'<>\\]*)""", re.I)

# key/value pairs from JS object literals or JSON
_KV_RE = re.compile(
    r"""(?P<k>[A-Za-z_$][\w$.$\[\]'"]{0,40}?)\s*(?::|=>|=)\s*"""
    r"""(?P<q>["'])(?P<v>[^"'\s<>\\]{6,900})(?P=q)""")
_VIDEO_KEY_RE = re.compile(
    r"video|hls|dash|stream|media|playback|movie|clip|source|file|mp4|m3u8|mpd"
    r"|manifest|contenturl|embedurl|playurl|redirect", re.I)

_ASSET_EXT_RE = re.compile(
    r"\.(?:jpe?g|png|gif|webp|avif|svg|ico|bmp|tiff|css|js|mjs|jsx|json|xml|txt|html?|woff2?|ttf|eot|map|vtt|srt)(?:$|[?#])",
    re.I)

_AD_HOST_RE = re.compile(
    r"(?:^|\.)(?:doubleclick|googlesyndication|googleadservices|adservice|adsystem"
    r"|adnxs|exoclick|exosrv|juicyads|trafficjunky|trafficfactory|popads|popcash"
    r"|propellerads|adsterra|tsyndicate|realsrv|adspy|clickadu|hilltopads|adcash"
    r"|zergnet|outbrain|taboola|mgid|revcontent|adroll|smartadserver|smartfloralab"
    r"|dreamserve|onclickads|popmyads|adnium|poptm|trafficstars)\.", re.I)

# paths that are almost never the feature video
_LOW_VALUE_RE = re.compile(r"thumb|poster|sprite|preview|trailer|sample|placeholder|logo|banner", re.I)
# A URL sitting in a tag attribute is a *link*, not a player-config URL: the
# caller classifies those itself (anchor / <video> / og:), so never double-label
# a directory listing as "qualities of one video".
_ATTR_PREFIX_RE = re.compile(r"""(?:href|src|poster|action|data-\w+)\s*=\s*["']\s*$""", re.I)

# resolution tokens: "1080p", "1280x720", "…_720m.mp4", "…-480p-…"
_HEIGHT_RE = re.compile(
    r"(?<![0-9A-Za-z])(2160|1440|1080|720|540|480|360|270|240|180|144)(?:[pP]|[mM]|[iI])?(?![0-9A-Za-z])",
    re.I)
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

# ── media announced by the document itself ────────────────────────────────
# og:video / twitter player streams / schema.org contentUrl
_META_STREAM_RE = re.compile(
    r"""<meta\b[^>]*?(?:property|name|itemprop)\s*=\s*["']"""
    r"""(?:og:video(?::(?:url|secure_url))?|twitter:player:stream|twitter:player|contentUrl|video_src)"""
    r"""["'][^>]*?content\s*=\s*["']([^"']+)["']""", re.I)
# the same tags written with content= first (common in hand-written templates)
_META_STREAM_REV = re.compile(
    r"""<meta\b[^>]*?content\s*=\s*["']([^"']+)["'][^>]*?(?:property|name|itemprop)\s*=\s*["']"""
    r"""(?:og:video(?::(?:url|secure_url))?|twitter:player:stream|twitter:player|contentUrl|video_src)"""
    r"""["']""", re.I)
# <link rel="video_src">, <link rel=preload as=video>, schema.org <link itemprop>
_LINK_STREAM_RE = re.compile(
    r"""<link\b[^>]*?(?:rel|as|itemprop)\s*=\s*["'](?:video_src|preload|video|contentUrl)["']"""
    r"""[^>]*?href\s*=\s*["']([^"']+)["']""", re.I)
# <video src> / <source> and the lazily-loaded spellings every tube site invents
_MEDIA_ATTR_RE = re.compile(
    r"""<(?:video|source|audio)\b[^>]*?"""
    r"""(?:data-(?:src|video|hls|dash|mp4|url|file|source|stream|video-src)|src)"""
    r"""\s*=\s*["']([^"']{8,})["']""", re.I)


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------
_ESCAPES = (
    (re.compile(r"\\/"), "/"),
    (re.compile(r"\\u002[fF]"), "/"),
    (re.compile(r"\\u003[aA]"), ":"),
    (re.compile(r"\\u0026"), "&"),
    (re.compile(r"\\u003[dD]"), "="),
    (re.compile(r"\\u0022"), '"'),
    (re.compile(r"\\u0027"), "'"),
    (re.compile(r"&#x2[fF];|&#47;"), "/"),
    (re.compile(r"&#x3[aA];|&#58;"), ":"),
    (re.compile(r"&amp;"), "&"),
)


def normalize(text: str) -> str:
    """Undo the escaping layers sites hide URLs behind (``\\\\/``, ``\\\\u002F``…)."""
    out = text or ""
    for pat, repl in _ESCAPES:
        out = pat.sub(repl, out)
    return out


# ---------------------------------------------------------------------------
# KVS / kt_player — the platform under a large share of tube sites
# ---------------------------------------------------------------------------
# KVS hides real files behind a permuted path segment:
#     video_url: 'function/0/https://host/get_file/9/<32 scrambled chars>/…/clip_720p.mp4/'
# The permutation is derived from the page's ``license_code``. This is the same
# reversible mapping yt-dlp applies in its generic extractor, implemented here
# so the app finds those files even when yt-dlp has no extractor for the site.
_KVS_LICENSE_RE = re.compile(r"""license_code\s*[:=]\s*['"]\$?(?P<code>\d{4,})['"]""", re.I)
_KVS_STREAM_RE = re.compile(r"""(?P<key>video_(?:url|alt_url\d*))\s*:\s*['"](?P<val>[^'"]{4,900})['"]""", re.I)
# a plain-URL match directly preceded by KVS's "function/0/" marker belongs to
# the flashvars slot above — it must be decrypted, never offered scrambled
_KVS_PREFIX_RE = re.compile(r"function/[0-9]+/\s*$", re.I)
_KVS_TEXT_MAX = 40


def kvs_license_code(text: str) -> str:
    """The page's KVS ``license_code`` ('' when the document is not KVS)."""
    m = _KVS_LICENSE_RE.search(text or "")
    return m.group("code") if m else ""


def kvs_license_token(license_code: str) -> list[int]:
    code = (license_code or "").replace("$", "").strip()
    values = [int(ch) for ch in code if ch.isdigit()]
    mod = code.replace("0", "1")
    center = len(mod) // 2
    try:
        front, back = int(mod[:center + 1]), int(mod[center:])
    except ValueError:
        return []
    mod = str(4 * abs(front - back))[:center + 1]
    return [(values[i + off] + cur) % 10
            for i, cur in enumerate(map(int, mod))
            for off in range(4)
            if i + off < len(values)]


def kvs_real_url(video_url: str, license_code: str = "") -> str:
    """Undo KVS's permuted path segment (``function/0/…``); unchanged otherwise."""
    url = (video_url or "").strip()
    if not url.lower().startswith("function/"):
        return url
    inner = url[len("function/0/"):] if url.startswith("function/0/") else url.split("/", 2)[-1]
    parts = urlparse(inner)
    path_parts = parts.path.split("/")
    token = kvs_license_token(license_code) if license_code else []
    # a genuine KVS license always expands to 32 digits; anything shorter
    # cannot describe the permutation, so the plain path is the honest answer
    if len(token) >= 32 and len(path_parts) > 3 and len(path_parts[3]) >= 32:
        length = 32
        hash_ = path_parts[3][:length]
        indices = list(range(length))
        accum = 0
        for src in reversed(range(length)):
            accum += token[src]
            dest = (src + accum) % length
            indices[src], indices[dest] = indices[dest], indices[src]
        path_parts[3] = "".join(hash_[i] for i in indices) + path_parts[3][length:]
    return urlunparse(parts._replace(path="/".join(path_parts)))


def _kvs_label(text: str, key: str, url: str) -> str:
    """The human label a KVS page gives this slot (``video_url_text: '720p'``)."""
    m = re.search(rf"""\b{re.escape(key)}_text\s*:\s*['"]([^'"]{{1,{_KVS_TEXT_MAX}}})['"]""", text, re.I)
    if m:
        return m.group(1).strip()
    m = re.search(r"""\bpostfix\s*:\s*['"]([^'"]{0,20})['"]""", text, re.I)
    found = re.search(r"(\d{3,4})[pP]", url) or re.search(r"_(\d{3,4})m?\.", url)
    if found:
        return f"{found.group(1)}p"
    return m.group(1) if m else ""


# ---------------------------------------------------------------------------
# Packed / obfuscated player scripts (Dean Edwards packer, used by file hosts)
# ---------------------------------------------------------------------------
_PACKED_RE = re.compile(
    r"""eval\s*\(\s*function\s*\(\s*p\s*,\s*a\s*,\s*c\s*,\s*k\s*,\s*e\s*,\s*[dr]\s*\)\s*\{.*?\}\s*"""
    r"""\(\s*'(?P<p>(?:\\.|[^'\\])*)'\s*,\s*(?P<a>\d+)\s*,\s*(?P<c>\d+)\s*,\s*"""
    r"""'(?P<k>(?:\\.|[^'\\])*)'\s*\.split\(\s*'\|'\s*\)\s*,\s*(?P<d>\d+)\s*,\s*\{\s*\}\s*\)\s*\)""",
    re.S)
_BASE62 = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"

# atob('…') / Base64.decode('…') wrappers around a player config
_ATOB_RE = re.compile(
    r"""(?:atob|base64decode|Base64\.decode|b64decode)\s*\(\s*["'](?P<v>[A-Za-z0-9+/=]{40,4000})["']\s*\)""",
    re.I)


# percent-encoded media URLs — ``?url=https%3A%2F%2Fcdn…%2Fclip.mp4``
_PCT_TOKEN_RE = re.compile(r"[A-Za-z0-9._~%:/?#\[\]@!$&'()*+,;=-]{12,2400}")


def decode_percent(text: str, *, limit: int = 400_000) -> str:
    """URL-decode percent-encoded media links (embed params, JSON payloads)."""
    src = text or ""
    if len(src) > limit or "%" not in src:
        return ""
    out: list[str] = []
    for m in _PCT_TOKEN_RE.finditer(src):
        token = m.group(0)
        if "%3" not in token and "%2" not in token:
            continue
        try:
            decoded = unquote(token)
        except Exception:  # noqa: BLE001 — malformed escape
            continue
        # keep only the URL inside the decoded token: the token itself is often
        # an embed path wrapping it (``/embed?u=<url>``), so start at the scheme.
        at = decoded.lower().find("http")
        if at < 0:
            continue
        for hit in MEDIA_URL_RE.finditer(decoded[at:]):
            if hit.group("url").startswith("//"):
                out.append("https:" + hit.group("url"))
            else:
                out.append(hit.group("url"))
    return "\n".join(dict.fromkeys(out))


def decode_atob(text: str, *, limit: int = 400_000) -> str:
    """Decode ``atob("…")`` blobs — some players keep the config base64-encoded."""
    import base64
    src = text or ""
    if len(src) > limit:
        return ""
    out: list[str] = []
    for m in _ATOB_RE.finditer(src):
        try:
            raw = base64.b64decode(m.group("v") + "===", validate=False)
        except Exception:  # noqa: BLE001 — not base64: ignore
            continue
        try:
            decoded = raw.decode("utf-8", "ignore")
        except Exception:  # noqa: BLE001
            continue
        if any(ext in decoded.lower() for ext in (".mp4", ".m3u8", ".mpd", "http")):
            out.append(decoded)
    return "\n".join(out)


def _base_convert(num: int, base: int) -> str:
    num = int(num)
    base = max(2, min(62, int(base)))
    if num <= 0:
        return "0"
    out = ""
    while num:
        out = _BASE62[num % base] + out
        num //= base
    return out


def unpack_packed(text: str, *, limit: int = 900_000) -> str:
    """Decode ``eval(function(p,a,c,k,e,d)…)`` blobs; returns '' when absent.

    File hosts (Filemoon, StreamWish, StreamHide, many tube embeds) ship the
    player config *only* in this packed form. Unpacking turns an opaque script
    into plain text our ordinary extraction pass already understands — no
    per-host regex zoo, no JavaScript engine.
    """
    src = text or ""
    if "eval(function(p,a,c,k,e" not in src.replace(" ", "") or len(src) > limit:
        return ""
    chunks: list[str] = []
    for m in _PACKED_RE.finditer(src):
        payload, words = m.group("p"), m.group("k")
        try:
            count = int(m.group("c"))
            base = int(m.group("a"))
        except (TypeError, ValueError):
            continue
        words = words.split("|")
        decoded = payload
        for i in range(count - 1, -1, -1):
            if i >= len(words) or not words[i]:
                continue
            decoded = re.sub(rf"\b{re.escape(_base_convert(i, base))}\b", words[i], decoded)
        chunks.append(decoded.replace("\\'", "'").replace('\\"', '"'))
    return "\n".join(chunks)


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
    if label:
        m = _HEIGHT_RE.search(label)
        if m:                       # label itself states the resolution ("1080p")
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
            "mov": 40, "m4v": 40, "f4v": 36, "flv": 34, "m4s": 24, "ts": 20,
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


def candidate(url: str, base_url: str, origin: str = "embed", label: str = "",
              *, license_code: str = "") -> dict | None:
    """Turn a raw URL found in a document into an analyzer candidate."""
    raw = (url or "").strip().strip('"\'')
    if not raw or len(raw) < 8:
        return None
    if raw.startswith(("data:", "blob:", "javascript:", "mailto:", "#")):
        return None
    if raw.lower().startswith("function/"):
        raw = kvs_real_url(raw, license_code)
        if raw.lower().startswith("function/"):
            return None
    full = urljoin(base_url, raw)
    full = re.sub(r"[),;\]}]+$", "", full)          # sentence punctuation
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


# ---------------------------------------------------------------------------
# Label discovery: "quality: 1080p" sitting next to the URL in a JSON blob
# ---------------------------------------------------------------------------
_NEAR_LABEL_RE = re.compile(
    r"""["']?(?:label|quality|resolution|res|name|title|height)["']?\s*:\s*["']?"""
    r"""([^"',}\]\n]{1,24}?)["']?\s*[,}\]\n]""", re.I)
_NEAR_RES_RE = re.compile(r"^(?:2160|1440|1080|720|540|480|360|270|240|180|144)\s*[pP]?$")


def _as_label(raw: str) -> str:
    cand = (raw or "").strip()
    if _NEAR_RES_RE.match(cand):
        return cand if cand.lower().endswith("p") else f"{cand}p"
    if re.fullmatch(r"(?:4K|UHD|FHD|HD|SD|High|Low|Medium)", cand, re.I):
        return cand
    return ""


def label_near(text: str, url: str, window: int = 240) -> str:
    """Human quality label stored beside this URL (jwplayer/videojs/KVS JSON).

    Only the *same object* counts: first the keys that follow the URL (up to the
    closing brace), then — when the label precedes the URL, as in
    ``{quality: "1080", videoUrl: "…"}`` — the nearest preceding key. A label
    from the next object in the array is never borrowed, so a 720p sibling can
    no longer relabel a 1080p file.
    """
    text = text or ""
    idx = text.find(url)
    if idx < 0:
        return ""
    after = text[idx: idx + window]
    cut = after.find("}")
    if cut >= 0:
        after = after[:cut + 1]          # keep the closing brace: the label regex needs a terminator
    for m in _NEAR_LABEL_RE.finditer(after):
        label = _as_label(m.group(1))
        if label:
            return label
    before = text[max(0, idx - window): idx]
    for m in reversed(list(_NEAR_LABEL_RE.finditer(before))):
        label = _as_label(m.group(1))
        if label:
            return label
    return ""


def extract(text: str, base_url: str, *, limit: int = 48,
            origin: str = "embed") -> list[dict]:
    """All media URLs in a document, de-duplicated and best-first."""
    norm = normalize(text)
    extra = "\n".join(x for x in (unpack_packed(norm), decode_atob(norm),
                                   decode_percent(norm)) if x)
    scan = f"{norm}\n{extra}" if extra else norm
    found: dict[str, dict] = {}

    def add(url: str, origin_: str = origin, label: str = "",
            license_code: str = "") -> None:
        c = candidate(url, base_url, origin_, label, license_code=license_code)
        if not c:
            return
        old = found.get(c["url"])
        if old is None or c["score"] > old["score"]:
            found[c["url"]] = c

    # 1) KVS flashvars first: their "function/0/…" form must be *decrypted*
    #    before the plain URL pass would harvest the scrambled one.
    license_code = kvs_license_code(scan)
    kvs_values: set[str] = set()
    for m in _KVS_STREAM_RE.finditer(scan):
        val = m.group("val")
        kvs_values.add(val)
        label = _kvs_label(scan, m.group("key"), val)
        add(val, origin, label, license_code)

    # 2) every plain media URL, absolute / protocol-relative / rooted
    for pat in (MEDIA_URL_RE, QUERY_EXT_RE):
        for m in pat.finditer(scan):
            before = scan[max(0, m.start() - 40):m.start()]
            if _ATTR_PREFIX_RE.search(before):
                continue
            if _KVS_PREFIX_RE.search(before):
                continue                      # KVS "function/0/" copy of a hashed URL
            raw = m.group("url")
            if raw in kvs_values:
                continue                      # already added (decrypted) above
            add(raw)

    # 3) key/value pairs from JS objects and JSON (escaped or not)
    for m in _KV_RE.finditer(scan):
        key, val = m.group("k") or "", m.group("v") or ""
        if val in kvs_values:
            continue
        if not _VIDEO_KEY_RE.search(key) or _ASSET_EXT_RE.search(val.lower()):
            continue
        # a URL-shaped value only: extension, or a rooted/absolute path
        if not (re.search(rf"\.(?:{_EXTS})(?:$|[?#/])", val, re.I)
                or val.startswith(("http", "//", "/", "function/"))):
            continue
        add(val, origin, label_near(scan, val), license_code)

    # 4) meta / link / <video>-attribute announcements
    for m in _META_STREAM_RE.finditer(norm):
        add(m.group(1))
    for m in _META_STREAM_REV.finditer(norm):
        add(m.group(1))
    for m in _LINK_STREAM_RE.finditer(norm):
        add(m.group(1))
    for m in _MEDIA_ATTR_RE.finditer(norm):
        add(m.group(1))

    # 5) a quality word sitting beside an otherwise unlabelled URL
    for c in found.values():
        if c["height"] or c.get("quality"):
            continue
        label = label_near(scan, c["url"])
        if label:
            h, q = quality_of(c["url"], label)
            c["height"], c["quality"] = h, (q or label)

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
