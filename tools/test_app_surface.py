#!/usr/bin/env python3
"""All Video Downloader — app-surface contract (what the user can actually see).

The Instagram checker was removed deliberately: it needed a third-party engine
(gallery-dl) and a logged-in session to answer, and it never worked reliably for
the person using the app. A removal like that only stays removed if something
asserts it, so this file locks the surface down:

  * three tabs, and no Instagram view / script / API left anywhere
  * the download engine's endpoints are all still there (that path was off-limits)
  * retired settings keys are stripped from settings.json on load
  * the Settings page renders four cards, in order, once — with one save chip

Run:  python tools/test_app_surface.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="avd-surface-"))
os.environ["AVD_HOME"] = str(TMP / "home")
(TMP / "home").mkdir(parents=True, exist_ok=True)
# a settings.json written by the Instagram era: its keys must not survive
(TMP / "home" / "settings.json").write_text(json.dumps({
    "download_dir": str(TMP / "dl"), "default_quality": "720",
    "instagram_include": "posts,reels", "instagram_limit": 30, "instagram_delay": "",
}), encoding="utf-8")

from fastapi.testclient import TestClient                        # noqa: E402
from webfinder.app import app                                     # noqa: E402
from webfinder.config import settings                             # noqa: E402

client = TestClient(app)


def check(name: str, cond: bool, extra: str = "") -> None:
    if not cond:
        raise AssertionError(f"{name} {extra}".strip())
    print(f"✓ {name}" + (f"  ({extra})" if extra else ""))


# ═══ 1. the checker is gone from the API ══════════════════════════════════
for path in ("/api/gallery/engine", "/api/gallery/scans", "/api/cookies/instagram-session"):
    r = client.post(path, json={}) if "session" in path else client.get(path)
    check(f"removed endpoint {path} is 404", r.status_code == 404, str(r.status_code))

meta = client.get("/api/meta").json()
check("meta no longer advertises gallery-dl", "gallery_dl" not in meta["system"],
      ",".join(sorted(meta["system"])))
check("meta still reports the download engine", all(
    k in meta["system"] for k in ("ffmpeg", "yt_dlp", "yt_dlp_engine", "cookies", "sites", "tls_impersonation")))

# ═══ 2. the download path is intact ═══════════════════════════════════════
for path in ("/api/settings", "/api/downloads", "/api/sites", "/api/cookies/status"):
    check(f"download-path endpoint {path} still answers", client.get(path).status_code == 200)

check("/api/analyze still accepts a URL", client.post("/api/analyze", json={"url": "not a url"}).status_code in (200, 400, 502))
check("/api/downloads rejects junk instead of crashing",
      client.post("/api/downloads", json={"url": "nonsense"}).status_code == 400)

# ═══ 3. retired settings keys never resurrect ═════════════════════════════
snap = client.get("/api/settings").json()
dead = [k for k in snap if k.startswith("instagram_")]
check("settings.json lost its instagram_* keys", not dead, ",".join(dead))
check("settings kept the user's real values", snap["default_quality"] == "720", snap["default_quality"])
patched = client.put("/api/settings", json={"patch": {"instagram_limit": 99}}).json()
check("and PUT cannot write them back", "instagram_limit" not in patched)

# ═══ 4. the frontend surface ══════════════════════════════════════════════
index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
check("no Instagram view in index.html", "view-instagram" not in index)
check("no instagram.js script tag", "views/instagram.js" not in index)
check("the three views that remain are declared", all(
    f'id="view-{v}"' in index for v in ("direct", "downloads", "settings")))
check("the old checker stylesheet block is gone",
      not re.search(r"\.ig-(card|warn|session|stage)", (ROOT / "web/css/views.css").read_text(encoding="utf-8")))

app_js = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
nav = re.findall(r'view: "(view-[a-z]+)"', app_js)
check("app.js declares three tabs", nav == ["view-direct", "view-downloads", "view-settings"], " ".join(nav))
check("app.js never touches an Instagram view", "Instagram" not in app_js)

api_js = (ROOT / "web" / "js" / "api.js").read_text(encoding="utf-8")
check("api.js exposes no gallery endpoints", not re.search(r"gallery|instagram", api_js, re.I))

settings_js = (ROOT / "web" / "js" / "views" / "settings.js").read_text(encoding="utf-8")
cards = re.findall(r'card\("([^"]+)"', settings_js)
check("settings builds four cards in a fixed order",
      cards == ["Downloads", "Video & capture", "Appearance", "System"], " ".join(cards))
check("settings page has no checker controls", not re.search(r"instagram|gallery|sessionid", settings_js, re.I))
check("one save indicator, not one per card", settings_js.count('id="set-saved"') == 0
      and settings_js.count("#set-saved") == 1)
check("index.html has exactly one save chip",
      index.count('id="set-saved"') == 1)

# ═══ 5. the build knows about everything that must ship ═══════════════════
spec = (ROOT / "build" / "webfinder.spec").read_text(encoding="utf-8")
check("the build spec no longer bundles gallery-dl",
      "gallery_dl" not in spec.split("excludes=")[0], "hiddenimports stay clean")
check("the spec bundles the web folder", '"web"' in spec)
for mod in ("webfinder.core.cookies", "webfinder.core.downloader", "webfinder.core.media",
            "webfinder.core.embed", "webfinder.core.sites", "webfinder.core.net"):
    check(f"spec hidden-imports {mod}", f'"{mod}"' in spec)
check("build.bat names the artifact it verifies",
      "AllVideoDownloader.exe" in (ROOT / "build.bat").read_text(encoding="utf-8", errors="ignore"))

# ═══ 6. the EXE carries an icon, and the installer knows about it ══════════
ico = ROOT / "build" / "icon.ico"
check("build/icon.ico exists for the PyInstaller --icon step", ico.is_file())
_blob = ico.read_bytes()
check("it is a real multi-resolution .ico",
      _blob[:4] == b"\x00\x00\x01\x00" and _blob[4] >= 5, f"{_blob[4]} frames")
_sizes = sorted({_blob[6 + 16 * i] or 256 for i in range(_blob[4])})
check("it scales from 16 px up to 256 px", _sizes[0] == 16 and _sizes[-1] == 256, str(_sizes))

check("the spec passes the icon to EXE()", 'icon=icon if os.path.exists(icon)' in spec)
check("the spec points at build/icon.ico", 'os.path.join(SPECPATH, "icon.ico")' in spec)
_iss = (ROOT / "build" / "installer.iss").read_text(encoding="utf-8")
check("the installer uses the same icon", "SetupIconFile=icon.ico" in _iss)
check("the icon is reproducible, not a mystery blob", (ROOT / "tools" / "make_icon.py").is_file())
check("build.bat regenerates a missing icon",
      "tools\\make_icon.py" in (ROOT / "build.bat").read_text(encoding="utf-8", errors="ignore"))

# ═══ 7. one version, stated once ═══════════════════════════════════════════
import re as _re

_cfg = (ROOT / "webfinder" / "config.py").read_text(encoding="utf-8")
_ver = _re.search(r'APP_VERSION\s*=\s*"([^"]+)"', _cfg).group(1)
check("the app version is 2.2.x", _ver.startswith("2.2"), _ver)
check("the installer version matches config.py",
      f'#define AppVersion "{_ver}"' in _iss, _ver)
_index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
check("the sidebar badge is not stale", 'id="app-version">v2.2<' in _index)

# ═══ 8. the home page does not hard-sell two sites ═════════════════════════
_direct = (ROOT / "web" / "js" / "views" / "direct.js").read_text(encoding="utf-8")
_quick = _direct.split("const QUICK = [", 1)[1].split("];", 1)[0]
check("no Aparat/Filimo quick-try chips on the home page",
      "aparat" not in _quick.lower() and "filimo" not in _quick.lower(), _quick.strip()[:60])
check("the quick-try row still offers generic examples",
      _quick.count("{ label:") >= 3, f"{_quick.count('{ label:')} chips")

print("\nAPP-SURFACE TESTS PASSED")
