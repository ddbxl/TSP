"""Generate the TSP icon: assets/icon.svg, icon.png, favicon.png, icon.ico.

The mark is a funnel of four bars, wide at the top and narrow at the bottom,
standing for a long document squeezed into a short one.

    python packaging/make_icon.py

Needs Pillow for the raster formats. The SVG lands without it.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

INK = (15, 23, 42)  # #0f172a
ACCENT = (94, 214, 200)  # #5ed6c8
LIGHT = (241, 245, 249)  # #f1f5f9

# Bar geometry on a 100x100 canvas: (width, y, height)
BARS = [
    (70, 24, 9),
    (54, 39, 9),
    (38, 54, 9),
    (22, 69, 9),
]
CORNER = 22


def to_hex(rgb: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % rgb


def write_svg(path: Path) -> None:
    bars = []
    for index, (width, y, height) in enumerate(BARS):
        colour = ACCENT if index == 0 else LIGHT
        x = (100 - width) / 2
        bars.append(
            f'  <rect x="{x:g}" y="{y}" width="{width}" height="{height}" '
            f'rx="{height / 2:g}" fill="{to_hex(colour)}"/>'
        )
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100" role="img" aria-label="TSP">
  <rect width="100" height="100" rx="{CORNER}" fill="{to_hex(INK)}"/>
{chr(10).join(bars)}
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def write_raster() -> None:
    from PIL import Image, ImageDraw

    def render(size: int) -> "Image.Image":
        scale = 8  # draw large, then downsample for clean edges
        big = size * scale
        image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        unit = big / 100

        draw.rounded_rectangle(
            [0, 0, big - 1, big - 1],
            radius=CORNER * unit,
            fill=INK + (255,),
        )
        for index, (width, y, height) in enumerate(BARS):
            colour = ACCENT if index == 0 else LIGHT
            x0 = (100 - width) / 2 * unit
            draw.rounded_rectangle(
                [x0, y * unit, x0 + width * unit, (y + height) * unit],
                radius=height / 2 * unit,
                fill=colour + (255,),
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
