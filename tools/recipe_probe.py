#!/usr/bin/env python3
"""All Video Downloader — recipe probe (debug a site in one command).

Shows exactly what the engine sees for a URL:

  * which built-in recipe matched (site name + player family), or "generic"
  * whether TLS impersonation (curl_cffi) is available for bot walls
  * every media candidate the page exposes, ranked, with the quality label
  * optionally the full analyzer verdict (`--analyze`), i.e. the card the UI
    would render

Usage
-----
    python tools/recipe_probe.py https://www.xvideos.com/video12345/title
    python tools/recipe_probe.py https://site.example/watch/1 --analyze
    python tools/recipe_probe.py page.html --file           # saved HTML, no network
    python tools/recipe_probe.py https://site.example/x --json

Adding a site is one line in ``webfinder/core/sites.py`` — run this first to see
which family it uses (html5player, kt_player, jwplayer or plain generic JSON).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from webfinder.core import adapters, embed, net, sites  # noqa: E402


async def _load(url: str, from_file: bool, base: str) -> tuple[str, str]:
    if from_file:
        p = Path(url)
        text = p.read_text(encoding="utf-8", errors="ignore")
        # a saved page still needs an http(s) base for relative URLs / recipes
        return text, (base or "https://example.invalid/")
    text, final, _hdrs = await net.fetch_text(url, timeout=30.0)
    return text, (base or final)


def main() -> int:
    ap = argparse.ArgumentParser(description="Show what the All Video Downloader engine sees for a URL.")
    ap.add_argument("url", help="page URL (or a local .html file with --file)")
    ap.add_argument("--file", action="store_true", help="treat the argument as a saved HTML file")
    ap.add_argument("--analyze", action="store_true", help="also run the full analyzer (network + yt-dlp)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--base", default="", help="base URL for relative links / recipe matching "
                                              "(useful with --file: --base https://www.xvideos.com/)")
    ap.add_argument("--limit", type=int, default=24)
    args = ap.parse_args()

    text, base = asyncio.run(_load(args.url, args.file, args.base))
    if not text:
        print("✗ nothing came back — the host refused, timed out, or the page is empty.")
        if not net.has_impersonation():
            print("  hint: pip install curl_cffi retries bot-walled pages with a Chrome TLS fingerprint.")
        return 2

    recipe = sites.recipe_for(base)
    family = sites.detect_family(text)
    adapter_hit = adapters.for_url(base)
    meta = embed.page_meta(text, base)
    cands = sites.candidates(text, base, limit=args.limit)

    report = {
        "url": base,
        "site": recipe.name if recipe else "",
        "recipe": recipe.key if recipe else "",
        "adapter": adapter_hit[0].key if adapter_hit else "",
        "embed_host": sites.embed_host_for(base),
        "player_family": family or (recipe.family if recipe else "generic"),
        "title": meta["title"],
        "thumbnail": meta["thumbnail"],
        "tls_impersonation": net.has_impersonation(),
        "candidates": [{k: c.get(k) for k in ("url", "quality", "height", "ext", "source", "score")}
                       for c in cands],
    }

    if args.analyze and not args.file:
        from webfinder.core import media
        try:
            card = asyncio.run(media.analyze(base))
        except Exception as exc:  # noqa: BLE001
            card = {"error": str(exc)[:300]}
        report["analyze"] = {
            "kind": card.get("kind"),
            "title": card.get("title"),
            "site": card.get("site"),
            "referer": card.get("referer"),
            "formats": [{k: f.get(k) for k in ("label", "height", "ext", "url")}
                        for f in card.get("formats") or []],
            "access_note": card.get("access_note"),
            "adapter": card.get("adapter"),
            "recovered_after_block": card.get("recovered_after_block"),
            "upgraded_from_extractor": card.get("upgraded_from_extractor"),
            "error": card.get("error"),
        }

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0

    print(f"URL        {report['url']}")
    print(f"Site       {report['site'] or '— (not in the recipe list; generic engine)'}")
    print(f"Recipe     {report['recipe'] or '—'}")
    if report["adapter"]:
        print(f"Adapter    {report['adapter']} (site API — resolved before yt-dlp)")
    if report["embed_host"]:
        print(f"Embed      {report['embed_host']} player")
    print(f"Player     {report['player_family'] or 'unknown'}")
    print(f"Title      {report['title'] or '—'}")
    print(f"Impersonate{'yes (curl_cffi)' if report['tls_impersonation'] else 'no  (pip install curl_cffi)'}")
    print(f"Candidates {len(cands)}")
    for c in cands:
        q = f"{c.get('quality') or '?':>10}  " if c.get("quality") else " " * 12
        print(f"  {c.get('score', 0):>4}  {q}{c.get('ext') or '?':<5} {c['url']}")
    if not cands:
        print("  (no media URL in the document — the player is fully scripted; "
              "check DevTools → Network for an .m3u8/.mp4 XHR)")

    if "analyze" in report:
        a = report["analyze"]
        print("\nAnalyzer verdict")
        print(f"  kind     {a.get('kind')}")
        if a.get("title"):
            print(f"  title    {a['title']}")
        for f in a.get("formats") or []:
            print(f"  chip     {f.get('label') or f.get('height')}  {f.get('url')}")
        for key in ("access_note", "recovered_after_block", "upgraded_from_extractor",
                    "error"):
            if a.get(key):
                print(f"  {key:23} {a[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
