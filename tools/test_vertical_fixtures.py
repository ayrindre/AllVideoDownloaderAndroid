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
    def __init__(self, text, status=200):
        self.text, self.status_code = text, status
    def json(self): return json.loads(self.text)
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError(f"HTTP {self.status_code}")

class FakeClient:
    def __init__(self, routes): self.routes, self.calls = routes, []
    async def get(self, url, params=None, headers=None):
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
