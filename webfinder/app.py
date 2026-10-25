"""WebFinder — FastAPI application factory.

Serves the REST + WebSocket API and the static frontend from one port, so
the same server works headless (browser dev), inside pywebview (Windows) or
behind Eel (optional). Hardware acceleration comes from the webview layer:
WebView2/Chromium on Windows.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import router
from .config import APP_NAME, settings
from .core.downloader import manager

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


class WsHub:
    """Fan-out of manager events to all live WebSocket clients (thread-safe)."""

    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()
        self.loop: asyncio.AbstractEventLoop | None = None

    def broadcast(self, event: dict) -> None:
        if not self.clients or not self.loop:
            return
        payload = json.dumps(event, default=str)
        async def _send() -> None:
            for ws in list(self.clients):
                try:
                    await ws.send_text(payload)
                except Exception:  # noqa: BLE001
                    self.clients.discard(ws)
        try:
            self.loop.call_soon_threadsafe(lambda: self.loop.create_task(_send()))
        except RuntimeError:
            pass

    async def accept(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.add(ws)
        try:
            await ws.send_text(json.dumps(
                {"type": "bootstrap", "payload": {"jobs": manager.list_jobs()}}, default=str))
            while True:  # keep-alive pings
                msg = await ws.receive_text()
                if msg == "ping":
                    await ws.send_text('{"type":"pong"}')
        except WebSocketDisconnect:
            pass
        finally:
            self.clients.discard(ws)


def create_app() -> FastAPI:
    app = FastAPI(title=APP_NAME, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
    )
    app.include_router(router)

    hub = WsHub()

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await hub.accept(ws)

    @app.on_event("startup")
    async def _startup():
        hub.loop = asyncio.get_event_loop()
        settings.apply_env_overrides()
        manager.attach(hub.broadcast)

    # Static frontend — index.html gets no-cache so dev iteration is instant.
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/")
    async def index():
        return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-store"})

    return app


app = create_app()
