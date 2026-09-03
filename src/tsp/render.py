"""Turn TSP's markdown into one self-contained HTML file.

Markdown is the cheaper output and the one to paste into a chat. This exists for
reading and sending: a single file that opens anywhere, with the page images
carried inside it rather than sitting in a folder beside it.

Only the subset TSP writes is handled, so there is no markdown library here and
nothing to install.

Copyright (C) 2026 Daga D.
Licensed under the GNU General Public License v3.0 or later. See LICENSE.
"""

from __future__ import annotations

import base64
import html
import re
from pathlib import Path

__all__ = ["to_html"]

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_LIST = re.compile(r"^-\s+(.*)$")
_PAGE = re.compile(r"^---\s*(p\..*?)\s*---$")
# A whole page rendered as a picture is named in its marker rather than on a
# line of its own, so a slide deck would otherwise reach the HTML with no
# pictures in it at all.
_SEEN = re.compile(r"see\s+(\S+\.(?:png|jpe?g))")
_FIGURE = re.compile(r"^\[figure:\s*(\S+)\]$")
_ROW = re.compile(r"^\|.*\|$")
_RULE = re.compile(r"^\|(\s*[-:]+\s*\|)+$")

STYLE = """
:root { color-scheme: light dark; }
body {
  margin: 0 auto; padding: 2.5rem 1.5rem 6rem; max-width: 46rem;
  font: 16px/1.6 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  color: #16202e; background: #fbfbf9;
}
h1, h2, h3, h4, h5, h6 { line-height: 1.25; margin: 2rem 0 0.6rem; }
h1 { font-size: 1.9rem; letter-spacing: -0.02em; }
h2 { font-size: 1.4rem; }
h3 { font-size: 1.15rem; }
p, li { margin: 0 0 0.8rem; }
table { border-collapse: collapse; margin: 1.2rem 0; font-size: 0.9rem; width: 100%; }
th, td { border: 1px solid #d8dce3; padding: 0.35rem 0.5rem; text-align: left; }
th { background: #f1f4f7; font-weight: 600; }
img { max-width: 100%; height: auto; border: 1px solid #e3e6ea; border-radius: 6px; }
figure { margin: 1.4rem 0; }
figcaption, .page {
  font: 0.78rem ui-monospace, "SF Mono", Menlo, monospace; color: #6b7686;
}
.page { margin: 1.8rem 0 0.6rem; padding-top: 0.5rem; border-top: 1px solid #e6e9ee; }
.missing { color: #a33a34; }
@media (prefers-color-scheme: dark) {
  body { color: #e6e9ee; background: #12161d; }
  th { background: #1c2230; }
  th, td, img { border-color: #2b323f; }
  .page, figcaption { color: #98a2b3; }
}
"""


def _inline(text: str) -> str:
    """Escape, then put back the little emphasis TSP emits."""
    escaped = html.escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"<em>\1</em>", escaped)
    return escaped


def _cells(row: str) -> list[str]:
    return [cell.strip() for cell in row.strip().strip("|").split("|")]


def _embed(name: str, folder: Path | None) -> str:
    """A picture as a data URI, so the file stands on its own."""
    if folder is None:
        return f'<img src="{html.escape(name)}" alt="{html.escape(name)}">'
    path = folder / name
    try:
        data = base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        return (
            f'<p class="missing">Missing image: {html.escape(name)}</p>'
        )
    suffix = path.suffix.lower().lstrip(".")
    kind = "jpeg" if suffix in ("jpg", "jpeg") else suffix or "png"
    return f'<img src="data:image/{kind};base64,{data}" alt="{html.escape(name)}">'


def to_html(body: str, title: str, folder: Path | None = None) -> str:
    """Convert one markdown body. Images come from `folder`, embedded."""
    out: list[str] = []
    lines = body.split("\n")
    index = 0
    paragraph: list[str] = []
    items: list[str] = []

    def flush() -> None:
        if paragraph:
            out.append(f"<p>{_inline(' '.join(paragraph))}</p>")
            paragraph.clear()
        if items:
            out.append("<ul>")
            out.extend(f"<li>{_inline(item)}</li>" for item in items)
            out.append("</ul>")
            items.clear()

    while index < len(lines):
        line = lines[index].rstrip()

        if not line.strip():
            flush()
            index += 1
            continue

        page = _PAGE.match(line)
        if page:
            flush()
            out.append(f'<p class="page">{_inline(page.group(1))}</p>')
            for name in _SEEN.findall(page.group(1)):
                out.append(f"<figure>{_embed(name, folder)}</figure>")
            index += 1
            continue

        figure = _FIGURE.match(line.strip())
        if figure:
            flush()
            out.append(
                f"<figure>{_embed(figure.group(1), folder)}"
                f"<figcaption>{html.escape(figure.group(1))}</figcaption></figure>"
            )
            index += 1
            continue

        heading = _HEADING.match(line)
        if heading:
            flush()
            level = len(heading.group(1))
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            index += 1
            continue

        bullet = _LIST.match(line)
        if bullet:
            if paragraph:
                flush()
            items.append(bullet.group(1))
            index += 1
            continue

        if _ROW.match(line):
            flush()
            block = []
            while index < len(lines) and _ROW.match(lines[index].rstrip()):
                block.append(lines[index].rstrip())
                index += 1
            header, rows = block[0], block[1:]
            if rows and _RULE.match(rows[0]):
                rows = rows[1:]
            out.append("<table>")
            out.append(
                "<tr>" + "".join(f"<th>{_inline(c)}</th>" for c in _cells(header)) + "</tr>"
            )
            for row in rows:
                out.append(
                    "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in _cells(row)) + "</tr>"
                )
            out.append("</table>")
            continue

        paragraph.append(line.strip())
        index += 1

    flush()

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(title)}</title>\n"
        f"<style>{STYLE}</style>\n</head>\n<body>\n"
        + "\n".join(out)
        + "\n</body>\n</html>\n"
    )
