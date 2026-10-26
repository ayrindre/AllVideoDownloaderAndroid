# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for All Video Downloader (Windows).

    .venv\\Scripts\\python.exe -m PyInstaller build\\webfinder.spec --noconfirm

Produces `dist\\AllVideoDownloader.exe` — one file, no console window, frameless
pywebview shell. Every path is derived from SPECPATH, so the build works from any
working directory (build.bat relies on that).

Notes that matter for a *working* EXE:
  * `web/` is bundled as data and app.py finds it through `_MEIPASS` — without
    this the packaged app starts and then serves a blank page.
  * yt-dlp loads its ~1,900 extractors by walking packages at runtime, so the
    whole `yt_dlp` tree has to be collected explicitly (PyInstaller alone only
    sees the modules that are imported at the top level).
  * curl_cffi ships native libraries (its TLS impersonation) that must ride
    along, or every Cloudflare-guarded site 403s inside the frozen build.
"""
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))          # noqa: F821
web_dir = os.path.join(ROOT, "web")
icon = os.path.join(SPECPATH, "icon.ico")
if not os.path.isdir(web_dir):
    raise SystemExit(f"[spec] frontend folder missing: {web_dir}")
for must in ("run.py", "webfinder"):
    if not os.path.exists(os.path.join(ROOT, must)):
        raise SystemExit(f"[spec] {must} missing next to build/ — wrong folder?")

hidden = [
    "webfinder", "webfinder.app", "webfinder.api", "webfinder.config",
    "webfinder.core", "webfinder.core.cookies", "webfinder.core.downloader",
    "webfinder.core.media", "webfinder.core.embed", "webfinder.core.sites",
    "webfinder.core.net", "webfinder.core.filekind", "webfinder.core.ytcli",
    "webfinder.core.ffmpeg_tools", "webfinder.core.ffmpeg_setup",
    "webfinder.desktop", "webfinder.desktop.window",
    "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto", "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto", "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan.on", "websockets", "httpx", "httpcore", "h2", "socksio",
    "yt_dlp", "yt_dlp.extractor", "yt_dlp.compat",
]
binaries = []
datas = [(web_dir, "web")]

# Dynamic importers: collect everything they can reach at runtime.
try:
    from PyInstaller.utils.hooks import collect_submodules
    hidden += collect_submodules("yt_dlp.extractor")
except Exception as exc:                                    # noqa: BLE001
    print(f"[spec] WARNING: could not enumerate yt_dlp extractors ({exc})")

for pkg in ("curl_cffi", "pywebview", "webview"):
    try:
        from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules
        hidden += collect_submodules(pkg)
        binaries += collect_dynamic_libs(pkg)
    except Exception:                                       # noqa: BLE001
        pass                                                # optional package, absent is fine

a = Analysis(
    [os.path.join(ROOT, "run.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6", "matplotlib",
              "pytest", "test", "gallery_dl"],
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
    name="AllVideoDownloader",
    debug=False,
    strip=False,
    upx=False,                       # UPX is not installed by default and corrupts Qt/DLLs
    runtime_tmpdir=None,
    console=False,                   # no black console window
    icon=icon if os.path.exists(icon) else None,
    disable_windowed_traceback=False,
)
