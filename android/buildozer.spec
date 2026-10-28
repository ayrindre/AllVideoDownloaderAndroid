[app]

# ── Identity ───────────────────────────────────────────────────────────────
title = All Video Downloader
package.name = allvideodownloader
package.domain = ir.avd
source.dir = src
source.include_exts = py,png,jpg,kv,atlas,ttf,txt,json
# The FFmpeg/FFprobe CLI executables ship without a file extension, so they
# must be pulled in explicitly instead of via include_exts.
source.include_patterns = assets/fonts/*.ttf,assets/bin/arm64-v8a/ffmpeg,assets/bin/arm64-v8a/ffprobe
version = 3.0.0
# p4a installs pip requirements with --no-deps, so every transitive
# pure-Python dependency is listed explicitly. The httpx p4a recipe also
# forgets anyio, hence it appears here in person.
requirements = python3,kivy,kivymd==1.2.0,pyjnius,android,httpx,anyio,httpcore,h11,sniffio,certifi,idna,requests,urllib3,charset-normalizer,Pillow,pycryptodome,yt-dlp,mutagen,websockets,arabic-reshaper,python-bidi,PyYAML,typing-extensions

# ── UI / orientation ───────────────────────────────────────────────────────
orientation = portrait
fullscreen = 0
presplash.filename = src/presplash.png
icon.filename = src/icon.png
android.presplash_color = #0E1120

# ── Android target ──────────────────────────────────────────────────────────
# arm64 only: the bundled FFmpeg executables are arm64-v8a and the device
# share is >98% in 2026; keeps the APK ~40 MB smaller than a fat ABI build.
android.archs = arm64-v8a
android.api = 35
android.minapi = 29
android.ndk = 28c
android.ndk_api = 29
android.enable_androidx = False
android.allow_backup = True

# ── Permissions ─────────────────────────────────────────────────────────────
# No storage permission: downloads live in app-specific external storage;
# sharing goes through MediaStore (see avd/platform/runtime.py).
android.permissions = INTERNET,ACCESS_NETWORK_STATE,WAKE_LOCK
android.wakelock = True

# ── Receive shared links from other apps (browser / YouTube share sheet) ───
android.manifest.intent_filters = intent_filters.xml

# ── Build behaviour ─────────────────────────────────────────────────────────
log_level = 2
warn_on_root = 1
android.accept_sdk_license = True
# The python-for-android release is pinned by the CI workflow
# (pip install python-for-android==2026.5.9); buildozer uses that p4a on PATH.

[buildozer]
log_level = 2
warn_on_root = 1
