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
| A magnet | Honestly identified; copy it to your torrent client. (This app doesn't fake P2P.) |

Pages whose only video surface is a **cross-origin `<iframe>` player** are not dead
ends either: the scan records every player-looking iframe as an `embed` candidate and
the analyzer **hops into the best one** (files first, embeds second) before giving up.

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
   every message shown. A refused extractor is also no longer a dead end: the page
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
│  ├─ filekind.py           URL→file-type taxonomy (the search-less descendant of dorks)
│  ├─ downloader.py         job manager: http | hls | ytdlp workers
│  ├─ ffmpeg_tools.py       capture_stream (variant-aware), probe
│  └─ ffmpeg_setup.py       auto-fetch of the official FFmpeg build
├─ desktop/                 pywebview shell + js bridge
└─ web/                     frontend (Direct · Downloads · Settings)
tools/test_video_core.py    manifest ladders, sniffing, picker ids, page-rescan loopback
tools/test_desktop_contract.py
```

## Tests

```bash
python tools/test_video_core.py           # fixture-tested engine (no network)
python tools/test_desktop_contract.py     # pywebview bridge hygiene
```

*GPL-3.0 (see LICENSE). Not affiliated with Google, FFmpeg or yt-dlp. Download what you
have the right to download.*
