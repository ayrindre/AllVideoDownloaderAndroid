#!/usr/bin/env python3
"""End-to-end test of the mobile Engine facade against a local HTTP server.

No external network: a localhost http.server serves a fake .mp4, an HLS
master playlist and an HTML page. Exercises the exact code paths the Kivy UI
calls (analyze → plan → enqueue → progress → done), plus job controls and
the settings/status bridges — all through the background asyncio thread.
"""
from __future__ import annotations

import http.server
import os
import shutil
import socketserver
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

os.environ["AVD_HOME"] = tempfile.mkdtemp(prefix="avd-svc-")

from avd.engine import engine  # noqa: E402

M3U8 = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=5500000,RESOLUTION=1920x1080,CODECS="avc1.640028,mp4a.40.2"
1080p/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=2800000,RESOLUTION=1280x720
720p/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=1200000,RESOLUTION=640x360
360p/index.m3u8
"""

PAGE = """<!doctype html><html><head>
<meta property="og:video" content="https://cdn.example.com/og-clip.mp4">
<title>Sample tube page</title></head>
<body><video><source src="/player/clip_720.mp4" type="video/mp4"></video>
<a href="/files/movie.mp4?download=true">movie</a></body></html>
"""


def main() -> None:
    webroot = Path(tempfile.mkdtemp(prefix="avd-web-"))
    payload = bytes((i * 73 + 17) % 256 for i in range(2 * 1024 * 1024))  # 2 MB
    (webroot / "clip.mp4").write_bytes(payload)
    (webroot / "master.m3u8").write_text(M3U8)
    (webroot / "page.html").write_text(PAGE)

    handler = lambda *a: http.server.SimpleHTTPRequestHandler(*a, directory=str(webroot))  # noqa: E731

    class _TCPServer(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    httpd = _TCPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"

    engine.start()
    print("✓ engine thread started with its own event loop")

    # 1) direct file → kind=direct card ------------------------------------------------
    card = engine.analyze(base + "/clip.mp4")
    assert card["kind"] == "direct", card
    assert card["size"] == len(payload)
    print("✓ analyze(direct mp4) → direct card with real size")

    # 2) real HTTP download through the manager on the engine thread ------------------
    jid = engine.enqueue_direct(base + "/clip.mp4", title="clip", filename="clip.mp4")
    deadline = time.time() + 30
    final = None
    while time.time() < deadline:
        jobs = {j["id"]: j for j in engine.list_jobs()}
        final = jobs.get(jid)
        if final and final["status"] in ("done", "error", "cancelled"):
            break
        time.sleep(0.2)
    assert final is not None and final["status"] == "done", final
    saved = Path(final["filepath"])
    assert saved.read_bytes() == payload, "downloaded bytes differ from source"
    print("✓ http worker downloaded and verified 2 MB, job = done")

    # 3) remove job ---------------------------------------------------------------------
    assert engine.remove(jid) is True
    assert all(j["id"] != jid for j in engine.list_jobs())
    print("✓ job removal is server-authoritative")

    # 4) HLS master → locally parsed variant ladder ------------------------------------
    hls = engine.analyze(base + "/master.m3u8")
    assert hls["kind"] == "hls", hls
    heights = sorted((f.get("height") or 0) for f in hls["formats"])
    assert 1080 in heights and 720 in heights and 360 in heights, heights
    print(f"✓ analyze(m3u8) → HLS card with variant ladder {heights}")

    # 5) HTML page deep-scan → media candidates ----------------------------------------
    page_card = engine.analyze(base + "/page.html")
    assert page_card["kind"] == "page", page_card
    urls = " ".join(c["url"] for c in page_card["candidates"])
    assert "clip_720.mp4" in urls and "movie.mp4" in urls, urls
    print(f"✓ analyze(html page) → {len(page_card['candidates'])} media candidates")

    # 6) settings bridge ----------------------------------------------------------------
    merged = engine.update_settings({"max_concurrent": 4, "proxy": ""})
    assert merged["max_concurrent"] == 4
    assert engine.system_status()["sites"] >= 380
    print("✓ settings update + system status (recipes/ffmpeg/yt-dlp) work")

    # 7) magnet link stays copy-only ----------------------------------------------------
    magnet = engine.analyze("magnet:?xt=urn:btih:aaa&dn=movie")
    assert magnet["kind"] == "magnet"
    try:
        engine.enqueue_from_card(magnet["url"])
        raise AssertionError("magnet enqueue should be refused")
    except ValueError:
        pass
    print("✓ magnet links are identified and refused for download")

    httpd.shutdown()
    shutil.rmtree(webroot, ignore_errors=True)
    print("\nENGINE SERVICE TESTS PASSED")


if __name__ == "__main__":
    main()
