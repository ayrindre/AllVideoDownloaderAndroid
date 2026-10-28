"""All Video Downloader — site API adapters.

Most sites are solved by the generic engine (:mod:`webfinder.core.embed`): the
player config is somewhere in the HTML and every media URL can be mined from
it. A few sites cannot be solved that way at any price, because their page is
an empty JavaScript shell and the stream only exists behind a JSON endpoint:

* **Aparat** — the watch page is a React app. Its CDN ladder (144p → 1080p, with
  sizes, plus the HLS master) is published by ``/etc/api/video/videohash/<id>``
  and by ``/api/fa/v1/video/video/show/videohash/<id>``.
* **Filimo** — the VOD front-end has no media URL in the document. The TV
  partner endpoint ``/api/fa/v1/partner/TV/watch/uid/<uid>`` answers with the
  signed HLS manifest for the item.

Those two need code, and that is exactly what lives here: one small, testable
bridge per site, each split into a **pure parser** (``parse_*`` — no network,
fully fixture-testable) and a thin async fetcher. Everything else stays in the
declarative recipe table (:mod:`webfinder.core.sites`).

Adding a site
-------------
1. write ``parse_mysite(payload, page_url) -> dict | None`` returning the same
   card shape the analyzer already renders,
2. register an :class:`Adapter` with its URL regex and a fetcher below,
3. add ``adapter="mysite"`` to the recipe in ``sites.py``.

Nothing else in the app changes.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from . import embed, filekind as fk, net


@dataclass(frozen=True)
class Adapter:
    key: str
    site: str
    match: re.Pattern
    priority: bool = False     # run before yt-dlp (authoritative, cheap answer)
    note: str = ""


_APARAT_RE = re.compile(
    r"^https?://(?:www\.|m\.)?aparat\.com/"
    r"(?:v/|video/video/embed/(?:videohash|vt/frame/showvideo/yes/videohash)/"
    r"|embed/videohash/)(?P<id>[A-Za-z0-9]{3,20})", re.I)

_FILIMO_RE = re.compile(
    r"^https?://(?:www\.)?filimo\.com/"
    r"(?:n|m|w|v|film|serial|movie/movie/watch|movie/movie/download_manager"
    r"|api/fa/v1/partner/TV/watch)/(?:uid/)?(?P<id>[A-Za-z0-9]{4,16})", re.I)


APARAT = Adapter(
    key="aparat", site="Aparat", match=_APARAT_RE, priority=True,
    note="public videohash API → every CDN profile (144p…1080p) with sizes")

FILIMO = Adapter(
    key="filimo", site="Filimo", match=_FILIMO_RE, priority=True,
    note="TV partner API → signed HLS manifest")

ADAPTERS: tuple[Adapter, ...] = (APARAT, FILIMO)
_BY_KEY: dict[str, Adapter] = {a.key: a for a in ADAPTERS}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
_PERSIAN_UNITS = (("کیلو", 1024), ("مگا", 1024 ** 2), ("گیگا", 1024 ** 3))


def size_bytes(text: str) -> int | None:
    """Parse '83.85 مگابایت' / '176 MB' / '8,62 GB' into bytes."""
    if not text or not isinstance(text, str):
        return None
    m = re.search(r"(\d+(?:[.,]\d+)?)", text)
    if not m:
        return None
    try:
        num = float(m.group(1).replace(",", "."))
    except ValueError:
        return None
    low = text.lower()
    mult = 1
    for word, value in _PERSIAN_UNITS:
        if word in text:
            mult = value
            break
    else:
        if "tb" in low:
            mult = 1024 ** 4
        elif "gb" in low:
            mult = 1024 ** 3
        elif "mb" in low:
            mult = 1024 ** 2
        elif "kb" in low:
            mult = 1024
    return int(num * mult) if num > 0 else None


def _ext_of(url: str) -> str:
    ext = fk.url_extension(url).lstrip(".").lower()
    if ext in ("m3u8", "mpd", "mp4", "webm", "mkv"):
        return ext
    return ext or "mp4"


def _format(url: str, *, height: int = 0, label: str = "", size: int | None = None,
            ext: str = "") -> dict:
    ext = ext or _ext_of(url)
    return {"height": int(height or 0),
            "label": label or (f"{height}p" if height else ext.upper()),
            "codecs": [ext], "fps": 0, "format": "url", "url": url,
            "size": size, "ext": ext}


def _dedupe(formats: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for f in formats:
        if f["url"] in seen:
            continue
        seen.add(f["url"])
        out.append(f)
    out.sort(key=lambda f: (-(f.get("height") or 0), f.get("size") or 0))
    return out


def _base_card(kind: str, url: str, title: str, site: str, *, thumbnail: str = "",
               referer: str = "", player: str = "", note: str = "") -> dict:
    card = {"kind": kind, "url": url, "file_type": "video",
            "title": title or fk.guess_filename(url, "video"),
            "site": site, "player": player or f"{site} API",
            "thumbnail": thumbnail, "referer": referer or url,
            "found_on_page": referer or url}
    if note:
        card["access_note"] = note
    return card


# ---------------------------------------------------------------------------
# Aparat
# ---------------------------------------------------------------------------
APARAT_ENDPOINTS = (
    "https://www.aparat.com/etc/api/video/videohash/{id}",
    "https://www.aparat.com/api/fa/v1/video/video/show/videohash/{id}?pr=1&mf=1&referer=direct",
)


def parse_aparat(payload: dict | list, page_url: str) -> dict | None:
    """Aparat's videohash JSON → a full mp4 quality ladder."""
    if not isinstance(payload, dict):
        return None
    video = payload.get("video")
    if not isinstance(video, dict):
        data = payload.get("data") or {}
        video = (data.get("attributes") if isinstance(data, dict) else None) or {}
    if not isinstance(video, dict) or not video:
        return None

    formats: list[dict] = []
    for entry in video.get("file_link_all") or []:
        if not isinstance(entry, dict):
            continue
        profile = str(entry.get("profile") or entry.get("text") or "")
        height, qlabel = embed.quality_of(profile)
        size = size_bytes(entry.get("size"))
        urls = entry.get("urls") or []
        if not isinstance(urls, list):
            urls = [urls]
        for raw in urls:
            if not isinstance(raw, str) or not raw.startswith("http"):
                continue
            formats.append(_format(raw, height=height, label=qlabel or profile,
                                   size=size))
    if not formats and isinstance(video.get("file_link"), str):
        # older payloads only expose the best single file
        h, label = embed.quality_of(video["file_link"])
        formats.append(_format(video["file_link"], height=h, label=label))
    if not formats:
        return None
    formats = _dedupe(formats)

    title = str(video.get("title") or "").strip() or fk.guess_filename(page_url, "Aparat video")
    thumb = str(video.get("big_poster") or video.get("small_poster") or "")
    card = _base_card("webmedia", page_url, title, "Aparat",
                      thumbnail=thumb, referer=page_url,
                      player="Aparat API",
                      note="Aparat publishes these CDN files for guests; if a link "
                           "expires, analyze the page again.")

    cost = video.get("cost_type")
    if isinstance(cost, dict) and str(cost.get("type") or "").lower() not in ("", "free"):
        card["access_note"] = (
            "This Aparat video is paywalled (" + str(cost.get("type")) + "). "
            "The CDN links are signed for the current visitor — if they refuse to "
            "play, add a logged-in cookies.txt in Settings → Video & capture.")
    elif video.get("can_download") is False:
        card["access_note"] = (
            "The uploader switched Aparat's own Download button off. The public "
            "stream files are still listed here, so you can grab the quality you want.")

    card["formats"] = formats
    card["formats_total"] = len(formats)
    duration = video.get("duration")
    try:
        card["duration"] = int(duration) if duration else 0
    except (TypeError, ValueError):
        card["duration"] = 0
    uploader = video.get("sender_name") or video.get("username")
    if uploader:
        card["uploader"] = str(uploader)
    return card


# ---------------------------------------------------------------------------
# Filimo
# ---------------------------------------------------------------------------
FILIMO_ENDPOINT = "https://www.filimo.com/api/fa/v1/partner/TV/watch/uid/{id}"
FILIMO_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Useragent": '{"an":"Filimo","os":"tv"}',
}


def parse_filimo(payload: dict | list, page_url: str) -> dict | None:
    """Filimo's TV-partner JSON → the signed HLS manifest for this item."""
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    attrs = data.get("attributes")
    if not isinstance(attrs, dict) or not attrs:
        return None

    streams: list[tuple[str, str]] = []
    raw_src = attrs.get("movie_src") or []
    groups = raw_src if isinstance(raw_src, list) else [raw_src]
    for group in groups:
        items = group if isinstance(group, list) else [group]
        for item in items:
            if isinstance(item, dict) and isinstance(item.get("src"), str):
                streams.append((item["src"], str(item.get("type") or "")))
    # some payloads carry the manifest under a plain key
    for key in ("movie_src_url", "src", "hls_url", "m3u8"):
        value = attrs.get(key)
        if isinstance(value, str) and value.startswith("http"):
            streams.append((value, ""))
    if not streams:
        return None

    def is_manifest(pair: tuple[str, str]) -> bool:
        url, kind = pair
        return "mpegurl" in kind.lower() or ".m3u8" in url.lower() or ".mpd" in url.lower()

    manifest = next((s for s in streams if is_manifest(s)), None)
    mp4s = [s for s in streams if not is_manifest(s) and s[0].startswith("http")]

    title = str(attrs.get("movie_title") or attrs.get("movie_title_en") or "").strip()
    if not title:
        title = fk.guess_filename(page_url, "Filimo video")
    thumb = str(attrs.get("pic") or "")

    pseudo = attrs.get("moviePseudo")
    note = ""
    if isinstance(pseudo, dict) and str(pseudo.get("type") or "").lower() == "error":
        note = ("Filimo marks this title as subscriber-only. The manifest below is the "
                "real, time-signed stream: to download it, add a logged-in cookies.txt "
                "in Settings → Video & capture (the API itself answered anonymously).")
    watch = attrs.get("watch_action")
    if not note and isinstance(watch, dict) and str(watch.get("type") or "").lower() == "login":
        note = ("Filimo wants a signed-in session for playback. The stream URL is valid; "
                "add a logged-in cookies.txt in Settings → Video & capture to download it.")

    card = _base_card("webmedia", page_url, title, "Filimo",
                      thumbnail=thumb, referer=page_url, player="Filimo API",
                      note=note)
    try:
        card["duration"] = int(attrs.get("duration") or 0)
    except (TypeError, ValueError):
        card["duration"] = 0
    if attrs.get("movie_title_en") and attrs.get("movie_title"):
        card["title_en"] = str(attrs["movie_title_en"])

    if manifest:
        # the analyzer parses the manifest into a variant ladder (heights/bitrates)
        card["kind"] = "hls"
        card["url"] = manifest[0]
        card["stream"] = manifest[0]
        card["formats"] = []
        card["formats_total"] = 0
        if mp4s:
            card["also_found"] = [{"url": u, "filename": fk.guess_filename(u, "video.mp4"),
                                   "file_type": "video", "size_bytes": None}
                                  for u, _ in mp4s[:8]]
        return card

    formats = [_format(u, height=embed.quality_of(u)[0]) for u, _ in mp4s]
    formats = _dedupe(formats)
    if not formats:
        return None
    card["formats"] = formats
    card["formats_total"] = len(formats)
    return card


# ---------------------------------------------------------------------------
# Fetchers + registry
# ---------------------------------------------------------------------------
async def _fetch_json(url: str, headers: dict | None = None) -> dict | list | None:
    text, _final, _hdrs = await net.fetch_text(
        url, headers={"Accept": "application/json, text/plain, */*", **(headers or {})},
        timeout=16.0)
    if not text:
        return None
    text = text.strip()
    if text[:1] not in "[{":
        # some front-ends wrap JSON in a callback / HTML shell — find the object
        start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
        if start < 0:
            return None
        text = text[start:]
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


async def _aparat(adapter: Adapter, url: str, match: re.Match) -> dict | None:
    vid = match.group("id")
    for template in APARAT_ENDPOINTS:
        payload = await _fetch_json(template.format(id=vid))
        card = parse_aparat(payload, url)
        if card:
            card["adapter"] = adapter.key
            return card
    return None


async def _filimo(adapter: Adapter, url: str, match: re.Match) -> dict | None:
    payload = await _fetch_json(FILIMO_ENDPOINT.format(id=match.group("id")),
                                FILIMO_HEADERS)
    card = parse_filimo(payload, url)
    if card:
        card["adapter"] = adapter.key
    return card


_HANDLERS = {"aparat": _aparat, "filimo": _filimo}


def for_url(url: str) -> tuple[Adapter, re.Match] | None:
    """The adapter (and its regex match) responsible for this URL, else None."""
    for adapter in ADAPTERS:
        m = adapter.match.search(url or "")
        if m:
            return adapter, m
    return None


def adapter_for_recipe(key: str) -> Adapter | None:
    return _BY_KEY.get(key or "")


async def resolve(url: str, *, priority_only: bool = False) -> dict | None:
    """Try the API bridge for this URL. Never raises — analysis must not die here."""
    hit = for_url(url)
    if not hit:
        return None
    adapter, match = hit
    if priority_only and not adapter.priority:
        return None
    handler = _HANDLERS.get(adapter.key)
    if not handler:
        return None
    try:
        return await handler(adapter, url, match)
    except Exception:  # noqa: BLE001 — a broken site API is not a broken app
        return None


def catalog() -> list[dict]:
    return [{"key": a.key, "site": a.site, "priority": a.priority, "note": a.note}
            for a in ADAPTERS]
