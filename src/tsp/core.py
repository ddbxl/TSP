"""TSP core engine: turn PDFs into token-efficient text plus page images.

This module holds no user-interface code. Import it from a GUI, a CLI, a
notebook or a WebAssembly runtime.

Copyright (C) 2026 Daga D.
Licensed under the GNU General Public License v3.0 or later. See LICENSE.
"""

from __future__ import annotations

import contextlib
import io
import os
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

try:  # PyMuPDF >= 1.24.3 prefers the `pymupdf` name; `fitz` is the legacy alias.
    import pymupdf
except ImportError:  # pragma: no cover
    import fitz as pymupdf

__all__ = [
    "Settings",
    "SUPPORTED_SUFFIXES",
    "process_document",
    "prepare_page_text",
    "PageStat",
    "Result",
    "MODES",
    "process_pdf",
    "estimate_tokens",
    "clean_text",
]

# Rough character-per-token ratio for English prose in cl100k/o200k-style
# tokenisers. Used only to report savings, never to make decisions.
CHARS_PER_TOKEN = 4.0

# Resolution of the grid used to measure how much of a page raster images
# cover. Marking cells rather than adding areas keeps overlapping images from
# counting twice.
COVERAGE_GRID = 32

MODES: dict[str, float] = {
    "Text documents (5%)": 0.05,
    "Mixed reports (20%)": 0.20,
    "Slide decks (50%)": 0.50,
    "Text only, skip images (100%)": 1.01,
}

_LIGATURES = {
    "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi",
    "\ufb04": "ffl", "\ufb05": "st", "\ufb06": "st",
}

_PUNCTUATION = {
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"',
    "\u2032": "'", "\u2033": '"',
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-",
    "\u2014": "-", "\u2015": "-", "\u2212": "-",
    "\u2026": "...", "\u00a0": " ", "\u2007": " ", "\u202f": " ",
    "\u2009": " ", "\u200a": " ", "\u2008": " ",
    "\u2022": "-", "\u00b7": "-", "\u25cf": "-", "\u25aa": "-",
    "\u2043": "-", "\u2219": "-", "\uf0b7": "-",
    "\u00ad": "",  # soft hyphen
    "\u200b": "", "\u200c": "", "\u200d": "", "\ufeff": "",
}

_TRANSLATION = str.maketrans({**_LIGATURES, **_PUNCTUATION})

_BLANK_RUN = re.compile(r"\n{3,}")
_SPACE_RUN = re.compile(r"[ \t]{2,}")
_TRAILING_WS = re.compile(r"[ \t]+$", re.MULTILINE)
_HYPHEN_BREAK = re.compile(r"([A-Za-zÀ-ÖØ-öø-ÿ])-\n([a-zà-öø-ÿ])")
_DIGIT_RUN = re.compile(r"\d+")
_PAGE_NUMBER_LINE = re.compile(
    r"^\s*(?:page\s+)?\d{1,4}(?:\s*[/|of]{1,2}\s*\d{1,4})?\s*$", re.IGNORECASE
)


@dataclass(frozen=True)
class Settings:
    """Knobs for one processing run.

    image_threshold: fraction of page area covered by raster images above
        which the page is also rendered to PNG. Set above 1.0 to never render.
    """

    image_threshold: float = 0.05
    render_zoom: float = 2.0  # 2.0 == 144 dpi
    min_image_fraction: float = 0.004  # ignore logos, rules, hairlines
    vector_min_paths: int = 60  # a chart drawn in vectors holds no raster image
    vector_max_chars: int = 400
    dehyphenate: bool = True
    normalise_punctuation: bool = True
    strip_repeated_lines: bool = True
    repeat_ratio: float = 0.5  # line must appear on this share of pages
    repeat_scan_lines: int = 3  # only the first/last N lines of each page
    drop_page_numbers: bool = True
    render_visual_pages: bool = True
    write_manifest: bool = True
    output_dir: Path | None = None  # None: a folder beside the source PDF

    # Remove the previous run's output before writing. Only files TSP itself
    # creates are touched, so pointing output at a shared folder stays safe.
    clean_target: bool = True

    # Tables. Detection costs about four times the text-extraction time, so it
    # stays off unless asked for. Markdown grids cost no more tokens than the
    # reading-order text they replace.
    extract_tables: bool = False
    # Table detection reads ruling lines, so a page without enough of them can
    # hold no table the detector would find. Skipping those pages is where
    # nearly all of the cost goes.
    table_min_lines: int = 4
    # A bordered callout box looks like a table to a line-reading detector, and
    # comes out as a grid of prose with empty columns. These reject that shape.
    # A rejected table still reaches the output as reading-order text, so the
    # cost of turning one down is structure rather than content.
    # A real table fills its columns down the page. A box or a chart's axis
    # labels leave most columns blank on most rows, which is the sharpest signal
    # of the two shapes apart: real tables measured 0 to 33% thin columns in a
    # Commission country report, boxes and charts 50 to 100%.
    table_max_thin_columns: float = 0.5

    # A chart drawn in vector paths carries no text layer worth reading: its
    # axis labels arrive as orphan numbers with nothing to attach them to. TSP
    # renders the area it occupies and drops the rubble inside it.
    # Off by default. Replacing text with an image reference loses the data for
    # anyone who pastes the markdown without carrying the images along, and a
    # chart cannot be told from a sparse table by any measure of its text:
    # measured on a Commission report, both run 1.4 to 2.0 words a line. With
    # tables on, a grid the table gate recovered wins over an image.
    chart_regions: bool = False
    chart_min_area: float = 0.04  # share of the page the drawings cover
    chart_min_paths: int = 3
    # Axis labels and a legend sit outside the drawn area, so the region grows
    # before its text is judged and before it is rendered.
    chart_margin: float = 18.0
    chart_max_words_per_line: float = 4.0  # above this the region holds prose
    table_max_mean_cell: int = 120  # cells hold values, not paragraphs
    table_max_cell: int = 600  # one cell this long is a paragraph

    # Scanned pages. Detection is cheap and always on; running OCR is not.
    ocr: bool = False
    ocr_language: str = "eng"
    ocr_dpi: int = 200
    scan_max_chars: int = 24  # a page with no more text than this, and
    scan_min_coverage: float = 0.8  # this much image, is a scan

    @property
    def dpi(self) -> int:
        return round(72 * self.render_zoom)


@dataclass
class PageStat:
    number: int
    chars: int
    visual: bool
    blank: bool
    image_name: str | None = None
    scanned: bool = False
    ocr: bool = False
    tables: int = 0


@dataclass
class Result:
    source: Path
    text_path: Path | None = None
    pages: int = 0
    images_saved: int = 0
    chars_in: int = 0
    chars_out: int = 0
    page_stats: list[PageStat] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    ok: bool = True
    message: str = ""
    tables_rejected: int = 0
    # The running headers and footers found for this document. Keeping them
    # lets text recognised later be cleaned the same way without reading the
    # PDF again.
    boilerplate: list[str] = field(default_factory=list)

    @property
    def scanned_pages(self) -> int:
        return sum(1 for s in self.page_stats if s.scanned)

    @property
    def ocr_pages(self) -> int:
        return sum(1 for s in self.page_stats if s.ocr)

    @property
    def tables_found(self) -> int:
        return sum(s.tables for s in self.page_stats)

    @property
    def needs_ocr(self) -> bool:
        """True when pages look scanned and none of them were read by OCR."""
        return self.scanned_pages > 0 and self.ocr_pages == 0

    @property
    def tokens_in(self) -> int:
        return estimate_tokens_from_chars(self.chars_in)

    @property
    def tokens_out(self) -> int:
        return estimate_tokens_from_chars(self.chars_out)

    @property
    def saving(self) -> float:
        """Share of raw extracted characters removed by cleaning, 0.0-1.0."""
        if self.chars_in <= 0:
            return 0.0
        return max(0.0, 1.0 - self.chars_out / self.chars_in)


def estimate_tokens_from_chars(chars: int) -> int:
    return int(round(chars / CHARS_PER_TOKEN))


def estimate_tokens(text: str) -> int:
    return estimate_tokens_from_chars(len(text))


# --------------------------------------------------------------------------
# Text cleaning
# --------------------------------------------------------------------------


def clean_text(raw: str, settings: Settings) -> str:
    """Collapse whitespace and strip characters that cost tokens but carry
    no meaning."""
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    if settings.normalise_punctuation:
        text = unicodedata.normalize("NFKC", text)
        text = text.translate(_TRANSLATION)
    if settings.dehyphenate:
        text = _HYPHEN_BREAK.sub(r"\1\2", text)
    text = _TRAILING_WS.sub("", text)
    text = _SPACE_RUN.sub(" ", text)
    text = _BLANK_RUN.sub("\n\n", text)
    return text.strip()


def prepare_page_text(
    raw: str, boilerplate: Iterable[str] = (), settings: Settings | None = None
) -> str:
    """Clean one page's text the way a whole run would.

    Text recognised outside the engine can be brought up to the same state
    without opening the PDF again.
    """
    settings = settings or Settings()
    return _strip_boilerplate(clean_text(raw, settings), set(boilerplate), settings)


def _boilerplate_key(line: str) -> str:
    """Collapse digits so `Page 4 of 30` and `Page 5 of 30` share a key."""
    return _DIGIT_RUN.sub("#", line)


def _boilerplate_lines(page_texts: Sequence[str], settings: Settings) -> set[str]:
    """Find running headers and footers, returning their digit-collapsed keys.

    A line qualifies when it

    * sits within the first or last few lines of a page,
    * recurs at the edge of at least `repeat_ratio` of pages,
    * never appears more than once on any single page, and
    * carries at least three letters and no more than 100 characters.

    The once-per-page condition protects body text. A paragraph repeating
    three times down a single page is prose, so it stays.
    """
    if not settings.strip_repeated_lines or len(page_texts) < 4:
        return set()

    edge_counts: Counter[str] = Counter()
    disqualified: set[str] = set()

    for text in page_texts:
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        if not lines:
            continue

        per_page: Counter[str] = Counter(_boilerplate_key(ln) for ln in lines)
        disqualified.update(key for key, n in per_page.items() if n > 1)

        edge = lines[: settings.repeat_scan_lines] + lines[-settings.repeat_scan_lines :]
        for key in {_boilerplate_key(ln) for ln in edge}:
            if 2 <= len(key) <= 100 and sum(c.isalpha() for c in key) >= 3:
                edge_counts[key] += 1

    floor = max(3, int(len(page_texts) * settings.repeat_ratio))
    return {
        key
        for key, n in edge_counts.items()
        if n >= floor and key not in disqualified
    }


def _strip_boilerplate(text: str, boilerplate: set[str], settings: Settings) -> str:
    if not boilerplate and not settings.drop_page_numbers:
        return text
    kept: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped and _boilerplate_key(stripped) in boilerplate:
            continue
        if settings.drop_page_numbers and stripped and _PAGE_NUMBER_LINE.match(stripped):
            continue
        kept.append(line)
    return _BLANK_RUN.sub("\n\n", "\n".join(kept)).strip()


# --------------------------------------------------------------------------
# Page classification
# --------------------------------------------------------------------------


def _raster_coverage(page, settings: Settings) -> float:
    """Share of the page covered by raster images, 0.0-1.0.

    Bounding boxes are clipped to the page and mapped onto a grid, so an image
    extending past the page edge or sitting on top of another counts once, for
    the area it actually covers.
    """
    rect = page.rect
    if rect.is_empty or rect.width <= 0 or rect.height <= 0:
        return 0.0

    page_area = rect.width * rect.height
    cells: set[int] = set()
    try:
        infos = page.get_image_info()
    except Exception:
        return 0.0

    for info in infos:
        try:
            bbox = pymupdf.Rect(info["bbox"]) & rect
        except Exception:
            continue
        if bbox.is_empty:
            continue
        if (bbox.width * bbox.height) / page_area < settings.min_image_fraction:
            continue
        x0 = int((bbox.x0 - rect.x0) / rect.width * COVERAGE_GRID)
        x1 = int((bbox.x1 - rect.x0) / rect.width * COVERAGE_GRID)
        y0 = int((bbox.y0 - rect.y0) / rect.height * COVERAGE_GRID)
        y1 = int((bbox.y1 - rect.y0) / rect.height * COVERAGE_GRID)
        for row in range(max(0, y0), min(COVERAGE_GRID, y1 + 1)):
            for col in range(max(0, x0), min(COVERAGE_GRID, x1 + 1)):
                cells.add(row * COVERAGE_GRID + col)

    return len(cells) / (COVERAGE_GRID * COVERAGE_GRID)


def _is_vector_heavy(path_count: int, char_count: int, settings: Settings) -> bool:
    """Catch charts drawn as vector paths, which carry no raster image and
    little text."""
    if char_count > settings.vector_max_chars:
        return False
    return path_count >= settings.vector_min_paths


# --------------------------------------------------------------------------
# Scanned pages
# --------------------------------------------------------------------------


def tesseract_available() -> bool:
    """True when PyMuPDF can find Tesseract's language data.

    PyMuPDF reads TESSDATA_PREFIX, so Tesseract 5 and its language files have
    to be installed separately. Nothing here bundles them.
    """
    try:
        return bool(pymupdf.get_tessdata())
    except Exception:
        return False


def _looks_scanned(char_count: int, coverage: float, settings: Settings) -> bool:
    """A page holding an image and almost no text is a scan."""
    return (
        char_count <= settings.scan_max_chars
        and coverage >= settings.scan_min_coverage
    )


def _ocr_page(page, settings: Settings) -> str:
    """Read a scanned page through Tesseract. Raises if Tesseract is absent."""
    textpage = page.get_textpage_ocr(
        language=settings.ocr_language,
        dpi=settings.ocr_dpi,
        full=True,
    )
    return page.get_text("text", textpage=textpage)


# --------------------------------------------------------------------------
# Tables
# --------------------------------------------------------------------------


def _line_like(drawings) -> int:
    """Count the lines and rectangles on a page.

    A ruled table is made of these. Curves and text belong to logos and charts.
    """
    total = 0
    for drawing in drawings:
        for item in drawing.get("items", ()):
            if item and item[0] in ("l", "re"):
                total += 1
    return total


def _looks_like_a_table(rows, settings: Settings) -> bool:
    """Judge whether a detected grid is a table or a bordered box of prose."""
    if len(rows) < 2:
        return False
    if max((len(row) for row in rows), default=0) < 2:
        return False

    cells = [(cell or "").strip() for row in rows for cell in row]
    filled = [cell for cell in cells if cell]
    if not filled:
        return False  # a grid of nothing

    if sum(len(cell) for cell in filled) / len(filled) > settings.table_max_mean_cell:
        return False
    if max(len(cell) for cell in filled) > settings.table_max_cell:
        return False

    # How many columns carry content on fewer than half the rows?
    width = max(len(row) for row in rows)
    thin = 0
    for column in range(width):
        carried = sum(
            1
            for row in rows
            if column < len(row) and (row[column] or "").strip()
        )
        if carried / len(rows) < 0.5:
            thin += 1
    return thin / width < settings.table_max_thin_columns


# --------------------------------------------------------------------------
# Charts drawn in vector paths
# --------------------------------------------------------------------------

REGION_CELL = 10.0  # points, the grain at which drawings are grouped


def _drawing_boxes(page, drawings) -> list:
    """Every drawn line, rectangle and curve as a rectangle clipped to the page."""
    rect = page.rect
    boxes = []
    for drawing in drawings:
        try:
            box = pymupdf.Rect(drawing["rect"]) & rect
        except Exception:
            continue
        if not box.is_empty:
            boxes.append(box)
    return boxes


def _drawn_regions(page, boxes) -> list:
    """Group drawings into the areas of the page they occupy.

    Cells of a coarse grid covered by any drawing are joined where they touch,
    so a chart's axes, bars and gridlines come back as one area while a header
    rule stays its own.
    """
    rect = page.rect
    if rect.is_empty or not boxes:
        return []

    columns = max(1, int(rect.width / REGION_CELL))
    rows = max(1, int(rect.height / REGION_CELL))
    filled: set[tuple[int, int]] = set()
    for box in boxes:
        x0 = max(0, int((box.x0 - rect.x0) / REGION_CELL))
        x1 = min(columns - 1, int((box.x1 - rect.x0) / REGION_CELL))
        y0 = max(0, int((box.y0 - rect.y0) / REGION_CELL))
        y1 = min(rows - 1, int((box.y1 - rect.y0) / REGION_CELL))
        for row in range(y0, y1 + 1):
            for column in range(x0, x1 + 1):
                filled.add((row, column))

    regions = []
    seen: set[tuple[int, int]] = set()
    for cell in filled:
        if cell in seen:
            continue
        stack = [cell]
        seen.add(cell)
        group = []
        while stack:
            row, column = stack.pop()
            group.append((row, column))
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    neighbour = (row + dr, column + dc)
                    if neighbour in filled and neighbour not in seen:
                        seen.add(neighbour)
                        stack.append(neighbour)
        top = min(r for r, _ in group)
        bottom = max(r for r, _ in group)
        left = min(c for _, c in group)
        right = max(c for _, c in group)
        regions.append(
            pymupdf.Rect(
                rect.x0 + left * REGION_CELL,
                rect.y0 + top * REGION_CELL,
                rect.x0 + (right + 1) * REGION_CELL,
                rect.y0 + (bottom + 1) * REGION_CELL,
            )
            & rect
        )
    return regions


def _words_per_line(text: str) -> float:
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if not lines:
        return 0.0
    return sum(len(line.split()) for line in lines) / len(lines)


def _lines_inside(region, blocks) -> list[str]:
    """Text lines whose block sits inside a region."""
    lines: list[str] = []
    for block in blocks:
        if not isinstance(block[4], str):
            continue
        middle = pymupdf.Point((block[0] + block[2]) / 2, (block[1] + block[3]) / 2)
        if region.contains(middle):
            lines.extend(line.strip() for line in block[4].split("\n") if line.strip())
    return lines


def _chart_regions(page, boxes, blocks, keep_as_text, settings: Settings) -> list:
    """Pick out the drawn areas whose text is worth replacing with a picture.

    A chart's labels arrive as orphan fragments: measured on a Commission
    report, 1.5 to 4 words a line against 9 to 12 inside a bordered box of
    prose. Prose stays. Areas a table gate already recovered stay too, since a
    grid beats a picture.
    """
    page_area = page.rect.get_area()
    if page_area <= 0:
        return []

    charts = []
    for drawn in _drawn_regions(page, boxes):
        region = (drawn + (
            -settings.chart_margin,
            -settings.chart_margin,
            settings.chart_margin,
            settings.chart_margin,
        )) & page.rect
        share = region.get_area() / page_area
        if share < settings.chart_min_area or share > 0.98:
            continue
        paths = sum(
            1 for box in boxes if region.contains(box.tl) or region.contains(box.br)
        )
        if paths < settings.chart_min_paths:
            continue
        if any(region.intersects(other) for other in keep_as_text):
            continue

        lines = _lines_inside(region, blocks)
        if not lines:
            continue
        words = sum(len(line.split()) for line in lines) / len(lines)
        if words > settings.chart_max_words_per_line:
            continue  # sentences, so leave them be

        charts.append(region)

    merged: list = []
    for region in sorted(charts, key=lambda r: -r.get_area()):
        for index, existing in enumerate(merged):
            if existing.intersects(region):
                merged[index] = existing | region
                break
        else:
            merged.append(region)
    return merged


def _fenced(grid: str) -> str:
    """Pad a markdown grid with blank lines.

    Without one on each side, a grid touching prose or a page marker is read as
    a paragraph of pipes rather than a table.
    """
    return f"\n{grid.strip()}\n"


def _assemble_page(
    page, flags: int, lines: int, boxes, settings: Settings, label: str
) -> tuple[str, int, int, list]:
    """Extract text with detected tables replaced by markdown grids.

    Text blocks falling inside a table's bounds are dropped and the grid takes
    their place, so a table's contents appear once rather than twice.

    Pages carrying fewer ruling lines than a table needs skip detection, which
    costs about 24 ms a page and rises with the amount of prose on it.
    """
    want_tables = settings.extract_tables and lines >= settings.table_min_lines
    want_charts = settings.chart_regions and bool(boxes)
    if not want_tables and not want_charts:
        return page.get_text("text", flags=flags, sort=True), 0, 0, []

    tables = []
    if want_tables:
        try:
            # find_tables() prints a suggestion to stdout on every call. Swallow
            # it so a caller's own output stays clean. Single-threaded only.
            with contextlib.redirect_stdout(io.StringIO()):
                tables = page.find_tables().tables
        except Exception:
            tables = []

    rejected = 0
    bounds: list = []
    grids: list[str] = []
    kept = 0
    for table in tables:
        try:
            rows = table.extract()
        except Exception:
            rows = []
        if not _looks_like_a_table(rows, settings):
            rejected += 1  # a box, a graph or an empty grid: leave the text be
            continue
        try:
            grid = table.to_markdown()
        except Exception:
            rejected += 1
            continue
        # to_markdown() marks line breaks inside a cell with <br>, which costs
        # tokens and reads no better than a space.
        grids.append(grid.replace("<br>", " "))
        bounds.append(pymupdf.Rect(table.bbox))
        kept += 1



    try:
        blocks = page.get_text("blocks", flags=flags, sort=True)
    except Exception:
        return page.get_text("text", flags=flags, sort=True), 0, rejected, []

    figures = (
        _chart_regions(page, boxes, blocks, bounds, settings) if want_charts else []
    )
    if not grids and not figures:
        return page.get_text("text", flags=flags, sort=True), 0, rejected, []

    placed: set[int] = set()
    shown: set[int] = set()
    parts: list[str] = []

    for block in blocks:
        x0, y0, x1, y1, text = block[0], block[1], block[2], block[3], block[4]
        if not isinstance(text, str) or not text.strip():
            continue
        centre = pymupdf.Point((x0 + x1) / 2, (y0 + y1) / 2)

        figure = next(
            (i for i, area in enumerate(figures) if area.contains(centre)), None
        )
        if figure is not None:
            if _words_per_line(text) > settings.chart_max_words_per_line:
                parts.append(text)  # a caption or a sentence, not a label
                continue
            if figure not in shown:
                shown.add(figure)
                parts.append(f"\n[figure: {label}_f{figure + 1}.png]\n")
            continue  # the picture stands in for these labels

        inside = next(
            (i for i, box in enumerate(bounds) if box.contains(centre)), None
        )
        if inside is None:
            parts.append(text)
        elif inside not in placed:
            placed.add(inside)
            if grids[inside]:
                parts.append(_fenced(grids[inside]))

    # A table whose blocks were all filtered out still belongs in the output.
    for index, grid in enumerate(grids):
        if index not in placed and grid:
            parts.append(_fenced(grid))
    for index in range(len(figures)):
        if index not in shown:
            parts.append(f"\n[figure: {label}_f{index + 1}.png]\n")

    return "\n".join(parts), kept, rejected, figures


# --------------------------------------------------------------------------
# Main entry point
# --------------------------------------------------------------------------

ProgressCb = Callable[[int, int], None]


# What TSP will open. PyMuPDF handles the first two groups; the office formats
# are read by tsp.office, which needs nothing beyond the standard library.
PAGED_SUFFIXES = {".pdf", ".xps", ".epub", ".mobi", ".fb2", ".cbz", ".svg"}
IMAGE_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".tif", ".pnm", ".ppm", ".pgm"
}
TEXT_SUFFIXES = {".txt", ".md", ".markdown"}
SUPPORTED_SUFFIXES = (
    PAGED_SUFFIXES | IMAGE_SUFFIXES | TEXT_SUFFIXES | {".docx", ".odt"}
)


def process_document(
    path: str | os.PathLike[str],
    settings: Settings | None = None,
    progress: ProgressCb | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    supplied_text: Mapping[int, str] | None = None,
) -> Result:
    """Turn any supported file into markdown, choosing the reader by suffix."""
    source = Path(path)
    suffix = source.suffix.lower()

    if suffix in {".docx", ".odt"}:
        return _process_office(source, settings or Settings(), progress)
    if suffix in TEXT_SUFFIXES:
        return _process_plain(source, settings or Settings(), progress)
    return process_pdf(path, settings, progress, is_cancelled, supplied_text)


def _write_result(
    result: Result, source: Path, settings: Settings, body: str, note: str
) -> Result:
    """Shared tail for the readers that produce one body of text."""
    out_dir = Path(settings.output_dir) if settings.output_dir else source.parent
    target = _target_dir(source, out_dir)
    target.mkdir(parents=True, exist_ok=True)
    if settings.clean_target:
        _clear_previous(target, source.stem)

    result.text_path = target / f"{source.stem}.md"
    result.text_path.write_text(f"# {source.name}\n\n{body}\n", encoding="utf-8")
    result.chars_out = len(body)
    result.page_stats = [
        PageStat(number=1, chars=len(body), visual=False, blank=not body)
    ]
    result.pages = 0  # these formats have no pages
    result.message = f"{note}, ~{result.tokens_out:,} tokens"

    if settings.write_manifest:
        _write_manifest(target / "MANIFEST.txt", result, settings, set())
    return result


def _process_office(source: Path, settings: Settings, progress) -> Result:
    from .office import blocks_to_markdown, read_office

    result = Result(source=source)
    if not source.is_file():
        result.ok = False
        result.message = f"File not found: {source}"
        return result
    try:
        if progress:
            progress(0, 1)
        blocks = read_office(source)
        raw = blocks_to_markdown(blocks)
        result.chars_in = len(raw)
        body = clean_text(raw, settings)
        tables = sum(1 for block in blocks if block.kind == "table")
        result.page_stats = []
        note = f"{len(blocks)} blocks"
        if tables:
            note += f", {tables} tables"
        if progress:
            progress(1, 1)
        return _write_result(result, source, settings, body, note)
    except Exception as exc:
        result.ok = False
        result.message = f"Could not read {source.name}: {exc}"
        return result


def _process_plain(source: Path, settings: Settings, progress) -> Result:
    result = Result(source=source)
    if not source.is_file():
        result.ok = False
        result.message = f"File not found: {source}"
        return result
    try:
        if progress:
            progress(0, 1)
        raw = source.read_text(encoding="utf-8", errors="replace")
        result.chars_in = len(raw)
        body = clean_text(raw, settings)
        if progress:
            progress(1, 1)
        return _write_result(result, source, settings, body, "plain text")
    except Exception as exc:
        result.ok = False
        result.message = f"Could not read {source.name}: {exc}"
        return result


def process_pdf(
    pdf_path: str | os.PathLike[str],
    settings: Settings | None = None,
    progress: ProgressCb | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    supplied_text: Mapping[int, str] | None = None,
) -> Result:
    """Extract one PDF into `<name>_TSP/<name>.md` plus page images.

    `supplied_text` maps a 1-based page number to text recognised elsewhere,
    which stands in for that page's own text layer. It lets an OCR engine that
    lives outside this module, in a browser for instance, fill in scanned pages
    without the engine caring where the words came from.

    Never raises for a bad input file: read `Result.ok` and `Result.message`.
    """
    settings = settings or Settings()
    source = Path(pdf_path)
    result = Result(source=source)

    if not source.is_file():
        result.ok = False
        result.message = f"File not found: {source}"
        return result

    out_dir = Path(settings.output_dir) if settings.output_dir else source.parent
    target = _target_dir(source, out_dir)

    doc = None
    try:
        doc = pymupdf.open(source)

        if doc.needs_pass:
            result.ok = False
            result.message = "Password protected; TSP cannot read it."
            return result

        page_count = doc.page_count
        if page_count == 0:
            result.ok = False
            result.message = "No pages found; the file may be truncated."
            return result

        target.mkdir(parents=True, exist_ok=True)
        if settings.clean_target:
            _clear_previous(target, source.stem)
        result.text_path = target / f"{source.stem}.md"
        width = max(3, len(str(page_count)))
        flags = pymupdf.TEXTFLAGS_TEXT
        if settings.dehyphenate:
            flags |= pymupdf.TEXT_DEHYPHENATE

        # Pass 1: extract, clean and classify. Cleaning happens before
        # detection so the header keys match the text they are stripped from.
        clean_pages: list[str] = []
        visual_flags: list[bool] = []
        scan_flags: list[bool] = []
        ocr_flags: list[bool] = []
        table_counts: list[int] = []
        rejected_counts: list[int] = []
        figure_rects: list[list] = []
        ocr_ready = settings.ocr and tesseract_available()
        if settings.ocr and not ocr_ready:
            result.warnings.append(
                "OCR requested but Tesseract was not found; reading the text "
                "layer only."
            )

        for index in range(page_count):
            if is_cancelled and is_cancelled():
                result.ok = False
                result.message = "Cancelled."
                return result
            if progress:
                progress(index, page_count)

            tables_here = 0
            rejected_here = 0
            try:
                page = doc.load_page(index)
                try:
                    drawings = page.get_cdrawings()
                except Exception:
                    drawings = []
                width_now = max(3, len(str(page_count)))
                # A page rendered whole needs no figure markers, and deciding
                # that here stops a marker naming a file nobody writes.
                coverage = -1.0
                whole_page = False
                if settings.render_visual_pages and settings.image_threshold <= 1.0:
                    coverage = _raster_coverage(page, settings)
                    whole_page = coverage >= settings.image_threshold
                boxes = (
                    _drawing_boxes(page, drawings)
                    if settings.chart_regions and not whole_page
                    else []
                )
                raw, tables_here, rejected_here, figures_here = _assemble_page(
                    page,
                    flags,
                    _line_like(drawings),
                    boxes,
                    settings,
                    f"p{index + 1:0{width_now}d}",
                )
            except Exception as exc:  # isolate the page, keep the document
                result.warnings.append(f"page {index + 1}: {exc}")
                visual_flags.append(False)
                scan_flags.append(False)
                ocr_flags.append(False)
                table_counts.append(0)
                rejected_counts.append(0)
                figure_rects.append([])
                clean_pages.append("")
                continue

            # A page with an image and no text is a scan. Only measure coverage
            # when the text is thin, so the check costs nothing on normal pages.
            scanned = False
            if len(raw.strip()) <= settings.scan_max_chars:
                if coverage < 0.0:
                    coverage = _raster_coverage(page, settings)
                scanned = _looks_scanned(len(raw.strip()), coverage, settings)

            did_ocr = False
            handed = (supplied_text or {}).get(index + 1)
            if handed and handed.strip():
                # Text recognised outside this module, for a page whose own
                # layer holds nothing.
                raw = handed
                did_ocr = True
            elif scanned and ocr_ready:
                try:
                    ocr_text = _ocr_page(page, settings)
                    if ocr_text.strip():
                        raw = ocr_text
                        did_ocr = True
                except Exception as exc:
                    result.warnings.append(f"page {index + 1} OCR: {exc}")

            result.chars_in += len(raw)
            clean_pages.append(clean_text(raw, settings))
            scan_flags.append(scanned)
            ocr_flags.append(did_ocr)
            table_counts.append(tables_here)
            rejected_counts.append(rejected_here)
            figure_rects.append(figures_here)

            visual = whole_page
            if (
                not visual
                and not settings.chart_regions
                and settings.render_visual_pages
                and settings.image_threshold <= 1.0
            ):
                visual = _is_vector_heavy(len(drawings), len(raw.strip()), settings)
            visual_flags.append(visual)

        boilerplate = _boilerplate_lines(clean_pages, settings)
        result.boilerplate = sorted(boilerplate)

        # Pass 2: strip boilerplate, render, assemble.
        chunks: list[str] = [_header(source, doc, settings, page_count)]
        for index, cleaned in enumerate(clean_pages):
            if is_cancelled and is_cancelled():
                result.ok = False
                result.message = "Cancelled."
                return result

            text = _strip_boilerplate(cleaned, boilerplate, settings)
            visual = visual_flags[index]
            image_name: str | None = None

            if visual:
                image_name = f"p{index + 1:0{width}d}.png"
                try:
                    page = doc.load_page(index)
                    pix = page.get_pixmap(
                        matrix=pymupdf.Matrix(settings.render_zoom, settings.render_zoom),
                        colorspace=pymupdf.csRGB,
                        alpha=False,
                    )
                    pix.save(target / image_name)
                    pix = None  # free the pixel buffer before the next page
                    result.images_saved += 1
                except Exception as exc:
                    result.warnings.append(f"page {index + 1} render: {exc}")
                    image_name = None
                    visual = False

            if not visual and figure_rects[index]:
                for number, area in enumerate(figure_rects[index], start=1):
                    name = f"p{index + 1:0{width}d}_f{number}.png"
                    try:
                        page = doc.load_page(index)
                        pix = page.get_pixmap(
                            clip=area,
                            matrix=pymupdf.Matrix(
                                settings.render_zoom, settings.render_zoom
                            ),
                            colorspace=pymupdf.csRGB,
                            alpha=False,
                        )
                        pix.save(target / name)
                        pix = None
                        result.images_saved += 1
                    except Exception as exc:
                        result.warnings.append(
                            f"page {index + 1} figure {number}: {exc}"
                        )

            marker = f"--- p.{index + 1}"
            if image_name:
                marker += f" | see {image_name}"
            if not text:
                marker += " | no text"
            marker += " ---"

            chunks.append(marker + "\n")
            if text:
                chunks.append(text)
            result.page_stats.append(
                PageStat(
                    number=index + 1,
                    chars=len(text),
                    visual=visual,
                    blank=not text,
                    image_name=image_name,
                    scanned=scan_flags[index],
                    ocr=ocr_flags[index],
                    tables=table_counts[index],
                )
            )

        body = "\n".join(chunks).rstrip() + "\n"
        result.chars_out = sum(s.chars for s in result.page_stats)
        result.pages = page_count
        result.tables_rejected = sum(rejected_counts)

        result.text_path.write_text(body, encoding="utf-8")
        if settings.write_manifest:
            _write_manifest(target / "MANIFEST.txt", result, settings, boilerplate)

        if result.needs_ocr:
            result.warnings.append(
                f"{result.scanned_pages} of {page_count} pages hold an image and "
                f"no text layer. Run OCR to read them."
            )

        parts = [f"{page_count} pages", f"{result.images_saved} images"]
        if result.tables_found:
            parts.append(f"{result.tables_found} tables")
        if result.ocr_pages:
            parts.append(f"{result.ocr_pages} pages read by OCR")
        parts.append(f"~{result.tokens_out:,} tokens")
        result.message = ", ".join(parts)
        if progress:
            progress(page_count, page_count)
        return result

    except Exception as exc:
        result.ok = False
        result.message = f"Could not process {source.name}: {exc}"
        return result

    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass


def _target_dir(source: Path, out_dir: Path) -> Path:
    """Where a document's output goes.

    Two files sharing a stem, report.docx and report.odt say, would otherwise
    write over each other. The suffix joins the folder name only when that
    would happen, so the common case stays tidy.
    """
    base = out_dir / f"{source.stem}_TSP"
    manifest = base / "MANIFEST.txt"
    if manifest.is_file():
        try:
            first = manifest.read_text(encoding="utf-8").split("\n", 1)[0]
        except OSError:
            return base
        if first.startswith("source: ") and first[8:].strip() != source.name:
            return out_dir / f"{source.stem}_{source.suffix.lstrip('.')}_TSP"
    return base


def _clear_previous(target: Path, stem: str) -> None:
    """Delete what an earlier run wrote, and nothing else.

    Reprocessing at a higher threshold renders fewer pages, so last run's
    images would otherwise linger and end up in the output.
    """
    for name in (f"{stem}.md", f"{stem}.txt", "MANIFEST.txt"):
        try:
            (target / name).unlink(missing_ok=True)
        except OSError:
            pass
    for image in target.glob("p[0-9]*.png"):
        try:
            image.unlink()
        except OSError:
            pass


def _header(source: Path, doc, settings: Settings, page_count: int) -> str:
    meta = doc.metadata or {}
    title = (meta.get("title") or "").strip()
    lines = [
        f"# {source.name}",
        f"pages: {page_count}",
    ]
    if title:
        lines.append(f"title: {title}")
    if settings.render_visual_pages and settings.image_threshold <= 1.0:
        lines.append(
            "note: pages marked 'see pNNN.png' hold graphics saved as images "
            "in this folder; their text follows the marker."
        )
    lines.append("")
    return "\n".join(lines)


def _write_manifest(
    path: Path, result: Result, settings: Settings, boilerplate: set[str]
) -> None:
    lines = [
        f"source: {result.source.name}",
        f"pages: {result.pages}",
        f"images: {result.images_saved} at {settings.dpi} dpi",
        f"image threshold: {settings.image_threshold:.0%} of page area",
        f"characters: {result.chars_in:,} extracted -> {result.chars_out:,} kept",
        f"estimated tokens: {result.tokens_in:,} -> {result.tokens_out:,}",
        f"reduction: {result.saving:.1%}",
    ]
    if settings.extract_tables:
        lines.append(f"tables kept as markdown grids: {result.tables_found}")
        if result.tables_rejected:
            lines.append(
                f"grids turned down as boxes or charts: {result.tables_rejected}"
            )
    if result.scanned_pages:
        lines.append(
            f"pages with no text layer: {result.scanned_pages}"
            + (f", read by OCR: {result.ocr_pages}" if result.ocr_pages else "")
        )
    if boilerplate:
        lines.append("")
        lines.append("running headers and footers removed (# = any number):")
        lines.extend(f"  - {line}" for line in sorted(boilerplate))
    if result.warnings:
        lines.append("")
        lines.append("warnings:")
        lines.extend(f"  - {w}" for w in result.warnings)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def process_batch(
    jobs: Iterable[tuple[str | os.PathLike[str], Settings]],
    progress: Callable[[int, int, Path], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> list[Result]:
    """Run several PDFs in order. Each job pairs a path with its own settings."""
    jobs = list(jobs)
    results: list[Result] = []
    for index, (path, settings) in enumerate(jobs):
        if is_cancelled and is_cancelled():
            break
        if progress:
            progress(index, len(jobs), Path(path))
        results.append(process_pdf(path, settings, is_cancelled=is_cancelled))
    return results
