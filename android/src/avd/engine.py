"""All Video Downloader (Android) — engine service.

Runs the *exact* desktop download engine inside a dedicated background thread
with its own asyncio event loop. The Kivy UI never touches asyncio directly:
it calls plain synchronous methods here from worker threads and reads job
snapshots on a Kivy-Clock interval.

This is the Android replacement for the FastAPI + WebSocket layer
(``webfinder/api`` + ``webfinder/app.WsHub``) — same calls, in-process.
"""
from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from .config import APP_VERSION, settings
from .core import media
from .core.downloader import manager
from .core.ffmpeg_tools import find_ffmpeg
from .platform import runtime


class Engine:
    """Background-thread facade over the analyzer and download manager."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        # small pool for blocking UI-side calls (analyze can take a while)
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="avd-ui")
        self._listeners: list[Callable[[dict, str], None]] = []
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self._thread is not None:
            return

        def _run() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            settings.apply_env_overrides()
            manager.attach(self._on_engine_event)
            # unpack the APK-bundled FFmpeg on first launch (non-fatal)
            if runtime.IS_ANDROID:
                try:
                    runtime.bundled_ffmpeg()
                except Exception:  # noqa: BLE001
                    pass
            self._ready.set()
            loop.run_forever()

        self._thread = threading.Thread(target=_run, name="avd-engine", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=30)

    def _on_engine_event(self, event: dict) -> None:
        # emitted from the engine loop thread — hand the payload to listeners,
        # which marshal onto the Kivy main thread themselves
        kind = event.get("type", "")
        payload = event.get("payload", {})
        with self._lock:
            listeners = list(self._listeners)
        for cb in listeners:
            try:
                cb(payload, kind)
            except Exception:  # noqa: BLE001 — a dead listener must not kill workers
                pass

    def add_listener(self, cb: Callable[[dict, str], None]) -> None:
        with self._lock:
            self._listeners.append(cb)

    def submit(self, fn, *args, **kwargs):
        """Run a blocking engine call on the UI worker pool (never the GL thread)."""
        return self._pool.submit(fn, *args, **kwargs)

    # ------------------------------------------------------------------ asyncio bridge
    def _run_async(self, coro, timeout: float | None = None):
        assert self._loop is not None
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    def _run_sync(self, fn, *args, **kwargs):
        """Run a synchronous manager call *on the loop thread* (asyncio objects
        are not safe to touch from arbitrary threads)."""
        assert self._loop is not None
        return asyncio.run_coroutine_threadsafe(
            self._sync_helper(fn, *args, **kwargs), self._loop
        ).result()

    @staticmethod
    async def _sync_helper(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    # ------------------------------------------------------------------ analysis
    def analyze(self, url: str) -> dict:
        """Blocking analyze() — call via :meth:`submit` from the UI."""
        return self._run_async(media.analyze(url), timeout=240)

    def scan_page(self, url: str) -> dict:
        from .core import media as m

        async def _go():
            candidates = await m.scan_page(url, limit=24)
            return {"candidates": candidates}

        return self._run_async(_go(), timeout=120)

    def enqueue_from_card(self, url: str, title: str = "", fmt: dict | None = None,
                          referer: str = "", kind: str = "") -> str:
        """The mobile twin of the desktop's POST /analyze/download:
        plan the worker, attach the hosting page as Referer, enqueue."""
        async def _go() -> str:
            if kind:
                plan = {"url": url, "kind": kind, "title": title,
                        "file_type": "video",
                        "meta": {"format": (fmt or {}).get("format", "bv*+ba/b"),
                                 "quality": (fmt or {}).get("label", "")}}
            else:
                plan = await media.plan_download(url, title=title, fmt=fmt)
            if plan["kind"] == "magnet":
                raise ValueError("لینک‌های مگنت فقط قابل کپی هستند — باید در کلاینت تورنت باز شوند.")
            meta = plan.get("meta", {})
            if referer:
                meta["referer"] = referer
            job = manager.enqueue(
                url=plan["url"], kind=plan["kind"],
                filename=plan.get("filename", ""), title=plan.get("title", ""),
                file_type=plan.get("file_type", "link"), meta=meta)
            return job.id

        return self._run_async(_go(), timeout=60)

    def enqueue_direct(self, url: str, title: str = "", filename: str = "",
                       meta: dict | None = None) -> str:
        def _go() -> str:
            job = manager.enqueue(url=url, kind="http", filename=filename,
                                  title=title or url, meta=meta or {})
            return job.id

        return self._run_sync(_go)

    # ------------------------------------------------------------------ job controls
    def list_jobs(self) -> list[dict]:
        return self._run_sync(manager.list_jobs)

    def pause(self, job_id: str) -> bool:
        return self._run_sync(manager.pause, job_id)

    def resume(self, job_id: str) -> bool:
        return self._run_sync(manager.resume, job_id)

    def cancel(self, job_id: str) -> bool:
        return self._run_sync(manager.cancel, job_id)

    def retry(self, job_id: str) -> bool:
        return self._run_sync(manager.retry, job_id)

    def remove(self, job_id: str) -> bool:
        return self._run_sync(manager.remove, job_id)

    def clear_finished(self) -> int:
        return self._run_sync(manager.clear_finished)

    def update_settings(self, patch: dict) -> dict:
        def _go() -> dict:
            merged = settings.update(patch)
            import asyncio as _aio

            manager._sem = _aio.Semaphore(max(1, int(merged.get("max_concurrent", 2))))
            if {"ytdlp_browser_cookies", "cookies_file"} & set(patch):
                from .core import cookies as cookie_state

                cookie_state.reset()
            return merged

        return self._run_sync(_go)

    # ------------------------------------------------------------------ diagnostics
    def system_status(self) -> dict:
        from .core import cookies as cookie_state, net, sites, ytcli

        ff = find_ffmpeg()
        engine = ytcli.detect()
        ytdlp_version = (engine["cli_version"] if engine["use_cli"]
                         else engine["module_version"] or "?")
        return {
            "app_version": APP_VERSION,
            "ffmpeg": ff,
            "yt_dlp": ytdlp_version,
            "yt_dlp_engine": engine["label"],
            "tls_impersonation": net.has_impersonation(),
            "sites": len(sites.RECIPES),
            "embed_hosts": len(sites.EMBED_HOSTS),
            "cookies": cookie_state.source(),
            "download_dir": settings.get("download_dir"),
            "is_android": runtime.IS_ANDROID,
            "abi": runtime._device_abi() if runtime.IS_ANDROID else "desktop",
        }


engine = Engine()
