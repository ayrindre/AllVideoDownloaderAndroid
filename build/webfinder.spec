# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for WebFinder (Windows).

    pyinstaller build/webfinder.spec

Produces `dist/WebFinder.exe` — a single-file, windowless app that starts the
FastAPI backend in-process and opens a frameless pywebview (WebView2) window.
"""
import os

block_cipher = None

a = Analysis(
    ["../run.py"],
    pathex=[os.path.abspath(".")],
    binaries=[],
    datas=[("../web", "web")],                    # frontend is bundled read-only
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
    excludes=["tkinter", "PyQt5", "PySide6", "matplotlib", "test"],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

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
    icon="icon.ico",
    disable_windowed_traceback=False,
)
