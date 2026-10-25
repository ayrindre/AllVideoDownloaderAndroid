# All Video Downloader — architecture notes

One promise: **any link containing a video → downloadable file, chosen quality.**

```
run.py ──▶ webfinder.app:create_app() ──▶ FastAPI ─┬─ /api/*        (webfinder/api)
   │  (deps check, FFmpeg bootstrap,               ├─ /ws           (WsHub ⇄ DownloadManager)
   │   daily yt-dlp pip refresh)                   └─ /static, /    (web/ frontend)
```

## Link engine — `core/media.py :: analyze(url)`

Resolution order, each stage proven and never guessed:

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
6. **Page** → `scan_page` (og:video, `<video>/<source>`, file anchors, index-of
   listings with sizes, iframe players) **plus the player-config engine**:
   `core/embed.py` de-escapes the document (`\/`, `\u002F`, `&amp;`) and mines
   every media URL — `html5player.setVideoUrlHigh/Low/HLS`, kt_player
   `video_url`/`_hd`/`_alt`, jwplayer `sources`, escaped JSON, `__NEXT_DATA__`,
   JSON-LD — while `core/sites.py` labels the family and names the site. Ad
   hosts, sprites and posters are scored out; tag-attribute URLs stay owned by
   the anchor/video/og passes so a directory listing is never sold as
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
optional extraction patterns), `net` supplies browser-grade requests and the
`curl_cffi` TLS-impersonation fallback. Adding a site never touches the
analyzer; `GET /api/sites` and `tools/recipe_probe.py` expose the registry.

## Settings — `config.py`

`~/.avd/settings.json`; one-shot migration from `~/.webfinder`; retired search keys
(`engines`, `result_limit`, `safe_search`, `resolve_pages`, `demo_mode`) are stripped
on load — a stale file can't resurrect the removed module. `PUT /api/settings` accepts
only keys present in the snapshot.

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
