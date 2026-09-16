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

INK = (30, 30, 30)  # #1e1e1e
TEAL = (139, 108, 239)  # #8b6cef
LIGHT = (218, 218, 218)  # #dadada
MUTED = (154, 154, 154)
DIM = (144, 144, 144)

WOFF2 = ROOT / "web" / "newsreader.woff2"

# The mark, as fractions of its 100-unit canvas: (y, width, struck).
LINES = [(20, 56, True), (40, 56, False), (56, 56, False), (72, 40, False)]
LINE_H = 9
STRIKE = (18, 32, 82, 14)


def unpack(woff2: Path) -> Path:
    """Pillow reads TrueType, the site ships woff2. One font file either way."""
    import tempfile

    from fontTools.ttLib import TTFont

    out = Path(tempfile.gettempdir()) / "newsreader-card.ttf"
    if not out.exists():
        TTFont(str(woff2), fontNumber=0).save(out)
    return out


def font(size: int, weight: int = 400, optical: int = 40) -> ImageFont.FreeTypeFont:
    face = ImageFont.truetype(str(unpack(WOFF2)), size * SCALE)
    try:
        face.set_variation_by_axes([weight, optical])
    except Exception:
        pass
    return face


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

    for bar_y, bar_w, struck in LINES:
        x0 = bx + (100 - bar_w) / 2 * unit
        y0 = by + bar_y * unit
        draw.rectangle(
            [x0, y0, x0 + bar_w * unit, y0 + LINE_H * unit],
            fill=LIGHT,
        )
    sx0, sy0, sx1, sy1 = STRIKE
    draw.line(
        [bx + sx0 * unit, by + sy0 * unit, bx + sx1 * unit, by + sy1 * unit],
        fill=(139, 108, 239),
        width=int(7 * unit),
    )

    # -- type, left --------------------------------------------------------
    x = 84 * SCALE

    title = font(82, weight=400, optical=72)
    draw.text((x - 3 * SCALE, 138 * SCALE), "Token Saving", font=title, fill=LIGHT)
    draw.text((x - 3 * SCALE, 226 * SCALE), "Protocol", font=title, fill=LIGHT)

    body = font(28, weight=400, optical=18)
    draw.text(
        (x, 352 * SCALE),
        "Documents into token-efficient markdown for LLMs.",
        font=body,
        fill=MUTED,
    )
    draw.text(
        (x, 388 * SCALE),
        "Read in your browser. Nothing is uploaded.",
        font=body,
        fill=MUTED,
    )

    # -- rule and facts ----------------------------------------------------
    draw.rectangle(
        [x, 448 * SCALE, (x + 330 * SCALE), 448 * SCALE + 1 * SCALE],
        fill=(45, 56, 75),
    )

    draw.text(
        (x, 484 * SCALE),
        "ddbxl.github.io/TSP",
        font=font(21, weight=500, optical=14),
        fill=TEAL,
    )

    return image.resize((W, H), Image.LANCZOS)


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    out = ASSETS / "social-preview.png"
    build().save(out, optimize=True)
    print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KB, limit 1024 KB)")


if __name__ == "__main__":
    main()
