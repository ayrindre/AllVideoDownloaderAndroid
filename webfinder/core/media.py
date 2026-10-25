"""WebFinder — Smart Direct Link module.

`analyze(url)` decides what a pasted URL actually is and returns the right
workbench for it:

  media   → YouTube / Vimeo / TikTok & the ~1800 yt-dlp extractors:
            metadata + selectable resolutions, downloaded through yt-dlp.
  hls     → .m3u8 / .mpd manifests: captured & converted with FFmpeg.
  direct  → a real file at the end of the URL (mp4, zip, torrent…):
            streamed with Range-resume support.
  magnet  → magnet link: copied to clipboard, handed to a torrent client.
  page    → ordinary web page: scanned for direct media links inside it.

Every path degrades gracefully; when the network is unavailable the whole
module answers with synthetic "demo" payloads so the UI keeps working.
"""
from __future__ import annotations

import asyncio
import re
from urllib.parse import urlparse, urljoin, unquote

import httpx

from ..config import settings
from . import dorks as dk
from .ffmpeg_tools import find_ffmpeg, probe

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36 WebFinder/1.0"
MEDIA_HREF_RE = re.compile(
    r"""href=["']([^"']+?\.(?:mp4|mkv|webm|m4v|avi|mov|mp3|flac|m4a|zip|rar|7z|gz|tar|exe|msi|iso|pdf|epub|torrent|m3u8|mpd))["']""",
    re.I)


async def analyze(url: str) -> dict:
    url = url.strip()
    if not re.match(r"^[a-z]+://", url, re.I) and not url.startswith("magnet:"):
        url = "https://" + url

    if settings.get("demo_mode"):
        return _demo_payload(url)

    if url.lower().startswith("magnet:"):
        return {"kind": "magnet", "url": url,
                "title": _magnet_title(url), "file_type": "magnet"}

    ext = dk.url_extension(url)
    if ext in dk.STREAM_EXTS:
        info = await probe(url)
        return {"kind": "hls", "url": url, "file_type": "video",
                "title": dk.guess_filename(url, "stream"),
                "ffmpeg": find_ffmpeg()["available"],
                "duration": info.get("duration", 0),
                "streams": info.get("streams", []),
                "bit_rate": info.get("bit_rate", 0)}

    # 1) Try the yt-dlp extractor registry — this covers YouTube & friends.
    media = await _try_ytdlp(url)
    if media:
        return media

    # 2) Probe the URL itself (HEAD → fallback GET) and look at what comes back.
    async with httpx.AsyncClient(follow_redirects=True, timeout=15.0,
                                 headers={"User-Agent": UA}) as client:
        try:
            resp = await client.head(url)
            if resp.status_code >= 400 or not (resp.headers.get("content-type") or resp.headers.get("content-length")):
                resp = await client.get(url, headers={"Range": "bytes=0-1"})
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Host unreachable: {exc}") from exc

        ctype = (resp.headers.get("content-type") or "").lower()
        size = None
        cl = resp.headers.get("content-length")
        crange = resp.headers.get("content-range")
        if crange and "/" in crange:
            size = int(crange.rsplit("/", 1)[-1])
        elif cl and cl.isdigit() and int(cl) > 1:
            size = int(cl)
        final = str(resp.url)

    if "mpegurl" in ctype or "m3u8" in final or "dash" in ctype or ".mpd" in final:
        info = await probe(final)
        return {"kind": "hls", "url": final, "file_type": "video",
                "title": dk.guess_filename(final, "stream"),
                "ffmpeg": find_ffmpeg()["available"],
                "duration": info.get("duration", 0),
                "streams": info.get("streams", []), "bit_rate": info.get("bit_rate", 0)}

    looks_like_file = bool(ext) or (size and (size > 1_000_000 or "octet-stream" in ctype))
    if looks_like_file:
        return {"kind": "direct", "url": final,
                "title": unquote(dk.guess_filename(final, "file")),
                "filename": unquote(dk.guess_filename(final, "file")),
                "file_type": dk.classify(final), "content_type": ctype,
                "size": size, "accepts_ranges": "206" in (resp.headers.get("accept-ranges", "") + resp.status_code.__str__())}

    # 3) Ordinary page — scan it for direct media links to offer as candidates.
    candidates = await scan_page(final) if settings.get("resolve_pages") else []
    return {"kind": "page", "url": final, "title": "", "size": size,
            "content_type": ctype, "candidates": candidates}


def _magnet_title(url: str) -> str:
    m = re.search(r"dn=([^&]+)", url)
    return unquote(m.group(1)).replace("+", " ") if m else "Magnet link"


# ---------------------------------------------------------------------------
# yt-dlp bridge
# ---------------------------------------------------------------------------
_QUALITY_ORDER = (4320, 2880, 2160, 1440, 1080, 720, 480, 360, 240, 144)


def _ytdlp_extract(url: str) -> dict | None:
    try:
        import yt_dlp
    except ImportError:
        return None
    opts = {"quiet": True, "no_warnings": True, "skip_download": True,
            "extract_flat": False, "playlist_items": "1", "noplaylist": True,
            "socket_timeout": 12, "nocheckcertificate": True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception:  # noqa: BLE001 — "no extractor" is the normal case here
        return None
    if not info or info.get("_type") == "playlist":
        entries = (info or {}).get("entries") or []
        info = entries[0] if entries else None
    if not info:
        return None

    formats: dict[int, dict] = {}
    for f in info.get("formats", []):
        vcodec, acodec = f.get("vcodec") or "none", f.get("acodec") or "none"
        h = f.get("height")
        if vcodec == "none" and acodec == "none":
            continue
        if vcodec == "none":                                   # audio-only
            key = 0
            entry = formats.setdefault(key, {"height": 0, "label": "Audio only",
                                             "exts": set(), "has_video": False,
                                             "abr": f.get("abr") or 0, "fps": 0})
            entry["exts"].add(f.get("ext") or "m4a")
            continue
        if not h:
            continue
        # round to the nearest canonical step (yt-dlp heights vary: 1088, 1080…)
        nearest = min(_QUALITY_ORDER, key=lambda q: abs(q - h))
        badge = " · 4K" if nearest >= 2160 else (" · FHD" if nearest == 1080 else "")
        entry = formats.setdefault(nearest, {"height": nearest,
                                             "label": f"{nearest}p{badge}",
                                             "exts": set(), "has_video": True,
                                             "fps": f.get("fps") or 0})
        entry["exts"].add(f.get("ext") or "mp4")
        if acodec != "none":
            entry["muxed"] = True

    chosen = []
    for q in _QUALITY_ORDER:
        if q in formats:
            e = formats[q]
            chosen.append({"height": q,
                           "label": e.get("label") or f"{q}p",
                           "codecs": sorted(e["exts"])[:3],
                           "fps": e.get("fps") or 0,
                           "format": (f"bestvideo[height<={q}]+bestaudio/best[height<={q}]"
                                      if q else "bestaudio/best"),
                           "size": None})
    if 0 in formats:
        chosen.append({"height": 0, "label": "Audio only (m4a)",
                       "codecs": sorted(formats[0]["exts"])[:3], "fps": 0,
                       "format": "bestaudio/best", "size": None})

    return {
        "kind": "media", "url": url, "file_type": "video",
        "extractor": info.get("extractor_key", "yt-dlp"),
        "title": info.get("title") or "Untitled",
        "uploader": info.get("uploader") or info.get("channel") or "",
        "duration": info.get("duration") or 0,
        "view_count": info.get("view_count") or 0,
        "thumbnail": info.get("thumbnail") or "",
        "webpage": info.get("webpage_url") or url,
        "formats": chosen,
        "formats_total": len(info.get("formats", [])),
        "needs_ffmpeg_merge": not find_ffmpeg()["available"],
        "ffmpeg": find_ffmpeg()["available"],
    }


async def _try_ytdlp(url: str) -> dict | None:
    return await asyncio.to_thread(_ytdlp_extract, url)


# ---------------------------------------------------------------------------
# Page scanning — crawl a result page for hidden direct file links
# ---------------------------------------------------------------------------
async def scan_page(url: str, limit: int = 12) -> list[dict]:
    async with httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(12.0, connect=8.0),
                                 headers={"User-Agent": UA}) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except httpx.HTTPError:
            return []
    seen: set[str] = set()
    out: list[dict] = []
    for m in MEDIA_HREF_RE.finditer(resp.text):
        href = unescape_html(m.group(1))
        if href.startswith(("data:", "javascript:")):
            continue
        full = urljoin(str(resp.url), href)
        if full in seen:
            continue
        seen.add(full)
        out.append({"url": full, "filename": unquote(dk.guess_filename(full, "file")),
                    "file_type": dk.classify(full)})
        if len(out) >= limit:
            break
    return out


def unescape_html(s: str) -> str:
    from html import unescape
    return unescape(s)


# ---------------------------------------------------------------------------
# Download planning — decide which worker handles a URL
# ---------------------------------------------------------------------------
async def plan_download(url: str, title: str = "", fmt: dict | None = None) -> dict:
    """Return the enqueue kwargs for any URL (used by result cards & direct link)."""
    if settings.get("demo_mode"):
        return {"url": url, "kind": "sim", "title": title or dk.guess_filename(url),
                "file_type": dk.classify(url), "meta": {}}
    ext = dk.url_extension(url)
    if ext in dk.STREAM_EXTS:
        return {"url": url, "kind": "hls", "title": title or dk.guess_filename(url),
                "file_type": "video", "meta": {}}
    if url.lower().startswith("magnet:"):
        return {"url": url, "kind": "magnet", "title": _magnet_title(url),
                "file_type": "magnet", "meta": {}}
    media = await _try_ytdlp(url) if not ext else None
    if media:
        quality = str(settings.get("default_quality", "1080"))
        chosen = None
        for f in media["formats"]:
            if quality == "best" or str(f["height"]) == quality:
                chosen = f
                break
        if chosen is None and media["formats"]:
            chosen = next((f for f in media["formats"] if f["height"]), media["formats"][0])
        fmt_spec = (fmt or {}).get("format") or (chosen or {}).get("format") or "bv*+ba/b"
        return {"url": url, "kind": "ytdlp", "title": media["title"],
                "file_type": "video",
                "filename": re.sub(r'[<>:"/\\|?*]', "_", media["title"])[:150] + f".{settings.get('default_container','mp4')}",
                "meta": {"format": fmt_spec, "quality": (chosen or {}).get("label", "best"),
                         "extractor": media["extractor"]}}
    # If the user explicitly chose a format card, trust yt-dlp.
    if fmt and fmt.get("format"):
        return {"url": url, "kind": "ytdlp", "title": title or dk.guess_filename(url),
                "file_type": "video", "meta": {"format": fmt["format"],
                                               "quality": fmt.get("label", "")}}
    return {"url": url, "kind": "http", "title": title or dk.guess_filename(url),
            "file_type": dk.classify(url), "meta": {}}


# ---------------------------------------------------------------------------
# Demo payloads (offline UI preview)
# ---------------------------------------------------------------------------
def _demo_payload(url: str) -> dict:
    host = urlparse(url).netloc or url
    ext = dk.url_extension(url)
    if ext in dk.STREAM_EXTS:
        return {"kind": "hls", "url": url, "file_type": "video",
                "title": f"Demo HLS stream — {host}", "demo": True,
                "ffmpeg": find_ffmpeg()["available"], "duration": 4520,
                "streams": [{"type": "video", "codec": "h264", "width": 1920, "height": 1080},
                            {"type": "audio", "codec": "aac"}], "bit_rate": 5_200_000}
    formats = [
        {"height": 2160, "label": "2160p 4K", "codecs": ["mp4", "webm"], "fps": 60, "format": "bestvideo[height<=2160]+bestaudio", "size": 1_930_000_000},
        {"height": 1080, "label": "1080p", "codecs": ["mp4", "webm"], "fps": 30, "format": "bestvideo[height<=1080]+bestaudio", "size": 486_000_000},
        {"height": 720, "label": "720p", "codecs": ["mp4", "webm"], "fps": 30, "format": "bestvideo[height<=720]+bestaudio", "size": 194_000_000},
        {"height": 0, "label": "Audio only (m4a)", "codecs": ["m4a"], "fps": 0, "format": "bestaudio", "size": 12_400_000},
    ]
    is_media_host = any(h in host for h in ("youtu", "vimeo", "dailymotion", "twitch", "tiktok"))
    if is_media_host or not ext:
        return {"kind": "media", "url": url, "demo": True, "file_type": "video",
                "extractor": "youtube-dlp-demo", "title": f"Demo video — {host}",
                "uploader": "WebFinder Demo Channel", "duration": 814, "view_count": 2_417_902,
                "thumbnail": "", "webpage": url, "formats": formats,
                "formats_total": 41, "needs_ffmpeg_merge": not find_ffmpeg()["available"],
                "ffmpeg": find_ffmpeg()["available"]}
    return {"kind": "direct", "url": url, "demo": True,
            "title": dk.guess_filename(url), "filename": dk.guess_filename(url),
            "file_type": dk.classify(url), "content_type": "application/octet-stream",
            "size": 734_000_000, "accepts_ranges": True}


def build_search_results(query: str, types: list[str], engines: list[str], limit: int) -> dict:
    """Synthetic-but-plausible result set for demo mode."""
    import hashlib
    domains = ["archive.org", "data.hobbyist.net", "cdn.filepile.io", "files.openstack.dev",
               "mirror.linux-iso.org", "media.poolcloud.tv", "repo.fossware.dev", "torrentbay.alt"]
    ext_map = {"video": ["mp4", "mkv", "webm"], "image": ["jpg", "png", "webp"],
               "torrent": ["torrent"], "magnet": [""], "software": ["exe", "msi"],
               "archive": ["zip", "7z", "rar"], "audio": ["mp3", "flac"], "ebook": ["pdf", "epub"],
               "link": ["pdf", "html"]}
    results = []
    ts = types or ["link"]
    for i in range(min(limit, 18)):
        t = ts[i % len(ts)]
        exts = ext_map.get(t, ext_map["link"])
        ext = exts[i % len(exts)]
        dom = domains[int(hashlib.md5(f"{query}{i}".encode()).hexdigest()[:6], 16) % len(domains)]
        if t == "magnet":
            h = hashlib.sha1(f"{query}{i}".encode()).hexdigest()
            url = f"magnet:?xt=urn:btih:{h}&dn={query.replace(' ', '+')}.{i}&tr=udp://tracker.opentrackr.org:1337/announce"
            title = f"{query.title()} — magnet #{i + 1}"
        else:
            slug = re.sub(r"[^\w]+", "-", query.lower()).strip("-") or "file"
            url = f"https://{dom}/files/{slug}-{i:02d}.{ext}"
            title = f"{query.title()} ({['Complete', 'Remastered', 'Pack Vol. ' + str(i), 'Archive', 'Full'][i % 5]})"
        size = int(hashlib.md5(url.encode()).hexdigest()[:5], 16) * 4096 + 12_000_000
        results.append({"title": title, "url": url,
                        "snippet": f"Demo result for “{query}”. Verified mirror with fast seeds, "
                                   f"no captcha and direct download. Size {size / 1024 / 1024:.1f} MB.",
                        "domain": dom, "engine": engines[i % len(engines)] if engines else "demo",
                        "size_bytes": size, "file_type": t if t != "link" else "link",
                        "is_direct": t != "link"})
    return {
        "query": dk.build_query(query, types),
        "elapsed_ms": 340,
        "demo": True,
        "engines": [{"engine": e, "ok": True, "error": "", "count": len(results) // max(1, len(engines) or 1)}
                    for e in (engines or ["demo"])],
        "results": results,
    }
