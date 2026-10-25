"""WebFinder — search engine scrapers.

Every engine is a thin async scraper on top of `httpx`. They all return a
list of result dicts. Scraping is best-effort by design: an engine that
rate-limits us simply yields zero results and the aggregator moves on.
"""
from __future__ import annotations

import asyncio
import random
import re
from dataclasses import dataclass, field
from html import unescape
from typing import Callable
from urllib.parse import quote_plus, urlparse, parse_qs, unquote

import httpx

from ..core import dorks as dk

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
]


@dataclass
class EngineResponse:
    engine: str
    ok: bool
    error: str = ""
    elapsed_ms: int = 0
    results: list[dict] = field(default_factory=list)


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    return unescape(re.sub(r"\s+", " ", text)).strip()


def _domain(url: str) -> str:
    try:
        host = urlparse(url).netloc
        return host[4:] if host.startswith("www.") else host
    except ValueError:
        return ""


def _base_client(proxy: str | None = None) -> httpx.AsyncClient:
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    return httpx.AsyncClient(
        headers=headers,
        timeout=httpx.Timeout(12.0, connect=8.0),
        follow_redirects=True,
        proxy=proxy or None,
        verify=False,
    )


def _strip_redirect(url: str) -> str:
    """Google/DDG wrap results in /url?q=… redirectors — unwrap them."""
    try:
        p = urlparse(url)
        if "duckduckgo.com" in p.netloc and (p.path.startswith("/l/") or "l.us1." in p.netloc):
            q = parse_qs(p.query).get("uddg")
            if q:
                return unquote(q[0])
        if p.path.startswith("/url") or p.path.startswith("/redirect"):
            q = parse_qs(p.query)
            for key in ("url", "q"):
                if key in q:
                    return unquote(q[key][0])
    except ValueError:
        pass
    return url


def _mk_result(url: str, title: str, snippet: str) -> dict:
    return {
        "title": title,
        "url": url,
        "snippet": snippet,
        "domain": _domain(url),
        "size_bytes": dk.extract_size_hint(snippet),
        "file_type": dk.classify(url, snippet, title),
        "is_direct": dk.url_extension(url) in _DIRECT_EXT_ALL or url.startswith("magnet:"),
    }


DIRECT_EXT_UNION = set()
for _spec in dk.FILE_TYPES.values():
    DIRECT_EXT_UNION |= _spec["exts"]
_DIRECT_EXT_ALL = DIRECT_EXT_UNION


# ---------------------------------------------------------------------------
# Engine implementations
# ---------------------------------------------------------------------------
async def search_duckduckgo(client: httpx.AsyncClient, query: str, limit: int) -> list[dict]:
    resp = await client.post(
        "https://html.duckduckgo.com/html/",
        data={"q": query, "kl": "us-en", "ia": "web"},
        headers={"Referer": "https://duckduckgo.com/"},
    )
    resp.raise_for_status()
    out: list[dict] = []
    for m in re.finditer(
        r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?'
        r'(?:<a[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>|result__snippet[^>]*>(.*?)</(?:a|td|div)>)',
        resp.text, re.S,
    ):
        url = _strip_redirect(unescape(m.group(1)))
        if not url.startswith("http"):
            continue
        snippet = _clean(m.group(3) or m.group(4) or "")
        out.append(_mk_result(url, _clean(m.group(2)), snippet))
        if len(out) >= limit:
            break
    return out


async def search_bing(client: httpx.AsyncClient, query: str, limit: int) -> list[dict]:
    # Bing's RSS endpoint is dramatically more scraper-friendly than its HTML.
    out: list[dict] = []
    resp = await client.get(
        "https://www.bing.com/search",
        params={"q": query, "count": min(limit, 50), "setlang": "en", "format": "rss"},
    )
    resp.raise_for_status()
    for m in re.finditer(r"<item>\s*<title>(.*?)</title>\s*<link>(.*?)</link>\s*<description>(.*?)</description>", resp.text, re.S):
        url = unescape(m.group(2))
        out.append(_mk_result(url, _clean(unescape(m.group(1))), _clean(unescape(m.group(3)))))
        if len(out) >= limit:
            break
    if out:
        return out
    # RSS can be disabled — fall back to HTML scraping.
    resp = await client.get("https://www.bing.com/search", params={"q": query, "count": min(limit, 30), "setlang": "en"})
    for m in re.finditer(r'<li class="b_algo".*?<h2><a href="([^"]+)"[^>]*>(.*?)</a>.*?(?:<p[^>]*>(.*?)</p>)?', resp.text, re.S):
        url = _strip_redirect(unescape(m.group(1)))
        if not url.startswith("http"):
            continue
        out.append(_mk_result(url, _clean(m.group(2)), _clean(m.group(3) or "")))
        if len(out) >= limit:
            break
    return out


async def search_google(client: httpx.AsyncClient, query: str, limit: int) -> list[dict]:
    resp = await client.get(
        "https://www.google.com/search",
        params={"q": query, "num": min(limit, 30), "hl": "en", "gl": "us"},
    )
    resp.raise_for_status()
    out: list[dict] = []
    # The consent/noscript variant still contains /url?q= redirects + titles.
    for m in re.finditer(r'<a[^>]*href="/url\?q=([^&"]+)[^"]*"[^>]*>(.*?)</a>', resp.text, re.S):
        url = unescape(unquote(m.group(1)))
        if not url.startswith("http") or "google." in urlparse(url).netloc:
            continue
        title = _clean(m.group(2))
        if not title:
            continue
        out.append(_mk_result(url, title, ""))
        if len(out) >= limit:
            break
    if not out and ("captcha" in resp.text.lower() or "unusual traffic" in resp.text.lower()):
        raise RuntimeError("Google flagged this IP (CAPTCHA). Try Bing/DuckDuckGo or a proxy.")
    return out


async def search_yandex(client: httpx.AsyncClient, query: str, limit: int) -> list[dict]:
    resp = await client.get(
        "https://yandex.com/search/", params={"text": query, "lr": 21204},
        headers={"Referer": "https://yandex.com/"},
    )
    resp.raise_for_status()
    if "Captcha" in resp.text[:4000] or resp.status_code == 403:
        raise RuntimeError("Yandex demanded a captcha — enable it only with a proxy.")
    out: list[dict] = []
    for m in re.finditer(r'<a[^>]*class="[^"]*organic__url[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', resp.text, re.S):
        url = _strip_redirect(unescape(m.group(1)))
        if not url.startswith("http"):
            continue
        out.append(_mk_result(url, _clean(m.group(2)), ""))
        if len(out) >= limit:
            break
    return out


async def search_mojeek(client: httpx.AsyncClient, query: str, limit: int) -> list[dict]:
    resp = await client.get("https://www.mojeek.com/search", params={"q": query})
    resp.raise_for_status()
    out: list[dict] = []
    for m in re.finditer(r'<a class="ob"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?(?:<p>(.*?)</p>)?', resp.text, re.S):
        url = _strip_redirect(unescape(m.group(1)))
        if not url.startswith("http"):
            continue
        out.append(_mk_result(url, _clean(m.group(2)), _clean(m.group(3) or "")))
        if len(out) >= limit:
            break
    return out


ENGINES: dict[str, Callable] = {
    "google": search_google,
    "bing": search_bing,
    "duckduckgo": search_duckduckgo,
    "yandex": search_yandex,
    "mojeek": search_mojeek,
}

ENGINE_META = {
    "google": {"label": "Google", "color": "#4285F4", "reliability": "medium (aggressive bot walls)"},
    "bing": {"label": "Bing", "color": "#00897B", "reliability": "high (RSS endpoint)"},
    "duckduckgo": {"label": "DuckDuckGo", "color": "#DE5833", "reliability": "high"},
    "yandex": {"label": "Yandex", "color": "#FC3F1D", "reliability": "low (captcha) — pair with proxy"},
    "mojeek": {"label": "Mojeek", "color": "#86B566", "reliability": "medium"},
}


async def run_search(
    query: str,
    types: list[str],
    engine_names: list[str],
    limit: int,
    proxy: str | None = None,
) -> list[EngineResponse]:
    """Fan-out the same dork-augmented query to every enabled engine."""
    full_query = dk.build_query(query, types)

    async def _guarded(fn: Callable, client: httpx.AsyncClient) -> EngineResponse:
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        name = fn.__name__.replace("search_", "")
        try:
            res = await fn(client, full_query, limit)
            return EngineResponse(name, True, "", int((loop.time() - t0) * 1000), res)
        except Exception as exc:  # noqa: BLE001
            return EngineResponse(name, False, str(exc)[:200], int((loop.time() - t0) * 1000), [])

    tasks = []
    async with _base_client(proxy) as client:
        for name in engine_names:
            fn = ENGINES.get(name)
            if fn:
                tasks.append(asyncio.create_task(_guarded(fn, client)))
        return list(await asyncio.gather(*tasks))
