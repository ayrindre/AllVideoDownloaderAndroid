"""Auto-install of FFmpeg/FFprobe into the app's own ``bin/`` folder.

HLS/DASH capture needs the ffmpeg binaries; most users don't have them and
"download FFmpeg yourself" is a dead end for non-technical users. This module
fetches the official community builds (gyan.dev for Windows, BtbN for Linux)
into <repo>/bin — the exact directory ``ffmpeg_tools.find_ffmpeg`` already
searches — and verifies the binaries before trusting them.

Rules:
  * never blocks the app: failures degrade to the existing clear error;
  * opt-out: ``WEBFINDER_NO_FFMPEG_INSTALL=1`` or Settings (future);
  * macOS: never download — Homebrew is the right answer there.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Callable

BIN_DIR = Path(__file__).resolve().parents[2] / "bin"
_UA = "Mozilla/5.0 (AVD ffmpeg-setup)"

_BUILDS = {
    "win32": ("https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip", "zip"),
    "linux": ("https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
              "ffmpeg-master-latest-linux64-gpl.tar.xz", "tar.xz"),
}

_state: dict = {"done": False, "ok": None, "error": ""}


def installed() -> bool:
    return all((BIN_DIR / (n + (".exe" if os.name == "nt" else ""))).exists()
               for n in ("ffmpeg", "ffprobe"))


def ensure_ffmpeg(progress: Callable[[str], None] | None = None) -> bool:
    """One-shot (cached) attempt to make ffmpeg available. Returns True when
    the binaries are usable afterwards."""
    if _state["done"]:
        return bool(_state["ok"])
    _state["done"] = True
    say = progress or (lambda m: None)
    if os.environ.get("WEBFINDER_NO_FFMPEG_INSTALL"):
        _state.update(ok=False, error="auto-install disabled via environment")
        return False
    if sys.platform == "darwin":
        _state.update(ok=False, error="on macOS run: brew install ffmpeg")
        return False
    key = "win32" if sys.platform == "win32" else "linux"
    url, kind = _BUILDS[key]
    try:
        say(f"FFmpeg not found — downloading the {'Windows' if key == 'win32' else 'Linux'} build…")
        _download(url, say)
        _ = kind  # format chosen per-platform above; extractor sniffing handles both
        _state.update(ok=True, error="")
        say("FFmpeg ready in the app's bin/ folder ✓")
        return True
    except Exception as exc:  # noqa: BLE001 — hard requirement: degrade, never crash
        _state.update(ok=False, error=f"{type(exc).__name__}: {exc}")
        say(f"FFmpeg auto-install failed ({_state['error']}) — HLS capture will stay unavailable.")
        return False


def status() -> dict:
    return dict(_state)


# ── internals ───────────────────────────────────────────────────────────────
def _download(url: str, say: Callable[[str], None]) -> None:
    import httpx
    tmp = Path(tempfile.mkdtemp(prefix="wf-ffmpeg-"))
    archive = tmp / ("ffmpeg.zip" if url.endswith(".zip") else "ffmpeg.tar.xz")
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=httpx.Timeout(30, read=600),
                          headers={"User-Agent": _UA}, verify=False) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length") or 0)
            got = 0
            last_pct = -10
            with archive.open("wb") as fh:
                for chunk in r.iter_bytes(1 << 18):
                    fh.write(chunk)
                    got += len(chunk)
                    if total:
                        pct = int(got * 100 / total)
                        if pct - last_pct >= 10:
                            last_pct = pct
                            say(f"FFmpeg download… {pct}%")
        _extract(archive, tmp)
        _place(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _extract(archive: Path, dest: Path) -> None:
    if archive.suffix == ".zip" or zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as z:
            z.extractall(dest)
    else:
        with tarfile.open(archive, "r:xz") as t:
            try:
                t.extractall(dest, filter="data")
            except TypeError:      # older stdlib without extraction filters
                t.extractall(dest)


def _place(dest: Path) -> None:
    found: dict[str, Path] = {}
    for p in dest.rglob("*"):
        name = p.name.lower()
        if not p.is_file():
            continue
        if name in ("ffmpeg.exe", "ffmpeg"):
            found["ffmpeg"] = p
        elif name in ("ffprobe.exe", "ffprobe"):
            found["ffprobe"] = p
    if "ffmpeg" not in found or "ffprobe" not in found:
        raise RuntimeError("archive did not contain ffmpeg/ffprobe binaries")
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    for name, src in found.items():
        suffix = ".exe" if os.name == "nt" else ""
        target = BIN_DIR / (name + suffix)
        shutil.copyfile(src, target)
        target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    # verify they actually run (AVX2-less CPUs fail on BtbN "latest" gpl builds)
    for name in ("ffmpeg", "ffprobe"):
        exe = BIN_DIR / (name + (".exe" if os.name == "nt" else ""))
        r = subprocess.run([str(exe), "-version"], capture_output=True, timeout=15)
        if r.returncode != 0:
            raise RuntimeError(f"{name} failed its self-test")
    # make children (ffmpeg worker) find them without PATH edits too
    os.environ["PATH"] = f"{BIN_DIR}{os.pathsep}" + os.environ.get("PATH", "")
