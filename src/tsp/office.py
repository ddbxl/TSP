"""Read Word and OpenDocument files into markdown.

Both formats are a zip of XML, so the standard library is enough and this runs
wherever the engine runs, WebAssembly included. Nothing here imports PyMuPDF.

What a PDF forces TSP to guess at, these formats state outright. A heading
carries a style name rather than a font size. A table is an element rather than
a grid of ruled lines. Running headers and footers live in separate parts of the
file and never reach the body, so no frequency test has to find them.

Copyright (C) 2026 Daga D.
Licensed under the GNU General Public License v3.0 or later. See LICENSE.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path

__all__ = ["Block", "read_office", "blocks_to_markdown", "OFFICE_SUFFIXES"]

OFFICE_SUFFIXES = {".docx", ".odt"}

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
TEXT_NS = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
TABLE_NS = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
OFFICE_NS = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"

_HEADING_STYLE = re.compile(r"heading[ _-]?(\d)", re.IGNORECASE)


@dataclass
class Block:
    """One piece of a document: a heading, a paragraph, a list or a table."""

    kind: str  # heading | body | list | table
    text: str = ""
    level: int = 0
    rows: list[list[str]] | None = None


# --------------------------------------------------------------------------
# Word
# --------------------------------------------------------------------------


def _docx_text(node) -> str:
    """Join a paragraph's runs, honouring tabs and line breaks."""
    parts: list[str] = []
    for element in node.iter():
        if element.tag == f"{W}t":
            parts.append(element.text or "")
        elif element.tag == f"{W}tab":
            parts.append(" ")
        elif element.tag in (f"{W}br", f"{W}cr"):
            parts.append("\n")
    return "".join(parts).strip()


def _docx_style(paragraph) -> str:
    style = paragraph.find(f"{W}pPr/{W}pStyle")
    return (style.get(f"{W}val") or "") if style is not None else ""


def _read_docx(path: Path) -> list[Block]:
    with zipfile.ZipFile(path) as archive:
        # Only the body. Headers and footers sit in their own parts.
        body = ET.fromstring(archive.read("word/document.xml")).find(f"{W}body")

    blocks: list[Block] = []
    if body is None:
        return blocks

    for child in body:
        if child.tag == f"{W}p":
            text = _docx_text(child)
            if not text:
                continue
            style = _docx_style(child)
            heading = _HEADING_STYLE.search(style)
            if heading:
                blocks.append(
                    Block("heading", text, level=min(6, int(heading.group(1))))
                )
            elif style.lower() in ("title",):
                blocks.append(Block("heading", text, level=1))
            elif child.find(f"{W}pPr/{W}numPr") is not None:
                blocks.append(Block("list", text))
            else:
                blocks.append(Block("body", text))

        elif child.tag == f"{W}tbl":
            rows = [
                [_docx_text(cell) for cell in row.findall(f"{W}tc")]
                for row in child.findall(f"{W}tr")
            ]
            if any(any(cell for cell in row) for row in rows):
                blocks.append(Block("table", rows=rows))

    return blocks


# --------------------------------------------------------------------------
# OpenDocument
# --------------------------------------------------------------------------


def _odt_text(node) -> str:
    parts: list[str] = []
    for element in node.iter():
        if element.tag == f"{TEXT_NS}tab":
            parts.append(" ")
        elif element.tag == f"{TEXT_NS}line-break":
            parts.append("\n")
        elif element.tag == f"{TEXT_NS}s":
            parts.append(" ")
        if element.text and element.tag not in (f"{TEXT_NS}tab",):
            parts.append(element.text)
        if element.tail:
            parts.append(element.tail)
    return "".join(parts).strip()


def _odt_blocks(node, blocks: list[Block]) -> None:
    for child in node:
        if child.tag == f"{TEXT_NS}h":
            text = _odt_text(child)
            if text:
                level = child.get(f"{TEXT_NS}outline-level") or "1"
                blocks.append(
                    Block("heading", text, level=min(6, max(1, int(level))))
                )
        elif child.tag == f"{TEXT_NS}p":
            text = _odt_text(child)
            if text:
                blocks.append(Block("body", text))
        elif child.tag == f"{TEXT_NS}list":
            for item in child.findall(f"{TEXT_NS}list-item"):
                text = _odt_text(item)
                if text:
                    blocks.append(Block("list", text))
        elif child.tag == f"{TABLE_NS}table":
            rows = []
            for row in child.findall(f"{TABLE_NS}table-row"):
                rows.append(
                    [
                        _odt_text(cell)
                        for cell in row.findall(f"{TABLE_NS}table-cell")
                    ]
                )
            if any(any(cell for cell in row) for row in rows):
                blocks.append(Block("table", rows=rows))
        elif child.tag in (f"{TEXT_NS}section", f"{OFFICE_NS}text"):
            _odt_blocks(child, blocks)


def _read_odt(path: Path) -> list[Block]:
    with zipfile.ZipFile(path) as archive:
        # content.xml only. Headers and footers live in styles.xml.
        root = ET.fromstring(archive.read("content.xml"))

    body = root.find(f"{OFFICE_NS}body")
    text = body.find(f"{OFFICE_NS}text") if body is not None else None
    blocks: list[Block] = []
    if text is not None:
        _odt_blocks(text, blocks)
    return blocks


# --------------------------------------------------------------------------


def read_office(path: str | Path) -> list[Block]:
    """Read a Word or OpenDocument file into blocks."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return _read_docx(path)
    if suffix == ".odt":
        return _read_odt(path)
    raise ValueError(f"not a Word or OpenDocument file: {path.name}")


def _grid(rows: list[list[str]]) -> str:
    """A markdown table. The structure is stated by the file, so unlike a PDF
    there is nothing to judge."""
    width = max(len(row) for row in rows)
    padded = [list(row) + [""] * (width - len(row)) for row in rows]
    header, *rest = padded
    if not any(cell.strip() for cell in header):
        header = [f"Col{index + 1}" for index in range(width)]
        rest = padded

    def line(cells: list[str]) -> str:
        return "|" + "|".join(cell.replace("|", "\\|").replace("\n", " ") for cell in cells) + "|"

    out = [line(header), "|" + "|".join("---" for _ in range(width)) + "|"]
    out.extend(line(row) for row in rest)
    return "\n".join(out)


def blocks_to_markdown(blocks: list[Block]) -> str:
    parts: list[str] = []
    for block in blocks:
        if block.kind == "heading":
            parts.append(f"{'#' * block.level} {block.text}")
        elif block.kind == "list":
            parts.append(f"- {block.text}")
        elif block.kind == "table" and block.rows:
            parts.append(_grid(block.rows))  # blank lines are added on join
        else:
            parts.append(block.text)
    return "\n\n".join(part for part in parts if part.strip())
