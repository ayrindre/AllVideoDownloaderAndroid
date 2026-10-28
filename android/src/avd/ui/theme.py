"""All Video Downloader (Android) — mobile visual system.

A Material-3-flavoured dark/light theme built on KivyMD 1.2 primitives:
rounded cards, a violet→blue brand gradient, four accent choices and the
bundled Vazirmatn font (graceful fallback to Roboto when absent).
"""
from __future__ import annotations

from pathlib import Path

from kivy.core.text import LabelBase
from kivy.graphics import RoundedRectangle
from kivy.metrics import dp
from kivy.utils import get_color_from_hex

ASSETS = Path(__file__).resolve().parent.parent.parent / "assets"
FONTS_DIR = ASSETS / "fonts"

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
ACCENTS = {
    "violet": {"hex": "#8B5CF6", "dark": "#7C3AED", "soft": "#A78BFA",
               "palette": "DeepPurple"},
    "azure":  {"hex": "#38BDF8", "dark": "#0EA5E9", "soft": "#7DD3FC",
               "palette": "LightBlue"},
    "magenta": {"hex": "#EC4899", "dark": "#DB2777", "soft": "#F472B6",
                "palette": "Pink"},
    "mint":   {"hex": "#34D399", "dark": "#10B981", "soft": "#6EE7B7",
               "palette": "Teal"},
}

DARK = {
    "bg": "#0E1120",
    "surface": "#171B2E",
    "surface_2": "#1F2440",
    "text": "#F1F3FF",
    "text_2": "#B7BDD9",
    "text_3": "#7C84A3",
    "success": "#34D399",
    "danger": "#FB7185",
    "warning": "#FBBF24",
    "info": "#38BDF8",
    "outline": "#2A3050",
}

LIGHT = {
    "bg": "#F3F4FB",
    "surface": "#FFFFFF",
    "surface_2": "#ECEEFA",
    "text": "#15182B",
    "text_2": "#454B66",
    "text_3": "#7A8099",
    "success": "#059669",
    "danger": "#E11D48",
    "warning": "#D97706",
    "info": "#0284C7",
    "outline": "#D8DBEC",
}

GRADIENT_TOP = "#8B5CF6"
GRADIENT_BOTTOM = "#2563EB"

FONT_NAME = "Vazirmatn"
_font_ready = False


def register_fonts() -> bool:
    """Register the bundled Vazirmatn family. Returns False on fallback."""
    global _font_ready
    if _font_ready:
        return True
    regular = FONTS_DIR / "Vazirmatn-Regular.ttf"
    bold = FONTS_DIR / "Vazirmatn-Bold.ttf"
    if not regular.exists():
        return False
    LabelBase.register(
        FONT_NAME,
        fn_regular=str(regular),
        fn_bold=str(bold if bold.exists() else regular),
        fn_italic=str(regular),
        fn_bolditalic=str(bold if bold.exists() else regular),
    )
    # KivyMD font-style table → Vazirmatn, so every styled label renders Persian
    try:
        from kivymd.app import MDApp

        styles = MDApp.get_running_app().theme_cls.font_styles
        for name, spec in list(styles.items()):
            # spec = [font_name, size, bold, letter_spacing]
            styles[name] = [FONT_NAME, spec[1], spec[2], spec[3]]
    except Exception:  # noqa: BLE001 — app not running yet; applied again later
        pass
    _font_ready = True
    return True


def font_name() -> str:
    return FONT_NAME if _font_ready else "Roboto"


def palette(style: str) -> dict:
    return DARK if style == "Dark" else LIGHT


def rgba(hex_color: str, alpha: float = 1.0):
    c = get_color_from_hex(hex_color)
    if alpha != 1.0:
        c = [c[0], c[1], c[2], alpha]
    return c


_gradient_texture = None


def gradient_texture():
    """Cached vertical violet→blue texture for brand headers / hero cards."""
    global _gradient_texture
    if _gradient_texture is not None:
        return _gradient_texture
    from kivy.graphics.texture import Texture

    w, h = 16, 256
    top = get_color_from_hex(GRADIENT_TOP)
    bottom = get_color_from_hex(GRADIENT_BOTTOM)
    # blit_buffer fills bottom→top (GL origin), so emit rows bottom-first
    rows = bytearray()
    for y in range(h - 1, -1, -1):
        t = y / (h - 1)
        r = int((top[0] * (1 - t) + bottom[0] * t) * 255)
        g = int((top[1] * (1 - t) + bottom[1] * t) * 255)
        b = int((top[2] * (1 - t) + bottom[2] * t) * 255)
        rows += bytes([r, g, b]) * w
    tex = Texture.create(size=(w, h), colorfmt="rgb", bufferfmt="ubyte")
    tex.blit_buffer(bytes(rows), colorfmt="rgb", bufferfmt="ubyte")
    tex.wrap = "repeat"
    _gradient_texture = tex
    return _gradient_texture


def is_mock_gl() -> bool:
    """Headless test environment (cgl_mock has no real texture storage)."""
    try:
        from kivy.graphics.cgl import cgl_get_backend_name

        return cgl_get_backend_name() == "mock"
    except Exception:  # noqa: BLE001
        return False


def paint_gradient(widget, radius: float = 0.0) -> None:
    """Fill a widget's canvas.before with the violet→blue brand gradient.

    Real GL gets a single textured quad; the headless mock backend (which
    cannot allocate textures) gets a banded fallback drawn from plain colors.
    """
    from kivy.graphics import Color, Rectangle

    if is_mock_gl():
        top = get_color_from_hex(GRADIENT_TOP)
        bottom = get_color_from_hex(GRADIENT_BOTTOM)
        bands = 36
        band_h = max(1.0, widget.height / bands)
        for i in range(bands):
            t = i / max(1, bands - 1)
            Color(*[top[j] * (1 - t) + bottom[j] * t for j in range(3)], 1)
            Rectangle(pos=[widget.x, widget.y + i * band_h],
                      size=[widget.width, band_h + 1])
        return
    tex = gradient_texture()
    Color(1, 1, 1, 1)
    if radius:
        RoundedRectangle(pos=widget.pos, size=widget.size, radius=[
            dp(radius), dp(radius), dp(radius), dp(radius)], texture=tex)
    else:
        Rectangle(pos=widget.pos, size=widget.size, texture=tex)


def apply_theme(app, style: str, accent: str) -> dict:
    """Push the chosen style/accent into KivyMD's theme_cls and return the
    active palette dict for direct widget coloring.

    KivyMD 1.2's ``primary_color`` is a read-only alias derived from the
    named palette, so accents map onto the closest Material palette; every
    custom widget also receives the exact hex from :data:`ACCENTS`.
    """
    pal = palette(style)
    app.theme_cls.theme_style = style
    app.theme_cls.primary_palette = ACCENTS[accent]["palette"]
    app.theme_cls.primary_hue = "500"
    app.theme_cls.accent_palette = "Blue"
    app.theme_cls.accent_hue = "400"
    # In KivyMD 1.2 the bg_*/text_* aliases are read-only derivatives of
    # theme_style; explicit widget colors come from our own palette dict.
    register_fonts()
    return pal
