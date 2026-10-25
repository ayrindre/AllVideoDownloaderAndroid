"""WebFinder — asynchronous download manager.

Job kinds
  http   : plain streaming download (httpx) with HTTP Range resume
  hls    : .m3u8 / .mpd streams captured through FFmpeg
  ytdlp  : media-platform links (YouTube & friends) via the yt-dlp API
  sim    : deterministic simulation — drives the entire UI pipeline offline

The manager never blocks the event loop; every worker is an asyncio task
guarded by a concurrency semaphore, and progress is pushed through an
`emit` callback (wired to the WebSocket broadcaster in app.py).
"""
from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import httpx

from ..config import settings
from . import dorks as dk

CHUNK = 256 * 1024
TERMINAL = {"done", "error", "cancelled"}
NETWORK_ERRORS = (httpx.TransportError, ConnectionError, OSError)


@dataclass
class DownloadJob:
    url: str
    kind: str = "http"                     # http | hls | ytdlp | sim
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    filename: str = "download"
    filepath: Optional[str] = None
    title: str = ""
    file_type: str = "link"
    status: str = "queued"                 # queued|downloading|paused|done|error|cancelled
    total: int = 0                         # bytes — or seconds while an HLS capture runs
    done: int = 0
    speed: float = 0.0
    eta: float = 0.0
    unit: str = "bytes"                    # bytes | time
    error: str = ""
    meta: dict = field(default_factory=dict)
    resume_offset: int = 0
    progress_pct: float = 0.0
    created_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    _task: Optional[asyncio.Task] = field(default=None, repr=False)
    _cancel: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    _pause: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    # -- serialization ------------------------------------------------------
    def to_dict(self) -> dict:
        d = {k: getattr(self, k) for k in (
            "id", "url", "kind", "filename", "filepath", "title", "file_type",
            "status", "total", "done", "speed", "eta", "unit", "error",
            "progress_pct", "created_at", "finished_at",
        )}
        d["meta"] = {k: v for k, v in self.meta.items() if k != "format"}
        return d

    def set_progress(self, done: int, total: int | None, speed: float | None = None) -> None:
        self.done = done
        if total:
            self.total = total
        if self.total:
            self.progress_pct = round(min(100.0, done / self.total * 100.0), 1)
            if speed and speed > 0:
                self.eta = max(0, (self.total - done) / speed)
        if speed is not None:
            self.speed = round(self.speed * 0.7 + speed * 0.3, 1)  # EMA


class DownloadManager:
    def __init__(self) -> None:
        self.jobs: dict[str, DownloadJob] = {}
        self.order: list[str] = []
        self._emit: Callable[[dict], None] = lambda evt: None
        self._sem: Optional[asyncio.Semaphore] = None

    # -- lifecycle ------------------------------------------------------------
    def attach(self, emit: Callable[[dict], None]) -> None:
        self._emit = emit
        self._sem = asyncio.Semaphore(max(1, int(settings.get("max_concurrent", 3))))

    def emit(self, event: str, payload: dict) -> None:
        try:
            self._emit({"type": event, "payload": payload})
        except Exception:  # noqa: BLE001 — broadcasting must never kill a worker
            pass

    def publish(self, job: DownloadJob) -> None:
        self.emit("job.update", job.to_dict())

    # -- job control ------------------------------------------------------------
    def enqueue(self, *, url: str, kind: str = "http", filename: str = "",
                title: str = "", file_type: str = "", meta: dict | None = None) -> DownloadJob:
        meta = meta or {}
        if settings.get("demo_mode"):
            kind = "sim"
        filename = filename or dk.guess_filename(url)
        dest_dir = Path(settings.get("download_dir", "."))
        dest_dir.mkdir(parents=True, exist_ok=True)
        job = DownloadJob(
            url=url, kind=kind,
            filename=self._unique_name(dest_dir, filename),
            title=title or filename,
            file_type=file_type or dk.classify(url),
            meta=meta,
        )
        job.filepath = str(dest_dir / job.filename)
        self.jobs[job.id] = job
        self.order.append(job.id)
        self._spawn(job)
        self.emit("jobs.list", {"jobs": self.list_jobs()})
        return job

    def _unique_name(self, dest: Path, name: str) -> str:
        name = re.sub(r'[<>:"/\\|?*]', "_", name) or "download"
        if not (dest / name).exists():
            return name
        stem, suffix = Path(name).stem, Path(name).suffix
        for i in range(1, 1000):
            cand = f"{stem} ({i}){suffix}"
            if not (dest / cand).exists():
                return cand
        return f"{stem}-{uuid.uuid4().hex[:6]}{suffix}"

    def _spawn(self, job: DownloadJob) -> None:
        job._cancel = asyncio.Event()
        job._pause = asyncio.Event()
        job._task = asyncio.create_task(self._guarded(job))

    async def _guarded(self, job: DownloadJob) -> None:
        assert self._sem is not None
        async with self._sem:
            job.status = "downloading"
            self.publish(job)
            try:
                workers = {"http": self._run_http, "hls": self._run_hls,
                           "ytdlp": self._run_ytdlp, "sim": self._run_sim}
                await workers.get(job.kind, self._run_http)(job)
            except asyncio.CancelledError:
                job.status = "cancelled"
            except Exception as exc:  # noqa: BLE001
                network_fail = isinstance(exc, NETWORK_ERRORS)
                if (job.kind == "http" and network_fail
                        and settings.get("simulate_on_network_error")):
                    # The host is unreachable (firewall, sandbox, dead link) —
                    # keep the pipeline alive in simulation mode so the user
                    # still sees the full transfer experience.
                    job.kind = "sim"
                    job.meta["simulated"] = True
                    job.meta["simulated_reason"] = str(exc)[:160]
                    job.done, job.total = 0, 0
                    await self._run_sim(job)
                else:
                    job.status = "error" if job.status != "cancelled" else job.status
                    job.error = str(exc)[:300]
            if job.status == "downloading":
                job.status = "done"
                job.finished_at = time.time()
                job.speed, job.eta = 0, 0
                # Reconcile the progress bar / "saved" stat with the REAL bytes
                # on disk — streamed totals can be estimates (server lied,
                # ytdlp merged extra streams, resume offsets double-count).
                try:
                    p = Path(job.filepath) if getattr(job, "filepath", "") else None
                    if p is not None and p.exists() and job.unit == "bytes":
                        job.done = job.total = p.stat().st_size
                except OSError:
                    pass
            self.publish(job)

    def pause(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if not job or job.status not in ("downloading", "queued"):
            return False
        job._pause.set()
        return True

    def resume(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if not job or job.status != "paused":
            return False
        job.resume_offset = job.done if job.kind == "http" else 0
        job._pause.clear()
        return True

    def cancel(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if not job or job.status in TERMINAL:
            return False
        job._cancel.set()
        if job._task and not job._task.done():
            job._task.cancel()
        job.status = "cancelled"
        self.publish(job)
        return True

    def retry(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if not job or job.status not in ("error", "cancelled"):
            return False
        job.status, job.error, job.done = "queued", "", 0
        job.progress_pct, job.resume_offset = 0, 0
        self._spawn(job)
        self.publish(job)
        return True

    def remove(self, job_id: str) -> bool:
        job = self.jobs.pop(job_id, None)
        if not job:
            return False
        job._cancel.set()
        if job._task and not job._task.done():
            job._task.cancel()
        if job_id in self.order:
            self.order.remove(job_id)
        self.emit("jobs.list", {"jobs": self.list_jobs()})
        return True

    def clear_finished(self) -> int:
        gone = [j for j in list(self.order) if self.jobs[j].status in TERMINAL]
        for j in gone:
            self.remove(j)
        return len(gone)

    def list_jobs(self) -> list[dict]:
        return [self.jobs[i].to_dict() for i in reversed(self.order) if i in self.jobs]

    # ------------------------------------------------------------------
    # Worker: plain HTTP download with Range resume
    # ------------------------------------------------------------------
    async def _run_http(self, job: DownloadJob) -> None:
        dest = Path(str(job.filepath))
        offset = job.resume_offset if dest.exists() else 0
        headers = {"Accept-Encoding": "identity",
                   "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) WebFinder/1.0"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        mode = "ab" if offset else "wb"
        recent_bytes, last_emit = 0, time.time()
        async with httpx.AsyncClient(follow_redirects=True,
                                     timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            async with client.stream("GET", job.url, headers=headers) as resp:
                if resp.status_code == 416 and dest.exists():
                    job.done = job.total = dest.stat().st_size  # already complete
                    job.progress_pct = 100.0
                    return
                resp.raise_for_status()
                cr = resp.headers.get("content-range")
                cl = resp.headers.get("content-length")
                if cr and "/" in cr:
                    job.total = int(cr.rsplit("/", 1)[-1])
                elif cl:
                    if resp.status_code == 206:
                        job.total = int(cl) + offset
                    else:
                        offset, mode, job.done = 0, "wb", 0
                        job.total = int(cl)
                job.done = offset if resp.status_code == 206 else 0
                with dest.open(mode) as fh:
                    async for chunk in resp.aiter_bytes(CHUNK):
                        await self._check_flags(job)
                        fh.write(chunk)
                        job.done += len(chunk)
                        recent_bytes += len(chunk)
                        if time.time() - last_emit >= 0.25:          # ~4 UI events/s
                            dt = max(0.001, time.time() - last_emit)
                            job.set_progress(job.done, job.total, recent_bytes / dt)
                            recent_bytes, last_emit = 0, time.time()
                            self.publish(job)
                job.set_progress(job.done, job.total or job.done, None)
                job.total = job.total or job.done
                job.progress_pct = 100.0
        self.publish(job)

    # ------------------------------------------------------------------
    # Worker: HLS/DASH capture through FFmpeg
    # ------------------------------------------------------------------
    async def _run_hls(self, job: DownloadJob) -> None:
        from . import ffmpeg_tools
        await ffmpeg_tools.capture_stream(job, self._check_flags, self.publish)

    # ------------------------------------------------------------------
    # Worker: yt-dlp media download (runs in a thread — its API is sync)
    # ------------------------------------------------------------------
    async def _run_ytdlp(self, job: DownloadJob) -> None:
        await asyncio.to_thread(self._ytdlp_thread, job)

    def _ytdlp_thread(self, job: DownloadJob) -> None:
        try:
            import yt_dlp
        except ImportError as exc:
            raise RuntimeError("yt-dlp is not installed — run `pip install yt-dlp`.") from exc
        last = {"t": time.time(), "done": 0}

        def hook(d: dict) -> None:
            if job._cancel.is_set():
                raise yt_dlp.utils.DownloadCancelled()
            while job._pause.is_set():
                if job._cancel.is_set():
                    raise yt_dlp.utils.DownloadCancelled()
                time.sleep(0.3)
            if d.get("status") == "downloading":
                done = d.get("downloaded_bytes") or 0
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                if time.time() - last["t"] >= 0.25:
                    dt = max(0.05, time.time() - last["t"])
                    job.set_progress(done, total or None, (done - last["done"]) / dt)
                    last.update(t=time.time(), done=done)
                    self.publish(job)
            elif d.get("status") == "finished":
                if job.total:
                    job.set_progress(job.total, job.total, None)
                self.publish(job)

        from .media import base_yt_opts
        parent = Path(str(job.filepath)).parent
        stem = Path(str(job.filename)).stem[:120] or "download"
        # Fixed basename (NOT %(title)s): the final file is predictably
        # <stem>.<ext>, so open-folder / reveal / size-reconcile all find it.
        core: dict[str, Any] = {
            "progress_hooks": [hook],
            "quiet": True, "no_warnings": True, "noprogress": True,
            "outtmpl": str(parent / (stem + ".%(ext)s")),
            "format": job.meta.get("format") or "bv*+ba/b",
            "merge_output_format": settings.get("default_container", "mp4"),
            "concurrent_fragment_downloads": 4,
            "windowsfilenames": True,
        }
        # YouTube serves anonymous WEB clients a 640×480-only stream map
        # ("quality ignores my selection" bug) — lead with the mobile/TV clients
        # that expose full-resolution formats, then fall back to web.
        attempts = [base_yt_opts({**core, "extractor_args":
                                 {"youtube": {"player_client": ["android", "tv", "web"]}}}),
                    base_yt_opts(core)]
        last_err: Exception | None = None
        for opts in attempts:
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([job.url])
                self._settle_ytdlp_file(job, parent, stem)
                return
            except yt_dlp.utils.DownloadCancelled:
                raise asyncio.CancelledError() from None
            except Exception as exc:  # noqa: BLE001 — retry / final error below
                last_err = exc
        # both errored but attempt 1 may still have produced a complete file
        settled = self._settle_ytdlp_file(job, parent, stem)
        if last_err is not None and not settled:
            raise RuntimeError(f"yt-dlp failed: {last_err}")

    def _settle_ytdlp_file(self, job: DownloadJob, parent: Path, stem: str) -> bool:
        """Point the job at the REAL file yt-dlp left on disk (extension comes
        from the site: mp4/mkv/webm…), then sync size with the truth.
        Returns True when a real, non-trivial file was located."""
        try:
            finals = [f for f in parent.glob(stem + ".*")
                      if f.suffix not in (".part", ".ytdl") and f.is_file()]
            if finals and max(f.stat().st_size for f in finals) > 1024:
                real = max(finals, key=lambda f: f.stat().st_size)
                job.filename = real.name
                job.filepath = str(real)
                size = real.stat().st_size
                if job.unit == "bytes" and size:
                    job.done = job.total = size
                    job.progress_pct = 100.0
                return True
        except OSError:
            pass
        return False

    # ------------------------------------------------------------------
    # Worker: simulated transfer (demo mode / offline & blocked networks)
    # ------------------------------------------------------------------
    async def _run_sim(self, job: DownloadJob) -> None:
        import random
        rng = random.Random(abs(hash(job.url)) % 10_000)
        if not job.total:
            job.unit = "bytes"
            job.total = int(job.meta.get("simulated_size")
                            or rng.choice([90, 140, 260, 420]) * 1024 * 1024)
            job.done = 0
        base_speed = float(job.meta.get("simulated_speed")
                           or rng.uniform(6.5, 30.0) * 1024 * 1024)
        while job.done < job.total:
            await self._check_flags(job)
            tick = 0.28
            step = max(4096, int(base_speed * tick * rng.uniform(0.55, 1.6)))
            job.done = min(job.total, job.done + step)
            job.set_progress(job.done, job.total, step / tick)
            self.publish(job)
            await asyncio.sleep(tick)
        dest = Path(str(job.filepath))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps({
            "webfinder": "simulated transfer", "url": job.url,
            "note": "The remote host was unreachable from this environment — "
                    "WebFinder finished the job in simulation mode.",
        }, indent=2), encoding="utf-8")
        job.progress_pct = 100.0
        self.publish(job)

    # ------------------------------------------------------------------
    async def _check_flags(self, job: DownloadJob) -> None:
        """Cooperative pause/cancel — pause parks the worker until resumed."""
        if job._cancel.is_set():
            raise asyncio.CancelledError()
        if job._pause.is_set():
            job.status = "paused"
            job.speed, job.eta = 0, 0
            self.publish(job)
            while job._pause.is_set():
                if job._cancel.is_set():
                    job.status = "cancelled"
                    self.publish(job)
                    raise asyncio.CancelledError()
                await asyncio.sleep(0.2)
            job.status = "downloading"
            if job.kind != "http":
                job.resume_offset = job.done
            self.publish(job)


manager = DownloadManager()
