"""WebFinder — dedicated image & video search verticals.

Web search + `filetype:` dorks returns *pages about* files. This module asks
the engines' own **media indexes** instead, so the user gets actual images and
videos — direct file URLs, thumbnails, dimensions, durations — and can filter
them like a pro:

  images  →  DuckDuckGo i.js (JSON)  ·  Bing Images (qft filters)  ·  Google tbm=isch
  videos  →  DuckDuckGo v.js (JSON)  ·  Bing Videos JSON blobs     ·  Google tbm=vid

Filters (per group):
  images: size (min w×h), aspect, color, type      → pushed to Bing via qft,
  videos: duration bucket, min height              → enforced post-fetch
Everything degrades per-source: one blocked engine never kills the search.
"""
from __future__ import annotations

import asyncio
import html as htmllib
import json
import re
from urllib.parse import quote_plus, urlparse, unquote

import httpx

DESKTOP_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
# Consent bypass cookies: without these Google serves the EU interstitial and a JS shell.
GOOGLE_COOKIES = {"CONSENT": "YES+cb.20220419-08-p0.en.LX.ALL", "SOCS": "CAISHAgBEhJnd3NfMjAyMjA0MjAtMF9SQzIaAmRlIAEaBgiA_LyuBg", "NP_done": "1"}


def _domain(url: str) -> str:
    try:
        host = urlparse(url).netloc
        return host[4:] if host.startswith("www.") else host
    except ValueError:
        return ""


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"User-Agent": DESKTOP_UA,
                 "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
                 "Accept-Language": "en-US,en;q=0.9"},
        timeout=httpx.Timeout(14.0, connect=8.0),
        follow_redirects=True, verify=False)


def _ok(url: str) -> bool:
    return bool(url) and url.startswith("http") and not url.startswith("data:")


# ── shared image result schema ──────────────────────────────────────────────
def _mk(url, thumb, title, page, w, h, source, duration=None, **extra) -> dict:
    d = {"title": (title or "").strip() or url.split("/")[-1],
         "url": url, "thumb": thumb or "", "page": page or "",
         "domain": _domain(page or url), "width": int(w or 0), "height": int(h or 0),
         "engine": source, "snippet": "", "size_bytes": None, "duration": duration}
    d.update(extra)
    return d


# ═══════════════════════════════════════════════════════════════════════════
#  IMAGE vertical
# ═══════════════════════════════════════════════════════════════════════════
SIZE_FILTERS = {  # frontend id → (min_w, min_h, bing qft)
    "any":       (0, 0, ""),
    "large":     (800, 600, "+filterui:imagesize-large"),
    "hd":        (1280, 720, "+filterui:imagesize-large"),
    "uhd":       (1920, 1080, "+filterui:imagesize-wallpaper"),
    "wallpaper": (2560, 1440, "+filterui:imagesize-wallpaper"),
}
COLOR_QFT = {c: f"+filterui:color2-{c}" for c in
             ("red", "orange", "yellow", "green", "teal", "blue", "purple", "pink",
              "brown", "white", "gray", "black", "transparent")}
TYPE_QFT = {t: f"+filterui:type-{t}" for t in ("photo", "clipart", "line", "greyscale", "face", "animated")}
ASPECT_QFT = {"wide": "+filterui:aspect-wide", "tall": "+filterui:aspect-tall", "square": "+filterui:aspect-square"}


async def search_images(query: str, filters: dict | None, limit: int, safe: bool = False) -> dict:
    f = filters or {}
    tasks = {
        "duckduckgo": _ddg_images(query, limit, safe),
        "bing": _bing_images(query, f, limit, safe),
        "google": _google_isch(query, limit, safe),
    }
    return await _collect(tasks, f, limit, kind="image")


async def _collect(tasks: dict[str, "asyncio.Future"], filters: dict, limit: int, kind: str) -> dict:
    sources = {}
    results: list[dict] = []
    gathered = await asyncio.gather(*tasks.values(), return_exceptions=True)
    for name, res in zip(tasks, gathered):
        if isinstance(res, BaseException):
            sources[name] = {"ok": False, "error": str(res)[:160], "count": 0}
        else:
            sources[name] = {"ok": True, "error": "", "count": len(res)}
            results.extend(res)
    results = _postfilter(results, filters, kind)
    results = _dedupe(results, key=lambda r: r["url"])[:limit]
    return {"results": results, "sources": sources}


def _postfilter(results: list[dict], f: dict, kind: str) -> list[dict]:
    out = []
    if kind == "image":
        size = f.get("size") or "any"
        min_w, min_h, _ = SIZE_FILTERS.get(size, (0, 0, ""))
        aspect = f.get("aspect") or ""
        for r in results:
            w, h = r.get("width") or 0, r.get("height") or 0
            if min_w and (w < min_w or h < min_h):
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


def _dedupe(results: list[dict], key) -> list[dict]:
    seen, out = set(), []
    for r in results:
        k = key(r)
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


# ── DuckDuckGo images (JSON API behind a vqd handshake) ─────────────────────
async def _ddg_vqd(client: httpx.AsyncClient, query: str, ia: str) -> str:
    r = await client.get(f"https://duckduckgo.com/?q={quote_plus(query)}&iax={ia}&ia={ia}")
    m = re.search(r"vqd=([\d-]+)", r.text)
    if not m:
        raise RuntimeError("DuckDuckGo did not issue an API token (rate limit?)")
    return m.group(1)


async def _ddg_images(query: str, limit: int, safe: bool) -> list[dict]:
    async with _client() as client:
        vqd = await _ddg_vqd(client, query, "images")
        r = await client.get("https://duckduckgo.com/i.js", params={
            "l": "us-en", "o": "json", "q": query, "vqd": vqd,
            "pn": 1, "af": "1" if not safe else "0", "s": "off" if not safe else "active"})
        data = r.json()
    out = []
    for it in data.get("results", []):
        img = it.get("image") or it.get("thumbnail") or ""
        if not _ok(img):
            continue
        out.append(_mk(img, it.get("thumbnail") or img, it.get("title"),
                       it.get("url"), it.get("width"), it.get("height"), "duckduckgo",
                       file_type="image", is_direct=True, source_engine=it.get("source", "")))
    return out


# ── Bing Images (HTML with escaped-JSON metadata + server-side qft filters) ─
def _bing_qft(f: dict) -> str:
    parts = []
    for spec in (SIZE_FILTERS.get(f.get("size", "any"), ("", "", ""))[2],
                 COLOR_QFT.get(f.get("color", ""), ""),
                 TYPE_QFT.get(f.get("type", ""), ""),
                 ASPECT_QFT.get(f.get("aspect", ""), "")):
        if spec:
            parts.append(spec)
    return "".join(parts)


async def _bing_images(query: str, f: dict, limit: int, safe: bool) -> list[dict]:
    params = {"q": query, "form": "HDRSC2", "first": 1, "count": min(max(limit, 35), 100),
              "view": "detail", "async": "content"}
    qft = _bing_qft(f)
    if qft:
        params["qft"] = qft
    if not safe:
        params["adlt"] = "off"
        params["safeSearch"] = "off"
    async with _client() as client:
        r = await client.get("https://www.bing.com/images/search", params=params)
    if r.status_code >= 400:
        raise RuntimeError(f"Bing Images returned HTTP {r.status_code}")
    out = []
    for m in re.finditer(r'm="(\{[^"]*murl[^"]*\})"', r.text):
        try:
            j = json.loads(htmllib.unescape(m.group(1)))
        except json.JSONDecodeError:
            continue
        url = j.get("murl") or ""
        if not _ok(url):
            continue
        out.append(_mk(url, j.get("turl") or "", j.get("desc") or j.get("title"),
                       j.get("purl"), j.get("w"), j.get("h"), "bing",
                       file_type="image", is_direct=True,
                       size_bytes=j.get("filesize") or None))
        if len(out) >= limit:
            break
    return out


# ── Google Images (tbm=isch — works once the consent cookies are set) ───────
_GOOGLE_IMG_RE = re.compile(r'\["(https?:[^",]{10,500}?\.(?:jpe?g|png|webp|gif)(?:\?[^"]{0,80})?)",(\d+),(\d+)\]')


async def _google_isch(query: str, limit: int, safe: bool) -> list[dict]:
    async with _client() as client:
        client.cookies.update(GOOGLE_COOKIES)
        r = await client.get("https://www.google.com/search", params={
            "q": query, "tbm": "isch", "hl": "en", "gl": "us",
            "num": min(max(limit, 30), 100), "safe": "active" if safe else "off"})
    text = r.text.replace("\\u002F", "/")
    if "sorry" in r.url.path or "CAPTCHA" in text[:3000]:
        raise RuntimeError("Google served a captcha wall — try again in a minute or use a proxy")
    out, seen = [], set()
    for m in _GOOGLE_IMG_RE.finditer(text):
        url, w, h = m.group(1), int(m.group(2)), int(m.group(3))
        if url in seen or not _ok(url):
            continue
        seen.add(url)
        out.append(_mk(url, url, query, "", w, h, "google",
                       file_type="image", is_direct=True))
        if len(out) >= limit:
            break
    if not out:
        raise RuntimeError("Google returned no parseable image results")
    return out


# ═══════════════════════════════════════════════════════════════════════════
#  VIDEO vertical
# ═══════════════════════════════════════════════════════════════════════════
async def search_videos(query: str, filters: dict | None, limit: int, safe: bool = False) -> dict:
    f = filters or {}
    tasks = {
        "duckduckgo": _ddg_videos(query, limit, safe),
        "bing": _bing_videos(query, f, limit, safe),
        "web_dorks": _video_dork_fallback(query, limit, safe),
    }
    data = await _collect(tasks, f, limit, kind="video")
    # de-dupe by normalized content path so a video isn't listed twice
    data["results"] = _dedupe(data["results"], key=lambda r: re.sub(r"\W", "", (r.get("title") or "")[:60].lower())[:48])
    return data


def _parse_len(v) -> int:
    if isinstance(v, (int, float)):
        return int(v)
    m = re.match(r"^(?:(\d+):)?(\d{1,2}):(\d{2})$", str(v or "").strip())
    if m:
        h = int(m.group(1) or 0)
        mm, ss = int(m.group(2)), int(m.group(3))
        return h * 3600 + mm * 60 + ss if m.group(1) else mm * 60 + ss
    return 0


async def _ddg_videos(query: str, limit: int, safe: bool) -> list[dict]:
    async with _client() as client:
        vqd = await _ddg_vqd(client, query, "videos")
        r = await client.get("https://duckduckgo.com/v.js", params={
            "l": "us-en", "o": "json", "q": query, "vqd": vqd, "pn": 1,
            "s": "off" if not safe else "active"})
        data = r.json()
    out = []
    for it in data.get("results", []):
        vurl = it.get("video_url") or it.get("content") or ""
        if not _ok(vurl):
            continue
        out.append(_mk(vurl, it.get("image") or "", it.get("title"),
                       it.get("url"), 0, it.get("resolution") or 0, "duckduckgo",
                       duration=_parse_len(it.get("length")),
                       file_type="video", is_direct=True,
                       publisher=it.get("publisher") or ""))
    return out


async def _bing_videos(query: str, f: dict, limit: int, safe: bool) -> list[dict]:
    params = {"q": query, "form": "HDRSC3", "count": min(max(limit, 30), 60), "first": 1}
    if f.get("duration"):
        params["qft"] = f"+filterui:video-duration-{f['duration']}"
    if not safe:
        params["adlt"] = "off"
    async with _client() as client:
        r = await client.get("https://www.bing.com/videos/search", params=params)
    if r.status_code >= 400:
        raise RuntimeError(f"Bing Videos returned HTTP {r.status_code}")
    out = []
    pat = re.compile(r'<a[^>]*class="videoclick"[^>]*murl="([^"]+)"[^>]*mth="([^"]+)"')
    for m in pat.finditer(r.text):
        src, meta = htmllib.unescape(m.group(1)), htmllib.unescape(m.group(2))
        if not _ok(src):
            continue
        out.append(_mk(src, "", query, "", 0, 0, "bing", file_type="video", is_direct=False))
        if len(out) >= limit:
            break
    if not out:
        # Modern Bing embeds a JSON state — try the raw markup for mediaurl blobs.
        for m in re.finditer(r'"mediaurl"\s*:\s*"([^"]+)"[^}]*"mktlen(?:gth)?"\s*:\s*"?(\d+)"?', r.text):
            src = m.group(1).replace("\\u002f", "/").replace("\\/", "/")
            if _ok(src):
                out.append(_mk(src, "", query, "", 0, 0, "bing",
                               duration=_parse_len(m.group(2)), file_type="video", is_direct=False))
                if len(out) >= limit:
                    break
    if not out:
        raise RuntimeError("Bing Videos markup changed — results came from other sources")
    return out


async def _video_dork_fallback(query: str, limit: int, safe: bool) -> list[dict]:
    """Web results restricted to video-file dorks — catches what the verticals miss."""
    from ..engines import run_search
    responses = await run_search(query, ["video"], ["bing", "duckduckgo"], limit, safe=safe)
    out = []
    for resp in responses:
        for r in resp.results:
            r["engine"] = resp.engine
            r.setdefault("duration", None)
            r.setdefault("thumb", "")
            r.setdefault("page", "")
            out.append(r)
    return out
