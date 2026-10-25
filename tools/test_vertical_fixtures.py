"""Offline parser fixtures for the new verticals (no network needed)."""
import asyncio
import json
import sys
sys.path.insert(0, ".")

from webfinder.core import verticals as v

# ── apibay JSON fixture ─────────────────────────────────────────────────────
APIBAY = json.dumps([
    {"ID": "9876543", "name": "Ubuntu.Server.24.04&#124;amd64", "link":
     "magnet:?xt=urn:btih:ABCDEF0123456789ABCDEF0123456789ABCDEF01",
     "size": "1234567890", "num_files": "3", "seeders": "412", "leechers": "77", "added": "2026-08-01 10:00:01"},
    {"ID": "9876542", "name": "Some Game PACK", "link": "magnet:?xt=urn:btih:1111222233334444555566667777888899990000&dn=x",
     "size": "999", "num_files": "1", "seeders": "5", "leechers": "1", "added": "2025-01-01 00:00:00"},
    {"ID": "1", "name": "no magnet here", "link": "https://not-a-magnet", "size": "1", "seeders": "0", "leechers": "0"},
])

class Resp:
    def __init__(self, text, status=200, headers=None):
        self.text, self.status_code = text, status
        self.headers = headers or {"content-type": "application/json"}
        self.url = "https://engine.example/search"
    def json(self): return json.loads(self.text)
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError(f"HTTP {self.status_code}")

class FakeClient:
    def __init__(self, routes): self.routes, self.calls = routes, []
    async def get(self, url, params=None, headers=None, cookies=None):
        self.calls.append(url)
        for frag, resp in self.routes.items():
            if frag in url: return resp
        raise RuntimeError(f"unrouted: {url}")

rows = asyncio.run(v._apibay(FakeClient({"apibay.org": Resp(APIBAY)}), "ubuntu server", 20))
assert len(rows) == 2, rows
assert rows[0]["title"] == "Ubuntu.Server.24.04|amd64"           # entity-unescaped
assert rows[0]["size_bytes"] == 1234567890 and rows[0]["seeders"] == 412
assert rows[0]["url"].startswith("magnet:") and "&tr=udp://" in rows[0]["url"]  # trackers augmented
assert rows[1]["url"] == "magnet:?xt=urn:btih:1111222233334444555566667777888899990000&dn=x&tr=" + v.TRACKERS
assert "apibay.org/t/9876543" in rows[0]["torrent_url"]
print("✓ apibay parser:", len(rows), "rows, magnet+stats ok, non-magnet row skipped")

# ── nyaa RSS fixture ────────────────────────────────────────────────────────
NYAA = """<?xml version="1.0"?><rss><channel>
<item><title>[Sub] Show S01E02 [1080p]</title><link>https://nyaa.si/view/555111</link>
<nyaa:infoHash>deadbeefdeadbeefdeadbeefdeadbeefdeadbeef</nyaa:infoHash>
<nyaa:size>858993459</nyaa:size><nyaa:seeders>42</nyaa:seeders><nyaa:leechers>7</nyaa:leechers></item>
<item><title>broken-no-hash</title><link>https://nyaa.si/view/555222</link></item>
</channel></rss>"""
rows = asyncio.run(v._nyaa(FakeClient({"nyaa.si": Resp(NYAA)}), "show", 20))
assert len(rows) == 2
assert rows[0]["url"].startswith("magnet:?xt=urn:btih:deadbeef") and "dn=%5BSub%5D" in rows[0]["url"]
assert rows[0]["seeders"] == 42 and rows[0]["size_bytes"] == 858993459
assert rows[0]["torrent_url"] == "https://nyaa.si/download/555111.torrent"
print("✓ nyaa parser: magnet built from hash, stats ok, hashless item falls back to page link")

# ── 1337x fixture ───────────────────────────────────────────────────────────
X = """
<tr><td class="tr3 t1"><article><h3><a href="/torrent/1234567/ubuntu-24-04-server/">Ubuntu 24.04 Server.iso</a></h3></article></td>
<td class="tr3">4.2 GB</td><td class="tr3 torrent-s"><span>1,205</span></td><td class="tr3 torrent-l"><span>98</span></td></tr>
<tr><td class="tr3 t1"><article><h3><a href="/torrent/7654321/other-thing/">Other &amp; Movie</a></h3></article></td>
<td class="tr3">700 MB</td></tr>"""
rows = asyncio.run(v._1337x(FakeClient({"1337x.to": Resp(X)}), "ubuntu", 20))
assert len(rows) == 2
assert rows[0]["title"] == "Ubuntu 24.04 Server.iso"
assert rows[0]["torrent_url"] == "https://1337x.to/torrent/1234567.torrent"
assert rows[0]["size_bytes"] == v._human_size("4.2 GB") == int(4.2 * 1024**3)
assert "Other & Movie" in rows[1]["title"]
print("✓ 1337x parser: rows, stable .torrent url, human-size decode")

# ── gutendex fixture ────────────────────────────────────────────────────────
GUT = json.dumps({"results": [
    {"title": "Dune Messiah", "authors": [{"name": "Frank Herbert"}], "download_count": 9001,
     "url": "http://www.gutenberg.org/ebooks/9999",
     "formats": {"application/epub+zip": "http://www.gutenberg.org/cache/epub/9999/9999.epub.images.zip",
                 "image/jpeg": "http://www.gutenberg.org/cache/epub/9999/9999.cover.medium.jpg",
                 "text/html": "http://www.gutenberg.org/ebooks/9999.html.images"}},
    {"title": "No Formats", "authors": [], "formats": {}},
]})
rows = asyncio.run(v._gutendex(FakeClient({"gutendex": Resp(GUT)}), "dune", 20))
assert len(rows) == 1 and rows[0]["url"].endswith(".zip")
assert rows[0]["publisher"] == "Frank Herbert" and "Dune Messiah" in rows[0]["title"]
assert rows[0]["thumb"].endswith(".jpg")
print("✓ gutendex parser: direct file url, cover, author")

# ── internet archive fixture (search + per-item metadata) ───────────────────
IAS = json.dumps({"response": {"docs": [{"identifier": "dunemessiah0000herb", "title": "Dune Messiah", "year": "1969"}]}})
IAM = json.dumps({"server": "ia801506.us.archive.org", "dir": "/12/items/x",
                  "files": [{"name": "dunemessiah0000herb.pdf", "size": "15000000"},
                            {"name": "dunemessiah0000herb_djvu.txt", "size": "900000"},
                            {"name": "__ia.tar", "size": "1"}]})
class SeqClient:
    def __init__(self): self.n = 0
    async def get(self, url, params=None, headers=None):
        if "advancedsearch" in url: return Resp(IAS)
        if "metadata" in url: return Resp(IAM)
        raise RuntimeError(url)
rows = asyncio.run(v._internet_archive(SeqClient(), "dune messiah", 10))
assert len(rows) == 1
assert rows[0]["url"] == "https://ia801506.us.archive.org/download/dunemessiah0000herb/dunemessiah0000herb.pdf"
assert rows[0]["size_bytes"] == 15000000 and rows[0]["year"] == "1969"
assert "services/img" in rows[0]["thumb"]
print("✓ Internet Archive parser: pdf preferred, direct download url, cover thumb")

# ── archive relevance gate ─────────────────────────────────────────────────
good = {"url": "https://mirror.example.org/pub/tools.7z", "title": "tools.7z", "snippet": ""}
dir_ = {"url": "https://host/files/", "title": "Index of /files — bigtoolkit.zip", "snippet": ""}
junk = {"url": "https://blog.example/what-is-a-zip", "title": "What is a ZIP file?", "snippet": "a zip is…"}
assert v._archive_relevant(good) and v._archive_relevant(dir_)
assert not v._archive_relevant(junk)
print("✓ archive gate: file urls + index-of listings pass, pages-about-zips drop")

# ── bing videos: current-JSON "murl" shape now matches (was anchor-attr only) ──
import re as _re
t = v._unesc("""m='{"murl":"https://video.example/clip.mp4?x=1","turl":"https://th/1","title":"Clip","length":"212"}'""")
hits = _re.findall(r'"(?:mediaurl|mediaUrl|contentUrl|murl)"\s*:\s*"(https?://[^"]+?\.(?:mp4|webm|mov|m4v|mkv|avi)(?:[^"]{0,90}))"', t)
assert hits == ["https://video.example/clip.mp4?x=1"], hits
print("✓ bing-videos murl-with-ext regex catches the current JSON shape")

# ── search_torrents merge: dedupe + seeders sort + min_seeds filter ─────────
class Multi:
    def __init__(self): pass
    async def get(self, url, params=None, headers=None):
        if "apibay" in url: return Resp(APIBAY)
        if "nyaa" in url: return Resp(NYAA)
        if "1337x" in url: return Resp(X)
        raise RuntimeError(url)
import types
orig = v._client
class Ctx:
    async def __aenter__(self): return Multi()
    async def __aexit__(self, *a): return False
v._client = lambda *a, **k: Ctx()
out = asyncio.run(v.search_torrents("ubuntu", {"min_seeds": "40"}, 30, False, ""))
v._client = orig
seeds_seq = [r["seeders"] for r in out["results"]]
assert out["results"] and all((r.get("seeders") or 0) >= 40 for r in out["results"])
assert seeds_seq == sorted(seeds_seq, reverse=True), seeds_seq
print("✓ search_torrents: merged", len(out["results"]), "across sources, min-seeds gate + health sort ok")

print("\nALL VERTICAL FIXTURE TESTS PASSED")


# ── YouTube videoRenderer fixture (video vertical) ─────────────────────────
YT_DATA = {"items": [{"sectionListRenderer": {"contents": [{"itemSectionRenderer": {"contents": [
    {"videoRenderer": {
        "videoId": "abc123",
        "title": {"runs": [{"text": "Hayedeh \u2013 Sobh e Delan (Live 1981)"}]},
        "lengthText": {"simpleText": "4:12"},
        "ownerText": {"runs": [{"text": "Rhythm of 60s"}]},
        "viewCountText": {"simpleText": "12,345,678 views"},
        "publishedTimeText": {"simpleText": "3 years ago"},
        "thumbnail": {"thumbnails": [{"url": "https://i.ytimg.com/vi/abc123/hq1.jpg"},
                                      {"url": "https://i.ytimg.com/vi/abc123/maxresdefault.jpg"}]},
    }},
    {"videoRenderer": {"videoId": "def456", "title": {"runs": [{"text": "short"}]}},
    }
]}}]}}]}
YT_HTML = '<html><body><script>var ytInitialData = ' + json.dumps(YT_DATA) + ';</script></body></html>'
rows = asyncio.run(v._youtube_videos(FakeClient({"youtube.com/results": Resp(YT_HTML, headers={"content-type": "text/html"})}), "hayedeh", 20, False))
assert len(rows) == 2, rows
r0 = rows[0]
assert r0["url"] == "https://www.youtube.com/watch?v=abc123"
assert r0["duration"] == 252, r0["duration"]                       # 4:12 → seconds
assert r0["thumb"].endswith("maxresdefault.jpg")                   # best thumbnail wins
assert r0["publisher"] == "Rhythm of 60s"
assert "views" in r0["snippet"]
print("✓ youtube source: videoRenderer walk, duration, maxres thumb, channel")

# ── Torlock fixture ─────────────────────────────────────────────────────────
TORLOCK = """<html><table>
<tr><td class="td6left"><a href="https://www.torlock.com/software/torrent/5047081/Windows-11-22H2.html">Windows 11 22H2 x64 Multilingual</a></td>
<td class="c1s">142</td><td class="c7s">3.5 GB</td>
<td><a href="magnet:?xt=urn:btih:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA">magnet</a></td></tr>
<tr><td class="td6left"><a href="/games/torrent/5047082/Old.Game.Edition.html">Old Game Edition</a></td>
<td class="c1s">7</td><td class="c7s">700 MB</td></tr>
</table></html>"""
rows = asyncio.run(v._torlock(FakeClient({"torlock.com": Resp(TORLOCK, headers={"content-type": "text/html"})}), "windows 11", 20))
assert len(rows) == 2, rows
assert rows[0]["url"].startswith("magnet:?xt=urn:btih:AAAA")           # magnet when present
assert rows[0]["seeders"] == 142 and rows[0]["size_bytes"] == int(3.5 * 1024**3)
assert rows[1]["url"].endswith("/download/5047082.torrent")             # .torrent file otherwise
assert rows[0]["torrent_url"].endswith("/download/5047081.torrent")
print("✓ torlock parser: magnet-first, .torrent fallback, seeds+size ok")

# ── Open Library (resolves IA ids to direct files) ─────────────────────────
OL = json.dumps({"docs": [
    {"key": "/works/OL1W", "title": "The C# Player's Guide", "author_name": ["RB Whitaker"],
     "first_publish_year": 2020, "cover_i": 123456, "ia": ["csharp_guide_2020"], "ebook_access": "borrowable"},
    {"key": "/works/OL2W", "title": "Metadata only book", "ia": [], "ebook_access": "none"},
]})
IAM = json.dumps({"server": "ia800000.us.archive.org", "dir": "/0/items/csharp_guide_2020",
                  "files": [{"name": "TheGuide_djvu.txt", "size": "90000"},
                            {"name": "TheGuide.pdf", "size": "8000000"},
                            {"name": "TheGuide.epub", "size": "2000000"}]})
rows = asyncio.run(v._openlibrary(FakeClient({"openlibrary.org/search.json": Resp(OL),
                                              "archive.org/metadata": Resp(IAM)}), "C#", 20))
assert len(rows) == 1, rows                                  # metadata-only rows skipped
r0 = rows[0]
assert r0["url"] == "https://ia800000.us.archive.org/download/csharp_guide_2020/TheGuide.epub"
assert r0["size_bytes"] == 2000000 and r0["engine"] == "openlibrary"
assert "covers.openlibrary.org" in r0["thumb"] and r0["publisher"] == "RB Whitaker"
print("✓ openlibrary: IA-direct EPUB preferred over PDF, cover + author mapped")

# ── Standard Ebooks OPDS ─────────────────────────────────────────────────────
SE = """<feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>The Great Gatsby — F. Scott Fitzgerald</title>
<id>https://standardebooks.org/ebooks/f-scott-fitzgerald/the-great-gatsby</id>
<author><name>F. Scott Fitzgerald</name></author>
<link href="/ebooks/f-scott-fitzgerald/the-great-gatsby/downloads/epub" type="application/epub+zip"/>
<link href="/url/cover.jpg" type="image/jpeg"/></entry>
<entry><title>No links here</title><id>x</id></entry>
</feed>"""
rows = asyncio.run(v._standardebooks(FakeClient({"standardebooks.org": Resp(SE, headers={"content-type": "application/atom+xml"})}), "gatsby", 20))
assert len(rows) == 1, rows
assert rows[0]["url"] == "https://standardebooks.org/ebooks/f-scott-fitzgerald/the-great-gatsby/downloads/epub"
assert rows[0]["file_type"] == "epub" and rows[0]["is_direct"] is True
print("✓ standard ebooks: OPDS entries → direct epub URLs, linkless entries skipped")

# ── F-Droid JSON API ─────────────────────────────────────────────────────────
FD = json.dumps({"count": 1, "packages": [{
    "packageName": "org.thunderdog.challegram", "name": "Telegram X", "summary": "An unofficial Telegram.",
    "versions": [{"versionCode": 100, "versionName": "0.26.1", "apk": "https://f-droid.org/repo/org.thunderdog.challegram_100.apk"},
                 {"versionCode": 110, "versionName": "0.27.0", "apk": "https://f-droid.org/repo/org.thunderdog.challegram_110.apk"}]}]})
rows = asyncio.run(v._fdroid(FakeClient({"search.f-droid.org": Resp(FD)}), "telegram", 20))
assert len(rows) == 1 and rows[0]["url"].endswith("_110.apk")     # newest versionCode wins
assert rows[0]["file_type"] == "apk" and rows[0]["publisher"] == "org.thunderdog.challegram"
print("✓ f-droid: latest version picked, direct APK url")

# ── GitHub Releases ──────────────────────────────────────────────────────────
GH_Q = json.dumps({"items": [{"full_name": "winamp-classic/winamp", "html_url": "https://github.com/winamp-classic/winamp",
                              "owner": {"avatar_url": "https://avatars.githubusercontent.com/u/1.png"}}]})
GH_R = json.dumps({"tag_name": "v3.7", "body": "Final release.",
                   "assets": [{"name": "WinampSetup.exe", "size": 30000000, "download_count": 9999,
                               "browser_download_url": "https://github.com/winamp-classic/winamp/releases/download/v3.7/WinampSetup.exe"},
                              {"name": "src.tar.gz", "size": 1, "browser_download_url": "https://github.com/x/y/releases/download/v1/src.tar.gz"}]})
rows = asyncio.run(v._github_releases(FakeClient({"search/repositories": Resp(GH_Q), "releases/latest": Resp(GH_R)}), "winamp", 20))
assert len(rows) == 1, rows                                        # tar.gz source filtered out
assert rows[0]["url"].endswith("WinampSetup.exe") and rows[0]["file_type"] == "exe"
assert rows[0]["size_bytes"] == 30000000 and rows[0]["is_direct"] is True
print("✓ github: real installer assets only, size + direct url ok")

# ── gate regexes: the two leaks from the field report ───────────────────────
assert v._archive_relevant({"url": "https://mirror.example/winamp/winamp5666_full_all.zip", "title": "Index of /winamp", "snippet": ""})
assert not v._archive_relevant({"url": "https://linkedin.com/in/robert-dodoo", "title": "Robert Dodoo – LinkedIn", "snippet": "Accessioner profile"})
assert v._FILE_EXT_RX["video"].search("https://files.example.org/a/b/clip.MP4")
assert not v._FILE_EXT_RX["video"].search("https://dictionary.example.org/langdict/hide")
assert v._PLAYABLE_HOST_RX.search("https://www.youtube.com/watch?v=abc123")
assert v._FILE_EXT_RX["app"].search("https://github.com/o/r/releases/download/v/Tool-setup.exe")
print("✓ gates: archive + video + app extension regexes behave (LinkedIn-style junk never passes)")


# ═══ ROUND 8: new web engines ══════════════════════════════════════════════
from webfinder import engines as E

SP = """<html><ol id='results'>
<li><a class="result-link" href="https://mirror.example/winamp/winamp.zip">Winamp zip mirror</a></li>
<li><a class="w-gl__result-url" href="https://files.zone/winamp-installer.exe">installer</a></li>
<li><a class="result-link" href="https://www.startpage.com/adnqs?x=1">ad</a></li>
</ol></html>"""
rows = asyncio.run(E.search_startpage(FakeClient({"startpage.com": Resp(SP, headers={"content-type": "text/html"})}), "q", 10))
assert [r["url"] for r in rows] == ["https://mirror.example/winamp/winamp.zip", "https://files.zone/winamp-installer.exe"], rows
print("✓ startpage parser: results extracted, startpage-internal links dropped")

BR = '<html><div id="results"><a class="h snippet-title" href="https://a.example/x"><div>Title One</div></a><a class="h snippet-title" href="https://b.example/y"><div>Title Two</div></a></div></html>'
rows = asyncio.run(E.search_brave(FakeClient({"brave.com": Resp(BR, headers={"content-type": "text/html"})}), "q", 10))
assert len(rows) == 2 and rows[0]["title"] == "Title One"
print("✓ brave parser: web anchors only")

EC = '<html><div class="result"><a data-mdurl="https://deep.example/file.mp4" href="/out/1"><div class="result__title"><span>Song</span></div></a></div></html>'
rows = asyncio.run(E.search_ecosia(FakeClient({"ecosia.org": Resp(EC, headers={"content-type": "text/html"})}), "q", 10))
assert len(rows) == 1 and rows[0]["url"] == "https://deep.example/file.mp4" and rows[0]["title"] == "Song"
print("✓ ecosia parser: data-mdurl + title block")

MG = ('<html><div class="main"><a class="result-link" href="https://old-search.marginalia.nu/redirect?url=https%3A%2F%2Farchive.ssite.org%2Fpub%2Fwinamp.zip&ctx=1">'
      '<div class="result-title">Winamp Archive</div></a></div></html>')
rows = asyncio.run(E.search_marginalia(FakeClient({"marginalia": Resp(MG, headers={"content-type": "text/html"})}), "q", 10))
assert len(rows) == 1 and rows[0]["url"] == "https://archive.ssite.org/pub/winamp.zip"
print("✓ marginalia parser: redirect?url= unwrapped")

# cooldown bookkeeping
E._note_block("mojeek", "Mojeek anti-bot (403)")
assert E.cooling_left("mojeek") >= 39
E._note_block("bing", "some parse failure")
assert E.cooling_left("bing") == 0
print("✓ engine cooldown: blocks cool down, parse errors don't")

# ═══ deepscan rescue inside the video dork fallback ════════════════════════
from webfinder.core import media as M

class PageClient(FakeClient):
    pass

_orig_engines = dict(E.ENGINES)
async def _fake_startpage(client, q, lim, safe=False):
    return [{"url": "https://blog.example/winamp-review", "title": "Review", "snippet": "", "domain": "blog.example"}]
async def _raise(client, q, lim, safe=False):
    raise RuntimeError("down")
E.ENGINES.update({"startpage": _fake_startpage})
for n in ("google", "bing", "brave", "duckduckgo", "ecosia", "mojeek", "marginalia"):
    if n in E.ENGINES and n != "startpage":
        E.ENGINES[n] = _raise if n in ("google",) else E.ENGINES[n]
_orig_scan = M.scan_page
async def _fake_scan(url, limit=14, wanted=None):
    import re as _re
    cand = {"url": "https://blog.example/media/winamp-clip.mp4", "filename": "winamp-clip.mp4",
            "file_type": "video", "size_bytes": 12345678}
    if wanted is not None and not wanted.search(cand["url"]):
        return []
    return [cand]
M.scan_page = _fake_scan
try:
    rows = asyncio.run(v._dork_files_fallback(None, "winamp", "video", 10, False))
finally:
    M.scan_page = _orig_scan
    E.ENGINES.clear(); E.ENGINES.update(_orig_engines)
assert len(rows) == 1 and rows[0]["engine"] == "deepscan" and rows[0]["is_direct"], rows
assert rows[0]["page"] == "https://blog.example/winamp-review"      # provenance kept
print("✓ deepscan rescue: review page → harvested .mp4 with page provenance")

# ═══ AUDIO: ccmixter + IA-audio kinds ══════════════════════════════════════
CC = json.dumps({"items": [{
    "title": "Sunny Cut", "itemurl": "https://ccmixter.org/files/u1/999",
    "user": {"name": "DJ One"}, "albumImage": "https://ccmixter.org/img/a.png",
    "licenseName": "Attribution", "duration": 195.6,
    "fileinfo": {"mp3": {"download_url": "https://ccmixter.org/content/u1/999.mp3", "size": "3100", "duration": 195.6}}}]}
)
rows = asyncio.run(v._ccmixter(FakeClient({"api.ccmixter.org": Resp(CC)}), "sunny", 10))
assert len(rows) == 1 and rows[0]["url"].endswith(".mp3")
assert rows[0]["size_bytes"] == 3100 * 1024 and rows[0]["duration"] == 195
print("✓ ccmixter: direct mp3 + KB→bytes + duration int")

IAX = json.dumps({"server": "ia900000.us.archive.org", "files": [
    {"name": "show01.flac", "size": "500000000"}, {"name": "show01.mp3", "size": "90000000"},
    {"name": "book.pdf", "size": "3000000"}]})
row = asyncio.run(v._ia_resolve(FakeClient({"archive.org/metadata": Resp(IAX)}), "show01", "Live Show",
                                kinds=v.AUDIO_KINDS))
assert row["url"].endswith("/show01.mp3"), row           # mp3 ranks first in AUDIO_KINDS
print("✓ ia audio resolve: file picked from AUDIO_KINDS:", row["url"].rsplit("/", 1)[-1])

# ═══ ytdlp picker: real format ids ride through the selector ════════════════
import types
fake_yt = types.ModuleType("yt_dlp")
INFO = {"title": "t", "extractor_key": "Youtube", "formats": [
    {"format_id": "399", "ext": "mp4", "vcodec": "av01.0.19M.08", "acodec": "none", "height": 2160, "tbr": 9000, "fps": 60},
    {"format_id": "299", "ext": "mp4", "vcodec": "avc1.640028", "acodec": "none", "height": 1080, "tbr": 4000},
    {"format_id": "137", "ext": "mp4", "vcodec": "avc1.640028", "acodec": "none", "height": 1080, "tbr": 6500},
    {"format_id": "140", "ext": "m4a", "vcodec": "none", "acodec": "mp4a.40.2", "abr": 129},
    {"format_id": "18", "ext": "mp4", "vcodec": "avc1.42001E", "acodec": "mp4a.40.2", "height": 360, "tbr": 600},
]}
class _YDL:
    def __init__(self, opts): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def extract_info(self, url, download=False): return INFO
fake_yt.YoutubeDL = _YDL
sys.modules.setdefault("yt_dlp_bak", sys.modules.get("yt_dlp"))
sys.modules["yt_dlp"] = fake_yt
media_obj, err = M._ytdlp_extract("https://youtu.be/x")
sel = {f["height"]: f["format"] for f in media_obj["formats"]}
assert "137+140/18" in sel[1080] or "137+140" in sel[1080], sel
assert "399+140" in sel[2160], sel
print("✓ picker format strings use real ids:", sel[1080], "|", sel[2160])

# ═══ cancel removes the job (and a dead worker can't revive it) ════════════
from webfinder.core.downloader import DownloadManager, DownloadJob
events = []
m = DownloadManager.__new__(DownloadManager)
m.jobs, m.order, m._emit = {}, [], (lambda evt: events.append(evt))
j = DownloadJob(url="https://x/a.bin", kind="sim", title="a"); j.id = "j1"
m.jobs["j1"] = j; m.order.append("j1")
assert m.cancel("j1") is True
assert "j1" not in m.jobs, "queued job must vanish on cancel"
assert any(e["type"] == "jobs.list" for e in events)
j.publish_ref = None
m.publish(j)                                    # zombie publish after removal → silent
assert not any(e["type"] == "job.update" and e["payload"].get("id") == "j1" for e in events[1:]), "revived!"
print("✓ cancel semantics: queued-cancel removes row; removed job can't republish")


# ═══ ROUND 8: new web engines ══════════════════════════════════════════════
from webfinder import engines as E

SP = """<html><ol id='results'>
<li><a class="result-link" href="https://mirror.example/winamp/winamp.zip">Winamp zip mirror</a></li>
<li><a class="w-gl__result-url" href="https://files.zone/winamp-installer.exe">installer</a></li>
<li><a class="result-link" href="https://www.startpage.com/adnqs?x=1">ad</a></li>
</ol></html>"""
rows = asyncio.run(E.search_startpage(FakeClient({"startpage.com": Resp(SP, headers={"content-type": "text/html"})}), "q", 10))
assert [r["url"] for r in rows] == ["https://mirror.example/winamp/winamp.zip", "https://files.zone/winamp-installer.exe"], rows
print("✓ startpage parser: results extracted, startpage-internal links dropped")

BR = '<html><div id="results"><a class="h snippet-title" href="https://a.example/x"><div>Title One</div></a><a class="h snippet-title" href="https://b.example/y"><div>Title Two</div></a></div></html>'
rows = asyncio.run(E.search_brave(FakeClient({"brave.com": Resp(BR, headers={"content-type": "text/html"})}), "q", 10))
assert len(rows) == 2 and rows[0]["title"] == "Title One"
print("✓ brave parser: web anchors only")

EC = '<html><div class="result"><a data-mdurl="https://deep.example/file.mp4" href="/out/1"><div class="result__title"><span>Song</span></div></a></div></html>'
rows = asyncio.run(E.search_ecosia(FakeClient({"ecosia.org": Resp(EC, headers={"content-type": "text/html"})}), "q", 10))
assert len(rows) == 1 and rows[0]["url"] == "https://deep.example/file.mp4" and rows[0]["title"] == "Song"
print("✓ ecosia parser: data-mdurl + title block")

MG = ('<html><div class="main"><a class="result-link" href="https://old-search.marginalia.nu/redirect?url=https%3A%2F%2Farchive.ssite.org%2Fpub%2Fwinamp.zip&ctx=1">'
      '<div class="result-title">Winamp Archive</div></a></div></html>')
rows = asyncio.run(E.search_marginalia(FakeClient({"marginalia": Resp(MG, headers={"content-type": "text/html"})}), "q", 10))
assert len(rows) == 1 and rows[0]["url"] == "https://archive.ssite.org/pub/winamp.zip"
print("✓ marginalia parser: redirect?url= unwrapped")

# cooldown bookkeeping
E._note_block("mojeek", "Mojeek anti-bot (403)")
assert E.cooling_left("mojeek") >= 39
E._note_block("bing", "some parse failure")
assert E.cooling_left("bing") == 0
print("✓ engine cooldown: blocks cool down, parse errors don't")

# ═══ deepscan rescue inside the video dork fallback ════════════════════════
from webfinder.core import media as M

class PageClient(FakeClient):
    pass

_orig_engines = dict(E.ENGINES)
async def _fake_startpage(client, q, lim, safe=False):
    return [{"url": "https://blog.example/winamp-review", "title": "Review", "snippet": "", "domain": "blog.example"}]
async def _raise(client, q, lim, safe=False):
    raise RuntimeError("down")
E.ENGINES.update({"startpage": _fake_startpage})
for n in ("google", "bing", "brave", "duckduckgo", "ecosia", "mojeek", "marginalia"):
    if n in E.ENGINES and n != "startpage":
        E.ENGINES[n] = _raise if n in ("google",) else E.ENGINES[n]
_orig_scan = M.scan_page
async def _fake_scan(url, limit=14, wanted=None):
    import re as _re
    cand = {"url": "https://blog.example/media/winamp-clip.mp4", "filename": "winamp-clip.mp4",
            "file_type": "video", "size_bytes": 12345678}
    if wanted is not None and not wanted.search(cand["url"]):
        return []
    return [cand]
M.scan_page = _fake_scan
try:
    rows = asyncio.run(v._dork_files_fallback(None, "winamp", "video", 10, False))
finally:
    M.scan_page = _orig_scan
    E.ENGINES.clear(); E.ENGINES.update(_orig_engines)
assert len(rows) == 1 and rows[0]["engine"] == "deepscan" and rows[0]["is_direct"], rows
assert rows[0]["page"] == "https://blog.example/winamp-review"      # provenance kept
print("✓ deepscan rescue: review page → harvested .mp4 with page provenance")

# ═══ AUDIO: ccmixter + IA-audio kinds ══════════════════════════════════════
CC = json.dumps({"items": [{
    "title": "Sunny Cut", "itemurl": "https://ccmixter.org/files/u1/999",
    "user": {"name": "DJ One"}, "albumImage": "https://ccmixter.org/img/a.png",
    "licenseName": "Attribution", "duration": 195.6,
    "fileinfo": {"mp3": {"download_url": "https://ccmixter.org/content/u1/999.mp3", "size": "3100", "duration": 195.6}}}]}
)
rows = asyncio.run(v._ccmixter(FakeClient({"api.ccmixter.org": Resp(CC)}), "sunny", 10))
assert len(rows) == 1 and rows[0]["url"].endswith(".mp3")
assert rows[0]["size_bytes"] == 3100 * 1024 and rows[0]["duration"] == 195
print("✓ ccmixter: direct mp3 + KB→bytes + duration int")

IAX = json.dumps({"server": "ia900000.us.archive.org", "files": [
    {"name": "show01.flac", "size": "500000000"}, {"name": "show01.mp3", "size": "90000000"},
    {"name": "book.pdf", "size": "3000000"}]})
row = asyncio.run(v._ia_resolve(FakeClient({"archive.org/metadata": Resp(IAX)}), "show01", "Live Show",
                                kinds=v.AUDIO_KINDS))
assert row["url"].endswith("/show01.mp3"), row           # mp3 ranks first in AUDIO_KINDS
print("✓ ia audio resolve: file picked from AUDIO_KINDS:", row["url"].rsplit("/", 1)[-1])

# ═══ ytdlp picker: real format ids ride through the selector ════════════════
import types
fake_yt = types.ModuleType("yt_dlp")
INFO = {"title": "t", "extractor_key": "Youtube", "formats": [
    {"format_id": "399", "ext": "mp4", "vcodec": "av01.0.19M.08", "acodec": "none", "height": 2160, "tbr": 9000, "fps": 60},
    {"format_id": "299", "ext": "mp4", "vcodec": "avc1.640028", "acodec": "none", "height": 1080, "tbr": 4000},
    {"format_id": "137", "ext": "mp4", "vcodec": "avc1.640028", "acodec": "none", "height": 1080, "tbr": 6500},
    {"format_id": "140", "ext": "m4a", "vcodec": "none", "acodec": "mp4a.40.2", "abr": 129},
    {"format_id": "18", "ext": "mp4", "vcodec": "avc1.42001E", "acodec": "mp4a.40.2", "height": 360, "tbr": 600},
]}
class _YDL:
    def __init__(self, opts): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def extract_info(self, url, download=False): return INFO
fake_yt.YoutubeDL = _YDL
sys.modules.setdefault("yt_dlp_bak", sys.modules.get("yt_dlp"))
sys.modules["yt_dlp"] = fake_yt
media_obj, err = M._ytdlp_extract("https://youtu.be/x")
sel = {f["height"]: f["format"] for f in media_obj["formats"]}
assert "137+140/18" in sel[1080] or "137+140" in sel[1080], sel
assert "399+140" in sel[2160], sel
print("✓ picker format strings use real ids:", sel[1080], "|", sel[2160])

# ═══ cancel removes the job (and a dead worker can't revive it) ════════════
from webfinder.core.downloader import DownloadManager, DownloadJob
events = []
m = DownloadManager.__new__(DownloadManager)
m.jobs, m.order, m._emit = {}, [], (lambda evt: events.append(evt))
j = DownloadJob(url="https://x/a.bin", kind="sim", title="a"); j.id = "j1"
m.jobs["j1"] = j; m.order.append("j1")
assert m.cancel("j1") is True
assert "j1" not in m.jobs, "queued job must vanish on cancel"
assert any(e["type"] == "jobs.list" for e in events)
j.publish_ref = None
m.publish(j)                                    # zombie publish after removal → silent
assert not any(e["type"] == "job.update" and e["payload"].get("id") == "j1" for e in events[1:]), "revived!"
print("✓ cancel semantics: queued-cancel removes row; removed job can't republish")
