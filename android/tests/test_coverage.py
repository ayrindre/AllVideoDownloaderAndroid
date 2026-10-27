#!/usr/bin/env python3
"""All Video Downloader — coverage tests: adapters, KVS, players, registry.

Every fixture here is shaped after a *real* response seen in the wild:

* Aparat ``/etc/api/video/videohash/<id>`` → 144p…1080p CDN ladder with sizes
* Filimo ``/api/fa/v1/partner/TV/watch/uid/<id>`` → signed HLS manifest
* 1porn.tv / KVS ``flashvars`` → ``function/0/…`` hashed ``get_file`` URLs
* video.js / Plyr / Clappr / Flowplayer / DPlayer / Shaka player configs
* a Dean-Edwards packed player script (Filemoon / StreamWish style)

Run:  python tools/test_coverage.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from avd.core import adapters as A          # noqa: E402
from avd.core import embed as E             # noqa: E402
from avd.core import filekind as fk         # noqa: E402
from avd.core import media as M             # noqa: E402
from avd.core import net                    # noqa: E402
from avd.core import sites as S             # noqa: E402

# ═══ APARAT: public videohash API → real mp4 ladder (with sizes) ════════════
APARAT_JSON = {
    "video": {
        "id": "73861477",
        "title": "فرق تو و رونالدو رو تو این ویدیو گفتم !",
        "username": "leosaeid",
        "sender_name": "آموزش فوتبال با لئو سعید",
        "duration": "508",
        "big_poster": "https://static.cdn.asset.aparat.com/avt/73861477-9672-l__9811.jpg",
        "size": "1067211029",
        "cost_type": {"type": "free"},
        "can_download": True,
        "file_link": "https://caspian30.cdn.asset.aparat.com/aparat-video/x-1080p.apt?wmsAuthSign=a",
        "file_link_all": [
            {"text": "با کیفیت 144p", "size": "8.62 مگابایت", "profile": "144p",
             "urls": ["https://caspian27.cdn.asset.aparat.com/aparat-video/x-144p.mp4?sig=1"]},
            {"text": "با کیفیت 240p", "size": "14.92 مگابایت", "profile": "240p",
             "urls": ["https://caspian27.cdn.asset.aparat.com/aparat-video/x-240p.mp4?sig=1"]},
            {"text": "با کیفیت 360p", "size": "28.56 مگابایت", "profile": "360p",
             "urls": ["https://caspian27.cdn.asset.aparat.com/aparat-video/x-360p.mp4?sig=1"]},
            {"text": "با کیفیت 480p", "size": "43.22 مگابایت", "profile": "480p",
             "urls": ["https://caspian27.cdn.asset.aparat.com/aparat-video/x-480p.mp4?sig=1"]},
            {"text": "با کیفیت 720p", "size": "83.85 مگابایت", "profile": "720p",
             "urls": ["https://caspian29.cdn.asset.aparat.com/aparat-video/x-720p.mp4?sig=1"]},
            {"text": "با کیفیت 1080p", "size": "176.73 مگابایت", "profile": "1080p",
             "urls": ["https://caspian30.cdn.asset.aparat.com/aparat-video/x-1080p.mp4?sig=1"]},
        ],
    }
}

aparat = A.parse_aparat(APARAT_JSON, "https://www.aparat.com/v/yab6353")
assert aparat and aparat["kind"] == "webmedia", aparat
assert [f["height"] for f in aparat["formats"]] == [1080, 720, 480, 360, 240, 144]
assert all(f["format"] == "url" and f["ext"] == "mp4" for f in aparat["formats"])
assert aparat["formats"][0]["url"].endswith("x-1080p.mp4?sig=1")
assert aparat["formats"][0]["size"] == int(176.73 * 1024 ** 2)
assert aparat["title"].startswith("فرق تو") and aparat["site"] == "Aparat"
assert aparat["duration"] == 508 and aparat["formats_total"] == 6
print("✓ aparat: 6 CDN profiles (144p→1080p) with sizes, labels and metadata")

# the second documented payload shape (api/fa/v1 …) parses identically
aparat2 = A.parse_aparat({"data": {"type": "VideoShow", "attributes": APARAT_JSON["video"]}},
                         "https://www.aparat.com/v/yab6353")
assert [f["height"] for f in aparat2["formats"]] == [1080, 720, 480, 360, 240, 144]
# paywalled / download-disabled videos still list their files but say so
paid = json.loads(json.dumps(APARAT_JSON))
paid["video"]["cost_type"] = {"type": "package"}
paid["video"]["can_download"] = False
assert "paywalled" in A.parse_aparat(paid, "https://www.aparat.com/v/x")["access_note"]
print("✓ aparat: both payload shapes + paywall/download-disabled notes")

# ═══ FILIMO: TV partner API → signed HLS manifest ══════════════════════════
FILIMO_M3U8 = ("https://www.filimo.com/movie/watch/m3u8/mof/yes/v/0/usid/0/uid/179310900764355603"
               "/tot/1792993807/utp/95902502/movie_uid/h78m0/movie_id/222373/devicetype/site"
               "/domain//agentsdk/0/agentafcn/0/issmart/0/hash_url/fb4affd6/hash_urlv2/b1fd7c45"
               "/clires//skf/no/stost/no/maost/no/as/22773/ref_res/0/h78m0.m3u8")
FILIMO_JSON = {"data": {"type": "Watch", "id": None, "attributes": {
    "uid": "h78m0",
    "movie_title": "سرخ و سیاه - فصل 1 قسمت 2",
    "movie_title_en": "The Red and the Black S01E02",
    "duration": "2957",
    "serial": {"enable": True},
    "movie_src": [[{"src": FILIMO_M3U8, "type": "application/vnd.apple.mpegurl"}]],
    "moviePseudo": {"type": "error", "value": "برای تماشای آفلاین باید اشتراک بخرید."},
    "watch_action": {"type": "login"},
    "pic": "https://static.cdn.asset.filimo.com/flmt/mov_193060_378225-b.jpg",
}}}

filimo = A.parse_filimo(FILIMO_JSON, "https://www.filimo.com/n/h78m0")
assert filimo and filimo["kind"] == "hls" and filimo["url"] == FILIMO_M3U8
assert filimo["site"] == "Filimo" and filimo["referer"] == "https://www.filimo.com/n/h78m0"
assert filimo["duration"] == 2957 and filimo["title_en"].startswith("The Red")
assert "subscriber-only" in filimo["access_note"], filimo["access_note"]
assert A.parse_filimo({"data": {"attributes": {}}}, "https://www.filimo.com/n/x") is None
print("✓ filimo: signed manifest + title/thumbnail/duration, subscription stated honestly")

# ═══ ADAPTER ROUTING: the sample links hit the right bridge ════════════════
for url, key in (
    ("https://www.aparat.com/v/yab6353", "aparat"),
    ("https://www.aparat.com/video/video/embed/videohash/yab6353/vt/frame", "aparat"),
    ("https://www.aparat.com/video/video/embed/videohash/yab6353", "aparat"),
    ("https://www.filimo.com/n/h78m0", "filimo"),
    ("https://www.filimo.com/m/h78m0", "filimo"),
    ("https://www.filimo.com/movie/movie/download_manager/uid/h78m0?details-v2=true", "filimo"),
):
    hit = A.for_url(url)
    assert hit and hit[0].key == key, (url, hit)
assert A.for_url("https://www.youtube.com/watch?v=x") is None
assert A.adapter_for_recipe("aparat").site == "Aparat"
assert S.recipe_for("https://www.aparat.com/v/yab6353").adapter == "aparat"
assert S.recipe_for("https://www.filimo.com/n/h78m0").adapter == "filimo"
print("✓ adapters: aparat (watch + 3 embed shapes) and filimo (n/m/download_manager) routed")

# ═══ END-TO-END: analyze() answers an Aparat page from the API, no yt-dlp ══
_calls: list[str] = []


async def _no_yt(url):
    _calls.append(url)
    return None, "should not be needed"


_orig_yt, _orig_fetch = M._try_ytdlp, net.fetch_text


async def _aparat_fetch(url, **kw):
    if "videohash/yab6353" in url:
        return json.dumps(APARAT_JSON), url, {"content-type": "application/json"}
    return "", url, {}


M._try_ytdlp, net.fetch_text = _no_yt, _aparat_fetch
try:
    card = asyncio.run(M.analyze("https://www.aparat.com/v/yab6353"))
finally:
    M._try_ytdlp, net.fetch_text = _orig_yt, _orig_fetch
assert card["kind"] == "webmedia" and card["site"] == "Aparat", card
assert [f["height"] for f in card["formats"]] == [1080, 720, 480, 360, 240, 144]
assert card["referer"] == "https://www.aparat.com/v/yab6353" and not _calls
print("✓ analyze: Aparat page → webmedia card straight from the API (yt-dlp untouched)")

# ═══ END-TO-END: analyze() turns Filimo's manifest into a variant ladder ═══
FILIMO_MASTER = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=5200000,RESOLUTION=1920x1080
1080/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=2400000,RESOLUTION=1280x720
720/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=900000,RESOLUTION=854x480
480/index.m3u8
"""


async def _filimo_fetch(url, **kw):
    if "partner/TV/watch/uid/h78m0" in url:
        return json.dumps(FILIMO_JSON), url, {}
    return "", url, {}


async def _manifest(url, referer=""):
    assert referer == "https://www.filimo.com/n/h78m0", referer
    return FILIMO_MASTER


_orig_mf = M.fetch_manifest
M.fetch_manifest, net.fetch_text = _manifest, _filimo_fetch
try:
    fcard = asyncio.run(M.analyze("https://www.filimo.com/n/h78m0"))
finally:
    M.fetch_manifest, net.fetch_text = _orig_mf, _orig_fetch
assert fcard["kind"] == "hls" and fcard["url"] == FILIMO_M3U8, fcard
assert [f["height"] for f in fcard["formats"]] == [0, 1080, 720, 480], fcard["formats"]
assert fcard["site"] == "Filimo" and fcard["referer"] == "https://www.filimo.com/n/h78m0"
assert "subscriber-only" in fcard.get("access_note", ""), fcard
assert fcard["formats"][1]["url"].endswith("1080/index.m3u8")
print("✓ analyze: Filimo manifest parsed into 1080p/720p/480p chips, note kept")

# ═══ KVS: hashed get_file URLs are decrypted with license_code ═════════════
LICENSE = "451596714898965"


def _kvs_scramble(real_hash: str, code: str) -> str:
    """Build the *obfuscated* hash KVS serves (inverse of the decoder)."""
    token = E.kvs_license_token(code)
    n = 32
    indices = list(range(n))
    accum = 0
    for src in reversed(range(n)):
        accum += token[src % len(token)]
        dest = (src + accum) % n
        indices[src], indices[dest] = indices[dest], indices[src]
    scrambled = [""] * n
    for pos, target in enumerate(indices):
        scrambled[target] = real_hash[pos]
    return "".join(scrambled)


REAL_HASH = "87c2e15e0d125d6c671ca5fadf7112d3"
SCRAMBLED = _kvs_scramble(REAL_HASH, LICENSE)
assert SCRAMBLED != REAL_HASH and len(SCRAMBLED) == 32
real_url = f"https://www.1porn.tv/get_file/9/{REAL_HASH}/93577000/93577082/93577082_720m.mp4/"
assert E.kvs_real_url(f"function/0/{'https://www.1porn.tv/get_file/9/' + SCRAMBLED}/93577000/93577082/93577082_720m.mp4/",
                      LICENSE) == real_url
assert E.kvs_real_url(real_url, LICENSE) == real_url          # untouched when plain
assert E.kvs_license_code(f"var flashvars = {{ license_code: '{LICENSE}' }}") == LICENSE
print("✓ kvs: function/0/ hash permutation decoded (round-trip), plain URLs untouched")

# ═══ 1porn.tv shape: flashvars ladder + get_file download link ═════════════
PAGE_1PORN = f"""<html><head><title>Brunette Babes Share a Massive Black Cock | Free Porn</title>
<meta property="og:image" content="https://img.1porn.tv/93577000/93577082/player/1.jpg"></head>
<body>
<video id="video" class="video-js" playsinline poster="/1.jpg"></video>
<a href="https://www.1porn.tv/get_file/9/{REAL_HASH}/93577000/93577082/93577082_720m.mp4/?download=true&amp;download_filename=x_720m.mp4">Download</a>
<script type="text/javascript">
  var flashvars = {{
    license_code: '{LICENSE}',
    video_id: '93577082',
    video_url: 'function/0/https://www.1porn.tv/get_file/9/{SCRAMBLED}/93577000/93577082/93577082_720m.mp4/',
    video_url_text: '720p',
    video_alt_url: 'https://www.1porn.tv/get_file/9/aaaa1111bbbb2222cccc3333dddd4444/93577000/93577082/93577082_480m.mp4/',
    video_alt_url_text: '480p',
    video_url_hd: '1',
    preview_url: '/preview/93577082_480m.jpg'
  }};
  kt_player('kt_player', '/player/kt_player.js', '100%', '100%', flashvars);
</script></body></html>"""
p1 = S.candidates(PAGE_1PORN, "https://www.1porn.tv/videos/brunette-babes-share-a-massive-black-cock/")
urls = [c["url"] for c in p1]
assert real_url in urls, urls
assert not any(SCRAMBLED in u for u in urls), "the scrambled hash must never be offered"
assert not any(u.endswith("_480m.jpg") for u in urls), "preview images are not videos"
heights = {c["height"] for c in p1 if c["height"]}
assert heights >= {720, 480}, heights
assert all(c["site"] == "1Porn" for c in p1) or all(c["site"] == "" for c in p1)
card_1p = M._files_card("https://www.1porn.tv/videos/x/", p1, title="clip")
assert card_1p and card_1p["kind"] == "webmedia", card_1p
assert {f["height"] for f in card_1p["formats"]} == {720, 480}, card_1p["formats"]
assert card_1p["referer"] == "https://www.1porn.tv/videos/x/"
print("✓ 1porn.tv: KVS flashvars → 720p/480p chips (hashed URL decrypted, poster dropped)")

# the Download anchor (…mp4/?download=true) is picked up on its own too
anchors = M.scan_page.__doc__ and M.MEDIA_HREF_RE.findall(PAGE_1PORN)
assert anchors and anchors[0].endswith("download_filename=x_720m.mp4"), anchors
print("✓ anchors: file hosts' '…mp4/?download=true' links are matched")

# ═══ PLAYER FAMILIES: modern players announce sources in their own dialect ══
VIDEOJS = """<html><head><title>Clip - Site</title></head><body><video id="v" class="video-js"></video>
<script>var player = videojs('v'); player.src({type: "application/x-mpegURL", src: "/hls/master.m3u8"});
player.src({type: "video/mp4", src: "/files/clip_1080p.mp4"});</script></body></html>"""
vj = S.candidates(VIDEOJS, "https://unlisted-player.example/watch/1")
vj_urls = [c["url"] for c in vj]
assert "https://unlisted-player.example/hls/master.m3u8" in vj_urls, vj_urls
assert any(u.endswith("clip_1080p.mp4") for u in vj_urls), vj_urls
assert S.detect_family(VIDEOJS) == "videojs"

SHaka = """<script>var player = new shaka.Player();
player.load({manifestUri: 'https://cdn.example/dash/manifest.mpd'});</script>"""
assert "https://cdn.example/dash/manifest.mpd" in [
    c["url"] for c in S.candidates(SHaka, "https://unlisted-player.example/x")]

CLAPPR = """<script>var p = new Clappr.Player({source: "https://cdn.example/v/clip.m3u8",
poster: "/p.jpg"});</script>"""
assert "https://cdn.example/v/clip.m3u8" in [
    c["url"] for c in S.candidates(CLAPPR, "https://unlisted-player.example/x")]

FLOW = """<script>flowplayer("#p", {clip: {sources: [
 {type: "video/mp4", src: "https://cdn.example/v/clip-480.mp4"},
 {type: "video/mp4", src: "https://cdn.example/v/clip-1080.mp4"}]}});</script>"""
fl = S.candidates(FLOW, "https://unlisted-player.example/x")
assert {c["height"] for c in fl} == {480, 1080}, fl

DPL = """<script>new DPlayer({video: {url: "https://cdn.example/v/dp_720p.mp4", pic: "/p.jpg"}});</script>"""
assert any(c["height"] == 720 for c in S.candidates(DPL, "https://unlisted-player.example/x"))
print("✓ families: video.js / Shaka / Clappr / Flowplayer / DPlayer all mined")

# ═══ LABELS: "quality: 1080p" beside a URL becomes the chip label ══════════
JW = """<script>jwplayer("p").setup({sources: [
 {"file": "https://cdn.example/v/a.mp4", "label": "1080p"},
 {"file": "https://cdn.example/v/b.mp4", "label": "720p"}]});</script>"""
jw = {c["url"]: c["height"] for c in S.candidates(JW, "https://unlisted-player.example/x")}
assert jw["https://cdn.example/v/a.mp4"] == 1080 and jw["https://cdn.example/v/b.mp4"] == 720, jw
MEDIADEF = """<script>var flashvars={mediaDefinitions:[
 {quality:"1080", videoUrl:"https://cdn.example/v/md_hi.mp4"},
 {quality:"480", videoUrl:"https://cdn.example/v/md_lo.mp4"}]};</script>"""
md = {c["url"]: c["height"] for c in S.candidates(MEDIADEF, "https://unlisted-player.example/x")}
assert md["https://cdn.example/v/md_hi.mp4"] == 1080, md
print("✓ labels: jwplayer labels / mediaDefinitions quality → real heights")

# ═══ PACKED PLAYERS: eval(function(p,a,c,k,e,d)) is unpacked and re-scanned ═
PACKED = ("<script>eval(function(p,a,c,k,e,d){e=function(c){return c};"
          "if(!''.replace(/^/,String)){while(c--){d[c]=k[c]||c}k=[function(e){return d[e]}];"
          "e=function(){return'\\\\w+'};c=1};while(c--){if(k[c]){p=p.replace(new RegExp('\\\\b'+e(c)+'\\\\b','g'),k[c])}}"
          "return p}('var u=\"0\";',62,1,'https://cdn.example/v/packed_master.m3u8'.split('|'),0,{}))</script>")
assert "eval(function(p,a,c,k,e,d)" in PACKED
assert E.unpack_packed(E.normalize(PACKED)), "packer must decode"
packed_urls = [c["url"] for c in S.candidates(PACKED, "https://unlisted-player.example/x")]
assert "https://cdn.example/v/packed_master.m3u8" in packed_urls, packed_urls
print("✓ packed JS: player URL recovered from an obfuscated script")

# ═══ EMBED HOSTS: file hosts and cross-origin players are hop targets ══════
for url, name in (
    ("https://streamtape.com/e/AbCdEf", "StreamTape"),
    ("https://dood.li/e/xyz123", "DoodStream"),
    ("https://mixdrop.co/e/abc", "MixDrop"),
    ("https://filemoon.sx/e/abc", "FileMoon"),
    ("https://voe.sx/e/abc", "VOE"),
    ("https://vidsrc.to/embed/movie/tt123", "VidSrc"),
    ("https://player.vimeo.com/video/123", "Vimeo"),
    ("https://www.youtube-nocookie.com/embed/abc", "YouTube"),
    ("https://ok.ru/videoembed/123", "OK.ru"),
    ("https://vk.com/video_ext.php?oid=1&id=2", "VK"),
    ("https://www.aparat.com/video/video/embed/videohash/x/vt/frame", "Aparat"),
):
    assert S.embed_host_for(url) == name, (url, S.embed_host_for(url))
assert S.is_embed_url("https://streamtape.com/e/x") and not S.is_embed_url("https://shop.example/cart")

EMBED_PAGE = """<html><body><div class="player-wrap">
<iframe data-src="https://filemoon.sx/e/qwerty" allowfullscreen></iframe></div></body></html>"""


class _Resp:
    def __init__(self, text="", url="", headers=None):
        self.text, self.status_code = text, 200
        self.headers = headers or {"content-type": "text/html"}
        self.url, self.content = url, text.encode()

    def raise_for_status(self):
        return None


async def _scan_fetch(url, **kw):
    return EMBED_PAGE, "https://movies.example/watch/9", {}


_orig_fetch = net.fetch_text
net.fetch_text = _scan_fetch
try:
    cands = asyncio.run(M.scan_page("https://movies.example/watch/9", limit=8))
finally:
    net.fetch_text = _orig_fetch
emb = [c for c in cands if c.get("file_type") == "embed"]
assert emb and emb[0]["url"] == "https://filemoon.sx/e/qwerty", cands
assert emb[0]["player"] == "FileMoon" and emb[0]["origin"] == "embed"
print("✓ embeds: known-host iframe (even data-src) becomes a labelled hop target")

# ═══ FILE KIND: '…/clip.mp4/?download=true' still classifies as video ══════
assert fk.url_extension("https://x.test/get_file/1/abc/1/2/clip_720m.mp4/?download=true") == ".mp4"
assert fk.classify("https://x.test/get_file/1/abc/1/2/clip_720m.mp4/") == "video"
print("✓ filekind: trailing-slash CDN paths keep their extension")

# ═══ KVS decoder parity: identical to yt-dlp's GenericIE implementation ════
try:
    from yt_dlp.extractor.generic import GenericIE          # optional (dev) dep
except Exception:                                          # noqa: BLE001
    GenericIE = None
if GenericIE is not None:
    import random
    random.seed(11)
    checked = 0
    for _ in range(120):
        code = "".join(random.choice("0123456789") for _ in range(15))
        h = "".join(random.choice("0123456789abcdef") for _ in range(32))
        sample = f"function/0/https://host.test/get_file/9/{h}/1/2/2_720p.mp4/"
        try:
            reference = GenericIE._kvs_get_real_url(sample, "$" + code)
        except IndexError:
            continue          # yt-dlp itself cannot decode this synthetic code
        assert E.kvs_real_url(sample, code) == reference
        checked += 1
    assert checked > 20, checked
    print(f"✓ kvs: decoder matches yt-dlp's on {checked} random license/hash pairs")
else:
    print("· kvs parity: yt-dlp not installed, skipped")

# ═══ video.js may put `type` before `src` (both orders are honoured) ═══════
VJS2 = """<script>videojs('v').src({type: "application/x-mpegURL",
  src: "https://cdn.example/hls/second.m3u8"});</script>"""
assert any(c["url"] == "https://cdn.example/hls/second.m3u8"
           for c in S.candidates(VJS2, "https://unlisted-player.example/x"))
print("✓ families: video.js source object parsed in either key order")

# ═══ an adapter that cannot reach its API is not a broken analysis ═════════
async def _dead_fetch(url, **kw):
    raise RuntimeError("network down")


_orig_fetch = net.fetch_text
net.fetch_text = _dead_fetch
try:
    assert asyncio.run(A.resolve("https://www.aparat.com/v/yab6353")) is None
finally:
    net.fetch_text = _orig_fetch

# …and analyze() then continues down the normal ladder (yt-dlp / page scan)
async def _yt_media(url):
    return {"kind": "media", "url": url, "title": "from extractor",
            "formats": [{"height": 720, "label": "720p", "format": "22",
                         "codecs": ["mp4"], "fps": 0, "size": None}],
            "extractor": "Aparat", "formats_total": 1}, ""


_orig_dl2 = M._try_ytdlp
M._try_ytdlp = _yt_media
net.fetch_text = _dead_fetch
try:
    fallback = asyncio.run(M.analyze("https://www.aparat.com/v/yab6353"))
finally:
    M._try_ytdlp = _orig_dl2
    net.fetch_text = _orig_fetch
assert fallback["kind"] == "media" and fallback["title"] == "from extractor", fallback
print("✓ adapters: API outage degrades to the extractor instead of failing the link")

# ═══ packed alternatives: base64 configs + content-first meta tags ═════════
import base64                                          # noqa: E402

_CFG = 'var player={file:"https://cdn.example/v/b64_720p.mp4",hls:"https://cdn.example/hls/b64.m3u8"};'
_b64 = base64.b64encode(_CFG.encode()).decode()
b64_urls = [c["url"] for c in S.candidates(f'<script>eval(atob("{_b64}"))</script>',
                                          "https://unlisted-player.example/x")]
assert "https://cdn.example/hls/b64.m3u8" in b64_urls, b64_urls
assert "https://cdn.example/v/b64_720p.mp4" in b64_urls, b64_urls
rev_meta = S.candidates('<meta content="https://cdn.example/v/rev.mp4" property="og:video">',
                        "https://unlisted-player.example/x")
assert [c["url"] for c in rev_meta] == ["https://cdn.example/v/rev.mp4"], rev_meta
print("✓ obfuscation: atob() base64 configs and content-first og:video tags resolved")

# percent-encoded media URLs inside embed params / JSON (?u=, ?file=, …)
_pct_page = ('<iframe src="/embed?u=https%3A%2F%2Fcdn.example%2Fv%2Fpct_1080p.mp4'
             '%3Ftok%3Dabc%26x%3D1"></iframe>')
_pct = S.candidates(_pct_page, "https://unlisted-player.example/watch/1")
assert [c["url"] for c in _pct] == ["https://cdn.example/v/pct_1080p.mp4?tok=abc&x=1"], _pct
assert _pct[0]["height"] == 1080 and _pct[0]["ext"] == "mp4", _pct[0]
print("✓ obfuscation: percent-encoded stream URLs unwrapped from embed params")

# the wider embed-host table: every new player / file host is a hop target
for href in ("https://vidlink.pro/movie/550", "https://vidoza.net/embed-abc123.html",
             "https://sbplay2.com/e/xyz", "https://vidsrc.icu/embed/movie/550",
             "https://nepu.to/watch/550"):
    assert S.is_embed_url(href), href
    assert S.embed_host_for(href), href
print("✓ embeds: VidLink/Vidoza/StreamSB/VidSrc-mirror/Nepu recognised by host")

# ═══ END-TO-END: the 1porn.tv sample resolves to a 720p/480p download card ═
import httpx                                           # noqa: E402


class _Resp:
    def __init__(self, text="", url="", headers=None):
        self.text, self.status_code = text, 200
        self.headers = headers or {"content-type": "text/html"}
        self.url, self.content = url, text.encode()

    def raise_for_status(self):
        return None


def _future(value):
    loop = asyncio.new_event_loop()
    fut = loop.create_future()
    fut.set_result(value)
    loop.close()
    return fut


class _HtmlClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def head(self, url, **k):
        return _future(_Resp(PAGE_1PORN, url=url))

    def get(self, url, headers=None, **k):
        return _future(_Resp(PAGE_1PORN, url=url))


async def _no_extractor(url):
    return None, ""


async def _page_fetch(url, **kw):
    return PAGE_1PORN, "https://www.1porn.tv/videos/x/", {}


_orig_client, _orig_fetch = httpx.AsyncClient, net.fetch_text
_orig_yt3, _orig_ie3 = M._try_ytdlp, M.find_extractor
M._try_ytdlp, M.find_extractor = _no_extractor, (lambda u: "")
net.fetch_text = _page_fetch


httpx.AsyncClient = _HtmlClient
try:
    sample = asyncio.run(M.analyze("https://www.1porn.tv/videos/x/"))
finally:
    httpx.AsyncClient = _orig_client
    net.fetch_text = _orig_fetch
    M._try_ytdlp, M.find_extractor = _orig_yt3, _orig_ie3
assert sample["kind"] == "webmedia", sample
assert [f["height"] for f in sample["formats"]] == [720, 480], sample["formats"]
assert sample["site"] == "1Porn" and sample["referer"] == "https://www.1porn.tv/videos/x/"
assert all(f["url"].startswith("https://www.1porn.tv/get_file/9/") for f in sample["formats"])
print("✓ analyze: 1porn.tv page → webmedia card with 720p/480p (page kept as Referer)")

# ═══ REGISTRY: broad, unique, and every adapter is wired both ways ═════════
keys = [r.key for r in S.RECIPES]
assert len(keys) == len(set(keys)), "recipe keys must be unique"
domains = [d for r in S.RECIPES for d in r.domains]
assert len(domains) == len(set(domains)), "a domain must belong to exactly one recipe"
assert len(S.RECIPES) >= 300, len(S.RECIPES)
for key, name in (("xvideos", "XVideos"), ("pornhub", "Pornhub"), ("youtube", "YouTube"),
                  ("aparat", "Aparat"), ("filimo", "Filimo"), ("1porn", "1Porn"),
                  ("streamtape", "StreamTape"), ("vidsrc", "VidSrc"),
                  ("bilibili", "Bilibili"), ("twitch", "Twitch")):
    r = next(x for x in S.RECIPES if x.key == key)
    assert r.name == name and r.domains
assert S.recipe_for("https://de.xhamster.desi/videos/x").key == "xhamster"
assert S.recipe_for("https://www.1porn.tv/videos/x/").family == "kt_player"
assert S.recipe_for("https://unknown.example/a") is None
assert S.site_name("https://www.brand-new-tube.example/x") == "Brand New Tube"
assert [a["key"] for a in A.catalog()] == ["aparat", "filimo"]
print(f"✓ registry: {len(S.RECIPES)} recipes / {len(domains)} domains, unique, adapters wired")

print("\nALL COVERAGE TESTS PASSED")
