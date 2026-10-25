"""All Video Downloader — REST + WebSocket API routes."""
from __future__ import annotations

import os
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import APP_NAME, APP_VERSION, CONFIG_FILE, settings
from ..core import media
from ..core.downloader import manager
from ..core.ffmpeg_tools import find_ffmpeg

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class DownloadRequest(BaseModel):
    url: str
    filename: str = ""
    title: str = ""
    kind: str = ""          # http | hls | ytdlp — empty = auto-plan
    meta: dict = Field(default_factory=dict)


class AnalyzeRequest(BaseModel):
    url: str


class MediaDownloadRequest(BaseModel):
    url: str
    title: str = ""
    format: dict = Field(default_factory=dict)
    referer: str = ""        # hosting page for hotlink-guarded CDNs


class SettingsPatch(BaseModel):
    patch: dict


class GalleryScanRequest(BaseModel):
    url: str = ""
    include: list[str] = Field(default_factory=list)   # posts|reels|stories|highlights|tagged
    limit: int = 0                                     # 0 → saved default
    cookies: str = ""                                  # "" → saved browser-cookie source


class GalleryDownloadRequest(BaseModel):
    items: list[dict] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Meta / system
# ---------------------------------------------------------------------------
@router.get("/meta")
async def meta():
    ff = find_ffmpeg()
    from ..core import cookies as cookie_state, gallery, net, sites, ytcli
    engine = ytcli.detect()
    gal = gallery.detect()
    ytdlp_version = engine["cli_version"] if engine["use_cli"] else (engine["module_version"] or None)
    return {
        "app": APP_NAME, "version": APP_VERSION,
        "platform": platform.system(), "python": platform.python_version(),
        "system": {
            "ffmpeg": ff,
            "yt_dlp": ytdlp_version,
            "yt_dlp_engine": {"use_cli": engine["use_cli"], "exe": engine["exe"],
                              "module_version": engine["module_version"],
                              "cli_version": engine["cli_version"]},
            "desktop": bool(os.environ.get("WEBFINDER_DESKTOP")),
            "gallery_dl": {"available": gal["available"], "version": gal["version"],
                           "exe": gal["exe"], "install_hint": gal["install_hint"]},
            "cookies": cookie_state.source(),
            "tls_impersonation": net.has_impersonation(),
            "sites": {"recipes": len(sites.RECIPES)},
        },
        "config_file": str(CONFIG_FILE),
    }


@router.get("/settings")
async def get_settings():
    return settings.snapshot()


@router.put("/settings")
async def put_settings(body: SettingsPatch):
    import asyncio
    allowed = set(settings.snapshot().keys())
    patch = {k: v for k, v in body.patch.items() if k in allowed}
    merged = settings.update(patch)
    if {"ytdlp_browser_cookies", "cookies_file"} & set(patch):
        # the user just changed the cookie source — forget the old failure so the
        # new one is actually tried instead of being skipped for the session
        from ..core import cookies as cookie_state
        cookie_state.reset()
    manager._sem = asyncio.Semaphore(max(1, int(merged.get("max_concurrent", 3))))
    return merged


@router.get("/cookies/status")
async def cookies_status():
    """Which cookie source is in effect, and whether it already failed."""
    from ..core import cookies as cookie_state
    return cookie_state.source()


@router.get("/cookies/probe")
async def cookies_probe():
    """Read the configured cookie source locally (no network) and report back."""
    import asyncio
    from ..core import cookies as cookie_state
    return await asyncio.to_thread(cookie_state.probe)


@router.post("/system/open-path")
async def open_path(path: str = ""):
    """Reveal a download (or the download folder) in the OS file manager."""
    target = Path(path) if path else Path(settings.get("download_dir", "."))
    revealed_file = target.is_file()
    if not target.exists():
        # stale path (renamed after merge, cleaned up…) — open the closest
        # existing parent instead of dead-ending
        revealed_file = False
        while not target.exists() and target.parent != target:
            target = target.parent
    if not target.exists():
        raise HTTPException(500, "Download folder not found — check Settings → Downloads")
    try:
        if sys.platform == "win32":
            # explorer needs ONE token: "/select,C:\path" — split args silently no-op
            subprocess.Popen(["explorer", f"/select,{target}" if revealed_file else str(target)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R" if revealed_file else "", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target if target.is_dir() else target.parent)])
    except OSError as exc:
        raise HTTPException(500, f"No file manager available to launch ({exc})") from exc
    return {"ok": True, "opened": str(target)}


@router.post("/system/selfupdate")
async def selfupdate():
    """One-click 'make the app's yt-dlp as fresh as my terminal's'.

    The #1 reason the CLI downloads 4K while the app only offers 480p is a
    stale pip copy inside the app venv (YouTube changes its API weekly).
    """
    import asyncio
    py = sys.executable
    try:
        proc = await asyncio.create_subprocess_exec(
            py, "-m", "pip", "install", "-U", "--quiet", "--disable-pip-version-check", "yt-dlp",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=300)
    except asyncio.TimeoutError:
        raise HTTPException(504, "pip timed out — network blocked? Try again or install manually.")
    except OSError as exc:
        raise HTTPException(500, f"pip could not run: {exc}")
    from ..core import ytcli
    ytcli.detect.cache_clear()      # re-eval module-vs-system preference
    # read the NEW version in a child process (this one still has the old import cached)
    new_v = "?"
    try:
        pv = await asyncio.create_subprocess_exec(
            py, "-c", "from yt_dlp.version import __version__; print(__version__)",
            stdout=asyncio.subprocess.PIPE)
        o2, _ = await asyncio.wait_for(pv.communicate(), timeout=20)
        new_v = o2.decode().strip() or "?"
    except Exception:  # noqa: BLE001
        pass
    return {"ok": proc.returncode == 0, "version": new_v, "restart_needed": True,
            "detail": (out or b"").decode("utf-8", "ignore")[-300:]}


@router.post("/system/exit")
async def exit_app():
    """Sidebar Exit: the backend terminates itself; the desktop window dies
    with it, browser tabs just stop answering."""
    def _die() -> None:
        time.sleep(0.35)          # let the HTTP response flush first
        os._exit(0)
    threading.Thread(target=_die, daemon=True).start()
    return {"ok": True, "msg": "All Video Downloader is closing."}


@router.get("/sites")
async def sites_catalog():
    """Built-in recipes: which sites the engine already understands, and how.

    Data-driven by design — adding a site is one line in ``core/sites.py``.
    """
    from ..core import net, sites
    return {"count": len(sites.RECIPES),
            "impersonation": net.has_impersonation(),
            "families": sorted(sites.FAMILIES),
            "recipes": sites.catalog()}


# ---------------------------------------------------------------------------
# Smart link analysis — the whole app hangs off this one endpoint
# ---------------------------------------------------------------------------
@router.post("/scan")
async def scan(body: AnalyzeRequest):
    """Deep-scan one URL for the media it hosts (pages the extractor refused,
    galleries, directory listings). Never a dead end."""
    return {"candidates": await media.scan_page(body.url, limit=24)}


@router.post("/analyze")
async def analyze(body: AnalyzeRequest):
    try:
        return await media.analyze(body.url)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, str(exc)[:300]) from exc


@router.post("/analyze/download")
async def analyze_download(body: MediaDownloadRequest):
    plan = await media.plan_download(body.url, title=body.title, fmt=body.format)
    if body.referer:
        plan.setdefault("meta", {})["referer"] = body.referer
    if plan["kind"] == "magnet":
        raise HTTPException(400, "Magnet links can only be copied — open them with your torrent client.")
    job = manager.enqueue(url=plan["url"], kind=plan["kind"],
                          filename=plan.get("filename", ""), title=plan.get("title", ""),
                          file_type=plan.get("file_type", "link"), meta=plan.get("meta", {}))
    return {"job_id": job.id}


# ---------------------------------------------------------------------------
# Instagram / gallery-dl — profile enumeration ("Instagram checker" tab)
# ---------------------------------------------------------------------------
@router.get("/gallery/engine")
async def gallery_engine():
    """Is gallery-dl usable, which version, which profile tabs exist."""
    from ..core import gallery
    return gallery.gallery_engine_info()


@router.post("/gallery/scan")
async def gallery_scan(body: GalleryScanRequest):
    """Start a profile scan (posts/reels/stories/highlights/tagged).

    Returns immediately with a task id — Instagram rate-limits page fetches, so
    the UI polls ``GET /gallery/scan/{id}`` for status, per-tab counts and the
    items found so far.
    """
    from ..core import gallery
    try:
        return {"scan": gallery.start_scan(body.url, include=body.include,
                                          limit=body.limit, cookie_source=body.cookies)}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("/gallery/scan/{scan_id}")
async def gallery_scan_status(scan_id: str):
    from ..core import gallery
    snap = gallery.get_scan(scan_id)
    if not snap:
        raise HTTPException(404, "Unknown scan id")
    return {"scan": snap}


@router.get("/gallery/scans")
async def gallery_scans():
    """Recent scans (newest first) — lets the tab restore after a reload."""
    from ..core import gallery
    return {"scans": gallery.list_scans()}


@router.post("/gallery/scan/{scan_id}/cancel")
async def gallery_scan_cancel(scan_id: str):
    from ..core import gallery
    return {"ok": gallery.cancel_scan(scan_id)}


@router.post("/gallery/download")
async def gallery_download(body: GalleryDownloadRequest):
    """Enqueue selected items into the normal Download Manager."""
    from ..core import gallery
    from ..core import filekind as fk
    queued = []
    for item in body.items[:500]:
        url = str(item.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        plan = gallery.to_job(item)
        job = manager.enqueue(url=url, kind=plan["kind"],
                              filename=plan["filename"] or fk.guess_filename(url),
                              title=plan["title"], file_type=plan["file_type"],
                              meta=plan["meta"])
        queued.append(job.id)
    if not queued:
        raise HTTPException(400, "Nothing to download — select at least one item.")
    return {"queued": len(queued), "job_ids": queued}


# ---------------------------------------------------------------------------
# Downloads
# ---------------------------------------------------------------------------
@router.post("/downloads")
async def start_download(body: DownloadRequest):
    url = body.url.strip()
    if not url.lower().startswith(("http://", "https://", "magnet:", "ftp://")):
        raise HTTPException(400, "Only http/https/ftp URLs can be downloaded.")
    if url.lower().startswith("magnet:"):
        raise HTTPException(400, "Magnet links are not direct files — copy the link and open it in your torrent client.")
    kind, meta = body.kind, body.meta
    if not kind:
        plan = await media.plan_download(url, title=body.title, fmt=meta.get("fmt") or None)
        kind, meta = plan["kind"], {**plan.get("meta", {}), **meta}
    job = manager.enqueue(url=url, kind=kind, filename=body.filename,
                          title=body.title, meta=meta)
    return job.to_dict()


@router.get("/downloads")
async def list_downloads():
    return {"jobs": manager.list_jobs()}


def _job_or_404(job_id: str):
    job = manager.jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown download id")
    return job


@router.post("/downloads/{job_id}/pause")
async def pause(job_id: str):
    _job_or_404(job_id)
    return {"ok": manager.pause(job_id)}


@router.post("/downloads/{job_id}/resume")
async def resume(job_id: str):
    _job_or_404(job_id)
    return {"ok": manager.resume(job_id)}


@router.post("/downloads/{job_id}/cancel")
async def cancel(job_id: str):
    _job_or_404(job_id)
    return {"ok": manager.cancel(job_id)}


@router.post("/downloads/{job_id}/retry")
async def retry(job_id: str):
    _job_or_404(job_id)
    return {"ok": manager.retry(job_id)}


@router.delete("/downloads/{job_id}")
async def remove(job_id: str):
    _job_or_404(job_id)
    return {"ok": manager.remove(job_id)}


@router.post("/downloads/clear")
async def clear_finished():
    return {"removed": manager.clear_finished()}
