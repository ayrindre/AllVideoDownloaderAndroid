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

### True media verticals (images · videos · torrents · e-books · archives)
Selecting a single file-type chip switches from web search to that type's dedicated
*index sources*, so you get the files themselves — not pages about them. This routing is
**unconditional** — the old `vertical_mode` kill-switch was removed because a stale
`"vertical_mode": false` in an existing `settings.json` silently degraded every media
vertical back to plain web search:

| | Sources | Direct fields | Filters |
|---|---|---|---|
| **Images** | DuckDuckGo `i.js` JSON · Bing Images · Google `tbm=isch` | full-res URL (IDM-ready), thumb, w×h, source page | size ≥800/HD/4K · aspect · color · kind (photo/clipart/line/GIF/B&W) |
| **Videos** | DuckDuckGo `v.js` JSON · Bing Videos · dorked web as third source | playable media URL, thumb, duration, publisher | length (<4m / 4–20m / >20m) · min height |
| **Torrents** | The Pirate Bay (`apibay.org` JSON) · Nyaa RSS · 1337x | **magnet link** (Copy → your client), seeders/leechers/size, `.torrent` file save | min seeders |
| **E-Books** | Project Gutenberg (`gutendex`) · Internet Archive (search + metadata) | direct EPUB/PDF file URL, cover, author, year | format (EPUB/PDF/DjVu) |
| **Archives** | Bing + DuckDuckGo + Mojeek with `intitle:"index of"` dorks, **hard-relevance-gated** | only file URLs & directory listings survive — pages *about* zips are dropped | — |

The **Magnet** chip merged into **Torrent**: one chip searches both `.torrent` files and
magnet links; every card leads with **Copy magnet / Copy direct link** (IDM-safe).

Filters live in the **⚙ Filters** popover next to the engine pills (color/kind ride Bing's
index, size & aspect are also enforced locally); **SafeSearch is OFF by default** with a
one-click pill next to it, and every source fails independently — a blocked engine shows
as `blocked` in the source strip instead of killing the search. Google traffic now leads
with **`curl-cffi`** — a real Chrome TLS/JA3 fingerprint plus the `CONSENT`/`SOCS` cookies
and `gbv=1` — which defeats the "200 OK but zero results" fingerprint wall; without the
package installed it degrades to httpx with a legacy-user-agent retry. DuckDuckGo falls
back to its `lite` markup bucket when the main HTML endpoint comes back empty.

**No garbage, ever.** If Image-only (or Video-only) finds zero media, WebFinder does **not**
quietly swap in irrelevant web pages — it shows an *indexes-blocked* panel listing what each
source said (captcha / bot wall / markup change), plus the fixes that actually work: wait a
minute, enable **Settings → Scrape proxy** (also applied to the media indexes), or retry.
On networks where Google/DuckDuckGo endpoints are filtered, Bing Images alone usually still
works — and if it is the one that failed, the parser speaks all three Bing markup
generations (legacy entity-escaped `m="{&quot;…}"`, raw JSON `m='{"murl":…}'`, and the
stable `/images/async` fragment endpoint).

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
   The download **leads with the `android`/`tv` player clients** (the anonymous `web` client is
   served a 640×480-capped stream map — that is why "1080p" used to arrive as 480p), a real
   browser `User-Agent` rides every request, and output uses a **fixed basename** (`<title>.%(ext)s`
   is *not* used): when the job settles, the app points itself at the real merged file on disk,
   correcting extension drift (`.webm`→`.mp4`) so reveal-in-folder, size math and stats all agree.
4. **Magnet** → copied/opened with your torrent client (never faked as a direct file).
5. **Extraction refused** (YouTube's "Sign in to confirm you're not a bot", age/region
   gates) → the analyzer now says so: a red card quoting yt-dlp's own error, with the two
   fixes it actually has — **Settings → Media → Browser cookies source** (reads your
   Chrome/Edge/Firefox session locally, so logged-in + gated videos work) and
   `pip install -U yt-dlp`. Failed web clients are auto-retried against yt-dlp's mobile
   players for both analysis and downloads.

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

### Troubleshooting

| Symptom | Fix |
|---|---|
| Window "hangs" / log floods `AccessibilityObject… recursion` | Older builds exposed the window object on the `js_api` bridge, which pywebview recursively scans — fixed (bridge now uses a private `_window`; `tools/test_desktop_contract.py` guards it). Any machine can use `browser.bat` as an instant escape hatch. |
| Console flashes and closes on `run.py` double-click | Use **`run.bat`** (manages the venv and keeps the window open on errors). `run.py` with a bare system Python now pauses with instructions instead of vanishing. |
| `A WebFinder backend is already running` | That is intentional: `run.py` detects a live backend on the port and attaches the browser to it instead of double-binding (no more `Only one usage of each socket address`). |
| "Open folder" said *only available in the desktop app* | That toast was a catch-all, not the truth: the folder was tracked under the *planned* filename while yt-dlp's merge renames the file, so the reveal call 404'd. Fixed on both sides — settled real paths + a reveal that walks up to the nearest existing folder and opens the downloads dir as last resort (works in browser mode too: the server is your machine). |
| Verticals (image/video/torrent/ebook/archive) behave like plain web search after a pull | Two causes, both fixed: a stored `vertical_mode:false` gate (removed — routing is now unconditional) and WebView2 serving **cached stale JS** (`/static` now sends `Cache-Control: no-cache` and revalidates via ETag). Restart the app once after pulling to pick both up. |
| Stats "Saved" doesn't match the files on disk | Completed jobs now reconcile `done`/`total` to the real `st_size` after the final rename; in-progress jobs intentionally show transfer bytes, and time-based (simulated) jobs never count into "Saved". |
| Few web results | Web engines now page: Bing RSS `first=` up to 4 pages, Google up to 4 `start=` pages on the fingerprinted path, Mojeek 3 pages; default `result_limit` raised 60→100. Engines you unchecked in Settings stay unchecked — the strip shows what actually ran. |
| Copy button "does nothing" on media cards | Fixed: handlers now capture `e.currentTarget` before `await` (the DOM nulls it after dispatch). |
| Dragging the titlebar didn't move the window / maximize never restored | Fixed: header carries pywebview's `.pywebview-drag-region` selector (CSS `-webkit-app-region` is a no-op in WebView2) and the bridge reads the LIVE native `WindowState` instead of pywebview's static `maximized` flag. Double-click the titlebar toggles maximize too. |
| Proxy env vars make the app ignore its own localhost | All self-probes (`run.py`, desktop launcher) now bypass the system proxy (`ProxyHandler({{})}`). |

## 6. Responsible use

WebFinder is an aggregator over public search engines and public URLs. It neither hosts nor
indexes content — **you are responsible for what you download**; respect copyright, licenses and
each site's terms. Scraping is best-effort: engines may rate-limit you (the app shows *which* one
failed instead of hiding it), and a `proxy` setting can be pointed at your own egress.

*GPL-3.0 (see LICENSE). Not affiliated with Google, Bing, Yandex, DuckDuckGo, Mojeek, IDM, FFmpeg or yt-dlp.*
