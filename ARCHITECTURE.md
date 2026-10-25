# WebFinder — Architecture Reference

Deep-dive companion to [README.md](README.md). Everything here matches the code in this repo.

---

## 1. Process model

```
┌────────────────────────────────────────────────────────────────────────┐
│  WebFinder process (run.py)                                            │
│                                                                        │
│   main thread                     worker thread                        │
│   ───────────                     ─────────────                        │
│   pywebview Window (WebView2)     uvicorn Server                       │
│    · frameless=True                · FastAPI app                       │
│    · js_api=DesktopBridge          · all I/O is asyncio                │
│    · loads http://127.0.0.1:8765   · blocking work → to_thread          │
│                                                                        │
│   Browser/dev fallback: same URL opened in the default browser         │
└────────────────────────────────────────────────────────────────────────┘
```

* **One port, one origin.** Static frontend, REST and WS share `127.0.0.1:8765` — no CORS pain, no file:// quirks, and the webview is just a *renderer*.
* **No magic bridge.** JS never calls Python functions directly (that's Eel's model). It talks HTTP/JSON + WebSocket. That keeps the frontend portable (browser preview, and — if you ever want it — Tauri or Electron swap-in) while pywebview handles the *window*, not the data.
* **pywebview-specific glue** lives only in `webfinder/desktop/window.py`:
  `DesktopBridge.minimize/toggle_maximize/close/pick_folder` are exposed as `window.pywebview.api.*`, and
  `frameless=True` + CSS `-webkit-app-region: drag` on the HTML titlebar gives the custom window frame.

## 2. Backend layout

```
webfinder/
├── app.py                 # FastAPI factory, static mount, WsHub (event fan-out), manager wiring
├── config.py              # DEFAULTS + ~/.webfinder/settings.json (atomic save, deep-merge patch)
├── api/__init__.py        # all routes + pydantic schemas (below)
├── engines/__init__.py    # scraper per engine + parallel aggregator w/ per-engine error capture
├── core/
│   ├── dorks.py           # FILE_TYPES catalogue → dork strings, ext classifier, size/URL heuristics
│   ├── downloader.py      # DownloadManager: DownloadJob state machine, 4 worker kinds, events
│   ├── media.py           # analyze(): media|hls|direct|magnet|page + plan_download() + page scanner
│   └── ffmpeg_tools.py    # find_ffmpeg/probe/capture_stream (progress via -progress pipe:1)
└── desktop/window.py      # pywebview host + JS api + server-readiness wait loop
```

## 3. REST / WS API

| Method + path | Purpose |
|---|---|
| `GET /api/meta` | app info, engine & file-type catalogues, FFmpeg/yt-dlp availability, desktop flag |
| `GET/PUT /api/settings` | read / deep-merge settings (validated against known keys) |
| `POST /api/search` | `{query, types[], engines[]}` → `{query(dorked), results[], engines[], elapsed_ms}` |
| `POST /api/analyze` | `{url}` → `kind: media|hls|direct|magnet|page` payload |
| `POST /api/analyze/download` | enqueue with format choice `{url,title,format}` |
| `POST /api/scan` | crawl page for hidden direct links |
| `POST /api/downloads` | enqueue `{url, filename?, title?, kind?}` (kind empty = auto-plan) |
| `GET /api/downloads` | job list (bootstrap after (re)connect) |
| `POST /api/downloads/{id}/pause·resume·cancel·retry` | job control (cooperative events, not thread-killing) |
| `DELETE /api/downloads/{id}` · `POST /api/downloads/clear` | list management |
| `POST /api/system/open-path?path=` | reveal file/folder in Explorer / Finder / xdg |
| `GET /ws` | server→client events: `bootstrap`, `jobs.list`, `job.update` (≈4/s per active job) |
| `GET /api/docs` | interactive OpenAPI docs |

WS client auto-falls back to `GET /api/downloads` polling (1.4 s) whenever the socket is down — so proxies/dev servers that drop upgrades still animate live.

## 4. Download state machine

```
            ┌────────── retry ◄──────────┐
            ▼                            │
 queued ─► downloading ─► done           │   (terminal: done · cancelled)
             ▲   │  ▲      error ◄───────┤
             │   ▼  │ pause↴             │
             └── paused ── cancel ─► cancelled
```

* A global `asyncio.Semaphore(max_concurrent)` queues `queued` jobs; each worker is an `asyncio.Task`.
* **pause/resume are cooperative**: workers poll `job._pause` between chunks/hooks. HTTP resumes use a saved byte offset + `Range: bytes=…` (416 ⇒ “already complete”); yt-dlp pauses in its progress hook; FFmpeg parks at its stdout read-loop and the child is `terminate()`d on cancel.
* `job.update` events are throttled to ~4/s and carry everything the UI needs (pct, speed EMA, eta, unit bytes|time, quality label, `meta.simulated` flag).
* Error strings are surfaced verbatim on the row + retry button — no silent failure states.

### Worker kinds (`core/downloader.py`)
| kind | Pipeline |
|---|---|
| `http` | httpx streaming, 256 KB chunks, Content-Range/Length totals, Range resume |
| `hls` | ffprobe duration → `ffmpeg -progress pipe:1 -i URL [-headers…] -c copy [-bsf:a aac_adtstoasc -movflags +faststart] out.mp4` (`libx264` when re-encode requested / container demands it); progress = decoded `out_time_us` clock |
| `ytdlp` | `yt_dlp.YoutubeDL({...}).download()` in a thread; `progress_hooks` push into the same `job.update` stream; format strings like `bestvideo[height<=1080]+bestaudio/best[height<=1080]`; `DownloadCancelled` for cancel |
| `sim` | deterministic-ish fake transfer (seeded RNG wobble), writes a real placeholder file, drives the identical UI path |

### Analysis routing (`core/media.py::analyze`)
```
magnet: → magnet           (copy / hand off — never “downloaded”)
.m3u8/.mpd or mpegurl → hls (ffprobe metadata in card)
else yt-dlp extract_info   → media (title, thumb, duration, per-height format table)
else HEAD/GET probe        → direct  (size, content-type, ranges support)
else HTML scan (regex over 12 media extensions) → page + candidate list
```
`scan_page()` is also run on the top ambiguous *search results* (`resolve_pages`) so cards can expose hidden direct links — this is what makes “Copy Download Link” meaningful for IDM users even when the SERP only shows a wrapper page.

## 5. Frontend foundation (HTML/CSS/JS)

```
web/
├── index.html        # semantic shell: .titlebar → .shell(sidebar, viewport) → 4 <section.view>
│                     # + <template>s for result card / download row (cloned, never re-parsed)
├── css/base.css      # design tokens, accents via html[data-accent], ambient orbs+grain, window chrome
├── css/components.css# buttons, chips, glass cards, FABs, skeletons/spinner/radar, progress, toasts
├── css/views.css     # hero layout, results head (sticky), direct workbench, dl rows, settings wall
└── js/               # icons.js · api.js · ui.js · state.js · app.js · views/{search,direct,downloads,settings}.js
```

* **Tokens first** — surfaces, radii, easings (`--ease`, `--ease-spring`) and three motion tiers live in `:root`; every accent is a gradient pair so swapping `data-accent` re-skins glows, focus rings and progress fills with zero JS re-render.
* **Layered glass recipe**: translucent gradient fill + `backdrop-filter: blur(22px) saturate(1.4)` + hairline `--panel-border` + inset highlight (`inset 0 1px 0 rgba(255,255,255,.05)`). Cards add a cursor-following `radial-gradient` (`--mx`) spotlight. All of it is compositor-only (opacity/transform/blur) so animations stay GPU-driven.
* **Motion system**: enter keyframes (`view-in`, `card-in` staggered via `--i`, `toast-in` spring), sliding nav indicator (`transform: translateY(var(--nav-y))` on one pseudo-element), shimmer skeletons (`::after` translate loop), animated stripe + sheen on progress. `body.preload` disables transitions until first paint; `prefers-reduced-motion` kills everything.
* **State**: one `Store` (settings, meta, results, jobs Map) + tiny pub/sub. Views subscribe to `job.update`/`jobs.hydrated`/`settings.changed`; nothing polls from the UI unless the WS is down.
* **Templates over string HTML**: `<template id="tpl-result-card">` cloned + hydrated — fast, XSS-safe by default (`textContent` everywhere user data lands).

## 6. Extending

* **New engine** → one `async fn(client, query, limit) -> list[dict]` in `engines/__init__.py` + one line in `ENGINES`/`ENGINE_META`. Errors propagate to the per-engine status strip for free.
* **New file type** → add to `core/dorks.FILE_TYPES` (dork + exts + color + icon name). Chips, classification and badge colors pick it up automatically.
* **Direct Python calls, Eel-style** → register pywebview `js_api` methods in `DesktopBridge` and call `window.pywebview.api.x()` (browser fallbacks are the pattern everywhere).
* **Torren**t deep-handling (tracker scrape, multi-source merge) → natural fit in `media.analyze`; keep the “copy link to IDM/your client” affordances intact.

## 7. Security & politeness notes

* Binds `127.0.0.1` in desktop mode (browser dev mode uses `0.0.0.0` only for this sandbox preview).
* `open-path` accepts settings-adjacent paths only in spirit — it's a localhost app; if you expose the port, gate it.
* Scrapers rotate realistic UA strings, never execute page JS, and cap snippet parsing with bounded regexes.
* `verify=False` on search clients is deliberate (some mirrors ship broken chains) — swap per-engine if policy requires.
