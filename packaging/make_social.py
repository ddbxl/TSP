"""Generate the GitHub social preview card: assets/social-preview.png.

    python packaging/make_social.py

GitHub renders social previews at 1280x640 and caps the file at 1 MB. Needs
Pillow.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

W, H = 1280, 640
SCALE = 2  # draw large, downsample once, for clean edges

INK = (15, 23, 42)
TEAL = (94, 214, 200)
LIGHT = (241, 245, 249)
MUTED = (148, 163, 184)
DIM = (100, 116, 139)

DISPLAY = "/usr/share/texmf/fonts/opentype/public/tex-gyre/texgyreheros-bold.otf"
BODY = "/usr/share/texmf/fonts/opentype/public/tex-gyre/texgyreheros-regular.otf"
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
MONO_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"

# The icon's bar geometry, as fractions of its 100-unit canvas.
BARS = [(70, 24, 9), (54, 39, 9), (38, 54, 9), (22, 69, 9)]


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size * SCALE)


def tracked(draw, xy, text, fnt, fill, tracking: float = 0.0):
    """Draw text with letter spacing, returning the width consumed."""
    x, y = xy
    start = x
    for char in text:
        draw.text((x, y), char, font=fnt, fill=fill)
        x += draw.textlength(char, font=fnt) + tracking * SCALE
    return x - start


def build() -> Image.Image:
    image = Image.new("RGB", (W * SCALE, H * SCALE), INK)
    draw = ImageDraw.Draw(image)

    # -- the mark, blown up on the right ---------------------------------
    box = 300 * SCALE          # size of the icon's notional canvas
    bx = (W - 100 - 300) * SCALE
    by = (H - 300) // 2 * SCALE
    unit = box / 100

    for index, (bar_w, bar_y, bar_h) in enumerate(BARS):
        colour = TEAL if index == 0 else LIGHT
        x0 = bx + (100 - bar_w) / 2 * unit
        y0 = by + bar_y * unit
        draw.rounded_rectangle(
            [x0, y0, x0 + bar_w * unit, y0 + bar_h * unit],
            radius=bar_h / 2 * unit,
            fill=colour,
        )

    # -- type, left --------------------------------------------------------
    x = 84 * SCALE

    label = font(MONO_BOLD, 19)
    tracked(draw, (x, 108 * SCALE), "TSP", label, TEAL, tracking=5)

    title = font(DISPLAY, 82)
    draw.text((x - 3 * SCALE, 152 * SCALE), "Token Saving", font=title, fill=LIGHT)
    draw.text((x - 3 * SCALE, 240 * SCALE), "Protocol", font=title, fill=LIGHT)

    body = font(BODY, 28)
    draw.text(
        (x, 356 * SCALE),
        "PDFs into token-efficient text for LLMs.",
        font=body,
        fill=MUTED,
    )
    draw.text(
        (x, 392 * SCALE),
        "Charts come back as images. Runs offline.",
        font=body,
        fill=MUTED,
    )

    # -- rule and facts ----------------------------------------------------
    draw.rectangle(
        [x, 462 * SCALE, (x + 430 * SCALE), 462 * SCALE + 1 * SCALE],
        fill=(45, 56, 75),
    )

    facts = font(MONO, 18)
    tracked(
        draw,
        (x, 486 * SCALE),
        "DESKTOP  \u00b7  CLI  \u00b7  BROWSER  \u00b7  GPLv3",
        facts,
        DIM,
        tracking=0.6,
    )
    tracked(
        draw,
        (x, 518 * SCALE),
        "ddbxl.github.io/TSP",
        font(MONO_BOLD, 18),
        TEAL,
        tracking=0.6,
    )

    return image.resize((W, H), Image.LANCZOS)


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    out = ASSETS / "social-preview.png"
    build().save(out, optimize=True)
    print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KB, limit 1024 KB)")


if __name__ == "__main__":
    main()
