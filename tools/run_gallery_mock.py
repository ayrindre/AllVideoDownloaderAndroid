#!/usr/bin/env python3
"""Run the REAL gallery-dl against tools/mock_instagram.py.

Used as the app's engine in tests:  AVD_GALLERYDL_BIN="python run_gallery_mock.py"

Only three things are redirected — nothing in the extractor is reimplemented:
  * `InstagramExtractor.root` → the mock host (http, random port)
  * DNS for www.instagram.com   → 127.0.0.1
  * gallery-dl's opname cache   → seeded, because the doc-id map normally comes
                                  from Instagram's CDN bundles (static.cdninstagram.com),
                                  which is unreachable offline
Everything else (page hydration, GraphQL variables, post parsing, cursor
handling, Message tuples) is gallery-dl's own code.
"""
from __future__ import annotations

import os
import pickle
import socket
import sys
import time

sys.path.insert(0, os.environ.get("AVD_MOCK_PYTHON_PATH", ""))

MOCK_PORT = int(os.environ.get("AVD_MOCK_IG_PORT", "8920"))
MOCK_SCHEME = os.environ.get("AVD_MOCK_IG_SCHEME", "https")
MOCK_HOST = f"www.instagram.com:{MOCK_PORT}"
MOCK_ROOT = f"{MOCK_SCHEME}://{MOCK_HOST}"
if ca := os.environ.get("AVD_MOCK_IG_CA"):
    os.environ.setdefault("REQUESTS_CA_BUNDLE", ca)   # trust the mock's cert

from gallery_dl import cache as dl_cache          # noqa: E402
from gallery_dl import main as dl_main           # noqa: E402
from gallery_dl.extractor import instagram as ig  # noqa: E402

# ── 1) point the extractor at the mock (plain HTTP, so no TLS plumbing) ──
ig.InstagramExtractor.root = MOCK_ROOT
ig.InstagramExtractor.browser = "chrome"

# ── 2) resolve www.instagram.com to the loopback mock ───────────────────
_real_getaddrinfo = socket.getaddrinfo


def _getaddrinfo(host, port, *args, **kwargs):
    if host in ("www.instagram.com", "instagram.com", "i.instagram.com"):
        host = "127.0.0.1"
        port = MOCK_PORT
    return _real_getaddrinfo(host, port, *args, **kwargs)


socket.getaddrinfo = _getaddrinfo

# ── 3) seed the GraphQL doc-id cache (normally scraped from the CDN) ────
db = dl_cache.database()
if db is not None:
    now = int(time.time())
    for opname, docid in ig.QUERIES.items():
        key = f"gallery_dl.extractor.instagram._extract_opname_info-{opname}"
        db.execute("INSERT OR REPLACE INTO data (key, value, expires) VALUES (?,?,?)",
                   (key, pickle.dumps((docid, None), protocol=2), now + 86400))
    db.commit()

if __name__ == "__main__":
    sys.argv = ["gallery-dl"] + sys.argv[1:]
    sys.exit(dl_main())
