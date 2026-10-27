"""All Video Downloader — built-in site recipes.

A *recipe* is data, not code: a set of hostnames plus the **player family**
that site uses. The heavy lifting is generic (see :mod:`webfinder.core.embed`,
which pulls media URLs out of every known player-config shape), so adding a new
site is normally one line here — that is the point of this module.

    Recipe("xvideos", "XVideos", ("xvideos.com",), family="html5player")

A recipe may also name an **adapter** (:mod:`webfinder.core.adapters`) for the
rare site whose page is an empty JavaScript shell and whose stream only exists
behind a JSON endpoint (Aparat, Filimo)::

    _r("aparat", "Aparat", ("aparat.com", "aparat.cam"), "generic", adapter="aparat")

Families
--------
``html5player``  ``html5player.setVideoUrlHigh/Low/HLS(...)``  — xvideos, xnxx…
``kt_player``    ``video_url`` / ``video_url_hd`` / ``video_alt_url`` (KVS)
``jwplayer``     ``sources: [{file: ...}]`` / ``file: "..."`` / playlists
``videojs``      ``player.src({src: ...})`` / ``sources: [{src: ...}]``
``plyr``         ``source: {src: ..., type: ...}``
``clappr``       ``source: "..."`` / ``playback: {hls: ...}``
``flowplayer``   ``clip: {sources: [...]}``
``dplayer``      ``video: {url: ...}``
``shaka``        ``manifestUri: "..."``
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
    adapter: str = ""                                          # API bridge (see core/adapters.py)


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
    # Kernel Video Sharing — the player behind most "tube" scripts
    "kt_player": (
        (re.compile(r"""video_alt_url3\s*:\s*['"]([^'"]{6,})""", re.I), "Alt 3"),
        (re.compile(r"""video_alt_url2\s*:\s*['"]([^'"]{6,})""", re.I), "Alt 2"),
        (re.compile(r"""video_url_hd\s*:\s*['"]([^'"]{6,})""", re.I), "HD"),
        (re.compile(r"""video_alt_url_hd\s*:\s*['"]([^'"]{6,})""", re.I), "Alt HD"),
        (re.compile(r"""video_url\s*:\s*['"]([^'"]{6,})""", re.I), "High"),
        (re.compile(r"""video_alt_url\s*:\s*['"]([^'"]{6,})""", re.I), "Alt"),
        (re.compile(r"""preview_url\s*:\s*['"]([^'"]{6,})""", re.I), "Preview"),
    ),
    "jwplayer": (
        (re.compile(r"""\bfile\s*:\s*['"]([^'"]{6,}?\.(?:mp4|m3u8|webm|mpd)[^'"]*)""", re.I), ""),
        (re.compile(r"""\bsrc\s*:\s*['"]([^'"]{6,}?\.(?:mp4|m3u8|webm|mpd)[^'"]*)""", re.I), ""),
        (re.compile(r"""["']file["']\s*:\s*["']([^"']{6,})""", re.I), ""),
    ),
    "videojs": (
        (re.compile(r"""\bsrc\s*:\s*['"]([^'"]{6,})['"]\s*,\s*type\s*:\s*['"]video/""", re.I), ""),
        (re.compile(r"""\bsrc\s*:\s*['"]([^'"]{6,})['"]\s*,\s*type\s*:\s*['"]application/(?:x-mpegurl|dash\+xml)""", re.I), "HLS"),
        (re.compile(r"""type\s*:\s*['"]application/(?:x-mpegurl|dash\+xml)['"]\s*,\s*src\s*:\s*['"]([^'"]{6,})""", re.I), "HLS"),
        (re.compile(r"""(?:player\.)?src\s*\(\s*\{?[^}]{0,120}?['"]?src['"]?\s*:\s*['"]([^'"]{6,})""", re.I), ""),
        (re.compile(r"""sources\s*:\s*\[\s*\{[^}]{0,160}?src\s*:\s*['"]([^'"]{6,})""", re.I), ""),
    ),
    "plyr": (
        (re.compile(r"""source\s*:\s*\{[^}]{0,160}?src\s*:\s*['"]([^'"]{6,})""", re.I), ""),
    ),
    "clappr": (
        (re.compile(r"""source\s*:\s*['"]([^'"]{6,}?\.(?:mp4|m3u8|mpd)[^'"]*)""", re.I), ""),
        (re.compile(r"""playback\s*:\s*\{[^}]{0,120}?(?:hls|dash|mp4)\s*:\s*['"]([^'"]{6,})""", re.I), "HLS"),
    ),
    "flowplayer": (
        (re.compile(r"""clip\s*:\s*\{[^}]{0,400}?sources\s*:\s*\[[^\]]{0,400}?src\s*:\s*['"]([^'"]{6,})""", re.I), ""),
        (re.compile(r"""m3u8\s*:\s*['"]([^'"]{6,})""", re.I), "HLS"),
    ),
    "dplayer": (
        (re.compile(r"""video\s*:\s*\{[^}]{0,200}?url\s*:\s*['"]([^'"]{6,})""", re.I), ""),
    ),
    "shaka": (
        (re.compile(r"""manifestUri\s*:\s*['"]([^'"]{6,})""", re.I), "DASH"),
        (re.compile(r"""src\s*=\s*['"]([^'"]{6,}?\.mpd[^'"]*)['"]""", re.I), "DASH"),
    ),
    "generic": (),
}

# how a page announces its player, regardless of host
_FAMILY_MARKERS = (
    ("html5player", re.compile(r"html5player\s*\.\s*setVideoUrl", re.I)),
    ("kt_player", re.compile(r"video_url\s*:\s*['\"]|kt_player\s*\(", re.I)),
    ("jwplayer", re.compile(r"jwplayer\s*\(|sources\s*:\s*\[\s*\{\s*file", re.I)),
    ("videojs", re.compile(r"videojs\s*\(|class=[\"'][^\"']*video-js|player\.src\s*\(\s*\{", re.I)),
    ("plyr", re.compile(r"new\s+Plyr\s*\(|plyr\.setup", re.I)),
    ("clappr", re.compile(r"new\s+Clappr\s*\.\s*Player", re.I)),
    ("flowplayer", re.compile(r"flowplayer\s*\(|flowplayer\s*\.\s*setup", re.I)),
    ("dplayer", re.compile(r"new\s+DPlayer\s*\(", re.I)),
    ("shaka", re.compile(r"shaka\s*\.\s*Player|manifestUri\s*:", re.I)),
    ("kvs", re.compile(r"license_code|/get_file/|flashvars\s*=", re.I)),
    ("nextjs", re.compile(r"__NEXT_DATA__|__NUXT__|__NUXT_DATA__|__INITIAL_STATE__", re.I)),
    ("jsonld", re.compile(r'"@type"\s*:\s*"(?:VideoObject|Movie|Clip)"', re.I)),
)

# ---------------------------------------------------------------------------
# Cross-origin players: an <iframe> pointing at one of these IS the video
# ---------------------------------------------------------------------------
# (regex on the iframe src, player/site label). The scanner records them as
# "embed" candidates even when the URL contains no "video/player/embed" word,
# and the analyzer hops into them — which is how file-host pages resolve.
EMBED_HOSTS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"youtube(?:-nocookie)?\.com/(?:embed|v)/|youtu\.be/|youtube\.com/watch", re.I), "YouTube"),
    (re.compile(r"player\.vimeo\.com/|vimeo\.com/\d+", re.I), "Vimeo"),
    (re.compile(r"dailymotion\.com/(?:embed|video)/|dai\.ly/", re.I), "Dailymotion"),
    (re.compile(r"(?:^|//)(?:www\.)?ok\.ru/(?:videoembed|video)/", re.I), "OK.ru"),
    (re.compile(r"vk\.com/video_ext|vkvideo\.ru/video_ext", re.I), "VK"),
    (re.compile(r"rutube\.ru/(?:play/embed|video)/", re.I), "Rutube"),
    (re.compile(r"(?:player\.)?twitch\.tv/(?:\?|videos/|clip)", re.I), "Twitch"),
    (re.compile(r"kick\.com/[^/]+/?(?:\?|clips)|player\.kick\.com", re.I), "Kick"),
    (re.compile(r"streamable\.com/(?:e|o)/", re.I), "Streamable"),
    (re.compile(r"rumble\.com/embed/", re.I), "Rumble"),
    (re.compile(r"bitchute\.com/embed/", re.I), "BitChute"),
    (re.compile(r"odysee\.com/\$/embed|lbry\.tv/\$/embed", re.I), "Odysee"),
    (re.compile(r"facebook\.com/plugins/video|fb\.watch/", re.I), "Facebook"),
    (re.compile(r"instagram\.com/(?:p|reel|tv)/", re.I), "Instagram"),
    (re.compile(r"tiktok\.com/(?:embed|player)/", re.I), "TikTok"),
    (re.compile(r"bilibili\.com/(?:player|blackboard)", re.I), "Bilibili"),
    (re.compile(r"aparat\.com/video/video/embed|aparat\.com/embed/", re.I), "Aparat"),
    (re.compile(r"filimo\.com/(?:movie|embed)", re.I), "Filimo"),
    (re.compile(r"(?:streamtape|tapecontent)\.(?:com|net)/e/", re.I), "StreamTape"),
    (re.compile(r"dood\.(?:so|watch|sh|pm|la|to)/e/|doodstream\.com/e/|dood\.[a-z]+/e/", re.I), "DoodStream"),
    (re.compile(r"mixdrop\.(?:co|to|ch|sx|vc|ag|bz|ps|wf|re|moe|club|icu|bio|fr|si|nz|is|day)/e/", re.I), "MixDrop"),
    (re.compile(r"filemoon\.(?:sx|to|in|nl|sk|com)/[ed]/", re.I), "FileMoon"),
    (re.compile(r"(?:streamwish|strwish|wishembed|wishfast)\.(?:to|com|top|site|xyz|info|fun|online|store|cc|vip|icu|biz)/[ed]/", re.I), "StreamWish"),
    (re.compile(r"(?:streamhide|guccihide|moviesm4u|streamhls|ahvsh|livesteam)\.(?:com|to|at|xyz|site|info|fun|online|pro|vip|cc|icu|biz)/[ed]/", re.I), "StreamHide"),
    (re.compile(r"voe\.sx/e/|voe\.sx/embed|voe\.sx/v/", re.I), "VOE"),
    (re.compile(r"vidmoly\.(?:to|me|net|tv)/[edw]/", re.I), "Vidmoly"),
    (re.compile(r"mp4upload\.com/(?:embed-|e/)", re.I), "MP4Upload"),
    (re.compile(r"sendvid\.com/embed/", re.I), "SendVid"),
    (re.compile(r"sibnet\.ru/(?:shell|video)/", re.I), "Sibnet"),
    (re.compile(r"vidsrc\.(?:to|xyz|me|cc|in|net)/embed|vsrc\.(?:to|xyz|sx)/embed", re.I), "VidSrc"),
    (re.compile(r"2embed\.(?:cc|to|sbs|tv)/embed|2embed\.ru/embed", re.I), "2Embed"),
    (re.compile(r"embed\.su/embed|embed\.sii|smashystream\.(?:com|xyz)/embed|autoembed\.(?:cc|co)/embed|superembed\.(?:stream|com)/", re.I), "Embed"),
    (re.compile(r"multiembed\.movie/video|multiembed\.(?:movie|com)/", re.I), "MultiEmbed"),
    (re.compile(r"vidlink\.(?:pro|pics)/|vidfast\.(?:pro|net|in)/|vidbinge\.(?:com|to|app)/"
                r"|videasy\.(?:net|to)/|vidora\.(?:stream|su)/|111movies\.com/|nepu\.to/", re.I), "VidLink"),
    (re.compile(r"vidsrc\.(?:icu|vip|pro|win|dev)/embed|vsembed\.ru/embed", re.I), "Vidsrc mirror"),
    (re.compile(r"upstream\.to/(?:e/|embed)|upstream\.to/[a-z0-9]{6,}", re.I), "UpStream"),
    (re.compile(r"(?:hxfile|luluvdo|lulustream|kotstream|kinoger|vidhide|vidspeeds|faststream|smoothpre|cloudhls|vudeo|vidoza|streamsb|sbplay\d*|sbfull|embedsb)\.", re.I), "FileHost"),
    (re.compile(r"(?:gdrive|drive\.google\.com/file|docs\.google\.com/file)/", re.I), "Google Drive"),
    (re.compile(r"player\.wistia\.(?:com|net)|fast\.wistia\.(?:com|net)", re.I), "Wistia"),
    (re.compile(r"play\.vidyard\.com|share\.vidyard\.com", re.I), "Vidyard"),
    (re.compile(r"loom\.com/(?:embed|share)/", re.I), "Loom"),
    (re.compile(r"archive\.org/embed/", re.I), "Internet Archive"),
    (re.compile(r"soundcloud\.com/player|w\.soundcloud\.com/player", re.I), "SoundCloud"),
    (re.compile(r"banned\.video|pornhub\.com/embed|redtube\.com/embed|youporn\.com/embed|xvideos\.com/embed|xhamster\.com/embed|xnxx\.com/embed", re.I), "Tube embed"),
)


def _r(key: str, name: str, domains: tuple[str, ...], family: str = "generic",
       note: str = "", patterns: tuple[str, ...] = (), adapter: str = "") -> Recipe:
    return Recipe(key=key, name=name, domains=domains, family=family,
                  note=note, patterns=patterns, adapter=adapter)


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------
RECIPES: tuple[Recipe, ...] = (
    # ── tube sites: script-embedded mp4 ladders ────────────────────────────
    _r("xvideos", "XVideos", ("xvideos.com", "xvideos.es", "xvideos2.com", "xvideos-ar.com"),
       "html5player", "html5player high/low ladder"),
    _r("xnxx", "XNXX", ("xnxx.com", "xnxx.health", "xnxx.tv", "xnxx1.com", "xnxx2.com"),
       "html5player", "html5player high/low ladder"),
    _r("xhamster", "xHamster", ("xhamster.com", "xhamster.desi", "xhamster.one",
                               "xhamster.xxx", "xhamster18.desi", "xhamster2.com",
                               "xhamster3.com", "xhwebsite.com", "xhopen.com"),
       "html5player", "videoUrl / hlsUrl JSON"),
    _r("txxx", "TXXX", ("txxx.com", "txxx.xxx", "txxx.tube", "txxxporn.tube"), "kt_player", "KVS flashvars"),
    _r("spankbang", "SpankBang", ("spankbang.com", "spankbang.party", "spankbang.porn"),
       "generic", "stream_data JSON"),
    _r("pornhub", "Pornhub", ("pornhub.com", "pornhubpremium.com", "pornhub.org", "pornhub.net"),
       "generic", "mediaDefinitions / HLS"),
    _r("redtube", "RedTube", ("redtube.com", "redtube.net", "redtube.xxx"), "generic", "mediaDefinitions JSON"),
    _r("youporn", "YouPorn", ("youporn.com", "youporngay.com", "youporn.xxx"),
       "generic", "videoUrl / mediaDefinitions"),
    _r("tube8", "Tube8", ("tube8.com", "tube8.fr", "tube8.es"), "generic", "mediaDefinitions JSON"),
    _r("playvids", "PlayVids", ("playvids.com", "playvids.xxx"), "generic"),
    _r("beeg", "Beeg", ("beeg.com", "beeg.porn", "beeg.xxx"), "generic", "escaped JSON playlist"),
    _r("eporner", "Eporner", ("eporner.com",), "generic", "hash-based URL builder"),
    _r("hqporner", "HQPorner", ("hqporner.com", "hqporner.mobi", "hqporner.xxx"),
       "generic", "myfile.php mp4"),
    _r("porntrex", "PornTrex", ("porntrex.com", "porntrex.io"), "kt_player", "KVS flashvars"),
    _r("motherless", "Motherless", ("motherless.com", "motherless.media", "motherless.net"), "generic"),
    _r("thisvid", "ThisVid", ("thisvid.com", "thisvid.xxx"), "kt_player", "KVS flashvars"),
    _r("thumbzilla", "Thumbzilla", ("thumbzilla.com", "thumbzilla.xxx"), "generic"),
    _r("drtuber", "DrTuber", ("drtuber.com", "drtuber.xxx"), "kt_player", "KVS flashvars"),
    _r("extremetube", "ExtremeTube", ("extremetube.com",), "kt_player", "KVS flashvars"),
    _r("gotporn", "GotPorn", ("gotporn.com", "gotporn.net"), "kt_player", "KVS flashvars"),
    _r("porntube", "PornTube", ("porntube.com", "porntube.xxx"), "generic"),
    _r("hclips", "HClips", ("hclips.com", "hclips.xxx"), "kt_player", "KVS flashvars"),
    _r("tnaflix", "TNAFlix", ("tnaflix.com", "tnaflix.xxx"), "kt_player", "KVS flashvars"),
    _r("tubegalore", "TubeGalore", ("tubegalore.com", "tubegalore.xxx"), "generic"),
    _r("pornone", "PornOne", ("pornone.com", "pornone.xxx", "pornone.expert"), "kt_player", "KVS flashvars"),
    _r("hdsex", "HDsex", ("hdsex.org", "hdzog.com", "sunporno.com", "porn300.com",
                          "anysex.com", "porn300.net"), "kt_player", "KVS flashvars"),
    _r("sexvid", "SexVid", ("sexvid.xxx", "sexvid.porn", "sexvid.pro"), "kt_player", "KVS flashvars"),
    _r("okxxx", "OK.xxx", ("ok.xxx", "okxxx.com", "okxxx1.com"), "kt_player", "KVS flashvars"),
    _r("javhd", "JavHD", ("javhd.com", "javhdx.tv", "javbangers.com", "javhd.today"), "kt_player"),
    _r("javmix", "JavMix", ("javmix.tv", "jav.guru", "javwhores.com", "javdoe.com",
                            "javdoe.sh", "vjav.com", "vjav.tube"), "kt_player", "KVS flashvars"),
    _r("missav", "MissAV", ("missav.com", "missav.ws", "missav.ai", "missav.live"), "generic", "m3u8 in JS"),
    _r("hanime", "Hanime", ("hanime.tv",), "generic", "HLS in __NEXT_DATA__"),
    _r("hentaihaven", "HentaiHaven", ("hentaihaven.xxx", "hentaihaven.com", "hhaven.com"), "generic"),
    _r("hanime_tv", "HentaiTv", ("hentaitv.com", "hentaigasm.com", "hentaicity.com",
                                 "hentaimama.io", "9hentai.com"), "generic"),
    _r("faphouse", "FapHouse", ("faphouse.com", "faphouse.tv"), "generic", "HLS playlists"),
    _r("nhentai", "nHentai", ("nhentai.net",), "generic"),
    _r("1porn", "1Porn", ("1porn.tv", "1porn.com"), "kt_player", "KVS flashvars + get_file download"),
    _r("4tube", "4Tube", ("4tube.com",), "generic", "player JSON"),
    _r("alohatube", "AlohaTube", ("alohatube.com",), "generic"),
    _r("analdin", "Analdin", ("analdin.com",), "kt_player", "KVS flashvars"),
    _r("ashemaletube", "AShemaleTube", ("ashemaletube.com", "ashemaletv.com"), "generic"),
    _r("avgle", "AVGL", ("avgle.com",), "generic", "HLS in JSON"),
    _r("boyfriendtv", "BoyFriendTV", ("boyfriendtv.com",), "kt_player", "KVS flashvars"),
    _r("camwhores", "CamWhores", ("camwhores.tv", "camwhoresbay.com", "camwhores.video"), "kt_player"),
    _r("chaturbate", "Chaturbate", ("chaturbate.com", "chaturbate.eu"), "generic", "live HLS"),
    _r("cliphunter", "ClipHunter", ("cliphunter.com",), "generic"),
    _r("definebabe", "DefineBabe", ("definebabe.com",), "generic"),
    _r("erome", "EroMe", ("erome.com", "erome.xxx"), "generic"),
    _r("flyflv", "FlyFlv", ("flyflv.com",), "generic"),
    _r("freeporn", "FreePorn", ("freeporn.com", "freeporn.xxx"), "kt_player", "KVS flashvars"),
    _r("fullporner", "FullPorner", ("fullporner.com",), "generic"),
    _r("gaytube", "GayTube", ("gaytube.com", "gaytubenetwork.com"), "kt_player"),
    _r("hamstertube", "HamsterTube", ("hamstertube.com",), "generic"),
    _r("hitomi", "Hitomi", ("hitomi.la",), "generic"),
    _r("iceporn", "IcePorn", ("iceporn.com", "iceporn.xxx"), "generic"),
    _r("josporn", "JosPorn", ("josporn.com",), "generic"),
    _r("justporno", "JustPorno", ("justporno.tv", "justporno.sex"), "generic"),
    _r("kissjav", "KissJAV", ("kissjav.com", "kissjav.li"), "generic"),
    _r("letsjerk", "LetsJerk", ("letsjerk.is", "letsjerk.com"), "generic"),
    _r("luxuretv", "LuxureTV", ("luxuretv.com",), "generic"),
    _r("megatube", "MegaTube", ("megatube.xxx",), "kt_player"),
    _r("mydirtyhobby", "MyDirtyHobby", ("mydirtyhobby.com", "mydirtyhobby.de"), "generic"),
    _r("netfapx", "NetFapX", ("netfapx.com", "netfapx.net"), "generic"),
    _r("nuvid", "NuVid", ("nuvid.com",), "generic"),
    _r("perfectgirls", "PerfectGirls", ("perfectgirls.net", "perfectgirls.xxx"), "kt_player"),
    _r("porn", "Porn.com", ("porn.com",), "generic", "mediaDefinitions JSON"),
    _r("pornhat", "PornHat", ("pornhat.com", "pornhat.xxx"), "generic"),
    _r("pornhd", "PornHD", ("pornhd.com", "pornhd3x.tv", "pornhd.xxx"), "kt_player"),
    _r("pornid", "PornID", ("pornid.xxx", "pornid.com"), "kt_player"),
    _r("pornoxo", "PornoXO", ("pornoxo.com",), "generic"),
    _r("pornzog", "PornZog", ("pornzog.com",), "generic"),
    _r("rule34video", "Rule34Video", ("rule34video.com", "rule34video.ru"), "generic"),
    _r("sex", "Sex.com", ("sex.com",), "generic", "HLS playlists"),
    _r("sex3", "Sex3", ("sex3.com",), "kt_player"),
    _r("sextb", "SexTB", ("sextb.net", "sextb.com"), "generic"),
    _r("sexu", "Sexu", ("sexu.com",), "kt_player"),
    _r("tokyomotion", "TokyoMotion", ("tokyomotion.net", "tokyomotion.com"), "generic"),
    _r("tubepornclassic", "TubePornClassic", ("tubepornclassic.com",), "kt_player"),
    _r("upornia", "Upornia", ("upornia.com",), "kt_player"),
    _r("wankoz", "Wankoz", ("wankoz.com",), "generic"),
    _r("xcafe", "XCafe", ("xcafe.com",), "kt_player"),
    _r("xozilla", "Xozilla", ("xozilla.com", "xozilla.xxx"), "kt_player"),
    _r("xpee", "XPee", ("xpee.com", "xpee.video"), "kt_player"),
    _r("xpornz", "XPornZ", ("xpornz.com",), "generic"),
    _r("xxxbunker", "XXXBunker", ("xxxbunker.com",), "generic"),
    _r("yespornplease", "YesPornPlease", ("yespornplease.com", "yespornplease.sex"), "generic"),
    _r("youjizz", "YouJizz", ("youjizz.com", "youjizz.xxx"), "generic", "VPAID / HLS"),
    _r("pornflip", "PornFlip", ("pornflip.com",), "generic"),
    _r("hqcollect", "HQCollect", ("hqcollect.me",), "kt_player"),
    _r("porndig", "PornDig", ("porndig.com",), "generic"),
    _r("pornbay", "PornBay", ("pornbay.xxx",), "kt_player"),
    _r("anyporn", "AnyPorn", ("anyporn.com",), "kt_player", "KVS flashvars"),
    _r("brazzers", "Brazzers", ("brazzers.com", "brazzersnetwork.com"), "generic", "login required"),
    _r("realitykings", "RealityKings", ("realitykings.com",), "generic", "login required"),
    _r("bangbros", "BangBros", ("bangbros.com",), "generic", "login required"),
    _r("naughtyamerica", "NaughtyAmerica", ("naughtyamerica.com",), "generic", "login required"),
    _r("teamskeet", "TeamSkeet", ("teamskeet.com",), "generic", "login required"),
    _r("onlyfans", "OnlyFans", ("onlyfans.com",), "generic", "login required"),
    _r("fansly", "Fansly", ("fansly.com",), "generic", "login required"),
    _r("manyvids", "ManyVids", ("manyvids.com",), "generic", "login required"),
    _r("clips4sale", "Clips4Sale", ("clips4sale.com",), "generic", "login required"),
    _r("modelhub", "Modelhub", ("modelhub.com",), "generic"),

    # ── mainstream platforms (yt-dlp has extractors; recipe = fallback) ────
    _r("youtube", "YouTube", ("youtube.com", "youtu.be", "youtube-nocookie.com",
                              "m.youtube.com", "music.youtube.com"),
       "generic", "full format ladder via yt-dlp"),
    _r("vimeo", "Vimeo", ("vimeo.com", "player.vimeo.com", "vimeo.tv"), "jsonld"),
    _r("dailymotion", "Dailymotion", ("dailymotion.com", "dai.ly", "dailymotion.tv"), "generic"),
    _r("okru", "OK.ru", ("ok.ru", "odnoklassniki.ru", "okvideo.ru"), "generic"),
    _r("vk", "VK", ("vk.com", "vk.video", "vk.ru", "vkvideo.ru", "m.vk.com"), "generic"),
    _r("mailru", "Mail.ru Video", ("my.mail.ru", "mail.ru", "video.mail.ru"), "generic"),
    _r("rutube", "Rutube", ("rutube.ru",), "generic"),
    _r("yandex", "Yandex Video", ("yandex.ru", "yandex.com", "ya.ru"), "generic"),
    _r("smotri", "Smotri", ("smotri.com", "smotri.net"), "generic"),
    _r("sibnet", "Sibnet", ("sibnet.ru", "video.sibnet.ru"), "generic"),
    _r("videa", "Videa", ("videa.hu",), "generic"),
    _r("indavideo", "Indavideo", ("indavideo.hu",), "generic"),
    _r("rumble", "Rumble", ("rumble.com",), "generic"),
    _r("bitchute", "BitChute", ("bitchute.com",), "generic"),
    _r("brighteon", "Brighteon", ("brighteon.com",), "generic"),
    _r("gab", "Gab", ("gab.com", "gab.ai"), "generic"),
    _r("odysee", "Odysee", ("odysee.com", "lbry.tv", "lbry.com"), "generic"),
    _r("streamable", "Streamable", ("streamable.com",), "generic"),
    _r("twitch", "Twitch", ("twitch.tv", "clips.twitch.tv", "player.twitch.tv"), "jsonld"),
    _r("kick", "Kick", ("kick.com", "player.kick.com"), "generic"),
    _r("trovo", "Trovo", ("trovo.live",), "generic"),
    _r("nimo", "Nimo TV", ("nimo.tv",), "generic"),
    _r("twitter", "X / Twitter", ("twitter.com", "x.com", "t.co"), "generic"),
    _r("reddit", "Reddit", ("reddit.com", "redd.it", "v.redd.it", "redditmedia.com"), "generic"),
    _r("imgur", "Imgur", ("imgur.com",), "generic"),
    _r("tiktok", "TikTok", ("tiktok.com", "vt.tiktok.com", "vm.tiktok.com"), "generic"),
    _r("instagram", "Instagram", ("instagram.com", "instagr.am"), "generic"),
    _r("facebook", "Facebook", ("facebook.com", "fb.watch", "fb.com", "m.facebook.com"), "generic"),
    _r("snapchat", "Snapchat", ("snapchat.com",), "generic"),
    _r("coub", "Coub", ("coub.com",), "generic"),
    _r("veoh", "Veoh", ("veoh.com",), "generic"),
    _r("archive", "Internet Archive", ("archive.org",), "generic"),
    _r("soundcloud", "SoundCloud", ("soundcloud.com", "snd.sc", "soundcloud.app.goo.gl"), "generic", "audio"),
    _r("bandcamp", "Bandcamp", ("bandcamp.com",), "generic", "audio"),
    _r("mixcloud", "Mixcloud", ("mixcloud.com",), "generic", "audio"),
    _r("hearthis", "HearThis.at", ("hearthis.at",), "generic", "audio"),
    _r("audiomack", "Audiomack", ("audiomack.com",), "generic", "audio"),
    _r("bilibili", "Bilibili", ("bilibili.com", "b23.tv", "bilibili.tv"), "generic"),
    _r("douyin", "Douyin", ("douyin.com", "iesdouyin.com"), "generic"),
    _r("youku", "Youku", ("youku.com", "tudou.com"), "generic"),
    _r("iqiyi", "iQIYI", ("iqiyi.com", "iq.com"), "generic"),
    _r("tencent", "Tencent Video", ("v.qq.com", "wetv.vip"), "generic"),
    _r("mgtv", "MGTV", ("mgtv.com",), "generic"),
    _r("weibo", "Weibo", ("weibo.com", "weibo.cn", "video.weibo.com"), "generic"),
    _r("kuaishou", "Kuaishou", ("kuaishou.com", "gifshow.com", "chenzhongtech.com"), "generic"),
    _r("xiaohongshu", "Xiaohongshu", ("xiaohongshu.com", "xhslink.com"), "generic"),
    _r("acfun", "AcFun", ("acfun.cn",), "generic"),
    _r("niconico", "Niconico", ("nicovideo.jp", "nico.ms"), "generic"),
    _r("abema", "AbemaTV", ("abema.tv",), "generic"),
    _r("tver", "TVer", ("tver.jp",), "generic"),
    _r("naver", "Naver TV", ("tv.naver.com", "naver.com"), "generic"),
    _r("kakao", "Kakao TV", ("tv.kakao.com", "kakao.com"), "generic"),
    _r("vidio", "Vidio", ("vidio.com",), "generic"),
    _r("baidu", "Baidu Video", ("haokan.baidu.com", "baidu.com"), "generic"),
    _r("wistia", "Wistia", ("wistia.com", "wistia.net"), "generic"),
    _r("vidyard", "Vidyard", ("vidyard.com",), "generic"),
    _r("loom", "Loom", ("loom.com",), "generic"),
    _r("vevo", "Vevo", ("vevo.com",), "generic"),
    _r("metacafe", "Metacafe", ("metacafe.com",), "generic"),
    _r("break", "Break", ("break.com",), "generic"),
    _r("newgrounds", "Newgrounds", ("newgrounds.com",), "generic"),
    _r("9gag", "9GAG", ("9gag.com",), "generic"),
    _r("giphy", "Giphy", ("giphy.com",), "generic"),
    _r("tenor", "Tenor", ("tenor.com",), "generic"),
    _r("imgflip", "Imgflip", ("imgflip.com",), "generic"),
    _r("linkedin", "LinkedIn", ("linkedin.com",), "generic"),
    _r("pinterest", "Pinterest", ("pinterest.com", "pin.it"), "generic"),
    _r("tumblr", "Tumblr", ("tumblr.com",), "generic"),
    _r("bilibili_live", "Bilibili Live", ("live.bilibili.com",), "generic"),
    _r("rumble_live", "Rumble Live", ("rumble.live",), "generic"),
    _r("crunchyroll", "Crunchyroll", ("crunchyroll.com",), "generic", "subscription"),
    _r("hidive", "HIDIVE", ("hidive.com",), "generic", "subscription"),
    _r("wakanim", "Wakanim", ("wakanim.tv",), "generic", "subscription"),
    _r("netflix", "Netflix", ("netflix.com",), "generic", "DRM — not downloadable"),
    _r("primevideo", "Prime Video", ("primevideo.com", "amazon.com"), "generic", "DRM — not downloadable"),
    _r("disneyplus", "Disney+", ("disneyplus.com",), "generic", "DRM — not downloadable"),
    _r("hbomax", "Max", ("max.com", "hbomax.com"), "generic", "DRM — not downloadable"),
    _r("spotify", "Spotify", ("spotify.com",), "generic", "DRM — not downloadable"),

    # ── Persian / regional ────────────────────────────────────────────────
    _r("aparat", "Aparat", ("aparat.com", "aparat.cam", "aparat.ir"),
       "generic", "public file_link_all API (144p→1080p)", adapter="aparat"),
    _r("filimo", "Filimo", ("filimo.com", "filimo.ir", "filimo.tv"),
       "generic", "TV partner API → signed HLS", adapter="filimo"),
    _r("namasha", "Namasha", ("namasha.com", "namasha.ir"), "generic"),
    _r("tamasha", "Tamasha", ("tamasha.com",), "generic"),
    _r("dideo", "Dideo", ("dideo.ir", "dideo.tv"), "generic"),
    _r("varzesh3", "Varzesh3", ("varzesh3.com", "varzesh3.ir"), "generic"),
    _r("telewebion", "Telewebion", ("telewebion.com", "telewebion.ir"), "generic"),
    _r("filmnet", "FilmNet", ("filmnet.ir", "filmnet.com"), "generic"),
    _r("shad", "Shad", ("shad.ir", "shadmessenger.ir"), "generic"),
    _r("namava", "Namava", ("namava.ir",), "generic"),
    _r("moonfilm", "Moonfilm", ("moonfilm.com",), "generic"),
    _r("film2movie", "Film2Movie", ("film2movie.ws", "film2movie.co"), "generic"),
    _r("bia2movies", "Bia2Movies", ("bia2movies.top", "bia2movies.live", "bia2movies.fun"), "generic"),
    _r("zendegitv", "Zendegi TV", ("zendegitv.com",), "generic"),
    _r("shahid", "Shahid", ("shahid.mbc.net", "shahid.net"), "generic"),
    _r("alarabiya", "Al Arabiya", ("alarabiya.net",), "generic"),
    _r("aljazeera", "Al Jazeera", ("aljazeera.net", "aljazeera.com"), "generic"),
    _r("trt", "TRT", ("trt.net.tr", "trtizle.com"), "generic"),
    _r("kanald", "Kanal D", ("kanald.com.tr",), "generic"),
    _r("startv", "Star TV", ("startv.com.tr",), "generic"),
    _r("atv", "ATV", ("atv.com.tr",), "generic"),
    _r("hotstar", "Hotstar", ("hotstar.com", "hotstar.com/in"), "generic"),
    _r("zee5", "ZEE5", ("zee5.com",), "generic"),
    _r("sonyliv", "SonyLIV", ("sonyliv.com",), "generic"),
    _r("voot", "Voot", ("voot.com",), "generic"),
    _r("jiocinema", "JioCinema", ("jiocinema.com", "jiohotstar.com"), "generic"),
    _r("mxplayer", "MX Player", ("mxplayer.in",), "generic"),
    _r("dailymotion_in", "Dailymotion IN", ("dailymotion.co.in",), "generic"),

    # ── European / Latin / other ──────────────────────────────────────────
    _r("rtve", "RTVE", ("rtve.es",), "generic"),
    _r("atresplayer", "Atresplayer", ("atresplayer.com",), "generic"),
    _r("mitele", "Mitele", ("mitele.es",), "generic"),
    _r("rtl", "RTL", ("rtl.de", "rtl2.de", "rtl.hr"), "generic"),
    _r("ard", "ARD Mediathek", ("ardmediathek.de", "ard.de", "das-erste.de"), "generic"),
    _r("zdf", "ZDF", ("zdf.de", "zdfmediathek.de"), "generic"),
    _r("prosieben", "ProSieben", ("prosieben.de", "joyn.de"), "generic"),
    _r("france_tv", "france.tv", ("france.tv", "francetvinfo.fr"), "generic"),
    _r("tf1", "TF1", ("tf1.fr", "lci.fr"), "generic"),
    _r("m6", "M6", ("m6.fr", "6play.fr"), "generic"),
    _r("arte", "Arte", ("arte.tv",), "generic"),
    _r("rai", "RaiPlay", ("raiplay.it", "rai.it"), "generic"),
    _r("mediaset", "Mediaset", ("mediasetinfinity.mediaset.it", "mediaset.it"), "generic"),
    _r("bbc", "BBC iPlayer", ("bbc.co.uk", "bbc.com"), "generic"),
    _r("itv", "ITV", ("itv.com",), "generic"),
    _r("channel4", "Channel 4", ("channel4.com",), "generic"),
    _r("sky", "Sky", ("sky.com",), "generic"),
    _r("rtl_nl", "RTL Nieuws", ("rtlnieuws.nl", "rtl.nl"), "generic"),
    _r("nos", "NOS", ("nos.nl",), "generic"),
    _r("svt", "SVT", ("svtplay.se", "svt.se"), "generic"),
    _r("nrk", "NRK", ("nrk.no", "tv.nrk.no"), "generic"),
    _r("dr", "DR TV", ("dr.dk",), "generic"),
    _r("yle", "Yle", ("yle.fi", "areena.yle.fi"), "generic"),
    _r("tv4", "TV4 Play", ("tv4play.se", "tv4.se"), "generic"),
    _r("viaplay", "Viaplay", ("viaplay.se", "viaplay.no", "viaplay.dk"), "generic"),
    _r("cbc", "CBC", ("cbc.ca",), "generic"),
    _r("ctv", "CTV", ("ctv.ca",), "generic"),
    _r("global", "Global", ("globalnews.ca", "globaltv.com"), "generic"),
    _r("tva", "TVA", ("tva.ca", "qub.ca"), "generic"),
    _r("abc_au", "ABC iview", ("abc.net.au", "iview.abc.net.au"), "generic"),
    _r("sbs_au", "SBS On Demand", ("sbs.com.au",), "generic"),
    _r("nine", "9Now", ("9now.com.au", "nine.com.au"), "generic"),
    _r("ten", "10 play", ("10play.com.au", "ten.com.au"), "generic"),
    _r("tv3_nz", "ThreeNow", ("threenow.co.nz", "tv3.co.nz"), "generic"),
    _r("globo", "Globoplay", ("globoplay.globo.com", "globo.com"), "generic"),
    _r("sbt", "SBT", ("sbt.com.br",), "generic"),
    _r("record", "Record TV", ("recordtv.r7.com", "r7.com"), "generic"),
    _r("band", "Band", ("band.uol.com.br", "band.com.br"), "generic"),
    _r("caracol", "Caracol TV", ("caracoltv.com",), "generic"),
    _r("rcn", "RCN", ("canalrcn.com",), "generic"),
    _r("telemundo", "Telemundo", ("telemundo.com",), "generic"),
    _r("univision", "Univision", ("univision.com",), "generic"),
    _r("azteca", "TV Azteca", ("tvazteca.com", "azteca7.com"), "generic"),
    _r("milenio", "Milenio", ("milenio.com",), "generic"),
    _r("elcomercio", "El Comercio", ("elcomercio.pe",), "generic"),
    _r("clarin", "Clarín", ("clarin.com",), "generic"),
    _r("lanacion", "La Nación", ("lanacion.com.ar",), "generic"),
    _r("folha", "Folha", ("folha.uol.com.br",), "generic"),
    _r("uol", "UOL", ("uol.com.br",), "generic"),
    _r("ig", "IG", ("ig.com.br",), "generic"),
    _r("rt", "RT", ("rt.com", "russiatoday.com"), "generic"),
    _r("rbc", "RBC", ("rbc.ru",), "generic"),
    _r("lenta", "Lenta", ("lenta.ru",), "generic"),
    _r("iz", "Izvestia", ("iz.ru",), "generic"),
    _r("kp", "KP", ("kp.ru",), "generic"),
    _r("1tv", "Channel One", ("1tv.ru", "1tv.com"), "generic"),
    _r("ntv", "NTV", ("ntv.ru",), "generic"),
    _r("rtvi", "RTVI", ("rtvi.com",), "generic"),
    _r("meduza", "Meduza", ("meduza.io",), "generic"),
    _r("currenttime", "Current Time", ("currenttime.tv",), "generic"),
    _r("svoboda", "Radio Svoboda", ("svoboda.org", "svaboda.org"), "generic"),
    _r("dw", "DW", ("dw.com", "dw.de"), "generic"),
    _r("voa", "VOA", ("voanews.com", "voa.gov"), "generic"),
    _r("cnn", "CNN", ("cnn.com", "cnnpressroom.com"), "generic"),
    _r("fox", "Fox", ("fox.com", "foxnews.com"), "generic"),
    _r("nbc", "NBC", ("nbc.com", "nbcnews.com"), "generic"),
    _r("cbs", "CBS", ("cbs.com", "cbsnews.com"), "generic"),
    _r("abc", "ABC", ("abc.com", "abcnews.go.com"), "generic"),
    _r("pbs", "PBS", ("pbs.org",), "generic"),
    _r("npr", "NPR", ("npr.org",), "generic"),
    _r("bloomberg", "Bloomberg", ("bloomberg.com",), "generic"),
    _r("reuters", "Reuters", ("reuters.com",), "generic"),
    _r("ap", "AP", ("apnews.com",), "generic"),
    _r("guardian", "The Guardian", ("theguardian.com",), "generic"),
    _r("nytimes", "NYTimes", ("nytimes.com",), "generic"),
    _r("washingtonpost", "Washington Post", ("washingtonpost.com",), "generic"),
    _r("wsj", "WSJ", ("wsj.com",), "generic"),
    _r("forbes", "Forbes", ("forbes.com",), "generic"),
    _r("economist", "Economist", ("economist.com",), "generic"),
    _r("ft", "Financial Times", ("ft.com",), "generic"),
    _r("espn", "ESPN", ("espn.com", "espn.co.uk"), "generic"),
    _r("skysports", "Sky Sports", ("skysports.com",), "generic"),
    _r("dazn", "DAZN", ("dazn.com",), "generic", "subscription"),
    _r("nba", "NBA", ("nba.com",), "generic"),
    _r("nfl", "NFL", ("nfl.com",), "generic"),
    _r("mlb", "MLB", ("mlb.com",), "generic"),
    _r("fifa", "FIFA", ("fifa.com",), "generic"),
    _r("uefa", "UEFA", ("uefa.com",), "generic"),
    _r("olympics", "Olympics", ("olympics.com",), "generic"),
    _r("redbull", "Red Bull", ("redbull.com",), "generic"),
    _r("ted", "TED", ("ted.com",), "generic"),
    _r("coursera", "Coursera", ("coursera.org",), "generic"),
    _r("udemy", "Udemy", ("udemy.com",), "generic", "login required"),
    _r("skillshare", "Skillshare", ("skillshare.com",), "generic", "login required"),
    _r("khanacademy", "Khan Academy", ("khanacademy.org",), "generic"),
    _r("masterclass", "MasterClass", ("masterclass.com",), "generic", "login required"),
    _r("pluralsight", "Pluralsight", ("pluralsight.com",), "generic", "login required"),
    _r("brightcove", "Brightcove", ("brightcove.com", "players.brightcove.net"), "generic"),
    _r("jwplatform", "JW Platform", ("jwplatform.com", "cdn.jwplayer.com"), "jwplayer"),
    _r("kaltura", "Kaltura", ("kaltura.com", "kaltura.org"), "generic"),
    _r("mux", "Mux", ("mux.com", "stream.mux.com"), "generic"),
    _r("cloudflarestream", "Cloudflare Stream", ("cloudflarestream.com", "videodelivery.net"), "generic"),
    _r("bunny", "Bunny Stream", ("bunny.net", "mediadelivery.net"), "generic"),
    _r("vimeo_ott", "Vimeo OTT", ("vimeo.com/ott", "vhx.tv"), "generic"),
    _r("peertube", "PeerTube", ("framatube.org", "peertube.tv"), "generic"),

    # ── file hosts / multi-link embeds (video pages, not tubes) ───────────
    _r("streamtape", "StreamTape", ("streamtape.com", "streamtape.net", "tapecontent.net",
                                   "tapeadvertisement.com"), "generic", "robotlink JS"),
    _r("doodstream", "DoodStream", ("dood.so", "dood.watch", "dood.sh", "dood.pm",
                                    "dood.la", "dood.to", "doodstream.com", "dood.cx",
                                    "dood.wf", "dood.re", "dood.li", "dood.yt"),
       "generic", "pass_md5 token"),
    _r("mixdrop", "MixDrop", ("mixdrop.co", "mixdrop.to", "mixdrop.ch", "mixdrop.sx",
                              "mixdrop.vc", "mixdrop.ag", "mixdrop.bz", "mixdrop.ps",
                              "mixdrop.wf", "mixdrop.re", "mixdrop.moe", "mixdrop.club",
                              "mixdrop.icu", "mixdrop.bio", "mixdrop.fr", "mixdrop.si"),
       "generic", "wurl JSON"),
    _r("filemoon", "FileMoon", ("filemoon.sx", "filemoon.to", "filemoon.in", "filemoon.nl",
                                "filemoon.sk", "filemoon.com"), "generic", "packed player"),
    _r("streamwish", "StreamWish", ("streamwish.to", "streamwish.com", "streamwish.top",
                                    "strwish.com", "wishembed.pro", "wishfast.top",
                                    "streamwish.site", "streamwish.xyz", "streamwish.info",
                                    "streamwish.fun", "streamwish.online", "streamwish.store"),
       "generic", "packed player"),
    _r("streamhide", "StreamHide", ("streamhide.com", "streamhide.to", "guccihide.com",
                                    "moviesm4u.com", "streamhls.to", "ahvsh.com",
                                    "livesteam.co"), "generic", "packed player"),
    _r("voe", "VOE", ("voe.sx", "voe-unblock.com", "voeunblock.com", "voeunbl0ck.com"), "generic"),
    _r("vidmoly", "Vidmoly", ("vidmoly.to", "vidmoly.me", "vidmoly.net", "vidmoly.tv"), "generic"),
    _r("mp4upload", "MP4Upload", ("mp4upload.com",), "generic"),
    _r("sendvid", "SendVid", ("sendvid.com",), "generic"),
    _r("upstream", "UpStream", ("upstream.to",), "generic"),
    _r("lulustream", "LuluStream", ("lulustream.com", "luluvdo.com", "luluvid.com"), "generic"),
    _r("hxfile", "HXFile", ("hxfile.co", "hxfile.io"), "generic"),
    _r("krakenfiles", "KrakenFiles", ("krakenfiles.com",), "generic"),
    _r("gofile", "Gofile", ("gofile.io",), "generic"),
    _r("pixeldrain", "Pixeldrain", ("pixeldrain.com",), "generic"),
    _r("1fichier", "1fichier", ("1fichier.com",), "generic"),
    _r("mega", "MEGA", ("mega.nz", "mega.co.nz"), "generic"),
    _r("gdrive", "Google Drive", ("drive.google.com", "docs.google.com"), "generic"),
    _r("dropbox", "Dropbox", ("dropbox.com", "dl.dropboxusercontent.com"), "generic"),
    _r("onedrive", "OneDrive", ("1drv.ms", "onedrive.live.com"), "generic"),
    _r("mediafire", "MediaFire", ("mediafire.com",), "generic"),
    _r("zippyshare", "Zippyshare", ("zippyshare.com",), "generic"),
    _r("vidsrc", "VidSrc", ("vidsrc.to", "vidsrc.xyz", "vidsrc.me", "vidsrc.cc",
                            "vidsrc.in", "vidsrc.net", "vsrc.to", "vsrc.xyz", "vsrc.sx"),
       "generic", "multi-source embed"),
    _r("2embed", "2Embed", ("2embed.cc", "2embed.to", "2embed.sbs", "2embed.ru"), "generic"),
    _r("embedsu", "Embed.su", ("embed.su", "embed.sii"), "generic"),
    _r("smashystream", "SmashyStream", ("smashystream.com", "smashystream.xyz"), "generic"),
    _r("autoembed", "AutoEmbed", ("autoembed.cc", "autoembed.co"), "generic"),
    _r("superembed", "SuperEmbed", ("superembed.stream", "superembed.com"), "generic"),
    _r("multiembed", "MultiEmbed", ("multiembed.movie", "multiembed.com"), "generic"),
    _r("bannedvideo", "Banned.video", ("banned.video",), "generic"),
    _r("rumble_embed", "Rumble Embed", ("rumble.com/embed",), "generic"),

    # ── tube networks & aggregators that wrap someone else's CDN ─────────────
    # The stream always sits in a player config on the page, so the generic
    # engine already finds it; a recipe only names the site and selects the
    # pattern set that carries its quality labels.
    _r("noodlemagazine", "Noodle Magazine", ("noodlemagazine.com", "noodlemagazine.download"),
       "kt_player", "aggregator: KVS-style flashvars"),
    _r("voyeurhit", "VoyeurHit", ("voyeurhit.com",), "kt_player", "KVS flashvars"),
    _r("3movs", "3Movs", ("3movs.com",), "generic", "video_urls JSON"),
    _r("sexix", "Sexix", ("sexix.net",), "generic", "kt_player-style vars"),
    _r("pornrabbit", "PornRabbit", ("pornrabbit.com",), "kt_player", "KVS flashvars"),
    _r("fuqer", "Fuqer", ("fuqer.com",), "generic", "jwplayer sources"),
    _r("porngo", "PornGO", ("porngo.com",), "kt_player", "KVS flashvars"),
    _r("hotmovs", "HotMovs", ("hotmovs.com",), "kt_player", "KVS flashvars"),
    _r("sxyprn", "SxyPrn", ("sxyprn.com", "sxyprn.net"), "generic", "poster/JSON-embedded mp4"),
    _r("pornkai", "PornKai", ("pornkai.com",), "generic", "aggregated source list"),
    _r("porn00", "Porn00", ("porn00.org", "porn00.com"), "kt_player", "KVS flashvars"),
    _r("pornhits", "PornHits", ("pornhits.com",), "kt_player", "KVS flashvars"),
    _r("pornftw", "PornFTW", ("pornftw.com",), "generic", "player JSON"),
    _r("watchporn", "WatchPorn", ("watchporn.com", "watchpornx.com"), "generic", "player JSON"),
    _r("javgg", "JavGG", ("javgg.net", "javgg.com"), "generic", "multi-host player list"),
    _r("javtiful", "JavTiful", ("javtiful.com",), "generic", "dood/streamtape embeds"),
    _r("supjav", "SupJav", ("supjav.com",), "generic", "multi-host player list"),
    _r("javmost", "JavMost", ("javmost.com", "javmost.cx"), "generic", "player JSON"),
    _r("hentai2read", "Hentai2Read", ("hentai2read.com",), "generic", "reader video slots"),
    _r("toonily", "Toonily", ("toonily.com", "toonily.net"), "generic", "multi-host embeds"),
    _r("asianstube", "AsiansTube", ("asianstube.net", "asianstube.com"), "kt_player", "KVS flashvars"),
    _r("pornfeat", "PornFeat", ("pornfeat.com",), "kt_player", "KVS flashvars"),
    _r("wankitnow", "WankitNow", ("wankitnow.com",), "generic", "player JSON"),

    # ── live-cam sites with public replay/recorded URLs ──────────────────────
    _r("cam4", "CAM4", ("cam4.com", "cam4.fr", "cam4.de"), "generic", "HLS replay"),
    _r("stripchat", "Stripchat", ("stripchat.com",), "generic", "HLS replay"),
    _r("bongacams", "BongaCams", ("bongacams.com", "bongacams.net"), "generic", "HLS replay"),
    _r("camsoda", "CamSoda", ("camsoda.com",), "generic", "HLS replay"),
    _r("myfreecams", "MyFreeCams", ("myfreecams.com", "mfc.im"), "generic", "HLS replay"),
    _r("livejasmin", "LiveJasmin", ("livejasmin.com",), "generic", "HLS replay"),

    # ── file hosts / multi-source players seen on movie & tube sites ────────
    _r("vidoza", "Vidoza", ("vidoza.net", "vidoza.org"), "generic", "sources[] mp4"),
    _r("vudeo", "Vudeo", ("vudeo.net", "vudeo.io", "vudeo.co"), "generic", "packed player"),
    _r("streamsb", "StreamSB", ("streamsb.net", "sbplay.org", "sbfull.com", "embedsb.com",
                                "sbplay2.com", "sbspeed.com"), "generic", "packed player"),
    _r("vidlink", "VidLink", ("vidlink.pro", "vidlink.pics"), "generic", "multi-source embed"),
    _r("vidfast", "VidFast", ("vidfast.pro", "vidfast.net", "vidfast.in"), "generic", "multi-source embed"),
    _r("vidbinge", "VidBinge", ("vidbinge.com", "vidbinge.to", "vidbinge.app"), "generic", "multi-source embed"),
    _r("vidora", "Vidora", ("vidora.stream", "vidora.su"), "generic", "multi-source embed"),
    _r("videasy", "Videasy", ("videasy.net", "videasy.to"), "generic", "multi-source embed"),
    _r("111movies", "111Movies", ("111movies.com",), "generic", "multi-source embed"),
    _r("nepu", "Nepu", ("nepu.to",), "generic", "multi-source embed"),
)


# ---------------------------------------------------------------------------
# Indexes
# ---------------------------------------------------------------------------
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
    host = host.rstrip(".")
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


def embed_host_for(url: str) -> str:
    """Player label when this URL is a known cross-origin embed host, else ''."""
    low = (url or "").lower()
    if not low:
        return ""
    for pat, name in EMBED_HOSTS:
        if pat.search(low):
            return name
    return ""


def is_embed_url(url: str) -> bool:
    """Is this a player URL worth hopping into (known host or embed-shaped)?"""
    if embed_host_for(url):
        return True
    low = (url or "").lower()
    return any(t in low for t in ("video", "embed", "player", "watch", "media", "/vid", "/e/"))


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
        if old is None:
            out[item["url"]] = item
            return
        if item.get("score", 0) > old.get("score", 0):
            # a named player slot outranks a random URL, but it must not forget
            # the resolution another pass already learned for the same file
            item["height"] = item.get("height") or old.get("height") or 0
            item["quality"] = item.get("quality") or old.get("quality") or ""
            out[item["url"]] = item

    # 1) generic scan of the (de-escaped) document — covers every player style
    for c in embed.extract(html, url, limit=limit * 2, origin="recipe" if recipe else "embed"):
        add(c)

    # 2) family patterns (they carry the human label: High/Low/HD/HLS).
    #    An UNKNOWN host still gets a family when the page announces its player —
    #    that is why an unlisted tube site works without a recipe.
    norm = embed.normalize(html)
    license_code = embed.kvs_license_code(norm)
    fam_key = recipe.family if recipe else ""
    if fam_key in ("", "generic"):
        detected = detect_family(html)
        if detected in FAMILIES:
            fam_key = detected
    fam = FAMILIES.get(fam_key or "generic", ())
    extra_pats = _RECIPE_PATTERNS.get(recipe.key, ()) if recipe else ()
    for pat, label in fam:
        for m in pat.finditer(norm):
            c = embed.candidate(m.group(1), url, "recipe", label,
                                license_code=license_code)
            if c:
                c["score"] += 6          # a named player slot beats a random URL
                add(c)
    for pat in extra_pats:
        for m in pat.finditer(norm):
            add(embed.candidate(m.group(1), url, "recipe", license_code=license_code))

    items = sorted(out.values(), key=lambda c: -c.get("score", 0))[:limit]
    name = recipe.name if recipe else ""
    for c in items:
        c["site"] = name
        c["recipe"] = recipe.key if recipe else ""
    return items


def catalog() -> list[dict]:
    """Public list for the UI/API: what the app knows about out of the box."""
    return [{"key": r.key, "name": r.name, "domains": list(r.domains),
             "family": r.family, "note": r.note, "adapter": r.adapter}
            for r in RECIPES]
