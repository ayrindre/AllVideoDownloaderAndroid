#!/usr/bin/env python3
"""Generate the Android icon and presplash for All Video Downloader.

Drawn with Pillow (a build-time-only dependency), so the brand art is
reproducible rather than an opaque binary blob — the mobile twin of the
desktop project's tools/make_icon.py.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parents[1] / "src"
VIOLET = (139, 92, 246)
BLUE = (37, 99, 235)
WHITE = (255, 255, 255)


def vertical_gradient(size: int, top=VIOLET, bottom=BLUE) -> Image.Image:
    img = Image.new("RGB", (size, size), top)
    px = img.load()
    for y in range(size):
        t = y / (size - 1)
        r = int(top[0] * (1 - t) + bottom[0] * t)
        g = int(top[1] * (1 - t) + bottom[1] * t)
        b = int(top[2] * (1 - t) + bottom[2] * t)
        for x in range(size):
            px[x, y] = (r, g, b)
    return img


def rounded_mask(size: int, radius_ratio: float) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle([0, 0, size - 1, size - 1],
                        radius=int(size * radius_ratio), fill=255)
    return mask


def draw_download_mark(canvas: Image.Image, cx: int, cy: int, scale: float,
                       color=WHITE) -> None:
    """A rounded downward arrow (shaft + triangle head) over a tray."""
    d = ImageDraw.Draw(canvas)
    s = scale
    # arrow shaft
    shaft_w = int(28 * s)
    shaft_top = cy - int(122 * s)
    shaft_bottom = cy + int(6 * s)
    d.rounded_rectangle(
        [cx - shaft_w // 2, shaft_top, cx + shaft_w // 2, shaft_bottom],
        radius=shaft_w // 2, fill=color)
    # arrow head: downward triangle, its tip tucked under the shaft
    half = int(74 * s)
    tip = cy + int(78 * s)
    head_top = cy - int(2 * s)
    d.polygon([(cx - half, head_top), (cx + half, head_top), (cx, tip)], fill=color)
    # round the triangle's two top corners by re-drawing small pills
    d.ellipse([cx - half - shaft_w // 3, head_top - shaft_w // 3,
               cx - half + shaft_w, head_top + shaft_w], fill=color)
    d.ellipse([cx + half - shaft_w, head_top - shaft_w // 3,
               cx + half + shaft_w // 3, head_top + shaft_w], fill=color)
    # tray
    tray_h = int(26 * s)
    tray_w = int(200 * s)
    d.rounded_rectangle(
        [cx - tray_w // 2, cy + int(118 * s),
         cx + tray_w // 2, cy + int(118 * s) + tray_h],
        radius=tray_h // 2, fill=color)
    # soft shadow under the glyph
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.ellipse([cx - int(128 * s), cy + int(152 * s),
                cx + int(128 * s), cy + int(178 * s)],
               fill=(20, 10, 60, 90))
    shadow = shadow.filter(ImageFilter.GaussianBlur(int(10 * s)))
    canvas.alpha_composite(shadow)


def make_icon(size: int = 1024) -> Image.Image:
    base = vertical_gradient(size).convert("RGBA")
    # subtle radial glow top-left
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([-size // 3, -size // 3, size // 2, size // 2],
               fill=(255, 255, 255, 38))
    glow = glow.filter(ImageFilter.GaussianBlur(size // 12))
    base.alpha_composite(glow)
    draw_download_mark(base, size // 2, size // 2, size / 1024 * 2.2)
    # mask to Android's squircle-ish rounded square
    mask = rounded_mask(size, 0.22)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(base, (0, 0), mask)
    return out


def make_presplash(size: int = 1024) -> Image.Image:
    bg = vertical_gradient(size).convert("RGBA")
    # decorative soft orbs
    for (ox, oy, r, a) in ((180, 220, 260, 40), (880, 820, 320, 34)):
        orb = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(orb)
        d.ellipse([ox - r, oy - r, ox + r, oy + r], fill=(255, 255, 255, a))
        bg.alpha_composite(orb.filter(ImageFilter.GaussianBlur(90)))
    mark = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw_download_mark(mark, size // 2, int(size * 0.44), size / 1024 * 2.4)
    bg.alpha_composite(mark)
    return bg


def main() -> None:
    icon = make_icon(1024)
    icon.save(OUT / "icon.png")
    icon.resize((512, 512), Image.LANCZOS).save(OUT / "icon-512.png")
    make_presplash(1024).save(OUT / "presplash.png")
    print(f"brand assets written to {OUT}")


if __name__ == "__main__":
    main()
