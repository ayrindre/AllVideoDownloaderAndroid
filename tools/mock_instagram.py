#!/usr/bin/env python3
"""A faithful-enough mock of Instagram's web endpoints, for offline testing.

It reproduces the one behaviour that decides whether a profile scan works at
all: **the profile page is login-gated**. Logged out (no `sessionid` cookie) it
serves the empty shell Instagram serves to visitors — which is what makes
gallery-dl raise `Requested user could not be found`. With a `sessionid` cookie
it serves the hydrated page (`profile_id`, GraphQL tokens) and answers the two
GraphQL operations a posts/reels walk needs.

Endpoints
  GET  /                     profile page (generic user, tokens)
  GET  /<user>/              profile page for <user>
  POST /api/graphql          PolarisProfilePageContentQuery  → user info
  POST /graphql/query        *TabContentQuery_connection    → feed edges
  GET  /media/<file>         the actual media bytes
  GET  /__log                what the server saw (cookies per request)
"""
from __future__ import annotations

import json
import re
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8920
CERT = sys.argv[2] if len(sys.argv) > 2 else ""      # enables HTTPS when given
SCHEME = "https" if CERT else "http"
BASE = f"{SCHEME}://www.instagram.com:{PORT}"

USER = {
    "pk": "52140523308",
    "id": "52140523308",          # real Instagram returns both pk and id
    "username": "snb.style",
    "full_name": "SNB Style",
    "is_private": False,
    "edge_followed_by": {"count": 12345},
    "edge_follow": {"count": 321},
    "edge_owner_to_timeline_media": {"count": 3},
}

POSTS = [
    {
        "pk": "3512345678901234567",
        "code": "C1photo",
        "taken_at": 1_790_000_000,
        "like_count": 412,
        "caption": {"text": "first look \u2014 spring edit #style"},
        "user": {"pk": USER["pk"], "username": USER["username"], "full_name": USER["full_name"]},
        "image_versions2": {"candidates": [
            {"url": f"{BASE}/media/C1photo_1.jpg", "width": 1080, "height": 1350}]},
    },
    {
        "pk": "3512345678901234568",
        "code": "C2reel",
        "taken_at": 1_789_900_000,
        "like_count": 1204,
        "caption": {"text": "reel: behind the scenes #reels"},
        "user": {"pk": USER["pk"], "username": USER["username"], "full_name": USER["full_name"]},
        "image_versions2": {"candidates": [
            {"url": f"{BASE}/media/C2reel_1.jpg", "width": 1080, "height": 1920}]},
        "video_versions": [
            {"url": f"{BASE}/media/C2reel_1.mp4", "width": 720, "height": 1280},
            {"url": f"{BASE}/media/C2reel_1_merged.mp4", "width": 1080, "height": 1920},
        ],
    },
    {
        "pk": "3512345678901234569",
        "code": "C3carousel",
        "taken_at": 1_789_800_000,
        "like_count": 98,
        "caption": {"text": "carousel: 2 shots of the same set"},
        "user": {"pk": USER["pk"], "username": USER["username"], "full_name": USER["full_name"]},
        "carousel_media": [
            {"pk": "3512345678901234569", "code": "C3carousel",
             "image_versions2": {"candidates": [
                 {"url": f"{BASE}/media/C3carousel_1.jpg", "width": 1080, "height": 1080}]}},
            {"pk": "3512345678901234570", "code": "C3carousel",
             "image_versions2": {"candidates": [
                 {"url": f"{BASE}/media/C3carousel_2.jpg", "width": 1080, "height": 1080}]}},
        ],
    },
]

SEEN: list[dict] = []

_ALPHABET = ("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")


def _wanted_user(raw: str) -> str:
    """The username a POST body asks about ('' when it is a media lookup)."""
    for pat in (r'"username":"([^"]+)"', r'"username":\s*"([^"]+)"'):
        m = re.search(pat, raw or "")
        if m:
            return m.group(1)
    return ""


def id_from_shortcode(code: str) -> str:
    n = 0
    for ch in code:
        n = n * 64 + _ALPHABET.index(ch)
    return str(n)


def profile_html(user: str, logged_in: bool) -> str:
    if not logged_in:
        # what Instagram really serves a visitor: the app shell, no data
        return ("<!DOCTYPE html><html><head><title>Instagram</title></head><body>"
                "<div id=\"react-root\"></div>"
                "<script>window._sharedData = {\"entry_data\":{}}</script>"
                "</body></html>")
    return (
        "<!DOCTYPE html><html><head><title>" + user + " (@:)</title>"
        "<meta property=\"og:title\" content=\"" + user + "\">"
        # GraphQL tokens live in this script block on every real page
        "<script id=\"__eqmc\">{\"l\":\"MOCKLSDTOKEN\",\"f\":\"MOCKDTSGTOKEN\"}</script>"
        "</head><body><div id=\"react-root\"></div>"
        "<script>window.__additionalDataLoaded('/" + user + "/',"
        "{\"profile_id\":\"" + USER["pk"] + "\","
        "\"params\":{\"username\":\"" + user + "\"}})</script>"
        "</body></html>")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):        # keep stderr readable
        pass

    # -- helpers ---------------------------------------------------------
    def cookie_header(self) -> str:
        return self.headers.get("Cookie") or ""

    def logged_in(self) -> bool:
        return "sessionid=" in self.cookie_header()

    def seen(self, note: str) -> None:
        SEEN.append({"path": self.path.split("?")[0], "note": note,
                     "cookie": "sessionid" in self.cookie_header(),
                     "user-agent": (self.headers.get("User-Agent") or "")[:40]})

    def send(self, body: bytes, ctype: str, code: int = 200) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def json(self, obj, code=200) -> None:
        self.send(json.dumps(obj).encode(), "application/json", code)

    # -- routes ----------------------------------------------------------
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/__log":
            return self.json(SEEN)
        if path.startswith("/api/v1/media/"):
            self.seen("api:media")
            if not self.logged_in():
                return self.json({"message": "login_required", "status": "fail"}, 401)
            return self.media_info(path)
        if path.startswith("/media/"):
            # a real image/video payload, so the download manager has something
            # honest to write to disk
            name = path.rsplit("/", 1)[-1]
            self.seen("media")
            if name.endswith(".mp4"):
                return self.send(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 2048, "video/mp4")
            return self.send(b"\xff\xd8\xff\xe0" + b"\x00" * 1024, "image/jpeg")
        self.seen("page:logged_in" if self.logged_in() else "page:logged_out")
        user = path.strip("/").split("/")[0] or USER["username"]
        if self.logged_in() and user.lower() != USER["username"].lower():
            # a signed-in visitor gets Instagram's "page isn't available" — the
            # one answer that proves the account itself does not exist
            self.seen("page:unknown-user")
            return self.send(b"<!DOCTYPE html><html><body><h2>Sorry, this page "
                             b"isn't available.</h2></body></html>", "text/html", 404)
        html = profile_html(user, self.logged_in())
        self.send(html.encode(), "text/html; charset=utf-8")

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8", "ignore")
        path = urllib.parse.urlparse(self.path).path
        if not self.logged_in():
            self.seen("api:logged_out")
            return self.json({"message": "login_required", "status": "fail"}, 401)
        self.seen("api:" + path)

        # a logged-in client still gets "user not found" for a profile that does
        # not exist — that is the difference between a login wall and a typo
        want = _wanted_user(raw)
        if want and want.lower() != USER["username"].lower():
            self.seen("api:unknown-user")
            return self.json({"message": "Not Found", "status": "fail"}, 404)

        if path == "/api/graphql":
            return self.json({"data": {"user": USER}, "status": "ok"})
        if path == "/graphql/query":
            friendly = (self.headers.get("X-FB-Friendly-Name") or "").lower()
            field = self.headers.get("X-Root-Field-Name") or ""
            if "reels" in friendly:
                # reels edges carry {"media": post}; the file is fetched later
                # through /api/v1/media/<pk>/info/
                return self.json({"data": {"fetch__XDTUserDict": {
                    "edges": [{"node": {"media": POSTS[1]}}],
                    "page_info": {"has_next_page": False, "end_cursor": None}}}})
            if "tagged" in friendly:
                field = "xdt_api__v1__usertags__user_id__feed_connection"
            field = field or "xdt_api__v1__feed__user_timeline_graphql_connection"
            return self.json({"data": {field: {
                "edges": [{"node": n} for n in POSTS],
                "page_info": {"has_next_page": False, "end_cursor": None}}}})
        if path.startswith("/api/v1/media/"):
            return self.media_info(path)
        return self.json({"message": "not found"}, 404)

    def media_info(self, path: str):
        """`/api/v1/media/<id>/info/` — how gallery-dl resolves a reel to a file.

        The id in the path is the *decoded shortcode*, which is how Instagram's
        own API addresses media, so resolve it the same way.
        """
        want = path.strip("/").split("/")[3]
        post = next((p for p in POSTS
                     if p["pk"] == want or id_from_shortcode(p["code"]) == want), None)
        if not post:
            return self.json({"message": "Media not found", "status": "fail"}, 404)
        return self.json({"items": [post], "num_results": 1, "status": "ok"})


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    if CERT:
        import ssl
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(CERT, CERT.replace("cert.pem", "key.pem"))
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    print(f"mock instagram on {SCHEME}://127.0.0.1:{PORT}", flush=True)
    srv.serve_forever()
