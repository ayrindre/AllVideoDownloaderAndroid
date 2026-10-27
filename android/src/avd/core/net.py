"""All Video Downloader — HTTP layer with browser-grade realism.

Tube sites and their CDNs stopped accepting "curl with a Chrome user-agent"
years ago: they check the full header set, the TLS handshake (JA3/JA4) and,
increasingly, answer anything that fails those checks with a Cloudflare
``Just a moment…`` page or a bare ``403``.

Two layers fix that here, both strictly optional/fallback so the existing
httpx code paths (and their fixture tests) keep working exactly as before:

1. :func:`browser_headers` — the header set a real Chrome sends for a page
   navigation (UA alone is not enough; ``Sec-Fetch-*``/``Accept-Language``
   matter to several tube front-ends).
2. :func:`fetch_text` — plain httpx first, then a **TLS-impersonating** retry
   through ``curl_cffi`` *when it is installed*. curl_cffi is a small optional
   dependency; without it the app simply behaves as it does today.
"""
from __future__ import annotations

import asyncio
import re
from functools import lru_cache

import httpx

from ..config import settings

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

_HTML_ACCEPT = ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8")
_FILE_ACCEPT = "*/*"

# "This request was answered by a bot wall, not by the site."
_BLOCK_MARKERS = re.compile(
    r"just a moment|attention required|cf-browser-verification|cf_chl_"
    r"|enable javascript and cookies to continue|checking your browser"
    r"|access denied|request blocked|unusual traffic|captcha-delivery"
    r"|ddos-guard|please verify you are a human",
    re.I)


def browser_headers(referer: str = "", *, accept: str = "") -> dict:
    """Headers a Chrome page navigation sends (Referer only when we have one)."""
    hdrs = {
        "User-Agent": UA,
        "Accept": accept or _HTML_ACCEPT,
        "Accept-Language": "en-US,en;q=0.9",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document" if not accept or accept == _HTML_ACCEPT else "empty",
        "Sec-Fetch-Mode": "navigate" if not accept or accept == _HTML_ACCEPT else "cors",
        "Sec-Fetch-Site": "same-origin" if referer else "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    if referer:
        hdrs["Referer"] = referer
        hdrs["Sec-Fetch-Site"] = "cross-site"
    return hdrs


def file_headers(referer: str = "") -> dict:
    """Headers for fetching an actual media file (CDNs, hotlink guards)."""
    hdrs = browser_headers(referer, accept=_FILE_ACCEPT)
    hdrs["Sec-Fetch-Dest"] = "video"
    hdrs["Sec-Fetch-Mode"] = "no-cors"
    hdrs["Range"] = "bytes=0-"
    return hdrs


@lru_cache(maxsize=1)
def has_impersonation() -> bool:
    """curl_cffi present? (Enables TLS-fingerprint retries for bot-walled hosts.)"""
    try:
        import curl_cffi  # noqa: F401
        from curl_cffi import requests as _r  # noqa: F401
        return True
    except Exception:  # noqa: BLE001 — optional dependency
        return False


def looks_blocked(text: str, status: int = 200) -> bool:
    """True when a response is a bot-wall/challenge rather than the real page."""
    if status in (401, 403, 429, 503):
        return True
    head = (text or "")[:6000]
    if not head:
        return status >= 400
    if _BLOCK_MARKERS.search(head):
        return True
    # Cloudflare's interstitial is tiny and carries no useful markup
    return status == 200 and len(head) < 900 and "<title>" not in head.lower()


def _proxy() -> str:
    return (settings.get("proxy") or "").strip()


def curl_get_text(url: str, headers: dict, referer: str = "",
                  proxy: str = "", timeout: float = 20.0) -> tuple[str, str, dict] | None:
    """Blocking curl_cffi GET with a real browser TLS fingerprint."""
    if not has_impersonation():
        return None
    try:
        from curl_cffi import requests as creq
    except Exception:  # noqa: BLE001
        return None
    px = proxy if proxy is not None else _proxy()
    proxies = {"http": px, "https": px} if px else None
    for target in ("chrome", "chrome124", "safari", "firefox"):
        try:
            r = creq.get(url, headers=headers, impersonate=target, timeout=timeout,
                         allow_redirects=True, proxies=proxies)
        except Exception:  # noqa: BLE001 — try the next profile
            continue
        text = r.text or ""
        if r.status_code < 400 and not _BLOCK_MARKERS.search(text[:6000]):
            return text, str(r.url), dict(r.headers)
        # a challenge answer: one more target may still get through
        if target == "firefox":
            return text, str(r.url), dict(r.headers)
    return None


async def fetch_text(url: str, *, referer: str = "", headers: dict | None = None,
                     proxy: str | None = None, timeout: float = 15.0,
                     allow_impersonate: bool = True) -> tuple[str, str, dict]:
    """GET a page like a browser. Returns ``(text, final_url, headers)``.

    Never raises for network trouble: an empty text means "we got nothing",
    which every caller already handles as "no candidates".
    """
    px = _proxy() if proxy is None else proxy
    hdrs = browser_headers(referer)
    if headers:
        hdrs.update(headers)
    text, final, rhdrs = "", url, {}
    try:
        async with httpx.AsyncClient(follow_redirects=True,
                                     timeout=httpx.Timeout(timeout, connect=min(8.0, timeout)),
                                     headers=hdrs,
                                     **({"proxy": px} if px else {})) as client:
            resp = await client.get(url)
            text = resp.text or ""
            final = str(resp.url)
            rhdrs = dict(resp.headers or {})
            if not looks_blocked(text, resp.status_code):
                return text, final, rhdrs
    except Exception:  # noqa: BLE001 — httpx raises a zoo of transport errors
        text = ""

    if allow_impersonate and has_impersonation():
        got = await asyncio.to_thread(curl_get_text, url, hdrs, referer, px, timeout)
        if got and got[0]:
            return got
    return text, final, rhdrs


async def fetch_manifest_text(url: str, *, referer: str = "", timeout: float = 20.0) -> str:
    """Manifest fetch with Referer + impersonation retry (raises on total failure)."""
    px = _proxy()
    hdrs = file_headers(referer)
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout,
                                     headers={"User-Agent": UA},
                                     **({"proxy": px} if px else {})) as client:
            r = await client.get(url, headers={"Range": "bytes=0-524287",
                                               **({"Referer": referer} if referer else {})})
            r.raise_for_status()
            return r.text
    except Exception as exc:  # noqa: BLE001
        if has_impersonation():
            got = await asyncio.to_thread(curl_get_text, url, hdrs, referer, px, timeout)
            if got and got[0]:
                return got[0]
        raise RuntimeError(f"Manifest unreachable: {str(exc)[:160]}") from exc
