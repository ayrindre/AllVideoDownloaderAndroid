"""WebFinder — Google-grade HTTP.

Google (web + Images) increasingly refuses plain `httpx` TLS fingerprints:
the request "succeeds" with a 200 consent/captcha shell and zero results.
`curl_cffi` spoofs Chrome's real TLS/H2 fingerprint (JA3) which flips most
of those walls. It is an OPTIONAL dependency — everything degrades to httpx
with the dual-UA attempt when curl_cffi is absent, so installs never break.
"""
from __future__ import annotations

try:  # optional — pip-installed in requirements, but never mandatory
    from curl_cffi.requests import AsyncSession  # type: ignore
    _HAS_CURL = True
except Exception:  # noqa: BLE001
    AsyncSession = None  # type: ignore
    _HAS_CURL = False

# Chrome-ish headers that pair with the impersonated fingerprint.
CHROME_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Site": "none",
}


def available() -> bool:
    return _HAS_CURL


async def google_get(url: str, params: dict | None = None, headers: dict | None = None,
                     cookies: dict | None = None, proxy: str = "", timeout: float = 16.0) -> tuple[int, str, str]:
    """GET via an impersonated browser session.

    Returns (status, text, final_url). Raises on transport failure so the
    caller's per-source error reporting stays honest.
    """
    if not _HAS_CURL:
        raise RuntimeError("curl-cffi unavailable")
    h = dict(CHROME_HEADERS)
    h.update(headers or {})
    async with AsyncSession(impersonate="chrome", proxy=proxy or None,
                            timeout=timeout, verify=False, cookies=cookies or None,
                            headers=h) as session:
        resp = await session.get(url, params=params, allow_redirects=True)
        return int(resp.status_code), resp.text or "", str(resp.url)
