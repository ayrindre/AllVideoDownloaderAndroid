"""All Video Downloader (Android) — platform abstraction layer.

Everything that is *different* between the desktop original and the Android
port lives here: storage paths, clipboard, share/open intents and the
first-launch bootstrap that turns the FFmpeg binaries shipped inside the APK
into executable files in app-private storage.

The download engine itself (``avd.core``) is the desktop engine, unchanged in
behaviour — it only asks this module where things are.
"""
from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------
IS_ANDROID = "ANDROID_ARGUMENT" in os.environ or "ANDROID_ROOT" in os.environ

_APP_NAME = "All Video Downloader"


def _jnius():
    """Import pyjnius lazily — it only exists on the Android runtime."""
    if not IS_ANDROID:
        return None
    from jnius import autoclass  # type: ignore

    return autoclass


# ---------------------------------------------------------------------------
# Storage — app-specific external storage needs NO runtime permission
# ---------------------------------------------------------------------------
_python_activity: object | None = None
_files_dir: Path | None = None
_external_files_dir: Path | None = None


def _resolve_dirs() -> None:
    global _python_activity, _files_dir, _external_files_dir
    if _files_dir is not None:
        return
    if IS_ANDROID:
        autoclass = _jnius()
        try:
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            activity = PythonActivity.mActivity
            _python_activity = activity
            context = activity.getApplicationContext()
            _files_dir = Path(str(context.getFilesDir().getAbsolutePath()))
            ext = context.getExternalFilesDir(None)
            _external_files_dir = Path(str(ext.getAbsolutePath())) if ext is not None else _files_dir
            return
        except Exception:  # noqa: BLE001 — fall through to plain-Linux paths
            pass
    # Desktop / unit-test fallback
    base = Path(os.environ.get("AVD_HOME") or Path.home() / ".avd-mobile")
    _files_dir = base / "files"
    _external_files_dir = base / "external"
    _files_dir.mkdir(parents=True, exist_ok=True)
    _external_files_dir.mkdir(parents=True, exist_ok=True)


def files_dir() -> Path:
    """Writable app-private internal storage (settings, cookies, executables)."""
    _resolve_dirs()
    assert _files_dir is not None
    return _files_dir


def external_dir() -> Path:
    """App-specific external storage — visible in Android's file manager under
    ``Android/data/<package>/files`` without any runtime permission."""
    _resolve_dirs()
    assert _external_files_dir is not None
    return _external_files_dir


def config_dir() -> Path:
    d = files_dir() / "config"
    d.mkdir(parents=True, exist_ok=True)
    return d


def downloads_dir() -> Path:
    # Movies/All Video Downloader inside the app-specific external volume
    d = external_dir() / "Movies" / _APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def bin_dir() -> Path:
    d = files_dir() / "bin"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cookies_path() -> Path:
    """A well-known location users can drop a Netscape ``cookies.txt`` into
    (via any Android file manager) — no Storage Access Framework plumbing."""
    return external_dir() / "cookies.txt"


# ---------------------------------------------------------------------------
# Bundled FFmpeg / FFprobe — the Android replacement for the Windows .exe files
# ---------------------------------------------------------------------------
def _asset_root() -> Path:
    """Where buildozer's ``include_patterns`` unpack data files at runtime."""
    # __file__ == .../avd/platform/runtime.py inside the extracted private bundle;
    # assets ship next to the `avd` package.
    return Path(__file__).resolve().parent.parent.parent / "assets"


def _device_abi() -> str:
    if not IS_ANDROID:
        return "x86_64"
    autoclass = _jnius()
    try:
        Build = autoclass("android.os.Build")
        abis = list(Build.SUPPORTED_ABIS or [])
        preferred = ("arm64-v8a", "armeabi-v7a", "x86_64", "x86")
        for abi in preferred:
            if abi in abis:
                return abi
        return abis[0] if abis else "arm64-v8a"
    except Exception:  # noqa: BLE001
        return "arm64-v8a"


def bundled_ffmpeg() -> dict:
    """Copy the APK-binned ffmpeg/ffprobe of the right ABI into private
    storage and make them executable.

    Files inside an APK are not executable, so the first launch pays the
    copy price once; afterwards the binaries are reused.
    """
    target = bin_dir()
    abi = _device_abi()
    result = {"ffmpeg": "", "ffprobe": "", "available": False, "abi": abi, "error": ""}
    try:
        src_dir = _asset_root() / "bin" / abi
        for name in ("ffmpeg", "ffprobe"):
            src = src_dir / name
            dst = target / name
            if not src.exists():
                result["error"] = f"bundled {name} for {abi} is missing"
                continue
            # re-copy when the APK shipped a newer build
            if (not dst.exists()) or src.stat().st_size != dst.stat().st_size:
                shutil.copyfile(src, dst)
            dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            result[name] = str(dst)
        result["available"] = bool(result["ffmpeg"] and result["ffprobe"])
    except Exception as exc:  # noqa: BLE001 — never break app startup
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def ffmpeg_self_test(path: str) -> bool:
    """Run `<ffmpeg> -version` to prove the binary actually executes here."""
    import subprocess

    try:
        r = subprocess.run([path, "-version"], capture_output=True, timeout=15)
        return r.returncode == 0
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# Clipboard
# ---------------------------------------------------------------------------
def clipboard_get() -> str:
    if IS_ANDROID:
        autoclass = _jnius()
        try:
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            Context = autoclass("android.content.Context")
            clip = PythonActivity.mActivity.getSystemService(Context.CLIPBOARD_SERVICE)
            data = clip.getPrimaryClip()
            if data is not None and data.getItemCount() > 0:
                item = data.getItemAt(0)
                text = item.getText()
                return str(text) if text is not None else ""
        except Exception:  # noqa: BLE001
            pass
        return ""
    try:
        import subprocess

        r = subprocess.run(["xclip", "-selection", "clipboard", "-o"],
                           capture_output=True, text=True, timeout=3)
        return (r.stdout or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def clipboard_set(text: str) -> None:
    if IS_ANDROID:
        autoclass = _jnius()
        try:
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            Context = autoclass("android.content.Context")
            ClipData = autoclass("android.content.ClipData")
            clip = PythonActivity.mActivity.getSystemService(Context.CLIPBOARD_SERVICE)
            clip.setPrimaryClip(ClipData.newPlainText("AVD", text))
            return
        except Exception:  # noqa: BLE001
            pass
    try:
        import subprocess

        p = subprocess.Popen(["xclip", "-selection", "clipboard"], stdin=subprocess.PIPE)
        p.communicate(text.encode("utf-8"), timeout=3)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Android intents — share / open a downloaded file
# ---------------------------------------------------------------------------
# Files live in app-specific external storage, which cannot leave the app
# through a bare file:// URI (FileUriExposedException on API 24+). Instead we
# publish the file into the shared MediaStore: that gives a content:// URI
# without any FileProvider/androidx dependency, and makes finished downloads
# visible in the system Files/Gallery apps too.
_media_uri_cache: dict[str, str] = {}


def _media_store_uri(path: Path, mime: str) -> str | None:
    """Insert (or reuse) a file in the shared MediaStore and return its
    content:// URI. API 29+ only — the app's minSdk."""
    if not IS_ANDROID:
        return None
    key = str(path)
    if key in _media_uri_cache:
        return _media_uri_cache[key]
    autoclass = _jnius()
    try:
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        context = PythonActivity.mActivity.getApplicationContext()
        resolver = context.getContentResolver()
        ContentValues = autoclass("android.content.ContentValues")
        ContentUris = autoclass("android.content.ContentUris")
        Environment = autoclass("android.os.Environment")
        MediaStore = autoclass("android.provider.MediaStore")
        File = autoclass("java.io.File")

        if mime.startswith("video/"):
            collection = MediaStore.Video.Media.getContentUri("external")
            rel_path = Environment.DIRECTORY_MOVIES + "/All Video Downloader/"
        elif mime.startswith("audio/"):
            collection = MediaStore.Audio.Media.getContentUri("external")
            rel_path = Environment.DIRECTORY_MUSIC + "/All Video Downloader/"
        else:
            Downloads = autoclass("android.provider.MediaStore$Downloads")
            collection = Downloads.Media.getContentUri("external")
            rel_path = Environment.DIRECTORY_DOWNLOADS + "/All Video Downloader/"

        java_file = File(str(path))
        display_name = java_file.getName()
        cols = MediaStore.MediaColumns
        String = autoclass("java.lang.String")

        # reuse an already-published entry instead of duplicating it
        cursor = resolver.query(
            collection, None,
            cols.RELATIVE_PATH + "=? AND " + cols.DISPLAY_NAME + "=?",
            String[2]([rel_path, display_name]), None)
        uri = None
        if cursor is not None:
            try:
                if cursor.moveToFirst():
                    uri = ContentUris.withAppendedId(collection, cursor.getLong(0))
            finally:
                cursor.close()

        if uri is None:
            values = ContentValues()
            values.put(cols.DISPLAY_NAME, display_name)
            values.put(cols.MIME_TYPE, mime)
            values.put(cols.RELATIVE_PATH, rel_path)
            values.put(cols.IS_PENDING, 1)
            uri = resolver.insert(collection, values)
            if uri is None:
                return None
            out = resolver.openOutputStream(uri)
            try:
                with open(path, "rb") as src:
                    while True:
                        chunk = src.read(1 << 18)
                        if not chunk:
                            break
                        out.write(chunk)
                out.flush()
            finally:
                out.close()
            done = ContentValues()
            done.put(cols.IS_PENDING, 0)
            resolver.update(uri, done, None, None)

        result = str(uri.toString())
        _media_uri_cache[key] = result
        return result
    except Exception:  # noqa: BLE001 — MediaStore is best-effort by design
        return None


def open_file(path: str | Path, mime: str = "*/*") -> bool:
    """Open a downloaded file in the user's preferred player/app."""
    p = Path(path)
    if not p.exists() or not IS_ANDROID:
        return False
    autoclass = _jnius()
    try:
        uri_str = _media_store_uri(p, mime)
        if not uri_str:
            return False
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Intent = autoclass("android.content.Intent")
        Uri = autoclass("android.net.Uri")
        intent = Intent(Intent.ACTION_VIEW)
        intent.setDataAndType(Uri.parse(uri_str), mime)
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION
                        | Intent.FLAG_ACTIVITY_NEW_TASK)
        PythonActivity.mActivity.startActivity(intent)
        return True
    except Exception:  # noqa: BLE001
        return False


def share_file(path: str | Path, mime: str = "video/mp4") -> bool:
    """Hand a finished download to the Android share sheet."""
    p = Path(path)
    if not p.exists() or not IS_ANDROID:
        return False
    autoclass = _jnius()
    try:
        uri_str = _media_store_uri(p, mime)
        if not uri_str:
            return False
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Intent = autoclass("android.content.Intent")
        Uri = autoclass("android.net.Uri")
        intent = Intent(Intent.ACTION_SEND)
        intent.setType(mime)
        intent.putExtra(Intent.EXTRA_STREAM, Uri.parse(uri_str))
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        chooser = Intent.createChooser(intent, "All Video Downloader")
        chooser.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        PythonActivity.mActivity.startActivity(chooser)
        return True
    except Exception:  # noqa: BLE001
        return False


def mime_for(path: str | Path) -> str:
    ext = Path(path).suffix.lower().lstrip(".")
    table = {
        "mp4": "video/mp4", "mkv": "video/x-matroska", "webm": "video/webm",
        "mov": "video/quicktime", "avi": "video/x-msvideo", "flv": "video/x-flv",
        "ts": "video/mp2t", "m4v": "video/mp4", "3gp": "video/3gpp",
        "mp3": "audio/mpeg", "m4a": "audio/mp4", "aac": "audio/aac",
        "opus": "audio/ogg", "ogg": "audio/ogg", "wav": "audio/wav",
        "flac": "audio/flac",
    }
    return table.get(ext, "*/*")


def incoming_share_url() -> str:
    """Read a text/URL the app received through the system share sheet
    (``ACTION_SEND`` intent filter declared in the buildozer spec)."""
    if not IS_ANDROID:
        return ""
    autoclass = _jnius()
    try:
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        intent = PythonActivity.mActivity.getIntent()
        if intent is None:
            return ""
        action = str(intent.getAction() or "")
        if action != "android.intent.action.SEND":
            return ""
        mime = str(intent.getType() or "")
        if not mime.startswith("text/"):
            return ""
        data = intent.getStringExtra("android.intent.extra.TEXT")
        return str(data or "").strip()
    except Exception:  # noqa: BLE001
        return ""
