# All Video Downloader — architecture notes

One promise: **any link containing a video → downloadable file, chosen quality.**

```
run.py ──▶ webfinder.app:create_app() ──▶ FastAPI ─┬─ /api/*        (webfinder/api)
   │  (deps check, FFmpeg bootstrap,               ├─ /ws           (WsHub ⇄ DownloadManager)
   │   daily yt-dlp pip refresh)                   └─ /static, /    (web/ frontend)
```

## Link engine — `core/media.py :: analyze(url)`

Resolution order, each stage proven and never guessed:

0. **site adapter** (`core/adapters.py`) — for the handful of sites whose page is an
   empty app shell and whose stream exists only behind a JSON endpoint: Aparat
   (`/etc/api/video/videohash/<id>` → every CDN profile 144p…1080p with sizes) and
   Filimo (`/api/fa/v1/partner/TV/watch/uid/<uid>` → the time-signed HLS manifest,
   which stage 2 turns into a variant ladder). Adapters run **before** yt-dlp because
   one request answers the whole question; a failing endpoint degrades silently to the
   normal ladder, and paywalls/login walls become an `access_note` instead of an error.
1. **magnet** → identified, copy-only (explained in UI).
2. **`.m3u8`/`.mpd`** → `parse_m3u8_master` / `parse_mpd_master` build the variant
   ladder (height · bandwidth · rep-id) + ffprobe info → UI quality chips.
3. **yt-dlp registry** — any site with an extractor. `_ytdlp_extract` runs up to
   **three client passes** (android+tv, ios+mweb, web), stops at the first map with
   anything above 480p, merges the rest by format-id union. The picker builder
   rounds heights to the canonical ladder and emits `"137+140/bestvideo[height<=1080]/…"`
   — **real ids first**, so the downloaded file matches the clicked chip.
4. **Extractor found but blocked** → `kind:"media_error"` carrying the raw yt-dlp
   message + fix hints (cookies source / restart after the daily refresh).
5. **Silent URL** → HEAD/ranged-GET probe: content-type, then **magic bytes**
   (`ftyp`, EBML, `FLV`, RIFF/AVI, MPEG-PS) via `sniff_container`. Lying
   `octet-stream` servers can't hide an MP4.
6. **Page** → `scan_page` (og:video/twitter:player/schema.org, `<video>/<source>` and
   every lazy `data-src|data-hls|data-mp4|data-video|…` spelling, file anchors incl.
   `…mp4/?download=true`, index-of listings with sizes, iframe players) **plus the
   player-config engine**: `core/embed.py` de-escapes the document (`\/`, `\u002F`,
   `\u0022`, `&amp;`) and mines every media URL —
   `html5player.setVideoUrlHigh/Low/HLS`, kt_player/KVS
   `video_url`/`_hd`/`_alt_url*`, jwplayer, video.js, Plyr, Clappr, Flowplayer,
   DPlayer, Shaka `manifestUri`, escaped JSON, `__NEXT_DATA__`, JSON-LD, meta/link/
   attribute announcements — while `core/sites.py` labels the family and names the
   site. Three deobfuscation layers run first, in this order:
   * **KVS** — a `function/0/https://…/<32 chars>/clip.mp4` slot is permuted with the
     page's `license_code`; the same reversible mapping yt-dlp uses is applied locally
     (so the scrambled URL is never offered), and `video_url_text` becomes the label.
   * **packed JS** — `eval(function(p,a,c,k,e,d)…)` payloads (Filemoon/StreamWish
     family) are unpacked and re-scanned.
   * **`atob("…")`** — base64 player configs are decoded.
   * **percent-encoding** — `?u=https%3A%2F%2F…%2Fclip.mp4` params are unwrapped
     (and only the inner absolute URL is kept, never the wrapper path).
   Quality words sitting next to a URL (`{"file": …, "label": "1080p"}`,
   `mediaDefinitions` `quality`) become the chip label; a label is only borrowed from
   the same object. Ad hosts, sprites and posters are scored out; tag-attribute URLs
   stay owned by the anchor/video/og passes so a directory listing is never sold as
   "qualities of one video".
7. **`webmedia` card** — when the player config exposed ≥2 real files, the
   analyzer returns them as a quality ladder (manifests first, then tallest)
   with the page as `Referer`. This is the generic answer for sites whose
   extractor is missing or refused (XVideos & friends) — no per-site code.
8. **yt-dlp rescue passes** — a refused extractor first tries the player config
   (`recovered_after_block`); a *capped* map (≤480p) on a named player family is
   upgraded from the page's own files (`upgraded_from_extractor`). Bot-wall
   refusals (`403`/Cloudflare) trigger one extra pass with a Chrome TLS
   fingerprint (`curl_cffi`, see `core/net.py`).

`plan_download` converts an analyze payload into enqueue kwargs:
media→`ytdlp` (with chosen format), stream→`ytdlp` (variant selector; ffmpeg fallback
via `meta.variant_url` when yt-dlp is absent), file→`http`.

## Workers — `core/downloader.py`

| kind | path |
|---|---|
| `http` | httpx stream with a full browser header set, 256 KB chunks, `Range` resume, size reconciliation, ~4 events/s. A CDN `401/403/406/429` is not fatal: the job is handed to `ytdlp` (TLS impersonation + Referer), which is exactly what hotlink guards check. |
| `ytdlp` | thread: fixed `outtmpl` stem, hook→progress, pause via `_pause` event, `android/tv→web` options attempts, cookies + proxy from settings; refusal passes retry without cookies (Chrome DB) and then with `--impersonate chrome` when the site answers 403/Cloudflare |
| `hls` | `ffmpeg_tools.capture_stream`: `meta.variant_url` if the user picked a rung, `-c copy` + `aac_adtstoasc` + `+faststart`, progress from `-progress pipe`, proxy env forwarded |

**Cancel = remove**: `cancel()` marks `_drop`, the worker self-removes on unwind;
`publish()` is muted for `_removed` jobs so a dying worker can never revive its row.

## Extension layer — `core/embed.py`, `core/sites.py`, `core/net.py`

`embed` is site-agnostic (any URL-shaped media in the document, ranked),
`sites` is one declarative line per site (name + hostnames + player family +
optional extraction patterns + optional adapter), `adapters` holds the few
API bridges that need code (Aparat, Filimo) as *pure parser + thin fetcher* pairs,
`net` supplies browser-grade requests and the `curl_cffi` TLS-impersonation
fallback. `sites.EMBED_HOSTS` recognises file hosts and cross-origin players by
host, so an iframe whose URL says nothing useful still counts as a hop target —
and a page's first candidates are walked (three deep) instead of dying with the
first expired mirror. Adding a site never touches the analyzer;
`GET /api/sites` and `tools/recipe_probe.py` expose the registry (the probe now
also prints the matched adapter and embed host).

## Cookies — `core/cookies.py` (one policy, four call sites)

Every engine used to reach into `settings["ytdlp_browser_cookies"]` on its own.
That produced the worst failure mode in the app: Chrome keeps its cookie DB
locked (and 127+ App-Bound-encrypts it), so *every* request that asked for
cookies failed the same way, twice (original + anonymous retry), printing
`ERROR: Could not copy Chrome cookie database` once per attempt.

One module now answers "which cookies?" for `media.py` (yt-dlp module),
`ytcli.py` (system yt-dlp CLI) and `downloader.py` (the job worker):

```
settings.cookies_file ──(exists, has rows)──► --cookies <file>   (always wins)
settings.ytdlp_browser_cookies ──► --cookies-from-browser <b>    (unless it failed)
neither / failed ──► no flags (anonymous)
```

- `mark_browser_failure(msg)` remembers the first unreadable-DB error for the
  process, so later requests skip the read instead of paying its timeout again;
  changing the setting in Settings (`PUT /api/settings`) or a successful
  `probe()` clears the memo.
- `strip_flags(argv)` is the anonymous retry path (drops every cookie flag and
  its value, keeps the URL).
- `probe()` reads the source **locally** (Netscape file parser, or yt-dlp's own
  cookie extractor) and returns one actionable sentence. It backs
  `GET /api/cookies/probe` — the *Check cookies* button in Settings.
- `auto_browser()`/`active_browser()` handle the realistic Windows case: the
  browser the user picked is the one whose DB is locked. Every other browser is
  probed once (cached), and a readable one is used automatically — extraction
  retries with it. `POST /api/cookies/use-best` plus `use_best()` turn that into
  a saved setting (the *Fix cookies* button).
- A 401 from a site is a login wall, not a broken cookie store:
  `mark_browser_failure()` refuses to remember anything unless a browser source
  is configured *and* the message is about copying/decrypting the database.

## Settings — `config.py`

`~/.avd/settings.json`; one-shot migration from `~/.webfinder`; retired search keys
(`engines`, `result_limit`, `safe_search`, `resolve_pages`, `demo_mode`) are stripped
on load — a stale file can't resurrect the removed module. `PUT /api/settings` accepts
only keys present in the snapshot.

## Tests — `tools/`

`test_video_core.py` (manifests, sniffing, picker ids, page loopback) and
`test_coverage.py` (Aparat/Filimo payloads, KVS hash round-trip cross-checked
against yt-dlp, player dialects, packed/atob obfuscation, embed hosts, registry
uniqueness, adapter-outage fallback) are both offline and fixture-driven;
`recipe_probe.py` is the live debugging entry point for a single URL.

## Build — `build/` + `build.bat`

`build/webfinder.spec` is the single PyInstaller recipe: `web/` is bundled as data,
every `webfinder.*` module is a hidden import, yt-dlp's extractor tree is collected
whole, and `build/icon.ico` is passed to `EXE(...)` so the packaged binary carries the
app mark. That icon is **generated**, not stored art: `tools/make_icon.py` renders a
1024 px master (violet→blue accent gradient + the sidebar's download arrow) and emits
a ten-frame `.ico` (16 → 256 px, with a compact drawing below 32 px), plus `icon.png`
for docs. `build.bat` regenerates it when missing and checks the finished EXE for an
embedded icon; `build/installer.iss` reuses the same file for the setup wizard.

`webfinder/config.py :: APP_VERSION` is the only place the version is written —
`/api/meta` serves it to the sidebar badge, and `build/installer.iss` states the same
number for the installer (`tools/test_app_surface.py` asserts the two never drift).

## Frontend — `web/`

Three views: **Grab a video** (analyze → quality chips → one button), **Downloads**
(rows hydrate from `jobs.list`, so removals are server-authoritative), **Settings**
(Downloads incl. proxy · Video & capture (container/quality/cookies/FFmpeg) ·
Appearance · System). Sidebar: About + **Exit** (POST `/api/system/exit` → backend
`os._exit`; desktop window dies with it). State lives in `Store` (Map of jobs + tiny
event bus); api.js WS with polling fallback.

## Desktop — `desktop/window.py`

pywebview `edgechromium`, frameless custom titlebar; the js bridge exposes **only
private attributes** (enforced by `tools/test_desktop_contract.py` — pywebview's
recursive `get_functions` scan otherwise drowns in WinForms internals).
