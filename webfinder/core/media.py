"""All Video Downloader — universal link engine.

`analyze(url)` is the heart of the app: ANY link that contains a video
becomes a downloadable job with a quality ladder you can pick from:

  media   → YouTube & the ~1900 yt-dlp extractors: metadata + selectable
            resolutions, downloaded through yt-dlp (multi-client, cookies).
  hls     → .m3u8 / .mpd manifests: variant ladder parsed locally so you
            can CHOOSE quality; captured via yt-dlp or FFmpeg -c copy.
  direct  → a real file at the end of the URL — verified by content-type
            AND container magic bytes (ftyp/EBML/FLV/AVI/…), streamed
            with Range-resume support.
  page    → ordinary web page: deep-scanned (og:video, <source>, raw
            anchors, directory listings); when the scan finds a video,
            the app re-analyzes THAT url instead of dead-ending.
  magnet  → recognized and explained; copy it to your torrent client.

Every path degrades gracefully with an honest error and a fix hint.
"""
from __future__ import annotations

import asyncio
import re
from functools import lru_cache
from urllib.parse import urlparse, urljoin, unquote

import httpx

from ..config import settings
from . import filekind as fk
from .ffmpeg_tools import find_ffmpeg, probe


def ytcli_use_cli() -> bool:
    from . import ytcli
    return ytcli.use_cli()

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36 AVD/2.0"


def base_yt_opts(extra: dict | None = None) -> dict:
    """Common yt-dlp options incl. optional browser cookie import.

    Reading cookies from the user's browser (Settings → YouTube cookies source)
    is the single most effective fix for "Sign in to confirm you're not a bot"
    and age/region-gated videos.
    """
    # NO custom http_headers here on purpose: yt-dlp picks a per-client
    # UA/header profile (web vs android vs tv) that its signature descrambling
    # depends on. Forcing a desktop-Chrome UA (what the app used to do) poisoned
    # every client pass — "the CLI works but the app doesn't" root cause.
    opts = {"quiet": True, "no_warnings": True, "noprogress": True,
            "socket_timeout": 30, "retries": 3, "nocheckcertificate": True}
    browser = (settings.get("ytdlp_browser_cookies") or "").strip()
    if browser:
        opts["cookiesfrombrowser"] = (browser,)
    px = (settings.get("proxy") or "").strip()
    if px:
        opts["proxy"] = px
    if extra:
        opts.update(extra)
    return opts


@lru_cache(maxsize=None)
def _ie_for(url: str) -> str:  # cached: the registry walk is ~1800 checks the first time
    try:
        from yt_dlp.extractor import gen_extractors
        for ie in gen_extractors():
            try:
                if ie.suitable(url) and ie.IE_NAME not in ("generic", "Generic"):
                    return ie.IE_NAME
            except Exception:  # noqa: BLE001 — some matchers choke on junk urls
                continue
    except Exception:  # noqa: BLE001 — no yt-dlp installed
        pass
    return ""


def find_extractor(url: str) -> str:
    """Name of the yt-dlp extractor registered for this URL ('' = none)."""
    return _ie_for(url)
MEDIA_HREF_RE = re.compile(
    r"""href=["']([^"']+?\.(?:mp4|mkv|webm|m4v|avi|mov|mp3|flac|m4a|zip|rar|7z|gz|tar|exe|msi|iso|pdf|epub|torrent|m3u8|mpd))["']""",
    re.I)


# container signatures — the truth behind lying Content-Types
_MAGIC_TESTS = (
    (lambda b: b[4:8] == b"ftyp", "mp4"),
    (lambda b: b[:4] == b"\x1a\x45\xdf\xa3", "mkv"),
    (lambda b: b[:3] == b"FLV", "flv"),
    (lambda b: b[:4] == b"RIFF" and b[8:12] == b"AVI ", "avi"),
    (lambda b: b[:4] == b"\x00\x00\x01\xba" or b[:4] == b"\x00\x00\x01\xb3", "mpeg"),
    (lambda b: b[:4] == b"\x00\x00\x00", "mp4"),          # bare ISO-BMFF heuristics
)


def sniff_container(head: bytes) -> str:
    for test, name in _MAGIC_TESTS:
        try:
            if test(head):
                return name
        except IndexError:
            continue
    return ""


_M3U8_STREAM_RE = re.compile(
    r"#EXT-X-STREAM-INF:([^\n]*)\n\s*([^#\n][^\n]*)", re.I)


def parse_m3u8_master(text: str, base: str) -> list[dict]:
    """Variant ladder from a master playlist: RESOLUTION/BANDWIDTH per entry."""
    out: list[dict] = []
    for i, (attrs, uri) in enumerate(_M3U8_STREAM_RE.findall(text)):
        hm = re.search(r"RESOLUTION=(\d+)x(\d+)", attrs)
        bw = re.search(r"BANDWIDTH=(\d+)", attrs)
        height = int(hm.group(2)) if hm else 0
        out.append({"idx": i, "url": urljoin(base, uri.strip()),
                    "height": height,
                    "width": int(hm.group(1)) if hm else 0,
                    "bandwidth": int(bw.group(1)) if bw else 0})
    out.sort(key=lambda v: -(v["height"] or 0) * 10**9 - v["bandwidth"])
    return out


def parse_mpd_master(text: str, base: str) -> list[dict]:
    """Video representations from a DASH MPD (AdaptationSet → Representations)."""
    import xml.etree.ElementTree as ET
    out: list[dict] = []
    try:
        root = ET.fromstring(re.sub("""\\sxmlns(\\:[^=]+)?=["'][^"']*["']""", "", text, count=1))
    except ET.ParseError:
        return []

    def walk(node, inherit_base: str):
        for aset in node.findall("AdaptationSet"):
            if (aset.get("contentType") or aset.get("mimeType") or "").lower().startswith("audio"):
                continue
            for rep in aset.findall("Representation"):
                w = int(rep.get("width") or 0) or int(aset.get("width") or 0)
                h = int(rep.get("height") or 0) or int(aset.get("height") or 0)
                bw = int(rep.get("bandwidth") or 0)
                rid = rep.get("id") or ""
                ouri = ""
                bu = rep.find("BaseURL")
                if bu is not None and (bu.text or "").strip():
                    ouri = urljoin(inherit_base, bu.text.strip())
                if not ouri:
                    continue
                out.append({"idx": len(out), "url": ouri, "height": h, "width": w,
                            "bandwidth": bw, "rep_id": rid})
        for period in node.findall("Period"):
            walk(period, inherit_base)

    walk(root, base)
    out.sort(key=lambda v: -(v["height"] or 0) * 10**9 - v["bandwidth"])
    return out


def stream_formats(ladder: list[dict]) -> list[dict]:
    """UI-ready quality picker for a raw manifest (auto + one entry per rung)."""
    forms = [{"height": 0, "label": "Best (auto)", "codecs": [], "fps": 0,
              "format": "bv*+ba/b", "url": "", "size": None}]
    for v in ladder:
        h = v["height"]
        sel = f"{v['idx']}/{v['idx'] + 1}"
        if v.get("rep_id"):
            sel = f"{v['rep_id']}/{sel}"
        sel += "/best" + (f"[height<={h}]" if h else "")
        label = (f"{h}p" if h else "") + (f" · {v['bandwidth'] // 1000} kbps" if v["bandwidth"] else "")
        forms.append({"height": h, "label": label or "variant", "codecs": [], "fps": 0,
                      "format": sel, "url": v["url"], "size": None})
    return forms


async def fetch_manifest(url: str) -> str:
    px = (settings.get("proxy") or "").strip()
    async with httpx.AsyncClient(follow_redirects=True, timeout=20.0,
                                 headers={"User-Agent": UA},
                                 **({"proxy": px} if px else {})) as client:
        try:
            r = await client.get(url, headers={"Range": "bytes=0-524287"})
            r.raise_for_status()
            return r.text
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Manifest unreachable: {str(exc)[:160]}") from exc


async def _stream_result(url: str) -> dict:
    """HLS/DASH → ffprobe info when available + a locally parsed variant ladder."""
    info: dict = {}
    ladder: list[dict] = []
    try:
        text = await fetch_manifest(url)
        if url.lower().endswith(".mpd") or "<mpd" in text[:600].lower():
            ladder = parse_mpd_master(text, url)
        elif "#EXTM3U" in text[:40] or "#EXT-X-STREAM-INF" in text[:6000]:
            ladder = parse_m3u8_master(text, url)
        elif text.lstrip().startswith("#EXTINF"):
            ladder = []                       # media playlist — a single stream
    except RuntimeError:
        info = {}
    if not info:
        try:
            info = await probe(url)
        except Exception:  # noqa: BLE001 — ffprobe optional
            info = {}
    return {"kind": "hls", "url": url, "file_type": "video",
            "title": fk.guess_filename(url, "stream"),
            "ffmpeg": find_ffmpeg()["available"],
            "duration": info.get("duration", 0), "streams": info.get("streams", []),
            "bit_rate": info.get("bit_rate", 0),
            "formats": stream_formats(ladder),
            "single_stream": not ladder}


async def analyze(url: str, _depth: int = 0) -> dict:
    url = url.strip()
    if not re.match(r"^[a-z]+://", url, re.I) and not url.startswith("magnet:"):
        url = "https://" + url

    if url.lower().startswith("magnet:"):
        return {"kind": "magnet", "url": url,
                "title": _magnet_title(url), "file_type": "magnet"}

    ext = fk.url_extension(url)
    if ext in fk.STREAM_EXTS:
        return await _stream_result(url)

    # 1) Try the yt-dlp extractor registry — this covers YouTube & friends.
    media, yt_err = await _try_ytdlp(url)
    if media and media.get("formats"):
        return media
    # A media dict with an EMPTY format list is the Generic extractor staring at
    # an HTML shell — never a verdict. Keep walking to the probe + deep-scan path
    # (which is what actually finds the video such pages embed).
    # 1b) A registered extractor exists but extraction failed (bot check, age
    #     gate, geo block, outdated yt-dlp). Say exactly that — never bury it
    #     in a misleading "regular web page" verdict.
    ie = await asyncio.to_thread(find_extractor, url)
    if ie:
        hints = []
        e_low = (yt_err or "").lower()
        if "cookie" in e_low or "could not copy" in e_low:
            hints.append("Your browser is <b>holding its cookie database open</b> (Chrome 127+ also App-Bound-encrypts it) — "
                         "fully close Chrome (check the tray), or switch the source to <code>edge</code>/<code>firefox</code> in "
                         "Settings → Video & capture. The app already retried this extraction without cookies.")
        if not settings.get("ytdlp_browser_cookies"):
            hints.append("Set Settings → Video & capture → <b>Browser cookies source</b> to <code>chrome</code>/<code>edge</code> so yt-dlp can use your logged-in session.")
        hints.append("The app auto-refreshes yt-dlp daily — if it just updated, restart All Video Downloader once.")
        if not ytcli_use_cli():
            hints.append("Tip: if <code>yt-dlp</code> in your terminal works better, install it on PATH and restart — "
                         "All Video Downloader prefers your newer system binary over its bundled copy automatically.")
        try:                                # the extractor said no — the page may
            cand = await scan_page(url)     # still carry a plain file/manifest
        except Exception:  # noqa: BLE001
            cand = []
        vids = [c for c in cand if fk.classify(c["url"]) == "video"
                or fk.url_extension(c["url"]) in fk.VIDEO_EXTS | fk.STREAM_EXTS]
        return {"kind": "media_error", "url": url, "extractor": ie, "file_type": "video",
                "title": fk.guess_filename(url, ie),
                "error": (yt_err or "yt-dlp returned no info")[:400],
                "hints": hints, "candidates": vids or cand}

    # 2) Probe the URL itself (HEAD → ranged GET) — content-type AND magic bytes.
    px = (settings.get("proxy") or "").strip()
    async with httpx.AsyncClient(follow_redirects=True, timeout=15.0,
                                 headers={"User-Agent": UA},
                                 **({"proxy": px} if px else {})) as client:
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

        # 2a) manifest served under a generic URL?
        if "mpegurl" in ctype or ".m3u8" in final or "dash" in ctype or ".mpd" in final:
            return await _stream_result(final)

        # 2b) lying/absent content-type with no extension → sniff the container.
        head_bytes = b""
        if ext not in fk.EXT_KIND and ("octet-stream" in ctype or not ctype or "html" in ctype):
            try:
                hr = await client.get(final, headers={"Range": "bytes=0-63"})
                head_bytes = hr.content[:64]
            except httpx.HTTPError:
                head_bytes = b""
        sniffed = sniff_container(head_bytes) if len(head_bytes) >= 12 else ""
        if sniffed and "html" not in ctype:
            name = fk.guess_filename(final, f"video.{sniffed}")
            if "." not in name:
                name += f".{sniffed}"
            return {"kind": "direct", "url": final, "title": unquote(name),
                    "filename": unquote(name), "file_type": "video",
                    "content_type": f"video/{sniffed} (magic-sniffed)",
                    "size": size,
                    "accepts_ranges": "206" in (resp.headers.get("accept-ranges", "") + resp.status_code.__str__())}

    # HTML is never "a file at the end of the URL", whatever the extension says —
    # .php/page.html pages must fall through to the deep-scan, not fake a download.
    looks_like_file = "html" not in ctype and (
        bool(ext) or (size and (size > 1_000_000 or "octet-stream" in ctype)))
    if looks_like_file:
        return {"kind": "direct", "url": final,
                "title": unquote(fk.guess_filename(final, "file")),
                "filename": unquote(fk.guess_filename(final, "file")),
                "file_type": fk.classify(final), "content_type": ctype,
                "size": size,
                "accepts_ranges": "206" in (resp.headers.get("accept-ranges", "") + resp.status_code.__str__())}

    # 3) Ordinary page — deep-scan for the video it actually hosts. A found
    #    video/manifest URL is RE-ANALYZED (one level deep) instead of
    #    dead-ending in a candidate list.
    candidates = await scan_page(final)
    vids = [c for c in candidates
            if fk.classify(c["url"]) == "video"
            or fk.url_extension(c["url"]) in fk.VIDEO_EXTS | fk.STREAM_EXTS]
    emb = [c for c in candidates if c.get("file_type") == "embed"]
    targets = vids + emb          # plain files first, scripted players second
    if targets and _depth < 2:
        targets.sort(key=lambda c: (-int(c.get("size_bytes") or 0),
                                    0 if fk.url_extension(c["url"]) in fk.STREAM_EXTS else 1))
        try:
            yt_err_referrer["url"] = final
            try:
                sub = await analyze(targets[0]["url"], _depth + 1)
            finally:
                yt_err_referrer.clear()
            if sub.get("kind") not in ("page", "magnet"):
                sub["found_on_page"] = final
                # most tube/CDN file links are hotlink-guarded: the download
                # needs the hosting page as Referer to answer like the browser
                sub["referer"] = final
                rest = targets[1:12]
                if rest:
                    sub["also_found"] = rest
                return sub
        except Exception:  # noqa: BLE001 — fall through to the plain page card
            pass
    return {"kind": "page", "url": final, "title": "", "size": size,
            "content_type": ctype, "candidates": candidates}


def _magnet_title(url: str) -> str:
    m = re.search(r"dn=([^&]+)", url)
    return unquote(m.group(1)).replace("+", " ") if m else "Magnet link"


# ---------------------------------------------------------------------------
# yt-dlp bridge
# ---------------------------------------------------------------------------
_QUALITY_ORDER = (4320, 2880, 2160, 1440, 1080, 720, 480, 360, 240, 144)


yt_err_referrer: dict = {}      # {'url': hosting page} while analyze recurses

_CLIENT_ATTEMPTS = (
    {},                                                  # bare CLI behaviour first
    {"player_client": ["android", "tv"]},                # rescue: web map capped?
    {"player_client": ["ios", "mweb"]},                  # rescue: still capped?
)


def _merge_infos(infos: list[tuple[dict, dict]]) -> tuple[dict, dict]:
    """Richest response wins; the others only add missing format ids."""
    infos.sort(key=lambda ci: -len((ci[1] or {}).get("formats") or []))
    win_client, info = infos[0]
    seen: set = set()
    merged: list[dict] = []
    for _, cand in infos:
        for f in (cand or {}).get("formats") or []:
            fid = f.get("format_id")
            if fid not in seen:
                seen.add(fid)
                merged.append(f)
    info = dict(info)
    info["formats"] = merged
    return info, (win_client or {})


def _module_attempt(url: str, mode: dict, *, no_cookies: bool = False
                    ) -> tuple[dict | None, str, dict]:
    try:
        import yt_dlp
    except ImportError:
        return None, "yt-dlp is not installed in the backend venv.", {}
    errors: list[str] = []
    infos: list[tuple[dict, dict]] = []
    for client_extra in _CLIENT_ATTEMPTS:
        extra = dict(mode)
        if client_extra:
            extra["extractor_args"] = {"youtube": client_extra}
        if no_cookies:
            extra["cookiesfrombrowser"] = None      # falsy → yt-dlp skips the read
        try:
            with yt_dlp.YoutubeDL(base_yt_opts(extra)) as ydl:
                infos.append((client_extra, ydl.extract_info(url, download=False)))
        except Exception as exc:  # noqa: BLE001 — "no extractor" is the normal case
            errors.append(str(exc).replace("\n", " ")[:220])
            continue
        fmap = (infos[-1][1] or {}).get("formats") or []
        if fmap and max((f.get("height") or 0) for f in fmap) > 480:
            break                                       # rich map — stop hammering
        if (infos[-1][1] or {}).get("_type") == "playlist":
            break                                       # listing worked; no rescue needed
    if not infos:
        return None, " · ".join(dict.fromkeys(errors)) or "yt-dlp returned nothing", {}
    info, win = _merge_infos(infos)
    return info, "", win


def _cli_attempt(url: str, mode: dict) -> tuple[dict | None, str, dict]:
    """System yt-dlp binary — used when the user's CLI is FRESHER than the app's
    pip copy (the usual cause of 'terminal downloads 4K, the app offers 480p')."""
    from . import ytcli
    flat = mode.get("extract_flat") == "in_playlist"
    items = mode.get("playlist_items")
    np = bool(mode.get("noplaylist", True))
    infos: list[tuple[dict, dict]] = []
    errors: list[str] = []
    for client_extra in _CLIENT_ATTEMPTS:
        info, err = ytcli.extract(url, flat=flat, playlist_items=items, noplaylist=np,
                                  client=client_extra or None,
                                  referer=mode.get("_referer", ""))
        if info is None:
            errors.append(err)
            continue
        infos.append((client_extra, info))
        fmap = info.get("formats") or []
        if fmap and max((f.get("height") or 0) for f in fmap) > 480:
            break
        if info.get("_type") == "playlist":
            break
    if not infos:
        return None, " · ".join(dict.fromkeys(errors)) or "yt-dlp CLI returned nothing", {}
    info, win = _merge_infos(infos)
    return info, "", win


def _attempt_extract(url: str, mode: dict) -> tuple[dict | None, str, dict]:
    """Client ladder for one URL; engine = pip module OR the user's system CLI.

    Chrome's locked/encrypted cookie DB (yt-dlp issue 7271) once bricked EVERY
    extraction with 'Could not copy Chrome cookie database' — so a cookie-read
    failure now transparently retries anonymous instead of dying on every site.
    """
    from . import ytcli
    if ytcli.use_cli():
        return _cli_attempt(url, mode)
    info, err, win = _module_attempt(url, mode)
    if (info is None and err and ytcli._ERR_MARKERS.search(err)
            and (settings.get("ytdlp_browser_cookies") or "").strip()):
        info2, err2, win2 = _module_attempt(url, mode, no_cookies=True)
        if info2 is not None:
            return info2, "", win2
    return info, err, win


def _ytdlp_extract(url: str) -> tuple[dict | None, str]:
    """Extract media info. Returns (info, error) — error is surfaced to the UI."""
    mode = {"skip_download": True, "extract_flat": "in_playlist",
            "noplaylist": False, "playlist_items": "1-25", "socket_timeout": 15}
    info, err, win_client = _attempt_extract(url, mode)
    if info is None and yt_err_referrer.get("url"):
        mode["_referer"] = yt_err_referrer["url"]      # retry with page context
        info, err, win_client = _attempt_extract(url, mode)
    if not info:
        return None, err

    # ── playlist / gallery URLs (tube channels, video sets, mix lists) ──────
    playlist_meta = None
    if info.get("_type") == "playlist":
        entries = [e for e in (info.get("entries") or []) if isinstance(e, dict)]
        if not entries:
            return None, "Extractor returned a playlist with no playable entry."
        playlist_meta = {
            "total": int(info.get("playlist_count") or len(entries)),
            "entries": [{"title": str(e.get("title") or e.get("id") or "untitled")[:160],
                         "url": e.get("url") or e.get("webpage_url") or "",
                         "duration": e.get("duration") or 0}
                        for e in entries[1:25]]}
        first_url = entries[0].get("url") or entries[0].get("webpage_url")
        if not first_url:
            return None, "Playlist entries carry no playable URLs."
        full = dict(mode)
        full.update({"extract_flat": False, "noplaylist": True})
        full.pop("playlist_items", None)
        info2, err2, win2 = _attempt_extract(first_url, full)
        if not info2 or info2.get("_type") == "playlist":
            return None, err2 or "First playlist entry could not be extracted."
        info, win_client = info2, win2
    elif "entries" in info and info.get("_type") != "video":
        pass  # a flat single entry — formats are already attached

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
                                             "abr": f.get("abr") or 0, "fps": 0,
                                             "aud_ids": []})
            entry["exts"].add(f.get("ext") or "m4a")
            entry["aud_ids"].append((f.get("abr") or 0, f.get("format_id")))
            continue
        if not h:
            continue
        # round to the nearest canonical step (yt-dlp heights vary: 1088, 1080…)
        nearest = min(_QUALITY_ORDER, key=lambda q: abs(q - h))
        badge = " · 4K" if nearest >= 2160 else (" · FHD" if nearest == 1080 else "")
        entry = formats.setdefault(nearest, {"height": nearest,
                                             "label": f"{nearest}p{badge}",
                                             "exts": set(), "has_video": True,
                                             "fps": f.get("fps") or 0,
                                             "vid_ids": [], "mux_ids": [], "aud_ids": []})
        entry["exts"].add(f.get("ext") or "mp4")
        (entry["mux_ids"] if acodec != "none" else entry["vid_ids"]).append(
            (f.get("tbr") or 0, f.get("format_id")))
        if acodec != "none":
            entry["muxed"] = True

    chosen = []
    for q in _QUALITY_ORDER:
        if q in formats:
            e = formats[q]
            # Real format IDs first ("137+140/…"): exact stream choice survives
            # even when generic selectors resolve to a capped ladder.
            best_v = max((t for t, i in (e.get("vid_ids") or []) if i), default=None)
            best_m = max((t for t, i in (e.get("mux_ids") or []) if i), default=None)
            _aud_src = e.get("aud_ids") or (formats.get(0) or {}).get("aud_ids") or []
            best_a = max((t for t, i in _aud_src if i), default=None)
            def _id_for(tb):   # highest-bitrate entry's format id
                for lst in (e.get("vid_ids"), e.get("mux_ids"), _aud_src, e.get("aud_ids")):
                    for t_, i_ in (lst or []):
                        if t_ == tb and i_:
                            return i_
                return None
            best_v, best_m, best_a = _id_for(best_v), _id_for(best_m), _id_for(best_a)
            generic = (f"bestvideo[height<={q}]+bestaudio/best[height<={q}]"
                       if q else "bestaudio/best")
            if q and best_v:
                exact = f"{best_v}" + (f"+{best_a}" if best_a else "") + (f"/{best_m}" if best_m else "")
            elif q and best_m:
                exact = str(best_m)
            else:
                exact = generic
            chosen.append({"height": q,
                           "label": e.get("label") or f"{q}p",
                           "codecs": sorted(e["exts"])[:3],
                           "fps": e.get("fps") or 0,
                           "format": f"{exact}/{generic}",
                           "size": None})
    if 0 in formats:
        chosen.append({"height": 0, "label": "Audio only (m4a)",
                       "codecs": sorted(formats[0]["exts"])[:3], "fps": 0,
                       "format": "bestaudio/best", "size": None})

    media = {
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
    # Remember WHICH client answered so the download runs the same recipe —
    # ids found by the tv client must be downloaded by the tv client, not web.
    if win_client:
        media["extractor_args"] = {"youtube": win_client}
    if playlist_meta:
        media["playlist"] = playlist_meta
    return media, ""


async def _try_ytdlp(url: str) -> tuple[dict | None, str]:
    return await asyncio.to_thread(_ytdlp_extract, url)


# ---------------------------------------------------------------------------
# Page scanning — crawl a result page for hidden direct file links
# ---------------------------------------------------------------------------
_OG_RE = re.compile('<meta[^>]+property=["\']og:(?:video|audio|image)(?::secure_url)?["\'][^>]+content=["\']([^"\']+)["\']', re.I)
_VIDSRC_RE = re.compile('<(?:video|source)[^>]+src=["\']([^"\']+)["\']', re.I)

_IFRAME_RE = re.compile('<iframe[^>]+src=["\']([^"\']+)["\']', re.I)

async def scan_page(url: str, limit: int = 12, wanted=None) -> list[dict]:
    """Deep-scan one page for hidden direct media files.

    Understands: bare file anchors (href ending in a media extension),
    ``og:video/og:audio/og:image`` meta tags, ``<video>/<source>`` sources,
    and classic Apache/nginx *index of* listings (name + size + date columns).
    ``wanted`` optionally restricts results to a compiled extension regex.
    """
    import re as _re
    async with httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(12.0, connect=8.0),
                                 headers={"User-Agent": UA}) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except httpx.HTTPError:
            return []
    text = resp.text
    seen: set[str] = set()
    out: list[dict] = []

    def _push(full: str, size: int | None = None) -> None:
        if not full.startswith(("http://", "https://")) or full in seen:
            return
        if wanted is not None and not wanted.search(full):
            return
        if _re.search(r"\.(js|css|png|jpe?g|svg|ico|woff2?)(\?|#|$)", full, _re.I) \
           and not _re.search(r"\.(mp4|mkv|webm|mov|avi|flv|m4v|zip|rar|7z|t?gz|epub|pdf|djvu|mp3|flac|ogg|m4a|wav|opus|aac)$", full, _re.I):
            return
        seen.add(full)
        entry = {"url": full, "filename": unquote(fk.guess_filename(full, "file")),
                 "file_type": fk.classify(full), "size_bytes": size}
        out.append(entry)

    # og: + <source>/<video> tags
    for m in _re.finditer(_OG_RE, text):
        _push(urljoin(str(resp.url), unescape_html(m.group(1))))
    for m in _re.finditer(_VIDSRC_RE, text):
        _push(urljoin(str(resp.url), unescape_html(m.group(1))))
    # iframe players — many (most?) tube/porn embed pages only expose the real
    # player through a cross-origin iframe; we hand it to the analyzer as an
    # "embed" candidate and hop into it ourselves when nothing better exists.
    for m in _re.finditer(_IFRAME_RE, text):
        src = urljoin(str(resp.url), unescape_html(m.group(1)))
        if not src.startswith("http") or src in seen:
            continue
        low = src.lower()
        if not any(t in low for t in ("video", "embed", "player", "watch", "media", "/vid")):
            continue
        seen.add(src)
        from urllib.parse import urlparse as _up
        pr = _up(src)
        out.append({"url": src,
                    "filename": f"embed · {pr.netloc}{pr.path[:36]}",
                    "file_type": "embed", "size_bytes": None})
    # plain file anchors + directory listings (name  <tab> size)
    for m in _re.finditer(MEDIA_HREF_RE, text):
        href = unescape_html(m.group(1))
        if href.startswith(("data:", "javascript:")):
            continue
        tail = text[m.end():m.end() + 260]
        size = None
        sm = _re.search(r"(\d+(?:[.,]\d+)\s?(?:\s?)(?:KB|MB|GB|TB))", tail, _re.I)
        if sm:
            size = _human_size_local(sm.group(1))
        _push(urljoin(str(resp.url), href), size)
    return out[:limit]


_SIZE_MULT = {"kb": 1024, "mb": 1024 ** 2, "gb": 1024 ** 3, "tb": 1024 ** 4}


def _human_size_local(text: str) -> int | None:
    import re as _re
    m = _re.search(r"([\d.,]+)\s*(kb|mb|gb|tb)", text, _re.I)
    if not m:
        return None
    try:
        return int(float(m.group(1).replace(",", "")) * _SIZE_MULT[m.group(2).lower()])
    except (ValueError, KeyError):
        return None



def unescape_html(s: str) -> str:
    from html import unescape
    return unescape(s)


# ---------------------------------------------------------------------------
# Download planning — decide which worker handles a URL
# ---------------------------------------------------------------------------
async def plan_download(url: str, title: str = "", fmt: dict | None = None) -> dict:
    """Return the enqueue kwargs for any URL (used by result cards & direct link)."""
    ext = fk.url_extension(url)
    if ext in fk.STREAM_EXTS:
        fmt = fmt or {}
        meta: dict = {}
        kind = "hls"
        try:
            import yt_dlp  # noqa: F401
            have_yt = True
        except ImportError:
            have_yt = False
        if fmt.get("format") and fmt["format"] != "bv*+ba/b":
            if have_yt:      # yt-dlp resolves variant idx / rep-id with audio muxing
                kind, meta = "ytdlp", {"format": fmt["format"], "quality": fmt.get("label", "")}
            elif fmt.get("url"):
                kind, meta = "hls", {"variant_url": fmt["url"], "quality": fmt.get("label", "")}
        elif have_yt:
            kind, meta = "ytdlp", {"format": "bv*+ba/b", "quality": "Best (auto)"}
        return {"url": url, "kind": kind, "title": title or fk.guess_filename(url),
                "file_type": "video", "meta": meta}
    if url.lower().startswith("magnet:"):
        return {"url": url, "kind": "magnet", "title": _magnet_title(url),
                "file_type": "magnet", "meta": {}}
    media = None
    if not ext or await asyncio.to_thread(find_extractor, url):
        media, _err = await _try_ytdlp(url)
    if media:
        quality = str(settings.get("default_quality", "1080"))  # noqa: E501
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
                         "extractor": media["extractor"],
                         "extractor_args": media.get("extractor_args") or None}}
    # If the user explicitly chose a format card, trust yt-dlp.
    if fmt and fmt.get("format"):
        return {"url": url, "kind": "ytdlp", "title": title or fk.guess_filename(url),
                "file_type": "video", "meta": {"format": fmt["format"],
                                               "quality": fmt.get("label", "")}}
    return {"url": url, "kind": "http", "title": title or fk.guess_filename(url),
            "file_type": fk.classify(url), "meta": {}}
