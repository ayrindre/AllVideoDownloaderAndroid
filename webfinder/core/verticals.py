"""WebFinder — dedicated image & video search verticals.

Web search + `filetype:` dorks returns *pages about* files. This module asks
the engines' own **media indexes** instead, so the user gets actual images and
videos — direct file URLs, thumbnails, dimensions, durations — with per-type
filters applied server-side where possible and locally always.

Parsing is deliberately lenient (windowed field extraction over both HTML
attribute quoting styles and entity-escaped JSON), because engines re-flow
their markup constantly and a dead regex must not degrade into garbage.
"""
from __future__ import annotations

import asyncio
import html as htmllib
import re
from urllib.parse import quote_plus, urlparse

import httpx

DESKTOP_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
# Consent bypass cookies: without these Google serves the EU interstitial and no results.
GOOGLE_CONSENT = {"CONSENT": "YES+cb.20220419-08-p0.en.LX.ALL",
                  "SOCS": "CAISHAgBEhJnd3NfMjAyMjA0MjAtMF9SQzIaAmRlIAEaBgiA_LyuBg"}
_IMG_EXT = r"(?:jpe?g|png|webp|gif|avif|bmp)"


def _domain(url: str) -> str:
    try:
        host = urlparse(url).netloc
        return host[4:] if host.startswith("www.") else host
    except ValueError:
        return ""


def _client(extra_headers: dict | None = None, proxy: str = "") -> httpx.AsyncClient:
    headers = {"User-Agent": DESKTOP_UA,
               "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
               "Accept-Language": "en-US,en;q=0.9"}
    headers.update(extra_headers or {})
    return httpx.AsyncClient(headers=headers, proxy=proxy or None,
                             timeout=httpx.Timeout(16.0, connect=8.0),
                             follow_redirects=True, verify=False)


def _okurl(u: str) -> bool:
    return bool(u) and u.startswith("http") and not u.startswith("data:")


def _unesc(text: str) -> str:
    """Normalize entity-escaped + slash-escaped JSON blobs into plain JSON."""
    return htmllib.unescape(text).replace("\\/", "/").replace("\\u002f", "/").replace("\\u002F", "/").replace("\\x22", '"')


def _field(t: str, a: int, b: int, anchor: int, names: str | tuple[str, ...],
           kind: str = "url") -> str:
    """Nearest-priority extractor.

    `names` are tried in preference order; within one name the occurrence
    CLOSEST to `anchor` (the item's murl position) wins — that stops fields of
    the previous card bleeding into the current one when ±1.5 KB windows overlap.
    """
    names = (names,) if isinstance(names, str) else names
    tails = {"url": r'\s*:\s*"(https?://[^"]+)"',
             "num": r'\s*:\s*"?(\d+)"?',
             "text": r'\s*:\s*"([^"]{1,300}?)"'}
    for n in names:
        best = None
        for m in re.compile('"' + re.escape(n) + '"' + tails[kind]).finditer(t, a, b):
            d = abs(m.start() - anchor)
            if best is None or d < best[0]:
                best = (d, m.group(1))
        if best:
            return htmllib.unescape(best[1])
    return ""


def _mk(url, thumb, title, page, w, h, source, **extra) -> dict:
    d = {"title": (title or "").strip()[:160] or url.split("/")[-1][:60],
         "url": url, "thumb": thumb or "", "page": page or "",
         "domain": _domain(page or url), "width": int(w or 0), "height": int(h or 0),
         "engine": source, "snippet": "", "size_bytes": None, "duration": None}
    d.update(extra)
    return d


def _dedupe(results: list[dict], key) -> list[dict]:
    seen, out = set(), []
    for r in results:
        k = key(r)
        if k and k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


# ── shared per-source error state ───────────────────────────────────────────
def _source_of(name: str, results: list[dict] | Exception) -> dict:
    if isinstance(results, Exception):
        msg = str(results)
        if "TLS" in msg or "connect" in msg.lower() or "EOF" in msg:
            msg = "unreachable from this network — Google/DDG may be blocked by your ISP; a proxy in Settings fixes it"
        return {"ok": False, "error": msg[:220], "count": 0}
    return {"ok": True, "error": "", "count": len(results)}


# ═══════════════════════════════════════════════════════════════════════════
#  IMAGE vertical — Bing (primary, most scrape-tolerant) · DDG · Google isch
# ═══════════════════════════════════════════════════════════════════════════
SIZE_FILTERS = {  # frontend id → (min_w, min_h, bing qft)
    "":       (0, 0, ""),
    "any":    (0, 0, ""),
    "large":  (800, 600, "+filterui:imagesize-large"),
    "hd":     (1280, 720, "+filterui:imagesize-large"),
    "uhd":    (1920, 1080, "+filterui:imagesize-wallpaper"),
}
COLOR_QFT = {c: f"+filterui:color2-{c}" for c in
             ("red", "orange", "yellow", "green", "teal", "blue", "purple", "pink",
              "brown", "white", "gray", "black", "transparent")}
TYPE_QFT = {t: f"+filterui:type-{t}" for t in ("photo", "clipart", "line", "greyscale", "face", "animated")}
ASPECT_QFT = {"wide": "+filterui:aspect-wide", "tall": "+filterui:aspect-tall", "square": "+filterui:aspect-square"}


def _bing_qft(f: dict) -> str:
    parts = [SIZE_FILTERS.get(f.get("size", "any"), ("", "", ""))[2],
             COLOR_QFT.get(f.get("color", ""), ""),
             TYPE_QFT.get(f.get("type", ""), ""),
             ASPECT_QFT.get(f.get("aspect", ""), "")]
    return "".join(p for p in parts if p)


def _parse_bing_items(text: str, limit: int) -> list[dict]:
    """Lenient parser: works on m='{...}', m=\"{&quot;...}\" and data=\"{...}\" variants."""
    t = _unesc(text)
    out: list[dict] = []
    for m in re.finditer(r'"murl"\s*:\s*"(https?://[^"]+?[^,"])"', t):
        url = m.group(1)
        if not _okurl(url):
            continue
        # Window = the *containing JSON object*. Bing item records are flat
        # {...} blobs; a fixed ±window lets the previous card's w/h/desc bleed
        # into the current one, which silently corrupts filters.
        a0 = t.rfind("{", max(0, m.start() - 400), m.start())
        b0 = t.find("}", m.end(), min(len(t), m.end() + 1400))
        a = max(0, m.start() - 600) if a0 == -1 else a0
        b = min(len(t), m.end() + 600) if b0 == -1 else b0 + 1
        anchor = m.start()
        thumb = _field(t, a, b, anchor, ("turl", "thurl", "murl"))
        page = _field(t, a, b, anchor, ("purl", "cdnurl"))
        desc = _field(t, a, b, anchor, ("desc", "title", "alt"), kind="text")
        w = _field(t, a, b, anchor, "w", kind="num")
        h = _field(t, a, b, anchor, "h", kind="num")
        out.append(_mk(url, thumb, desc, page, w, h, "bing",
                       file_type="image", is_direct=True))
        if len(out) >= limit:
            break
    return out


async def _bing_images(client: httpx.AsyncClient, query: str, f: dict, limit: int, safe: bool) -> list[dict]:
    n = min(max(limit * 2, 35), 150)
    base = {"q": query, "count": n}
    if qft := _bing_qft(f):
        base["qft"] = qft
    if not safe:
        base.update({"adlt": "off", "safeSearch": "off"})
    # Strategy 1: the async fragment endpoint (stable markup for years).
    r = await client.get("https://www.bing.com/images/async",
                         params={**base, "first": 1, "mmasync": 1,
                                 "sapi": "images", "tsc": "ImageDetailMenu"})
    out = _parse_bing_items(r.text, limit)
    if out:
        return out
    # Strategy 2: full results page (m="..." anchors).
    r = await client.get("https://www.bing.com/images/search",
                         params={**base, "form": "HDRSC2", "first": 1, "view": "detail", "async": "content"})
    out = _parse_bing_items(r.text, limit)
    if out:
        return out
    challenge = any(s in r.text for s in ("challenge", "CAPTCHA", "captcha"))
    raise RuntimeError("Bing Images returned a challenge page — wait a minute and retry, or set a proxy"
                       if challenge else "Bing Images markup changed or returned nothing parseable")


async def _ddg_vqd(client: httpx.AsyncClient, query: str, ia: str) -> str:
    r = await client.get(f"https://duckduckgo.com/?q={quote_plus(query)}&iax={ia}&ia={ia}",
                         headers={"Referer": "https://duckduckgo.com/"})
    m = re.search(r"vqd=([\w-]{6,})", r.text)
    if not m:
        raise RuntimeError("DuckDuckGo issued no API token (bot wall or blocked network)")
    return m.group(1)


async def _ddg_images(client: httpx.AsyncClient, query: str, limit: int, safe: bool) -> list[dict]:
    vqd = await _ddg_vqd(client, query, "images")
    r = await client.get("https://duckduckgo.com/i.js",
                         params={"l": "us-en", "o": "json", "q": query, "vqd": vqd,
                                 "s": "off" if not safe else "active"},
                         headers={"Referer": "https://duckduckgo.com/"})
    try:
        data = r.json()
    except Exception:  # noqa: BLE001
        raise RuntimeError("DuckDuckGo image API replied with a non-JSON wall") from None
    out = []
    for it in data.get("results", []):
        img = it.get("image") or it.get("thumbnail") or ""
        if not _okurl(img):
            continue
        out.append(_mk(img, it.get("thumbnail") or img, it.get("title"),
                       it.get("url"), it.get("width"), it.get("height"), "duckduckgo",
                       file_type="image", is_direct=True))
    if not out:
        raise RuntimeError("DuckDuckGo image index returned nothing")
    return out


_GOOGLE_IMG_RES = (
    # "https://host/path.jpg",1024,768 — classic isch metadata triples.
    # The (?:[^"]{0,120})? tail tolerates ?w=800 / %3Fw%3D800 / &amp; suffixes.
    re.compile(rf'\["(https?://[^",]{{10,480}}?\.{_IMG_EXT}(?:[^"]{{0,120}})?)",(\d+),(\d+)\]'),
    # googleusercontent full-size entries often carry no file extension at all
    re.compile(r'\["(https?://[^",]*googleusercontent\.com/[^"]{0,300})",(\d+),(\d+)\]'),
)

GOOGLE_ISCH_PARAMS = {"hl": "en", "gl": "us", "gbv": 1}


async def _google_isch(client: httpx.AsyncClient, query: str, limit: int, safe: bool,
                       proxy: str = "") -> str:
    params = {"q": query, "tbm": "isch", "num": min(max(limit, 30), 100),
              "safe": "active" if safe else "off", **GOOGLE_ISCH_PARAMS}
    text = ""
    # Attempt 0: curl_cffi Chrome fingerprint — beats the 200-but-empty shell
    # that plain httpx gets served on strict networks.
    try:
        from . import tls
        if tls.available():
            status, text, final = await tls.google_get("https://www.google.com/search", params=params,
                                                       cookies=GOOGLE_CONSENT, proxy=proxy)
            if "sorry" not in final and text:
                return text
    except Exception:  # noqa: BLE001 — fall through to the httpx session
        pass
    client.cookies.update(GOOGLE_CONSENT)
    r = await client.get("https://www.google.com/search", params=params,
                         headers={"Referer": "https://www.google.com/"})
    if "sorry" in str(r.url):
        raise RuntimeError("Google served its captcha interstitial ('sorry' page)")
    return r.text


async def _google_isch_parse(client: httpx.AsyncClient, raw_text: str, query: str, limit: int) -> list[dict]:
    t = _unesc(raw_text)
    out, seen = [], set()
    for rx in _GOOGLE_IMG_RES:
        for m in rx.finditer(t):
            url = htmllib.unescape(m.group(1))
            if not _okurl(url) or url in seen or "gstatic.com" in urlparse(url).netloc and rx is _GOOGLE_IMG_RES[0]:
                continue
            seen.add(url)
            out.append(_mk(url, url, query, "", m.group(2), m.group(3), "google",
                           file_type="image", is_direct=True))
            if len(out) >= limit:
                return out
    if not out:
        if "consent.google.com" in t[:4000]:
            raise RuntimeError("Google consent wall — cookies not honored; retry or use a proxy")
        raise RuntimeError("Google image results page had no parseable media triples")
    return out


async def _google_images(client: httpx.AsyncClient, query: str, limit: int, safe: bool,
                         proxy: str = "") -> list[dict]:
    raw = await _google_isch(client, query, limit, safe, proxy)
    return await _google_isch_parse(client, raw, query, limit)


async def search_images(query: str, filters: dict | None, limit: int, safe: bool = False,
                        proxy: str = "") -> dict:
    f = filters or {}
    sources: dict[str, dict] = {}
    results: list[dict] = []
    async with _client(proxy=proxy) as client:
        jobs = {
            "bing": _bing_images(client, query, f, limit, safe),
            "duckduckgo": _ddg_images(client, query, limit, safe),
            "google": _google_images(client, query, limit, safe, proxy),
        }
        gathered = await asyncio.gather(*jobs.values(), return_exceptions=True)
    for name, res in zip(jobs, gathered):
        sources[name] = _source_of(name, res)
        if not isinstance(res, Exception):
            results.extend(res)
    results = _postfilter(results, f, "image")
    results = _dedupe(results, key=lambda r: r["url"])[:limit]
    return {"results": results, "sources": sources}


def _postfilter(results: list[dict], f: dict, kind: str) -> list[dict]:
    out = []
    if kind == "image":
        min_w, min_h, _ = SIZE_FILTERS.get(f.get("size", "any"), (0, 0, ""))
        aspect = f.get("aspect") or ""
        for r in results:
            w, h = r.get("width") or 0, r.get("height") or 0
            if min_w and w and h and (w < min_w or h < min_h):
                continue
            if aspect == "square" and w and h and not (0.85 <= w / h <= 1.18):
                continue
            if aspect == "wide" and w and h and w <= h:
                continue
            if aspect == "tall" and w and h and h <= w:
                continue
            out.append(r)
    else:  # video
        dur = f.get("duration") or ""
        min_res = int(f.get("min_res") or 0)
        for r in results:
            d = r.get("duration") or 0
            if dur == "short" and d > 240:
                continue
            if dur == "medium" and not (240 <= d <= 1200):
                continue
            if dur == "long" and d < 1200:
                continue
            if min_res and (r.get("height") or 0) < min_res:
                continue
            out.append(r)
    return out


# ═══════════════════════════════════════════════════════════════════════════
#  VIDEO vertical
# ═══════════════════════════════════════════════════════════════════════════
def _parse_len(v) -> int:
    if isinstance(v, (int, float)):
        return int(v)
    m = re.match(r"^(?:(\d+):)?(\d{1,2}):(\d{2})$", str(v or "").strip())
    if m:
        mm, ss = int(m.group(2)), int(m.group(3))
        return (int(m.group(1) or 0) * 3600 + mm * 60 + ss) if m.group(1) else mm * 60 + ss
    return 0


async def _ddg_videos(client: httpx.AsyncClient, query: str, limit: int, safe: bool) -> list[dict]:
    vqd = await _ddg_vqd(client, query, "videos")
    r = await client.get("https://duckduckgo.com/v.js",
                         params={"l": "us-en", "o": "json", "q": query, "vqd": vqd,
                                 "s": "off" if not safe else "active"},
                         headers={"Referer": "https://duckduckgo.com/"})
    try:
        data = r.json()
    except Exception:  # noqa: BLE001
        raise RuntimeError("DuckDuckGo video API replied with a non-JSON wall") from None
    out = []
    for it in data.get("results", []):
        vurl = it.get("video_url") or it.get("content") or ""
        if not _okurl(vurl):
            continue
        out.append(_mk(vurl, it.get("image") or "", it.get("title"), it.get("url"),
                       0, it.get("resolution") or 0, "duckduckgo",
                       duration=_parse_len(it.get("length")), publisher=it.get("publisher") or "",
                       file_type="video", is_direct=True))
    if not out:
        raise RuntimeError("DuckDuckGo video index returned nothing")
    return out


async def _bing_videos(client: httpx.AsyncClient, query: str, f: dict, limit: int, safe: bool) -> list[dict]:
    params = {"q": query, "form": "HDRSC3", "count": min(max(limit, 30), 60), "first": 1}
    if f.get("duration"):
        params["qft"] = f"+filterui:video-duration-{f['duration']}"
    if not safe:
        params["adlt"] = "off"
    r = await client.get("https://www.bing.com/videos/search", params=params)
    if r.status_code >= 400:
        raise RuntimeError(f"Bing Videos returned HTTP {r.status_code}")
    t = _unesc(r.text)
    out, seen = [], set()
    # Anchor-attribute style (legacy markup):  murl="…mp4" … length="245"
    for m in re.finditer(r'<a[^>]*murl="(https?://[^"]+)"', t):
        win = t[max(0, m.start() - 1200): min(len(t), m.end() + 1200)]
        url = htmllib.unescape(m.group(1))
        if _okurl(url) and url not in seen:
            seen.add(url)
            out.append(_mk(url, "", query, "", 0, 0, "bing",
                           duration=_parse_len(re.search(r'length="(\d+)"', win) and
                                               re.search(r'length="(\d+)"', win).group(1)),
                           file_type="video", is_direct=False))
    # JSON-state style: "mediaurl"/"contentUrl" fields with windowed metadata
    for m in re.finditer(r'"(?:mediaurl|mediaUrl|contentUrl|murl)"\s*:\s*"(https?://[^"]+?\.(?:mp4|webm|mov|m4v|mkv|avi)(?:[^"]{0,90}))"', t):
        url = htmllib.unescape(m.group(1))
        if not _okurl(url) or url in seen:
            continue
        seen.add(url)
        a2, b2, anc = max(0, m.start() - 1400), min(len(t), m.end() + 1400), m.start()
        title = _field(t, a2, b2, anc, ("title", "q"), kind="text")
        thumb = _field(t, a2, b2, anc, ("mthumb", "autoplaythumb", "thumbnailurl", "thumbnailUrl"))
        out.append(_mk(url, thumb, title, "", 0, 0, "bing",
                       duration=_parse_len(_field(t, a2, b2, anc, ("length", "duration"), kind="num")),
                       file_type="video", is_direct=True))
        if len(out) >= limit:
            break
    if not out:
        raise RuntimeError("Bing Videos markup changed or returned nothing parseable")
    return out


async def _video_dork_fallback(client: httpx.AsyncClient, query: str, limit: int, safe: bool) -> list[dict]:
    """Web results restricted to video-file dorks — catches what the verticals miss.

    Runs the *engines'* dork flow inside this client so it fails/succeeds with the
    same network conditions the verticals saw.
    """
    from ..engines import ENGINES
    from ..core import dorks as dk
    full = dk.build_query(query, ["video"])
    out: list[dict] = []
    seen: set[str] = set()
    for name in ("bing", "duckduckgo"):
        try:
            # NOTE: ENGINES maps bare names — "search_bing" caused a silent
            # KeyError that used to kill the whole dorked-video source.
            res = await ENGINES[name](client, full, min(limit, 40), safe)
        except Exception:  # noqa: BLE001 — supplementary source only
            continue
        for r in res:
            if r["url"] in seen:
                continue
            seen.add(r["url"])
            r.setdefault("thumb", "")
            r.setdefault("page", "")
            r.setdefault("duration", None)
            r["is_direct"] = True      # these ARE direct file urls (filetype: dorks)
            r["file_type"] = r.get("file_type") or "video"
            out.append(r)
    return out


async def search_videos(query: str, filters: dict | None, limit: int, safe: bool = False,
                        proxy: str = "") -> dict:
    f = filters or {}
    sources: dict[str, dict] = {}
    results: list[dict] = []
    async with _client(proxy=proxy) as client:
        jobs = {
            "bing": _bing_videos(client, query, f, limit, safe),
            "duckduckgo": _ddg_videos(client, query, limit, safe),
            "web_dorks": _video_dork_fallback(client, query, limit, safe),
        }
        gathered = await asyncio.gather(*jobs.values(), return_exceptions=True)
    for name, res in zip(jobs, gathered):
        sources[name] = _source_of(name, res)
        if not isinstance(res, Exception):
            results.extend(res)
    results = _postfilter(results, f, "video")
    results = _dedupe(results, key=lambda r: r.get("url"))[:limit]
    return {"results": results, "sources": sources}


# ═══════════════════════════════════════════════════════════════════════════
#  TORRENT vertical — real torrent indexes (magnets + .torrent files)
# ═══════════════════════════════════════════════════════════════════════════
TRACKERS = ("udp://tracker.opentrackr.org:1337/announce"
            "&tr=udp://open.stealth.si:80/announce"
            "&tr=udp://tracker.torrent.eu.org:451/announce")


def _torrent(title: str, url: str, *, page: str = "", torrent_url: str = "",
             size=None, seeds=None, leeches=None, files=None, age: str = "",
             source: str = "") -> dict:
    d = _mk(url or torrent_url or page, "", title, page, 0, 0, source,
             file_type="torrent", is_direct=False)
    d.update({"size_bytes": int(size) if size else None,
              "seeders": int(seeds) if seeds not in (None, "") else None,
              "leechers": int(leeches) if leeches not in (None, "") else None,
              "files": int(files) if files not in (None, "") else None,
              "age": age, "torrent_url": torrent_url, "thumb": ""})
    return d


async def _apibay(client: httpx.AsyncClient, query: str, limit: int) -> list[dict]:
    """The Pirate Bay's official JSON API — info_hash → magnet, no scraping."""
    r = await client.get("https://apibay.org/q.php", params={"q": query},
                         headers={"Referer": "https://apibay.org/"})
    r.raise_for_status()
    try:
        rows = r.json()
    except Exception:  # noqa: BLE001
        raise RuntimeError("apibay replied with non-JSON") from None
    if isinstance(rows, dict):  # error objects like {"error":"1"}
        return []
    out = []
    for row in rows[:limit]:
        name = htmllib.unescape(row.get("name") or "").strip()
        magnet = (row.get("link") or "").strip()
        if not name or not magnet.startswith("magnet:"):
            continue
        if "tr=" not in magnet:  # augment bare btih magnets with healthy trackers
            magnet += "&tr=" + TRACKERS
        rid = str(row.get("ID") or "")
        out.append(_torrent(name, magnet,
                            torrent_url=f"https://apibay.org/t/{rid}" if rid else "",
                            size=row.get("size"), seeds=row.get("seeders"),
                            leeches=row.get("leechers"), files=row.get("num_files"),
                            age=(row.get("added") or "")[:10], source="apibay"))
    if not out:
        raise RuntimeError("The Pirate Bay index returned nothing for this query")
    return out


async def _nyaa(client: httpx.AsyncClient, query: str, limit: int) -> list[dict]:
    """nyaa.si RSS — stable public feed with hashes and stats per item."""
    r = await client.get("https://nyaa.si/", params={"page": "rss", "q": query})
    r.raise_for_status()
    if "<item" not in r.text:
        raise RuntimeError("Nyaa RSS unavailable (blocked or malformed reply)")
    out = []
    for blk in re.findall(r"<item>(.*?)</item>", r.text, re.S)[:limit]:
        def tag(name):
            m = re.search(rf"<{name}[^>]*>(.*?)</{name}>", blk, re.S)
            return htmllib.unescape(m.group(1)).strip() if m else ""
        title = tag("title")
        link = tag("link")
        hash_m = re.search(r"<nyaa:infoHash>([0-9a-fA-F]{40})</nyaa:infoHash>", blk)
        size = re.search(r"<nyaa:size>(\d+)</nyaa:size>", blk)
        seeds = re.search(r"<nyaa:seeders>(\d+)</nyaa:seeders>", blk)
        lech = re.search(r"<nyaa:leechers>(\d+)</nyaa:leechers>", blk)
        if not title:
            continue
        magnet = (f"magnet:?xt=urn:btih:{hash_m.group(1)}&dn={quote_plus(title)}"
                  f"&tr={TRACKERS}" if hash_m else "")
        fid = re.search(r"/view/(\d+)", link)
        out.append(_torrent(title, magnet or link, page=link,
                            torrent_url=f"https://nyaa.si/download/{fid.group(1)}.torrent" if fid else "",
                            size=size and size.group(1), seeds=seeds and seeds.group(1),
                            leeches=lech and lech.group(1), source="nyaa"))
    if not out:
        raise RuntimeError("Nyaa feed had no entries for this query")
    return out


async def _1337x(client: httpx.AsyncClient, query: str, limit: int) -> list[dict]:
    """1337x search page — lenient row scrape; .torrent download pattern is stable."""
    r = await client.get(f"https://1337x.to/search/{quote_plus(query)}/1/")
    if r.status_code in (403, 429):
        raise RuntimeError(f"1337x anti-bot ({r.status_code})")
    r.raise_for_status()
    out = []
    for row in re.findall(r'<tr>.*?</tr>', r.text, re.S):
        name_m = re.search(r'<a href="/torrent/(\d+)/[^"]*/"[^>]*>\s*([^<]{4,200}?)\s*</a>', row)
        if not name_m:
            continue
        fid, name = name_m.group(1), htmllib.unescape(name_m.group(2)).strip()
        cells = [re.sub(r"<[^>]+>", " ", c).strip() for c in re.findall(r"<td[^>]*>.*?</td>", row, re.S)]
        size, nums = "", []
        for txt in cells:
            if re.search(r"\d+(?:\.\d+)?\s*(?:B|kB|KB|MB|GB|TB)\b", txt):
                size = size or str(_human_size(txt))
            elif re.fullmatch(r"\d[\d,]*", txt):
                nums.append(txt.replace(",", ""))
        seeds = nums[0] if nums else ""     # positional: search rows are size|seed|peer
        leeches = nums[1] if len(nums) > 1 else ""
        out.append(_torrent(name, "", page=f"https://1337x.to/torrent/{fid}/x/",
                            torrent_url=f"https://1337x.to/torrent/{fid}.torrent",
                            size=size, seeds=seeds, leeches=leeches, source="1337x"))
        if len(out) >= limit:
            break
    if not out:
        raise RuntimeError("1337x markup changed or search returned no rows")
    return out


_SIZE_UNITS = {"b": 1, "kb": 1024, "mb": 1024**2, "gb": 1024**3, "tb": 1024**4}


def _human_size(text: str) -> int:
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(B|kB|KB|MB|GB|TB)", text)
    if not m:
        return 0
    return int(float(m.group(1).replace(",", ".")) * _SIZE_UNITS[m.group(2).lower()])


async def search_torrents(query: str, filters: dict | None, limit: int, safe: bool = False,
                          proxy: str = "") -> dict:
    f = filters or {}
    sources: dict[str, dict] = {}
    results: list[dict] = []
    async with _client({"Referer": "https://apibay.org/"}, proxy=proxy) as client:
        jobs = {
            "apibay": _apibay(client, query, limit),
            "nyaa": _nyaa(client, query, limit),
            "1337x": _1337x(client, query, limit),
        }
        gathered = await asyncio.gather(*jobs.values(), return_exceptions=True)
    for name, res in zip(jobs, gathered):
        sources[name] = _source_of(name, res)
        if not isinstance(res, Exception):
            results.extend(res)
    min_seeds = int(f.get("min_seeds") or 0)
    if min_seeds:
        results = [r for r in results if (r.get("seeders") or 0) >= min_seeds]
    results = _dedupe(results, key=lambda r: (r.get("url") or r.get("torrent_url") or r["title"]).lower())
    # healthiest first — seed count is what makes a torrent actually downloadable
    results.sort(key=lambda r: -(r.get("seeders") or 0))
    return {"results": results, "sources": sources}


# ═══════════════════════════════════════════════════════════════════════════
#  E-BOOK vertical — real book FILES (Gutenberg / Internet Archive / Open Library)
# ═══════════════════════════════════════════════════════════════════════════
async def _gutendex(client: httpx.AsyncClient, query: str, limit: int) -> list[dict]:
    r = await client.get("https://gutendex.com/books", params={"search": query, "results_per_page": min(max(limit, 20), 64)})
    r.raise_for_status()
    data = r.json()
    out = []
    for bk in data.get("results", []):
        fmts = bk.get("formats") or {}
        url = (fmts.get("application/epub+zip") or fmts.get("text/html")
               or fmts.get("application/x-mobipocket-ebook") or "")
        if not url:
            continue
        author = ", ".join(a.get("name", "") for a in (bk.get("authors") or [])[:2])
        title = htmllib.unescape(bk.get("title") or "")
        out.append(_mk(url, fmts.get("image/jpeg") or "", f"{title}" + (f" — {author}" if author else ""),
                       bk.get("url") or "", 0, 0, "gutenberg", file_type="book",
                       is_direct=True, publisher=author,
                       extra={"downloads": bk.get("download_count") or 0, "year": ""}))
    if not out:
        raise RuntimeError("Project Gutenberg had no matching books")
    return out


async def _internet_archive(client: httpx.AsyncClient, query: str, limit: int) -> list[dict]:
    r = await client.get("https://archive.org/advancedsearch.php", params={
        "q": f"({query}) AND mediatype:(texts)", "fl[]": ["identifier", "title", "year"],
        "rows": min(max(limit // 2, 8), 20), "page": 1, "output": "json",
        "sort[]": "downloads desc"})
    r.raise_for_status()
    docs = (((r.json() or {}).get("response") or {}).get("docs")) or []
    if not docs:
        raise RuntimeError("Internet Archive found no matching texts")

    async def one(doc: dict) -> dict | None:
        ident = doc.get("identifier") or ""
        title = htmllib.unescape(str(doc.get("title") or ident)) + (f" ({doc['year']})" if doc.get("year") else "")
        item = {"title": title, "url": "", "thumb": f"https://archive.org/services/img/{ident}",
                "page": f"https://archive.org/details/{ident}", "domain": "archive.org",
                "width": 0, "height": 0, "engine": "internetarchive", "snippet": "",
                "size_bytes": None, "duration": None, "file_type": "book", "is_direct": False,
                "publisher": "", "year": str(doc.get("year") or "")}
        try:  # metadata → pick a real downloadable file
            meta = (await client.get(f"https://archive.org/metadata/{ident}")).json()
            server, root = meta.get("server"), meta.get("dir") or ""
            best = None
            for fil in ((meta.get("files") or [])):
                name = (fil.get("name") or "").lower()
                if name.endswith((".pdf", ".epub", ".djvu")):
                    pref = {".pdf": 0, ".epub": 1, ".djvu": 2}[name[-4:]]
                    if best is None or pref < best[0]:
                        best = (pref, fil.get("name"), int(fil.get("size") or 0))
            if best and server:
                item["url"] = f"https://{server}/download/{ident}/{quote_plus(best[1])}"
                item["size_bytes"] = best[2] or None
        except Exception:  # noqa: BLE001 — details stay optional
            pass
        return item

    gathered = await asyncio.gather(*(one(d) for d in docs[:10]), return_exceptions=True)
    out = [g for g in gathered if isinstance(g, dict) and g["url"]]
    if not out:
        # keep read-only entries as fallback so the source still contributes
        out = [g for g in gathered if isinstance(g, dict)]
    if not out:
        raise RuntimeError("Internet Archive metadata fetch failed")
    return out


async def search_ebooks(query: str, filters: dict | None, limit: int, safe: bool = False,
                        proxy: str = "") -> dict:
    f = filters or {}
    sources: dict[str, dict] = {}
    results: list[dict] = []
    async with _client(proxy=proxy) as client:
        jobs = {
            "gutenberg": _gutendex(client, query, limit),
            "internetarchive": _internet_archive(client, query, limit),
        }
        gathered = await asyncio.gather(*jobs.values(), return_exceptions=True)
    for name, res in zip(jobs, gathered):
        sources[name] = _source_of(name, res)
        if not isinstance(res, Exception):
            results.extend(res)
    fmt = (f.get("format") or "").lower()
    if fmt:
        results = [r for r in results if fmt in (r.get("url") or "").lower()]
    results = _dedupe(results, key=lambda r: (r.get("url") or r.get("page") or r["title"]).lower())[:limit]
    return {"results": results, "sources": sources}


# ═══════════════════════════════════════════════════════════════════════════
#  ARCHIVE vertical — dorked web, hard-relevance-gated to actual files/dirs
# ═══════════════════════════════════════════════════════════════════════════
async def search_archives(query: str, filters: dict | None, limit: int, safe: bool = False,
                          proxy: str = "") -> dict:
    """Archives have no public media index — so we dork harder (intitle:"index of")
    and then GATE: a result only survives when its URL or title actually names a
    compressed file or a directory listing. Pages about zip files never pass."""
    from ..engines import ENGINES
    from . import dorks as dk
    f = filters or {}
    ext = (f.get("ext") or "").strip(". ")
    mod = f"filetype:{ext}" if ext else "zip OR rar OR 7z OR tar OR gz"
    q = f'{query} ("index of" OR "download") ({mod})'
    sources: dict[str, dict] = {}
    kept: list[dict] = []
    dropped = 0
    async with _client(proxy=proxy) as client:
        jobs = {}
        for name in ("bing", "duckduckgo", "mojeek"):
            if name in ENGINES:
                jobs[name] = ENGINES[name](client, q, max(limit, 30), safe)
        gathered = await asyncio.gather(*jobs.values(), return_exceptions=True)
    for name, res in zip(jobs, gathered):
        if isinstance(res, Exception):
            sources[name] = _source_of(name, res)
            continue
        rows = [r for r in res if _archive_relevant(r)]
        dropped += len(res) - len(rows)
        for r in rows:
            r.setdefault("thumb", "")
            r["file_type"] = "archive"
            r["is_direct"] = bool(re.search(r"\.(zip|rar|7z|t?gz|bz2|xz|iso)(\?|#|$)", r["url"], re.I))
        kept.extend(rows)
        sources[name] = {"ok": True, "error": (f"page-only hits dropped: {len(res) - len(rows)}" if dropped else ""),
                         "count": len(rows)}
    kept = _dedupe(kept, key=lambda r: r["url"])[:limit]
    return {"results": kept, "sources": sources, "dropped_irrelevant": dropped}


def _archive_relevant(r: dict) -> bool:
    blob = (r.get("url", "") + " " + r.get("title", "") + " " + r.get("snippet", "")).lower()
    return bool(re.search(r"\.(zip|rar|7z|tar|t?gz|bz2|xz|iso)\b", blob)
                or "index of" in blob or "directory listing" in blob)
