"""All Video Downloader — FFmpeg / ffprobe integration for stream capture & remux.

The app ships *without* FFmpeg (it is ~100 MB); at runtime we look it up in
Settings → ffmpeg_path, then on PATH, then next to the executable. When it is
found, `.m3u8` / `.mpd` links are captured with `-c copy` (lossless, nearly
CPU-free) into the user's preferred container, with an x264 re-encode
available as fallback when codecs don't fit the target container.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import time
from pathlib import Path

from ..config import settings

RECODE_CONTAINERS = {"mp4", "mkv", "mov"}
_TIME_RE = re.compile(r"out_time_(?:us|ms)=(\d+)")


def find_ffmpeg() -> dict:
    """Locate ffmpeg/ffprobe: settings override → PATH → app folder."""
    cfg = (settings.get("ffmpeg_path") or "").strip()

    def locate(binary: str) -> str:
        if cfg:
            p = Path(cfg)
            cand = p if p.suffix else p / f"{binary}.exe"
            if cand.exists():
                return str(cand)
        w = shutil.which(binary)
        if w:
            return w
        for d in (Path.cwd(), Path.cwd() / "bin"):
            for suffix in ("", ".exe"):
                p = d / f"{binary}{suffix}"
                if p.exists():
                    return str(p)
        return ""

    ffmpeg, ffprobe = locate("ffmpeg"), locate("ffprobe")
    if not (ffmpeg and ffprobe):
        # one-shot auto-heal: fetch the official build into <app>/bin (no-op when
        # already tried, disabled via WEBFINDER_NO_FFMPEG_INSTALL=1)
        from . import ffmpeg_setup
        if ffmpeg_setup.ensure_ffmpeg():
            ffmpeg, ffprobe = locate("ffmpeg"), locate("ffprobe")
    return {"ffmpeg": ffmpeg, "ffprobe": ffprobe, "available": bool(ffmpeg and ffprobe)}


async def probe(url: str, headers: dict | None = None) -> dict:
    """Return {duration, bit_rate, size, streams} for any URL ffmpeg can open."""
    bins = find_ffmpeg()
    if not bins["available"]:
        return {}
    args = [bins["ffprobe"], "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams"]
    for k, v in (headers or {}).items():
        args += [f"-{k.lower()}", v]
    args.append(url)
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=25)
        data = json.loads(out.decode("utf-8", "ignore") or "{}")
        fmt = data.get("format", {})
        return {
            "duration": float(fmt.get("duration") or 0),
            "bit_rate": int(fmt.get("bit_rate") or 0),
            "size": int(fmt.get("size") or 0),
            "streams": [
                {"type": s.get("codec_type"), "codec": s.get("codec_name"),
                 "width": s.get("width"), "height": s.get("height")}
                for s in data.get("streams", [])
            ],
        }
    except (asyncio.TimeoutError, json.JSONDecodeError, OSError, ValueError):
        return {}


async def capture_stream(job, check_flags, publish) -> None:
    """Capture an HLS/DASH stream to job.filepath, updating progress as it runs."""
    bins = find_ffmpeg()
    if not bins["available"]:
        raise RuntimeError(
            "FFmpeg was not found. Install it with `winget install Gyan.FFmpeg` "
            "or set Settings → FFmpeg path to the folder containing ffmpeg.exe.")

    container = (settings.get("default_container") or "mp4").lower().lstrip(".")
    out_path = Path(str(job.filepath))
    if out_path.suffix.lstrip(".").lower() != container:
        out_path = out_path.with_suffix(f".{container}")
        job.filepath = str(out_path)
        job.filename = out_path.name
    job.filepath = str(out_path)

    headers = job.meta.get("headers") or {}
    # a user-picked variant: fetch THAT media playlist instead of letting
    # ffmpeg auto-climb the master (this is what makes stream quality a CHOICE)
    source = job.meta.get("variant_url") or job.url
    info = await probe(source, headers)
    duration = int(info.get("duration") or 0)
    job.unit = "time"
    job.total = duration
    job.done = 0

    reencode = bool(job.meta.get("reencode"))
    args = [bins["ffmpeg"], "-hide_banner", "-nostdin", "-loglevel", "error",
            "-progress", "pipe:1", "-nostats", "-y",
            "-user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AVD/2.0"]
    for k, v in headers.items():
        args += [f"-{k.lower()}", v]
    if job.meta.get("referer"):
        args += ["-headers", f"Referer: {job.meta['referer']}\r\n"]
    args += ["-i", source]
    if reencode:
        args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                 "-c:a", "aac", "-b:a", "192k"]
    elif container == "mp4":
        args += ["-c", "copy", "-bsf:a", "aac_adtstoasc", "-movflags", "+faststart"]
    else:
        args += ["-c", "copy"]
    args.append(str(out_path))

    t0, last_emit = time.time(), 0.0
    env = None
    px = (settings.get("proxy") or "").strip()
    if px:
        env = {**os.environ, "http_proxy": px, "https_proxy": px}
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env)
    assert proc.stdout is not None
    try:
        while True:
            chunk = await proc.stdout.readline()
            if not chunk:
                break
            m = _TIME_RE.search(chunk.decode("utf-8", "ignore"))
            if not m:
                continue
            seconds = int(m.group(1)) / 1_000_000  # ffmpeg reports microseconds
            job.done = int(seconds)
            if duration:
                job.progress_pct = round(min(100.0, seconds / duration * 100), 1)
                job.eta = max(0, duration - seconds)
            job.speed = round(seconds / max(0.5, time.time() - t0), 1)  # x realtime
            if time.time() - last_emit >= 0.4:
                last_emit = time.time()
                await check_flags(job)
                publish(job)
    except asyncio.CancelledError:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
        raise
    ret = await proc.wait()
    if ret not in (0, None) and not job._cancel.is_set():
        err = b""
        if proc.stderr:
            err = await proc.stderr.read()
        raise RuntimeError(f"FFmpeg exited with {ret}. {err.decode('utf-8','ignore')[-400:]}")
    if not out_path.exists():
        raise RuntimeError("FFmpeg finished but no output file was produced.")
    job.unit = "bytes"
    job.done = job.total = out_path.stat().st_size
    job.progress_pct = 100.0
    publish(job)
