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

# A cell longer than this holds prose, so the table is a layout frame rather
# than data. Measured on a Commission partnership agreement: data cells reached
# 143 characters, layout cells 5,000 to 59,000.
MAX_DATA_CELL = 300

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
TEXT_NS = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
TABLE_NS = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
OFFICE_NS = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"

_HEADING_NAME = re.compile(r"heading[ _-]?(\d)", re.IGNORECASE)
_TOC_NAME = re.compile(r"^toc[ _-]?\d", re.IGNORECASE)


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


def _docx_styles(archive) -> tuple[dict[str, int], set[str]]:
    """Map a style id to a heading level, and collect the contents styles.

    A Slovenian author's headings are called Naslov1 and Naslov2, a German's
    berschrift1. The style definitions carry `w:name` of "heading 1" and an
    outline level regardless, so the mapping comes from there rather than from
    the identifier.
    """
    headings: dict[str, int] = {}
    contents: set[str] = set()
    try:
        root = ET.fromstring(archive.read("word/styles.xml"))
    except (KeyError, ET.ParseError):
        return headings, contents

    for style in root.iter(f"{W}style"):
        style_id = style.get(f"{W}styleId")
        if not style_id:
            continue
        name_node = style.find(f"{W}name")
        name = (name_node.get(f"{W}val") or "") if name_node is not None else ""

        if _TOC_NAME.match(name):
            contents.add(style_id)
            continue

        match = _HEADING_NAME.search(name)
        if match:
            headings[style_id] = min(6, int(match.group(1)))
            continue
        level = style.find(f"{W}pPr/{W}outlineLvl")
        if level is not None and name.lower() != "toc heading":
            try:
                depth = int(level.get(f"{W}val") or "9")
            except ValueError:
                continue
            if depth <= 5:
                headings[style_id] = depth + 1
    return headings, contents


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


def _docx_body(node, headings, contents, blocks: list[Block], depth: int = 0) -> None:
    """Walk a body or a table cell, appending blocks in reading order."""
    for child in node:
        if child.tag == f"{W}p":
            style = _docx_style(child)
            if style in contents:
                continue  # a table of contents entry, whose page numbers are gone
            text = _docx_text(child)
            if not text:
                continue
            if style in headings:
                blocks.append(Block("heading", text, level=headings[style]))
            elif style.lower() == "title":
                blocks.append(Block("heading", text, level=1))
            elif child.find(f"{W}pPr/{W}numPr") is not None:
                blocks.append(Block("list", text))
            else:
                blocks.append(Block("body", text))

        elif child.tag == f"{W}tbl":
            rows_xml = child.findall(f"{W}tr")
            grid = [
                [_docx_text(cell) for cell in row.findall(f"{W}tc")]
                for row in rows_xml
            ]
            if not any(any(cell for cell in row) for row in grid):
                continue

            longest = max((len(cell) for row in grid for cell in row), default=0)
            if longest <= MAX_DATA_CELL and depth < 4:
                blocks.append(Block("table", rows=grid))
                continue

            # A layout frame. Its cells hold sections of the document, so walk
            # into them rather than flattening a chapter into one row.
            for row in rows_xml:
                for cell in row.findall(f"{W}tc"):
                    _docx_body(cell, headings, contents, blocks, depth + 1)


def _read_docx(path: Path) -> list[Block]:
    with zipfile.ZipFile(path) as archive:
        headings, contents = _docx_styles(archive)
        # Only the body. Headers and footers sit in their own parts.
        body = ET.fromstring(archive.read("word/document.xml")).find(f"{W}body")

    blocks: list[Block] = []
    if body is not None:
        _docx_body(body, headings, contents, blocks)
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
