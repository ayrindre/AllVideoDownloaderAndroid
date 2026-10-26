<div align="right">

**All Video Downloader** — یک‌کاره، دقیق، فارم‌پسند.

</div>

# All Video Downloader

One job, done properly: **paste any link that contains a video — get the file, at the quality you chose.**

The app used to be a dork-powered meta search *and* a downloader. It is now deliberately
one thing, and that one thing is engineered hard.

```
Windows → double-click run.bat      (venv + deps + FFmpeg auto-install, first run only)
any OS  → python run.py --no-open   (browser mode at http://127.0.0.1:8765)
```

## What "any link" actually covers

| The link looks like | What the engine does |
|---|---|
| YouTube / Vimeo / TikTok / ~1,900 sites | yt-dlp runs with **bare CLI defaults first** — the exact recipe that works in a terminal (no forced UA headers: those poisoned yt-dlp's per-client profiles). Only if the map comes back 480p-capped do android/tv and ios/mweb passes kick in, and **the client that answered is remembered** so the download reuses the same recipe. Quality chips carry **exact format IDs** (`137+140/…`) — "picked 1080p, got 480p" is structurally impossible. |
| A raw `.mp4/.mkv/.webm/…` URL | Content-type **and magic bytes** (`ftyp`/EBML/FLV/RIFF) are checked; streamed with HTTP Range resume through the built-in manager. No yt-dlp detour when there's nothing to detour from. |
| `.m3u8` / `.mpd` manifests | The master is fetched and **parsed locally**: every variant/representation becomes a selectable rung (height + bitrate, real rep-ids for DASH). Chosen rung → yt-dlp (muxes the separate audio track!); no yt-dlp → FFmpeg `-c copy` on exactly that variant playlist. |
| Playlist / channel / tube-gallery pages | Extracted flat (`in_playlist`): the **first entry** becomes the fully-analyzed card, the next 24 ride along under *"More from this playlist"* with per-entry Analyze / Download / Copy. Nothing gets silently truncated to one video. |
| A page that *plays* a video | Deep-scan: `og:video`, `<video>/<source>`, file anchors, Apache *index-of* listings (with sizes) — and when a video URL surfaces, the app **re-analyzes that URL** one level deep and hands you its real card, not a candidate list. |
| A page whose video lives in its **player config** — XVideos, XNXX, xHamster, TXXX, SpankBang, kt_player tubes, jwplayer/video.js, `__NEXT_DATA__`, JSON-LD | The document is de-escaped (`\/`, `\u002F`, `&amp;`) and mined for every media URL: `html5player.setVideoUrlHigh/Low/HLS`, `video_url` / `video_url_hd`, `sources:[{file:…}]`, escaped JSON, manifests. Ads, sprites and posters are scored out; the real files become **quality chips** (1080p / 720p / HLS), and the hosting page rides along as `Referer`. |
| A page that only exists as a **JavaScript app** — Aparat, Filimo | Those two publish their stream through an API, not in the HTML. A tiny per-site *adapter* asks that API directly: Aparat returns its whole CDN ladder (144p→1080p, with real file sizes); Filimo returns the signed HLS manifest, which is parsed into 1080p/720p/480p chips. Paywalls and login walls are stated in plain words instead of hiding behind a generic error. |
| An adult tube built on **KVS/kt_player** — 1porn.tv, PornTrex, JAVHD, TXXX… | KVS hides each file behind a permuted `get_file` path (`function/0/https://…/<hash>/clip_720p.mp4`). The permutation is derived from the page's `license_code`, and the app now reverses it locally (verified against yt-dlp's own decoder on random license/hash pairs), so the *real* 1080p/720p/480p URLs become chips — plus `video_url_text` labels, `get_file` download anchors and the `…mp4/?download=true` form. |
| A magnet | Honestly identified; copy it to your torrent client. (This app doesn't fake P2P.) |

Pages whose only video surface is a **cross-origin `<iframe>` player** are not dead
ends either: the scan records every player-looking iframe as an `embed` candidate and
the analyzer **hops into the best one** (files first, embeds second) — and now tries up
to three candidates instead of dying with the first expired mirror. File hosts and
multi-source front-ends are recognised by host, even when the URL says nothing:
StreamTape, DoodStream, MixDrop, FileMoon, StreamWish/StreamHide, VOE, Vidmoly,
MP4Upload, SendVid, UpStream, VidSrc, 2Embed, embed.su, SmashyStream, SuperEmbed,
MultiEmbed, plus YouTube/Vimeo/Dailymotion/OK.ru/VK/Rutube/Twitch/Kick/Facebook/
Instagram/TikTok/Bilibili/Aparat/Filimo player URLs.

Obfuscation is handled in-place, without a JavaScript engine: Dean-Edwards packed
scripts (`eval(function(p,a,c,k,e,d)…)`, the Filemoon/StreamWish family) are unpacked
and re-scanned, `atob("…")` base64 configs are decoded, percent-encoded stream URLs
(`?u=https%3A%2F%2F…%2Fclip.mp4`) are unwrapped, and the player dialects of
**video.js, Plyr, Clappr, Flowplayer, DPlayer, Shaka, jwplayer** — in either key order —
feed the same candidate pipeline as `html5player` and KVS. Quality words stored *next
to* a URL (`{"file": "…", "label": "1080p"}`, Pornhub's `mediaDefinitions` `quality`)
become the chip label, and a label from a neighbouring entry is never borrowed.

## When the extractor refuses — or lies about quality

A tube site is three moving parts: the page, the player config embedded in it, and
the CDN serving the file. yt-dlp knows the first two only while its extractor still
matches the site; the day the site ships a new player, extraction returns
*"Unable to extract…"* and a downloader that only trusts extractors dead-ends.
All Video Downloader no longer has that dead end — and it needs no per-site code
for it:

* **Extractor refused** → the page is deep-scanned. If the player lists files you
  get a complete **quality card** (marked *recovered after block*); if it links one
  manifest, that ladder is served. The page is kept as `Referer`.
* **Extractor lies about quality** (a 480p-only map on a site whose player offers
  1080p) → the taller file from the player config wins, and the card says so
  instead of pretending 480p is the ceiling.
* **Bot walls** — Cloudflare *"Just a moment"*, `403` for anything that is not a
  browser → every page fetch **and** every yt-dlp run retries with a real Chrome
  TLS fingerprint (`curl_cffi`), and the direct-http worker hands the file to that
  engine instead of failing. `GET /api/meta` reports whether impersonation is live;
  Settings → System shows it.
* **Unknown sites** → the same generic engine runs on *every* page. No site is
  "unsupported"; at worst it is unnamed.

Built-in recipes (`webfinder/core/sites.py` — **384 sites / 717 hostnames**,
`GET /api/sites` lists them, domain-matched including subdomains): adult tube sites and
networks (XVideos, XNXX, xHamster, Pornhub, RedTube, YouPorn, Tube8, TXXX, SpankBang,
Eporner, HQPorner, PornTrex, ThisVid, DrTuber, TNAFlix, JavHD, MissAV, Hanime, 1Porn,
AnyPorn, Vjav, Japan/Asian tubes, Gay/trans/hentai tubes…), file hosts and multi-source
embeds (StreamTape, DoodStream, MixDrop, FileMoon, StreamWish, VOE, VidSrc, 2Embed,
MEGA, Google Drive, Dropbox, Pixeldrain…), mainstream platforms (YouTube, Vimeo,
Dailymotion, OK.ru, VK, Rutube, Rumble, BitChute, Odysee, Twitch/Kick, X, Reddit,
TikTok, Instagram, Facebook, Bilibili, Douyin, Youku, iQIYI, Weibo, Niconico…), the
world's broadcasters (BBC, ITV, ZDF, ARD, France.tv, RAI, SVT, NRK, CBC, ABC/9Now,
Globoplay, Telemundo…) and Persian platforms (Aparat, Filimo, Namava, Namasha, Tamasha,
Dideo, Telewebion, Varzesh3, FilmNet, Shad…).

### Adding a site without touching the engine

```python
# webfinder/core/sites.py
_r("mynewtube", "MyNewTube", ("mynewtube.com", "mynewtube.net"), "kt_player")
```

When a site's stream is **not in the HTML at all** (the page is an empty app shell),
add an API bridge — that is what `webfinder/core/adapters.py` is for, and it is still
only two lines plus a parser:

```python
# webfinder/core/sites.py
_r("mysite", "MySite", ("mysite.com",), "generic", adapter="mysite")
```

Aparat and Filimo ship that way: a regex for the site's URL shapes, one JSON endpoint,
a parser that returns the ordinary card the analyzer already renders (and optional
`access_note` for paywalls / login walls). An adapter that cannot reach its API is
skipped silently, so a dead endpoint degrades to yt-dlp + the page scan instead of
breaking the link.

`generic` is the default and usually needs nothing else: any media URL in the HTML —
plain, escaped, inside JSON, inside a `<video>` tag — is already found. Pick a family
(`html5player`, `kt_player`, `jwplayer`) when the site labels its qualities in a way
worth keeping, or pass `patterns=(r"myPlayer\('([^']+)",)` for a shape the generic
pass cannot see. For a site yt-dlp already supports a recipe is optional: it adds the
friendly name and the page-based fallback. `python tools/recipe_probe.py <url>` shows
which recipe matched and what the engine finds — the fastest way to debug a new site.

Hotlink-guarded CDNs (a lot of file hosts and tube sites) get the hosting page sent as
**Referer** automatically — analyze found the file on a page, the download inherits it.
Failures are honest: a bot-walled platform returns the *actual* extractor error, **plus a
"Deep-scan anyway" button that digs the page for plain file links regardless** — and the
two fixes that work (browser cookies source; Settings → System → *Update yt-dlp now*,
mirroring the daily automatic refresh `run.py` performs at launch).

## "My terminal downloads 4K but the app offers 480p"

Two causes, both handled structurally now:

1. **Stale bundled copy.** The app's private yt-dlp (in its venv) ages a week =
   blocked clients = capped ladders. On launch it pip-upgrades itself daily — and if
   PyPI is unreachable (filtered networks), the app now **detects a newer `yt-dlp`
   on your PATH and drives that binary directly** for extraction *and* downloads
   (flag-mapped 1:1, progress streamed back through `--progress-template`).
   Terminal parity by construction. Settings → System shows which engine is live;
   *Update now* forces a refresh attempt.
2. **Chrome's cookie DB.** Since Chrome 127 (App-Bound Encryption) / while Chrome is
   running, `--cookies-from-browser chrome` can die with *"Could not copy Chrome
   cookie database"* — and that one browser quirk used to abort **every** analysis
   *and every* yt-dlp download. Now the cookie failure transparently reruns the
   whole client ladder anonymously **on both paths** (analyzer and downloader,
   module and system-CLI), the error card names the cause (close Chrome fully, or
   prefer `firefox`/`edge`), and raw ANSI/`ERROR: ERROR:` noise is stripped from
   every message shown. A failure is also **remembered for the session**: the DB
   cannot become readable twice, so the app stops re-reading it (that is what
   used to print the same `ERROR:` line for every single request) and goes
   straight to the anonymous path instead. **Settings → Video & capture →
   *Cookies file*** takes precedence over the browser for every engine — an
   exported `cookies.txt` always reads — and the **Check cookies** button reads
   the configured source locally (no network) to say exactly what is broken.
   When the chosen browser cannot be read, the app **switches to another browser
   on the same machine whose database does read** (Firefox never locks its own),
   says so, and *Fix cookies* makes that permanent in one click. A refused
   extractor is also no longer a dead end: the page
   gets scanned and if it links a `master.m3u8`/mp4, **that** becomes the card —
   quality ladder included, hosting page attached as Referer, with a green
   "recovered after block" note.

## Features that survived the pivot — and got better

- **Download manager** — pause/resume with Range resume, retry, per-job speed + global
  stats, FFmpeg worker for streams with `-c copy` (no re-encode), concurrency dial.
- **Network proxy** (Settings → Downloads) now routes *everything*: downloads, manifest
  fetches, page scans, yt-dlp, and the FFmpeg child process.
- **FFmpeg installs itself** into the app folder when missing (opt-out
  `WEBFINDER_NO_FFMPEG_INSTALL=1`).
- **Native frameless window** via pywebview/WebView2 (drag, maximize, folder picker);
  the sidebar's red **Exit** terminates the backend cleanly.
- Settings migrate automatically from `~/.webfinder` to `~/.avd` on first launch —
  retired search keys are dropped, never resurrected.

## Layout

```
run.py / run.bat            launcher (deps, FFmpeg bootstrap, yt-dlp daily refresh)
webfinder/
├─ api/                     REST routes: /analyze, /analyze/download, /downloads…, /system/exit
├─ config.py                ~/.avd/settings.json (+ one-shot migration)
├─ core/
│  ├─ media.py              THE brain: sniff → ladder → yt-dlp matrix → plan_download
│  ├─ cookies.py            cookies.txt vs browser source, failure memory, probe
│  ├─ embed.py              de-escape + mine media URLs (KVS, packed JS, atob, players)
│  ├─ sites.py              declarative recipe table (384 sites) + player families
│  ├─ adapters.py           API bridges for API-only sites (Aparat, Filimo)
│  ├─ net.py                browser headers, bot-wall detection, TLS impersonation
│  ├─ ytcli.py              system-yt-dlp bridge (cookies, impersonation, progress)
│  ├─ filekind.py           URL→file-type taxonomy (the search-less descendant of dorks)
│  ├─ downloader.py         job manager: http | hls | ytdlp workers
│  ├─ ffmpeg_tools.py       capture_stream (variant-aware), probe
│  └─ ffmpeg_setup.py       auto-fetch of the official FFmpeg build
├─ desktop/                 pywebview shell + js bridge
└─ web/                     frontend (Direct · Downloads · Settings)
tools/test_video_core.py    manifest ladders, sniffing, picker ids, page-rescan loopback
tools/test_coverage.py      adapters, KVS hashing, player dialects, embed hosts, registry
tools/test_desktop_contract.py
```

## Tests

```bash
python tools/test_video_core.py           # fixture-tested engine (no network)
python tools/test_coverage.py             # adapters, KVS, players, embeds, registry
python tools/test_desktop_contract.py     # pywebview bridge hygiene
python tools/test_cookies.py              # cookie source: file vs browser, failure memory
python tools/recipe_probe.py <url>        # which recipe matches, what it finds (needs network)
```

`test_coverage.py` pins the *new* breadth offline against real-shaped payloads: the
Aparat videohash JSON (six profiles with Persian size strings), Filimo's TV-partner
JSON (signed manifest → variant chips), a KVS page whose `function/0/` hash is
constructed the same way the CDN builds it (and cross-checked against yt-dlp's decoder),
jwplayer/video.js/Plyr/Clappr/Flowplayer/DPlayer/Shaka configs, a packed script, an
`atob` config, embed-host iframes, the full registry (unique keys/domains) and the
"API is down → fall back to the extractor" guarantee.

`test_video_core.py` covers the player-config engine with real-world-shaped
fixtures: `html5player.setVideoUrlHigh/Low/HLS`, kt_player `video_url`/`_hd`,
SpankBang `stream_data`, escaped `__NEXT_DATA__`, JSON-LD, jwplayer — plus ad and
poster rejection, directory-listing-vs-quality disambiguation, the refused-extractor
recovery card, the capped-map upgrade, and the 403 → yt-dlp hand-off.

*GPL-3.0 (see LICENSE). Not affiliated with Google, FFmpeg or yt-dlp. Download what you
have the right to download.*
