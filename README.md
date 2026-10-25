# 🔦 WebFinder

**A premium dark-glass Windows desktop app for multi-engine file search, smart downloading and stream capture — Python backend, HTML/CSS/JS frontend.**

Search Google / Bing / DuckDuckGo / Yandex / Mojeek for **videos, images, torrents, magnets, installers and archives**, grab direct download links for IDM, capture `.m3u8` streams with **FFmpeg**, and paste any media URL (YouTube & friends) into the **Smart Direct Link** module powered by **yt-dlp** — all inside one buttery-smooth, hardware-accelerated window.

**Windows — double-click [`run.bat`](run.bat).** It creates `.venv`, installs
requirements (and yt-dlp) on first run, then launches the app — no commands needed.

Or manually:

```
python -m venv .venv
.venv\Scripts\activate            # Windows   (source .venv/bin/activate on Linux/macOS)
pip install -r requirements.txt
python run.py                     # → frameless pywebview window (falls back to browser)
```

To produce a single-file `dist\WebFinder.exe`, double-click [`build.bat`](build.bat)
(it installs PyInstaller into the venv and runs `build/webfinder.spec`).

> The UI speaks **English only**, by design, everywhere.

---

## 1. Which Python ↔ HTML bridge? (and why)

| Option | Verdict |
|---|---|
| **pywebview + FastAPI/uvicorn** ✅ **chosen** | Native Windows shell via **Edge WebView2 (Chromium)** → real GPU compositing, `backdrop-filter` glassmorphism, 60 fps CSS animations. Supports `frameless=True` for the custom titlebar, JS→Python API for window buttons and native folder dialogs, and it degrades to “just a web app” for dev. |
| Eel | Great for tiny tools; it *wraps* a Chrome app-mode window — weaker window control (no first-class frameless/custom chrome API), and its `eel.js` bridge couples JS calls to Python functions one-by-one. Our WebSocket progress stream would be awkward on it. |
| PyQtWebEngine / Qt6 | Most control, but ships a ~170 MB Qt+Chromium runtime, a GPL flavor question, and a heavier dev loop. Overkill when Chromium is already built into Windows 10/11 via WebView2. |

The architecture keeps the frontend **100% HTTP + WebSocket** (`/api/*`, `/ws`) instead of a magic JS bridge, so the exact same HTML/CSS/JS runs in a plain browser (fast iteration: edit file → reload) **and** inside the native window. pywebview only *adds*: frameless chrome, native dialogs, single process.

## 2. Architecture at a glance

```
┌───────────────────────────── WebFinder.exe (PyInstaller) ─────────────────────────────┐
│                                                                                          │
│  web/  (static HTML + CSS + vanilla JS ES modules — no build step)                      │
│   ├─ titlebar (custom window frame, -webkit-app-region drag)                             │
│   ├─ sidebar rail · view router · results grid · download manager · settings             │
│   ▼                                                                                      │
│  HTTP/JSON  +  WebSocket progress stream  ──►  FastAPI (uvicorn, in-process thread)      │
│                                                 ├─ /api/search   → engines/ (httpx)       │
│                                                 │    Google · Bing(RSS) · DDG(html) ·     │
│                                                 │    Yandex · Mojeek   + dorks/core       │
│                                                 ├─ /api/downloads → core/downloader.py    │
│                                                 │    ├─ http  : httpx stream, Range-resume │
│                                                 │    ├─ hls   : core/ffmpeg_tools.py       │
│                                                 │    ├─ ytdlp : yt-dlp API + progress hooks│
│                                                 │    └─ sim   : simulated worker (demo)    │
│                                                 └─ /api/analyze → core/media.py            │
│                                                      yt-dlp metadata → resolutions UI     │
│  pywebview window (WebView2) ◄── serves 127.0.0.1:8765, frameless, min-size clamped      │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

Module map and API reference: **[ARCHITECTURE.md](ARCHITECTURE.md)**

## 3. How the smart logic works

### Interaction model
Typing a **bare URL into the main search box routes it straight into the Smart Direct
Link analyzer** (that's what it is — not a search query). Once a search runs, the hero
folds into a compact sticky command bar: the query stays editable, and the file-type
chips + engine pills stay one click from the results — toggling a chip re-runs the search
automatically. Each section (Search / Direct / Downloads / Settings) is a true page —
never stacked.

### Multi-engine search + dork operators
`core/dorks.py` maps each file-type chip to real search operators (`filetype:mkv OR …`,
`inurl:magnet "xt=urn:btih"`, …). The aggregator fans the augmented query out to every enabled
engine **in parallel**, unwraps redirect URLs, dedupes, extracts size hints from snippets,
classifies each hit by extension heuristics, and round-robins engines so no single source
dominates. `resolve_pages` additionally crawls the top web-page results to reveal *hidden
direct file links* — those get their own **Copy link / Download** buttons on the card.

### Smart Download routing (`core/media.py → core/downloader.py`)
1. **Direct file** (`.mp4 .mkv .zip .exe .torrent …`) → httpx streaming worker: 256 KB chunks,
   `Content-Length`/`Content-Range` totals, **HTTP Range resume** on pause→resume, UI events
   throttled to ~4/s.
2. **HLS/DASH stream** (`.m3u8`, `.mpd`, `mpegurl` content-type) → **FFmpeg worker**: ffprobe
   probes duration, `ffmpeg -i URL -c copy -bsf:a aac_adtstoasc -movflags +faststart out.mp4`
   (lossless remux into your preferred container; `libx264` re-encode only when asked). Progress
   parses ffmpeg's `-progress pipe:1` microsecond clock, so the bar moves in real time.
   No FFmpeg? The app says so precisely and everything else keeps working.
3. **Media-platform URL** (YouTube, Vimeo, TikTok, ~1800 sites) → **yt-dlp**: metadata + per-height
   resolution table is returned to a *format picker card*; the chosen
   `bestvideo[height<=1080]+bestaudio/best[height<=1080]` string streams through yt-dlp's API
   with `progress_hooks` feeding the same live UI pipeline as every other job.
4. **Magnet** → copied/opened with your torrent client (never faked as a direct file).

Every job exposes **Pause · Resume · Retry · Cancel · Copy source URL · Open in folder**, plus a
one-click **Copy Download Link** on every result card — paste-ready for IDM/NDM/aria2.

### Graceful demo mode
`Settings → Demo mode` synthesizes search results and *simulates* transfers through the identical
worker/progress path (also: real downloads that hit an unreachable host auto-switch to a flagged
`simulated` run). This makes the whole app demo-able offline and makes this sandbox preview alive.

## 4. UI / UX system

- **Design language** — deep charcoal `#121212`, glass panels (`backdrop-filter: blur(22px) saturate()` +
  layered translucent gradients), accent presets (neon **violet→electric-blue** default, azure, magenta, mint —
  one `data-accent` attribute re-tints glows, gradients and focus rings instantly).
- **Motion** — one shared spring-ish easing `cubic-bezier(.34,1.56,.64,1)` and 160/260/420 ms tiers;
  sliding sidebar indicator, chip pop-check, card lift + spotlight follow-cursor, gradient-halo focus on the
  search bar, shimmering skeleton cards, striped animated progress + sheen sweeps, toast spring-ins,
  `prefers-reduced-motion` respected. First paint runs with transitions suppressed (`.preload`) — zero flash.
- **Custom frame** — borderless window, in-HTML titlebar with drag region and hover-lit
  min/max/close controls (red glow close, per spec), background ambient orbs + film grain behind the glass.
- **Panels** — collapsible icon rail (state persisted), centered hero search that morphs into a
  sticky results header, Direct-Link workbench with radar loader, Download Manager with stat cards +
  live sparkline canvas, and a settings wall persisted to `~/.webfinder/settings.json`.
  Keyboard: `/` focuses search, `Ctrl+1..4` switch panels, `Esc` returns to hero.

## 5. Windows: install, ffmpeg, packaging

```powershell
winget install Gyan.FFmpeg          # stream capture & quality merging
pyinstaller build/webfinder.spec    # → dist\WebFinder.exe (single file, no console)
iscc build\installer.iss            # → Setup wizard (optional bundled ffmpeg folder)
```

`run.py --browser` serves the same UI to your default browser for styling work.
`.venv` and `downloads/` are git-ignored; nothing else needs configuring — settings live in `%USERPROFILE%\.webfinder\settings.json`.

## 6. Responsible use

WebFinder is an aggregator over public search engines and public URLs. It neither hosts nor
indexes content — **you are responsible for what you download**; respect copyright, licenses and
each site's terms. Scraping is best-effort: engines may rate-limit you (the app shows *which* one
failed instead of hiding it), and a `proxy` setting can be pointed at your own egress.

*GPL-3.0 (see LICENSE). Not affiliated with Google, Bing, Yandex, DuckDuckGo, Mojeek, IDM, FFmpeg or yt-dlp.*
