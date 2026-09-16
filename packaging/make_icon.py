"""Generate the TSP mark: assets/icon.svg, icon.png, favicon.png, icon.ico.

Four lines of a page with the top one struck through. The running head goes,
the text stays.

    python packaging/make_icon.py

Needs Pillow for the raster formats. The SVG lands without it.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

INK = (218, 218, 218)  # #dadada, the lines
ACCENT = (139, 108, 239)  # #8b6cef, the pencil

GROUND = (30, 30, 30)  # #1e1e1e

# Lines on a 100-unit page: (y, width, struck)
LINES = [(20, 56, True), (40, 56, False), (56, 56, False), (72, 40, False)]
LINE_H = 9
STRIKE = (18, 32, 82, 14)  # x0, y0, x1, y1
STRIKE_W = 7


def to_hex(rgb: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % rgb


def write_svg(path: Path) -> None:
    parts = []
    for y, width, struck in LINES:
        x = (100 - width) / 2
        parts.append(
            f'  <rect x="{x:g}" y="{y}" width="{width}" height="{LINE_H}" '
            f'fill="{to_hex(INK)}"/>'
        )
    x0, y0, x1, y1 = STRIKE
    parts.append(
        f'  <line x1="{x0}" y1="{y0}" x2="{x1}" y2="{y1}" '
        f'stroke="{to_hex(ACCENT)}" stroke-width="{STRIKE_W}"/>'
    )
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100" role="img" aria-label="TSP">
  <rect width="100" height="100" fill="{to_hex(GROUND)}"/>
{chr(10).join(parts)}
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def write_raster() -> None:
    from PIL import Image, ImageDraw

    def render(size: int) -> "Image.Image":
        scale = 8
        big = size * scale
        image = Image.new("RGB", (big, big), GROUND)
        draw = ImageDraw.Draw(image)
        unit = big / 100

        for y, width, struck in LINES:
            x = (100 - width) / 2 * unit
            draw.rectangle(
                [x, y * unit, x + width * unit, (y + LINE_H) * unit],
                fill=INK,
            )
        x0, y0, x1, y1 = STRIKE
        draw.line(
            [x0 * unit, y0 * unit, x1 * unit, y1 * unit],
            fill=ACCENT,
            width=int(STRIKE_W * unit),
        )
        return image.resize((size, size), Image.LANCZOS)

    render(512).save(ASSETS / "icon.png")
    render(64).save(ASSETS / "favicon.png")
    render(256).save(
        ASSETS / "icon.ico",
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    write_svg(ASSETS / "icon.svg")
    try:
        write_raster()
    except ImportError:
        print("Pillow missing: wrote icon.svg only. pip install pillow")
        return
    print(f"wrote icon.svg, icon.png, favicon.png, icon.ico to {ASSETS}")


if __name__ == "__main__":
    main()
