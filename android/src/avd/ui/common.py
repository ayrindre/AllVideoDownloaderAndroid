"""All Video Downloader (Android) — shared mobile widgets & helpers."""
from __future__ import annotations

import re
from typing import Callable

from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp
from kivy.properties import ListProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.image import AsyncImage
from kivy.uix.label import Label
from kivy.uix.widget import Widget
from kivymd.uix.card import MDCard
from kivymd.uix.label import MDLabel
from kivymd.uix.snackbar import MDSnackbar

from ..i18n import fa
from . import theme


def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", str(text or "")).replace("&amp;", "&").strip()


def fa_label(text: str = "", *, bold: bool = False, color: str | None = None,
             size: float = 14, halign: str = "right", opacity: float = 1.0,
             **kw) -> MDLabel:
    lbl = MDLabel(
        text=fa(text),
        halign=halign,
        valign="center",
        font_style="Body1" if not bold else "Subtitle1",
        font_name=theme.font_name(),
        markup=False,
        adaptive_height=True,
        **kw,
    )
    lbl.font_size = dp(size)
    if color:
        lbl.text_color = theme.rgba(color)
    lbl.opacity = opacity
    return lbl


def latin_label(text: str = "", *, color: str | None = None, size: float = 12,
                halign: str = "left", **kw) -> MDLabel:
    """Label for LTR technical strings (URLs, paths, format ids)."""
    lbl = MDLabel(text=str(text), halign=halign, valign="center",
                  font_name=theme.font_name(), adaptive_height=True, **kw)
    lbl.font_size = dp(size)
    if color:
        lbl.text_color = theme.rgba(color)
    return lbl


class RoundedButton(ButtonBehavior, Label):
    """Mobile pill button — gradient/flat variants, full touch control."""

    bg = ListProperty([0, 0, 0, 0])
    bg_pressed = ListProperty([0, 0, 0, 0])
    radius_val = dp(16)

    def __init__(self, text: str = "", on_press_cb: Callable | None = None,
                 bg_color: str = "", text_color: str = "#FFFFFF", bold: bool = True,
                 radius: float = 16, font_size: float = 15, icon: str = "", **kw):
        super().__init__(**kw)
        self.text = fa(text)
        self.font_name = theme.font_name()
        self.font_size = dp(font_size)
        self.bold = bold
        self.color = theme.rgba(text_color)
        self.radius_val = dp(radius)
        self.adaptive_height = False
        self.size_hint_y = None
        self.height = dp(52)
        base = theme.rgba(bg_color or "#8B5CF6")
        self.bg = base
        self._base = list(base)
        self.bg_pressed = [min(1, c + 0.12) if i < 3 else c for i, c in enumerate(base)]
        self._cb = on_press_cb
        self.bind(pos=self._redraw, size=self._redraw, bg=self._redraw)
        self._redraw()

    def _redraw(self, *args):
        self.canvas.before.clear()
        with self.canvas.before:
            Color(*self.bg)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[
                self.radius_val, self.radius_val, self.radius_val, self.radius_val])

    def on_press(self):
        self.bg = self.bg_pressed

    def on_release(self):
        self.bg = self._base
        if self._cb:
            self._cb(self)

    def set_text(self, text: str):
        self.text = fa(text)

    def set_bg(self, hex_color: str):
        base = theme.rgba(hex_color)
        self._base = list(base)
        self.bg = base
        self.bg_pressed = [min(1, c + 0.12) if i < 3 else c for i, c in enumerate(base)]


class Chip(ButtonBehavior, BoxLayout):
    """Selectable quality/option chip."""

    def __init__(self, label: str, selected: bool = False, on_select: Callable | None = None,
                 accent: str = "", icon: str = "", small: bool = False, **kw):
        super().__init__(**kw)
        self.orientation = "horizontal"
        self.spacing = dp(6)
        self.size_hint_y = None
        self.height = dp(38 if small else 44)
        self.size_hint_x = None
        self.padding = [dp(14), 0, dp(14), 0]
        self._selected = selected
        self._on_select = on_select
        self._accent = accent
        self._label = MDLabel(text=fa(label), halign="center", valign="middle",
                              font_name=theme.font_name(), adaptive_height=False)
        self._label.font_size = dp(13 if small else 14)
        self.add_widget(self._label)
        self.bind(pos=self._redraw, size=self._redraw)
        self._redraw()
        # width hugs content (Persian shaping changes glyph count)
        self._label.bind(texture_size=lambda *a: setattr(
            self, "width", max(dp(72), self._label.texture_size[0] + dp(28))))

    @property
    def selected(self) -> bool:
        return self._selected

    def set_selected(self, value: bool):
        self._selected = value
        self._redraw()

    def _redraw(self, *args):
        self.canvas.before.clear()
        pal = getattr(self, "_pal", None)
        with self.canvas.before:
            if self._selected:
                Color(*theme.rgba(self._accent or "#8B5CF6"))
            else:
                Color(*theme.rgba(pal["surface_2"] if pal else "#1F2440"))
            RoundedRectangle(pos=self.pos, size=self.size, radius=[
                dp(22), dp(22), dp(22), dp(22)])
        if self._label:
            self._label.text_color = theme.rgba("#FFFFFF" if self._selected else (pal["text_2"] if pal else "#B7BDD9"))

    def attach_palette(self, pal: dict):
        self._pal = pal
        self._redraw()

    def on_release(self):
        if self._on_select:
            self._on_select(self)


class IconChip(ButtonBehavior, BoxLayout):
    """Small square icon action (copy/open/retry…)."""

    def __init__(self, icon: str, on_press_cb: Callable, bg: str = "", **kw):
        super().__init__(**kw)
        self.size_hint = (None, None)
        self.size = [dp(42), dp(42)]
        self._bg = bg
        self._cb = on_press_cb
        from kivymd.uix.label import MDIcon

        self._icon = MDIcon(icon=icon, halign="center", valign="center",
                            font_size=dp(20))
        self._icon.icon = icon
        self.add_widget(self._icon)
        self.bind(pos=self._redraw, size=self._redraw)
        self._redraw()

    def _redraw(self, *args):
        self.canvas.before.clear()
        with self.canvas.before:
            Color(*theme.rgba(self._bg or "#1F2440"))
            RoundedRectangle(pos=self.pos, size=self.size, radius=[
                dp(12), dp(12), dp(12), dp(12)])

    def on_release(self):
        if self._cb:
            self._cb(self)


class Card(MDCard):
    """Rounded surface card used across every screen."""

    def __init__(self, pal: dict, padding: float = 18, **kw):
        super().__init__(**kw)
        self.orientation = "vertical"
        self.radius = [dp(22)]
        self.padding = dp(padding)
        self.spacing = dp(12)
        self.size_hint_y = None
        self.md_bg_color = theme.rgba(pal["surface"])
        self.elevation = 0
        self.line_width = 1
        self.line_color = theme.rgba(pal["outline"])


class SectionLabel(MDLabel):
    def __init__(self, text: str, pal: dict, **kw):
        super().__init__(**kw)
        self.text = fa(text)
        self.font_name = theme.font_name()
        self.font_size = dp(13)
        self.bold = True
        self.halign = "right"
        self.adaptive_height = True
        self.text_color = theme.rgba(pal["text_3"])


class Thumbnail(BoxLayout):
    """16:9 thumbnail with a graceful gradient fallback."""

    def __init__(self, url: str = "", pal: dict | None = None, **kw):
        super().__init__(**kw)
        self.size_hint_y = None
        self.height = dp(190)
        self._pal = pal
        self._url = url
        self.bind(pos=self._redraw, size=self._redraw)
        if url:
            img = AsyncImage(source=url, allow_stretch=True, keep_ratio=False)
            img.bind(error=lambda *a: self._clear_img(img))
            self.add_widget(img)

    def _clear_img(self, img):
        if img in self.children:
            self.remove_widget(img)

    def _redraw(self, *args):
        self.canvas.before.clear()
        theme.paint_gradient(self, radius=18)


def spacer(h: float = 10) -> Widget:
    w = Widget()
    w.size_hint_y = None
    w.height = dp(h)
    return w


_snack: MDSnackbar | None = None


def snackbar(text: str, pal: dict, color: str = "") -> None:
    global _snack
    if _snack is not None:
        try:
            _snack.dismiss()
        except Exception:  # noqa: BLE001
            pass
    bg = color or pal["surface_2"]
    _snack = MDSnackbar(
        MDLabel(text=fa(text), font_name=theme.font_name(), font_size=dp(13),
                text_color=theme.rgba(pal["text"]), adaptive_height=True),
        md_bg_color=theme.rgba(bg),
        duration=2.4,
        pos_hint={"center_x": 0.5},
        size_hint_x=0.92,
        radius=[dp(16), dp(16), dp(16), dp(16)],
        snackbar_animation_dir=["y"],
    )
    _snack.open()
