# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for WebFinder (Windows).

    python -m PyInstaller build/webfinder.spec --noconfirm

Produces `dist/WebFinder.exe` — single file, no console, frameless pywebview
window. All paths resolve from SPECPATH so the build works from any cwd
(`build.bat` does exactly this).
"""
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))          # noqa: F821
web_dir = os.path.join(ROOT, "web")
icon = os.path.join(SPECPATH, "icon.ico")
if not os.path.exists(web_dir):
    raise SystemExit(f"[spec] frontend folder missing: {web_dir}")

a = Analysis(
    [os.path.join(ROOT, "run.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[(web_dir, "web")],                 # frontend bundled read-only
    hiddenimports=[
        "webfinder", "webfinder.app", "webfinder.api", "webfinder.core",
        "webfinder.core.downloader", "webfinder.core.media", "webfinder.core.dorks",
        "webfinder.core.ffmpeg_tools", "webfinder.engines",
        "webfinder.desktop.window",
        "uvicorn.logging", "uvicorn.loops.asyncio", "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.websockets.wsproto_impl", "websockets",
        "yt_dlp", "httpx", "h2",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "PyQt5", "PySide6", "matplotlib", "test", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="WebFinder",
    debug=False,
    strip=False,
    upx=True,
    upx_exclude=["ffmpeg.dll"],
    runtime_tmpdir=None,
    console=False,                       # no black console window
    icon=icon if os.path.exists(icon) else None,
    disable_windowed_traceback=False,
)
