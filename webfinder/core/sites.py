"""All Video Downloader — built-in site recipes.

A *recipe* is data, not code: a set of hostnames plus the **player family**
that site uses. The heavy lifting is generic (see :mod:`webfinder.core.embed`,
which pulls media URLs out of every known player-config shape), so adding a new
site is normally one line here — that is the point of this module.

    Recipe("xvideos", "XVideos", ("xvideos.com",), family="html5player")

Families
--------
``html5player``  ``html5player.setVideoUrlHigh/Low/HLS(...)``  — xvideos, xnxx…
``kt_player``    ``video_url`` / ``video_url_hd`` / ``video_alt_url`` (KT Player)
``jwplayer``     ``sources: [{file: ...}]`` / ``file: "..."``
``generic``      everything else: plain JSON, ``__NEXT_DATA__``, JSON-LD, <video>

The generic extractor runs for *every* page regardless of recipe, so an unknown
site is never a dead end — a recipe only adds the site's name, a family label
and (optionally) extra patterns for a URL shape the generic pass cannot see.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from . import embed


@dataclass(frozen=True)
class Recipe:
    key: str
    name: str
    domains: tuple[str, ...]
    family: str = "generic"
    note: str = ""
    patterns: tuple[str, ...] = field(default_factory=tuple)   # extra regexes (group 1 = url)


# ---------------------------------------------------------------------------
# Player families → label-carrying patterns
# ---------------------------------------------------------------------------
FAMILIES: dict[str, tuple[tuple[re.Pattern, str], ...]] = {
    "html5player": (
        (re.compile(r"setVideoUrlHigh\s*\(\s*['\"]([^'\"]{6,})", re.I), "High"),
        (re.compile(r"setVideoUrlLow\s*\(\s*['\"]([^'\"]{6,})", re.I), "Low"),
        (re.compile(r"setVideoHLS\s*\(\s*['\"]([^'\"]{6,})", re.I), "HLS"),
        (re.compile(r"setVideoUrl_flv\s*\(\s*['\"]([^'\"]{6,})", re.I), "FLV"),
        (re.compile(r"html5player\.setVideoUrl\w*\s*\(\s*['\"]([^'\"]{6,})", re.I), ""),
    ),
    "kt_player": (
        (re.compile(r"""video_url_hd\s*:\s*['"]([^'"]{6,})""", re.I), "HD"),
        (re.compile(r"""video_alt_url_hd\s*:\s*['"]([^'"]{6,})""", re.I), "Alt HD"),
        (re.compile(r"""video_url\s*:\s*['"]([^'"]{6,})""", re.I), "High"),
        (re.compile(r"""video_alt_url\s*:\s*['"]([^'"]{6,})""", re.I), "Alt"),
        (re.compile(r"""preview_url\s*:\s*['"]([^'"]{6,})""", re.I), "Preview"),
    ),
    "jwplayer": (
        (re.compile(r"""\bfile\s*:\s*['"]([^'"]{6,}?\.(?:mp4|m3u8|webm|mpd)[^'"]*)""", re.I), ""),
        (re.compile(r"""\bsrc\s*:\s*['"]([^'"]{6,}?\.(?:mp4|m3u8|webm|mpd)[^'"]*)""", re.I), ""),
    ),
    "generic": (),
}

# how a page announces its player, regardless of host
_FAMILY_MARKERS = (
    ("html5player", re.compile(r"html5player\s*\.\s*setVideoUrl", re.I)),
    ("kt_player", re.compile(r"video_url\s*:\s*['\"]", re.I)),
    ("jwplayer", re.compile(r"jwplayer\s*\(|sources\s*:\s*\[\s*\{", re.I)),
    ("videojs", re.compile(r"videojs\s*\(|class=[\"'][^\"']*video-js", re.I)),
    ("nextjs", re.compile(r"__NEXT_DATA__|__NUXT__|__NUXT_DATA__", re.I)),
    ("jsonld", re.compile(r'"@type"\s*:\s*"(?:VideoObject|Movie|Clip)"', re.I)),
)


def _r(key: str, name: str, domains: tuple[str, ...], family: str = "generic",
       note: str = "", patterns: tuple[str, ...] = ()) -> Recipe:
    return Recipe(key=key, name=name, domains=domains, family=family,
                  note=note, patterns=patterns)


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------
RECIPES: tuple[Recipe, ...] = (
    # ── tube sites: script-embedded mp4 ladders ────────────────────────────
    _r("xvideos", "XVideos", ("xvideos.com", "xvideos.es", "xvideos2.com"),
       "html5player", "html5player high/low ladder"),
    _r("xnxx", "XNXX", ("xnxx.com", "xnxx.health", "xnxx.tv"),
       "html5player", "html5player high/low ladder"),
    _r("xhamster", "xHamster", ("xhamster.com", "xhamster.desi", "xhamster.one",
                               "xhamster.xxx", "xhamster18.desi", "xhwebsite.com"),
       "html5player", "videoUrl / hlsUrl JSON"),
    _r("txxx", "TXXX", ("txxx.com", "txxx.xxx", "txxx.tube"), "kt_player"),
    _r("spankbang", "SpankBang", ("spankbang.com", "spankbang.party"), "generic",
       "stream_data JSON"),
    _r("pornhub", "Pornhub", ("pornhub.com", "pornhubpremium.com", "pornhub.org"),
       "kt_player", "mediaDefinition / HLS"),
    _r("redtube", "RedTube", ("redtube.com", "redtube.net"), "generic", "mediaDefinition JSON"),
    _r("youporn", "YouPorn", ("youporn.com", "youporngay.com"), "generic", "videoUrl / mediaDefinition"),
    _r("playvids", "PlayVids", ("playvids.com",), "generic"),
    _r("beeg", "Beeg", ("beeg.com", "beeg.porn"), "generic", "escaped JSON playlist"),
    _r("eporner", "Eporner", ("eporner.com",), "generic", "hash-based URL builder"),
    _r("hqporner", "HQPorner", ("hqporner.com", "hqporner.mobi"), "generic", "myfile.php mp4"),
    _r("porntrex", "PornTrex", ("porntrex.com", "porntrex.io"), "kt_player"),
    _r("motherless", "Motherless", ("motherless.com", "motherless.media"), "generic"),
    _r("thisvid", "ThisVid", ("thisvid.com",), "kt_player"),
    _r("thumbzilla", "Thumbzilla", ("thumbzilla.com",), "generic"),
    _r("tube8", "Tube8", ("tube8.com",), "kt_player"),
    _r("drtuber", "DrTuber", ("drtuber.com",), "kt_player"),
    _r("extremetube", "ExtremeTube", ("extremetube.com",), "kt_player"),
    _r("gotporn", "GotPorn", ("gotporn.com", "gotporn.net"), "kt_player"),
    _r("porntube", "PornTube", ("porntube.com",), "kt_player"),
    _r("hclips", "HClips", ("hclips.com",), "kt_player"),
    _r("tnaflix", "TNAFlix", ("tnaflix.com",), "kt_player"),
    _r("tubegalore", "TubeGalore", ("tubegalore.com",), "generic"),
    _r("pornone", "PornOne", ("pornone.com", "pornone.xxx"), "kt_player"),
    _r("hdsex", "HDsex", ("hdsex.org", "hdzog.com", "sunporno.com", "porn300.com"), "kt_player"),
    _r("sexvid", "SexVid", ("sexvid.xxx", "sexvid.porn"), "kt_player"),
    _r("okxxx", "OK.xxx", ("ok.xxx", "okxxx.com"), "kt_player"),
    _r("javhd", "JavHD", ("javhd.com", "javhdx.tv", "javbangers.com"), "kt_player"),
    _r("javmix", "JavMix", ("javmix.tv", "jav.guru", "javwhores.com"), "generic"),
    _r("missav", "MissAV", ("missav.com", "missav.ws", "missav.ai"), "generic", "m3u8 in JS"),
    _r("hanime", "Hanime", ("hanime.tv",), "generic", "HLS in __NEXT_DATA__"),
    _r("hentaihaven", "HentaiHaven", ("hentaihaven.xxx", "hentaihaven.com"), "generic"),
    _r("hanime_tv", "HentaiTv", ("hentaitv.com", "hentaigasm.com"), "generic"),
    _r("faphouse", "FapHouse", ("faphouse.com",), "generic", "HLS playlists"),
    _r("nhentai", "nHentai", ("nhentai.net",), "generic"),

    # ── mainstream platforms (yt-dlp has extractors; recipe = fallback) ────
    _r("youtube", "YouTube", ("youtube.com", "youtu.be", "youtube-nocookie.com"),
       "generic", "full format ladder via yt-dlp"),
    _r("vimeo", "Vimeo", ("vimeo.com", "player.vimeo.com"), "jsonld"),
    _r("dailymotion", "Dailymotion", ("dailymotion.com", "dai.ly"), "generic"),
    _r("okru", "OK.ru", ("ok.ru", "odnoklassniki.ru"), "generic"),
    _r("vk", "VK", ("vk.com", "vk.video", "vk.ru"), "generic"),
    _r("rumble", "Rumble", ("rumble.com",), "generic"),
    _r("bitchute", "BitChute", ("bitchute.com",), "generic"),
    _r("odysee", "Odysee", ("odysee.com", "lbry.tv"), "generic"),
    _r("streamable", "Streamable", ("streamable.com",), "generic"),
    _r("twitch", "Twitch", ("twitch.tv", "clips.twitch.tv"), "jsonld"),
    _r("kick", "Kick", ("kick.com",), "generic"),
    _r("twitter", "X / Twitter", ("twitter.com", "x.com", "t.co"), "generic"),
    _r("reddit", "Reddit", ("reddit.com", "redd.it", "v.redd.it"), "generic"),
    _r("imgur", "Imgur", ("imgur.com",), "generic"),
    _r("tiktok", "TikTok", ("tiktok.com",), "generic"),
    _r("instagram", "Instagram", ("instagram.com", "instagr.am"), "generic"),
    _r("facebook", "Facebook", ("facebook.com", "fb.watch", "fb.com"), "generic"),
    _r("snapchat", "Snapchat", ("snapchat.com",), "generic"),
    _r("coub", "Coub", ("coub.com",), "generic"),
    _r("veoh", "Veoh", ("veoh.com",), "generic"),
    _r("archive", "Internet Archive", ("archive.org",), "generic"),
    _r("soundcloud", "SoundCloud", ("soundcloud.com", "snd.sc"), "generic", "audio"),
    _r("bilibili", "Bilibili", ("bilibili.com", "b23.tv"), "generic"),
    _r("douyin", "Douyin", ("douyin.com", "iesdouyin.com"), "generic"),
    _r("youku", "Youku", ("youku.com",), "generic"),
    _r("iqiyi", "iQIYI", ("iqiyi.com",), "generic"),
    _r("weibo", "Weibo", ("weibo.com", "weibo.cn"), "generic"),
    _r("kuaishou", "Kuaishou", ("kuaishou.com", "gifshow.com"), "generic"),
    _r("xiaohongshu", "Xiaohongshu", ("xiaohongshu.com", "xhslink.com"), "generic"),
    _r("vidio", "Vidio", ("vidio.com",), "generic"),

    # ── Persian / regional ────────────────────────────────────────────────
    _r("aparat", "Aparat", ("aparat.com", "aparat.cam"), "generic", "HLS inside player JSON"),
    _r("namasha", "Namasha", ("namasha.com",), "generic"),
    _r("tamasha", "Tamasha", ("tamasha.com",), "generic"),
    _r("dideo", "Dideo", ("dideo.ir", "dideo.tv"), "generic"),
    _r("varzesh3", "Varzesh3", ("varzesh3.com",), "generic"),
    _r("telewebion", "Telewebion", ("telewebion.com",), "generic"),
    _r("filmnet", "FilmNet", ("filmnet.ir",), "generic"),
    _r("shad", "Shad", ("shad.ir",), "generic"),
)


_BY_DOMAIN: dict[str, Recipe] = {}
for _recipe in RECIPES:
    for _d in _recipe.domains:
        _BY_DOMAIN.setdefault(_d.lower(), _recipe)

_RECIPE_PATTERNS: dict[str, tuple[re.Pattern, ...]] = {
    r.key: tuple(re.compile(p, re.I) for p in r.patterns) for r in RECIPES if r.patterns
}


def host_of(url: str) -> str:
    try:
        host = (urlparse(url).netloc or "").lower().split("@")[-1].split(":")[0]
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def recipe_for(url: str) -> Recipe | None:
    """Recipe matching this URL's host (longest suffix wins), else ``None``."""
    host = host_of(url)
    if not host:
        return None
    if host in _BY_DOMAIN:
        return _BY_DOMAIN[host]
    parts = host.split(".")
    for i in range(1, len(parts) - 1):
        cand = ".".join(parts[i:])
        if cand in _BY_DOMAIN:
            return _BY_DOMAIN[cand]
    return None


def site_name(url: str) -> str:
    """Friendly site label: recipe name, else a title-cased host (IPs → '')."""
    r = recipe_for(url)
    if r:
        return r.name
    host = host_of(url)
    if not host or "." not in host or host.replace(".", "").isdigit():
        return ""                                  # localhost / bare host / IP
    parts = host.split(".")
    if len(parts) > 2 and parts[0] in ("www", "m", "mobile", "amp"):
        parts = parts[1:]
    return parts[0].replace("-", " ").replace("_", " ").title()


def detect_family(html: str) -> str:
    """Which player/config style does this page use? (for the UI badge)"""
    for name, pat in _FAMILY_MARKERS:
        if pat.search(html or ""):
            return name
    return ""


def candidates(html: str, url: str, *, limit: int = 48) -> list[dict]:
    """Every media candidate this page exposes, recipes + generic extraction."""
    recipe = recipe_for(url)
    out: dict[str, dict] = {}

    def add(item: dict | None) -> None:
        if not item:
            return
        old = out.get(item["url"])
        if old is None or item.get("score", 0) > old.get("score", 0):
            out[item["url"]] = item

    # 1) generic scan of the (de-escaped) document — covers every player style
    for c in embed.extract(html, url, limit=limit * 2, origin="recipe" if recipe else "embed"):
        add(c)

    # 2) family patterns (they carry the human label: High/Low/HD/HLS).
    #    An UNKNOWN host still gets a family when the page announces its player —
    #    that is why an unlisted tube site works without a recipe.
    norm = embed.normalize(html)
    fam_key = recipe.family if recipe else ""
    if fam_key in ("", "generic"):
        detected = detect_family(html)
        if detected in FAMILIES:
            fam_key = detected
    fam = FAMILIES.get(fam_key or "generic", ())
    extra_pats = _RECIPE_PATTERNS.get(recipe.key, ()) if recipe else ()
    for pat, label in fam:
        for m in pat.finditer(norm):
            c = embed.candidate(m.group(1), url, "recipe", label)
            if c:
                c["score"] += 6          # a named player slot beats a random URL
                add(c)
    for pat in extra_pats:
        for m in pat.finditer(norm):
            add(embed.candidate(m.group(1), url, "recipe"))

    items = sorted(out.values(), key=lambda c: -c.get("score", 0))[:limit]
    name = recipe.name if recipe else ""
    for c in items:
        c["site"] = name
        c["recipe"] = recipe.key if recipe else ""
    return items


def catalog() -> list[dict]:
    """Public list for the UI/API: what the app knows about out of the box."""
    return [{"key": r.key, "name": r.name, "domains": list(r.domains),
             "family": r.family, "note": r.note} for r in RECIPES]
