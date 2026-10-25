"""WebFinder — REST + WebSocket API routes."""
from __future__ import annotations

import asyncio
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from ..config import APP_NAME, APP_VERSION, CONFIG_FILE, settings
from ..core import dorks as dk
from ..core import media
from ..core.downloader import manager
from ..core.ffmpeg_tools import find_ffmpeg
from ..engines import ENGINE_META, run_search

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=400)
    types: list[str] = Field(default_factory=list)
    engines: Optional[list[str]] = None
    limit: Optional[int] = None


class DownloadRequest(BaseModel):
    url: str
    filename: str = ""
    title: str = ""
    kind: str = ""          # http | hls | ytdlp | sim — empty = auto-plan
    meta: dict = Field(default_factory=dict)


class AnalyzeRequest(BaseModel):
    url: str


class MediaDownloadRequest(BaseModel):
    url: str
    title: str = ""
    format: dict = Field(default_factory=dict)


class SettingsPatch(BaseModel):
    patch: dict


# ---------------------------------------------------------------------------
# Meta / system
# ---------------------------------------------------------------------------
@router.get("/meta")
async def meta():
    ff = find_ffmpeg()
    try:
        import yt_dlp
        ytdlp_version = getattr(yt_dlp, "VERSION", "?")
    except ImportError:
        ytdlp_version = None
    return {
        "app": APP_NAME, "version": APP_VERSION,
        "platform": platform.system(), "python": platform.python_version(),
        "engines": ENGINE_META,
        "file_types": {k: {kk: vv for kk, vv in v.items() if kk in ("label", "icon", "color")}
                       for k, v in dk.FILE_TYPES.items()},
        "system": {
            "ffmpeg": ff,
            "yt_dlp": ytdlp_version,
            "desktop": bool(os.environ.get("WEBFINDER_DESKTOP")),
        },
        "config_file": str(CONFIG_FILE),
    }


@router.get("/settings")
async def get_settings():
    return settings.snapshot()


@router.put("/settings")
async def put_settings(body: SettingsPatch):
    allowed = set(settings.snapshot().keys())
    patch = {k: v for k, v in body.patch.items() if k in allowed}
    merged = settings.update(patch)
    manager._sem = asyncio.Semaphore(max(1, int(merged.get("max_concurrent", 3))))
    return merged


@router.post("/system/open-path")
async def open_path(path: str = ""):
    """Reveal a download (or the download folder) in the OS file manager."""
    target = Path(path) if path else Path(settings.get("download_dir", "."))
    if not target.exists():
        raise HTTPException(404, "Path does not exist")
    if sys.platform == "win32":
        flag = "/select," if target.is_file() else ""
        subprocess.Popen(["explorer", flag, str(target)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R" if target.is_file() else "", str(target)])
    else:
        subprocess.Popen(["xdg-open", str(target if target.is_dir() else target.parent)])
    return {"ok": True}


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
def _normalize(url: str) -> str:
    p = urlparse(url)
    return f"{p.netloc.lower().lstrip('www.')}{p.path.rstrip('/')}{'' if not p.query else '?' + p.query[:80]}".lower()


@router.post("/search")
async def search(body: SearchRequest):
    cfg = settings.snapshot()
    engines = body.engines or [e for e, on in cfg["engines"].items() if on]
    engines = [e for e in engines if e in ENGINE_META] or ["bing"]
    limit = min(int(body.limit or cfg["result_limit"]), 200)
    t0 = time.time()

    if cfg["demo_mode"]:
        data = media.build_search_results(body.query, body.types, engines, limit)
    else:
        responses = await run_search(body.query, body.types, engines, limit,
                                     proxy=cfg.get("proxy"))
        results, seen = [], set()
        # Round-robin across engines so every source is represented fairly.
        buckets = {r.engine: list(r.results) for r in responses if r.ok}
        while any(buckets.values()) and len(results) < limit:
            for name, lst in buckets.items():
                if not lst:
                    continue
                r = lst.pop(0)
                r["engine"] = name
                key = _normalize(r["url"])
                if key in seen:
                    continue
                seen.add(key)
                r["is_direct"] = r.get("is_direct") or r["file_type"] != "link"
                results.append(r)
                if len(results) >= limit:
                    break
        # rank: direct files first, then size hint, then source order
        results.sort(key=lambda r: (0 if r.get("is_direct") else 1,
                                    0 if r.get("size_bytes") else 1))
        data = {
            "query": dk.build_query(body.query, body.types),
            "elapsed_ms": int((time.time() - t0) * 1000),
            "engines": [{"engine": r.engine, "ok": r.ok, "error": r.error,
                         "count": len(r.results)} for r in responses],
            "results": results,
        }

    # Optional enhancement: crawl the top ambiguous pages for hidden direct links.
    if cfg.get("resolve_pages") and not cfg["demo_mode"]:
        targets = [r for r in data["results"] if r.get("file_type") == "link"][:5]
        scans = await asyncio.gather(*(media.scan_page(r["url"]) for r in targets),
                                     return_exceptions=True)
        for r, scan in zip(targets, scans):
            if isinstance(scan, list) and scan:
                r["media_candidates"] = scan[:6]
    data["raw_query"] = body.query
    data["types"] = body.types
    return data


# ---------------------------------------------------------------------------
# Smart direct link
# ---------------------------------------------------------------------------
@router.post("/analyze")
async def analyze(body: AnalyzeRequest):
    try:
        return await media.analyze(body.url)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, str(exc)[:300]) from exc


@router.post("/analyze/download")
async def analyze_download(body: MediaDownloadRequest):
    plan = await media.plan_download(body.url, title=body.title, fmt=body.format)
    if plan["kind"] == "magnet":
        raise HTTPException(400, "Magnet links can only be copied — open them with your torrent client.")
    job = manager.enqueue(url=plan["url"], kind=plan["kind"],
                          filename=plan.get("filename", ""), title=plan.get("title", ""),
                          file_type=plan.get("file_type", "link"), meta=plan.get("meta", {}))
    return {"job_id": job.id}


@router.post("/scan")
async def scan(body: AnalyzeRequest):
    if settings.get("demo_mode"):
        return {"candidates": [{"url": "https://demo.local/files/sample-1080p.mp4",
                                "filename": "sample-1080p.mp4", "file_type": "video"},
                               {"url": "https://demo.local/files/sample.zip",
                                "filename": "sample.zip", "file_type": "archive"}]}
    return {"candidates": await media.scan_page(body.url)}


# ---------------------------------------------------------------------------
# Downloads
# ---------------------------------------------------------------------------
@router.post("/downloads")
async def start_download(body: DownloadRequest):
    url = body.url.strip()
    if not url.lower().startswith(("http://", "https://", "magnet:", "ftp://")):
        raise HTTPException(400, "Only http/https/magnet/ftp URLs can be downloaded.")
    if url.lower().startswith("magnet:"):
        raise HTTPException(400, "Magnet links are not direct files — copy the link and open it in your torrent client.")
    kind, meta = body.kind, body.meta
    if not kind:
        plan = await media.plan_download(url, title=body.title)
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
