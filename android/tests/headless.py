"""Headless Kivy/KivyMD fixture for sandboxed UI tests.

The CI runner builds the real APK with a real GL context; locally there is no
libGL in this container, so we install a mock GL backend *and* a dummy Window
singleton before anything imports ``kivymd`` (its theming module touches the
window at import time). Widget construction, layout properties and canvas
instruction creation all work without a real window; only actual rendering is
mocked away.
"""
from __future__ import annotations

import os
import sys
import types

os.environ.setdefault("KIVY_NO_ARGS", "1")
os.environ.setdefault("KIVY_GL_BACKEND", "mock")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from kivy.event import EventDispatcher  # noqa: E402
from kivy.properties import ListProperty  # noqa: E402


class DummyWindow(EventDispatcher):
    size = ListProperty([360, 780])
    clearcolor = ListProperty([0.05, 0.07, 0.12, 1])

    def __init__(self, **kw):
        super().__init__()
        self.dpi = 320
        self.density = 2.0
        self.width, self.height = self.size
        self.children = []
        self.keyboard = None
        self._dummy_bindings: dict = {}

    def bind(self, **kw):
        self._dummy_bindings.update(kw)

    def unbind(self, **kw):
        for k in kw:
            self._dummy_bindings.pop(k, None)

    def fbind(self, *a, **kw):
        return 0

    def funbind(self, *a, **kw):
        pass

    def register_event_type(self, *a):
        pass

    def add_widget(self, *a):
        pass

    def remove_widget(self, *a):
        pass

    def on_draw(self):
        pass

    def flip(self):
        pass

    def release(self):
        pass

    def request_keyboard(self, *a, **k):
        return None

    def get_root_window(self):
        return self

    def to_widget(self, x, y, **k):
        return x, y

    def to_window(self, x, y, **k):
        return x, y

    def screenshot(self, *a, **k):
        return None

    def create_window(self, *a, **k):
        pass

    def close(self):
        pass


def install() -> DummyWindow:
    fake_window = DummyWindow()
    fake_module = types.ModuleType("kivy.core.window")
    # behave like a package so `kivy.core.window.window_sdl2` resolves
    fake_module.__path__ = []  # type: ignore[attr-defined]
    fake_module.Window = fake_window
    fake_module.WindowBase = DummyWindow
    sys.modules["kivy.core.window"] = fake_module

    # KivyMD 1.2 imports the SDL2 window class directly in a couple of places
    sdl2_module = types.ModuleType("kivy.core.window.window_sdl2")
    sdl2_module.WindowSDL = DummyWindow
    sys.modules["kivy.core.window.window_sdl2"] = sdl2_module

    from kivy.base import EventLoop

    EventLoop.window = fake_window
    EventLoop.ensure_window = lambda *a, **k: None  # idempotent safety net
    return fake_window
