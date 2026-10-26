"""All Video Downloader — application icon generator.

Produces the icon the Windows build embeds in the EXE and the Inno Setup
installer uses for its own chrome:

    build/icon.ico    multi-resolution Windows icon (16 → 256 px)
    build/icon.png    512 px master, handy for docs / store listings

The artwork is the same mark the front-end uses (``web/index.html`` favicon and
the sidebar brand): a rounded square in the app's violet→blue accent gradient
with a white download arrow. Generating it here keeps the .ico reproducible
instead of being an opaque binary blob:

    python tools/make_icon.py            # rewrite both files
    python tools/make_icon.py --preview  # also dump a contact sheet

Pillow is a build-time dependency only — the app itself never imports it.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFilter
except ImportError:  # pragma: no cover - build-time tool
    sys.exit("Pillow is required: pip install pillow")

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"

# app accent gradient (web/css/base.css: --accent, --accent-2)
VIOLET = (168, 85, 247)
BLUE = (79, 124, 255)

CANVAS = 1024                      # master render size, downsampled per frame
RADIUS = 224                       # ≈22% — Windows 11 icon corner feel
SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)


def _gradient(size: int) -> Image.Image:
    """Diagonal violet→blue gradient (Pillow has no gradient: 2×2 + resize)."""
    # 115deg in CSS ≈ top-left → bottom-right-ish; a 2×2 seed resized bicubic
    # gives exactly the smooth diagonal ramp we want with zero per-pixel work.
    seed = Image.new("RGB", (2, 2))
    seed.putpixel((0, 0), VIOLET)
    seed.putpixel((1, 0), (124, 105, 251))
    seed.putpixel((0, 1), (124, 105, 251))
    seed.putpixel((1, 1), BLUE)
    return seed.resize((size, size), Image.BICUBIC)


def _rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1),
                                           radius=radius, fill=255)
    return mask


def _glyph(size: int, *, compact: bool = False) -> Image.Image:
    """White download arrow (stem + head + tray) on a transparent canvas.

    ``compact`` is the 16–24 px variant: the tray collapses into a single bar
    and every stroke thickens, because at that size an open U turns into mush.
    """
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    u = size / 1024.0                      # design grid is 1024 px
    white = (255, 255, 255, 255)

    def px(*vals: float) -> tuple[float, ...]:
        return tuple(v * u for v in vals)

    if compact:
        d.rounded_rectangle(px(452, 150, 572, 400), radius=60 * u, fill=white)
        d.polygon([px(288, 372), px(512, 624), px(736, 372)], fill=white)
        d.rounded_rectangle(px(262, 690, 762, 830), radius=62 * u, fill=white)
        return layer

    # stem
    d.rounded_rectangle(px(460, 168, 564, 438), radius=52 * u, fill=white)
    # head (overlaps the stem, so the two shapes never show a seam)
    d.polygon([px(298, 396), px(512, 636), px(726, 396)], fill=white)
    # tray: a U opening upwards. Drawn as "thick rounded bar minus its inside"
    # so the arms and the base meet in a clean fillet instead of three strokes.
    tray = Image.new("L", (size, size), 0)
    td = ImageDraw.Draw(tray)
    td.rounded_rectangle(px(310, 690, 714, 826), radius=52 * u, fill=255)
    td.rounded_rectangle(px(372, 690, 652, 758), radius=28 * u, fill=0)
    layer.paste(Image.new("RGBA", (size, size), white), (0, 0), tray)
    return layer


def render(size: int = CANVAS, *, compact: bool = False) -> Image.Image:
    """The full icon at `size` px (RGBA, transparent outside the rounded square)."""
    base = _gradient(size)
    tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    tile.paste(base, (0, 0))

    # soft top-left sheen, then a hairline inner edge — gives the flat gradient
    # a bit of depth without looking like a different product
    sheen = Image.new("L", (size, size), 0)
    ImageDraw.Draw(sheen).ellipse((int(-size * 0.35), int(-size * 0.75),
                                  int(size * 1.05), int(size * 0.55)), fill=26)
    sheen = sheen.filter(ImageFilter.GaussianBlur(size * 0.06))
    tile = Image.composite(Image.new("RGBA", (size, size), (255, 255, 255, 255)),
                           tile, sheen.point(lambda v: v))
    # (composite() above blends by mask; re-apply the original gradient underneath)
    plate = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    plate.paste(_gradient(size), (0, 0))
    plate.alpha_composite(tile)

    plate.alpha_composite(_glyph(size, compact=compact))
    plate.putalpha(_rounded_mask(size, int(RADIUS * size / 1024)))
    return plate


def build() -> tuple[Path, Path]:
    BUILD.mkdir(parents=True, exist_ok=True)
    master = render(CANVAS)
    ico_path, png_path = BUILD / "icon.ico", BUILD / "icon.png"

    frames = []
    for s in SIZES:
        if s < 32:
            # rendered separately: a bare downsample of the detailed glyph
            # smears at 16/20/24 px, the compact drawing stays legible
            frames.append(render(s, compact=True))
        else:
            frames.append(master.resize((s, s), Image.LANCZOS))
    frames[-1].save(ico_path, format="ICO",
                    sizes=[(s, s) for s in SIZES], append_images=frames[:-1])
    master.resize((512, 512), Image.LANCZOS).save(png_path, format="PNG")
    return ico_path, png_path


def preview() -> Path:
    """Contact sheet at real 16/32/48 px plus a 256 px hero — a sanity check."""
    sheet = Image.new("RGBA", (760, 300), (24, 24, 32, 255))
    hero = render(1024).resize((256, 256), Image.LANCZOS)
    sheet.alpha_composite(hero, (22, 22))
    x = 310
    for s in (128, 64, 48, 32, 24, 16):
        im = (render(s, compact=True) if s < 32
              else render(1024).resize((s, s), Image.LANCZOS))
        sheet.alpha_composite(im, (x, 22 + (128 - s) // 2))
        x += s + 18
    out = BUILD / "icon-preview.png"
    sheet.save(out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--preview", action="store_true", help="also write build/icon-preview.png")
    args = ap.parse_args()
    ico, png = build()
    print(f"✓ {ico.relative_to(ROOT)}  ({ico.stat().st_size / 1024:.1f} kB, "
          f"{len(SIZES)} sizes)")
    print(f"✓ {png.relative_to(ROOT)}  ({png.stat().st_size / 1024:.1f} kB)")
    if args.preview:
        print(f"✓ {preview().relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
