"""TSP core engine: turn PDFs into token-efficient text plus page images.

This module holds no user-interface code. Import it from a GUI, a CLI, a
notebook or a WebAssembly runtime.

Copyright (C) 2026 TSP contributors
Licensed under the GNU General Public License v3.0 or later. See LICENSE.
"""

from __future__ import annotations

import os
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Sequence

try:  # PyMuPDF >= 1.24.3 prefers the `pymupdf` name; `fitz` is the legacy alias.
    import pymupdf
except ImportError:  # pragma: no cover
    import fitz as pymupdf

__all__ = [
    "Settings",
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


def _is_vector_heavy(page, char_count: int, settings: Settings) -> bool:
    """Catch charts drawn as vector paths, which carry no raster image and
    little text."""
    if char_count > settings.vector_max_chars:
        return False
    try:
        paths = page.get_cdrawings()
    except Exception:
        return False
    return len(paths) >= settings.vector_min_paths


# --------------------------------------------------------------------------
# Main entry point
# --------------------------------------------------------------------------

ProgressCb = Callable[[int, int], None]


def process_pdf(
    pdf_path: str | os.PathLike[str],
    settings: Settings | None = None,
    progress: ProgressCb | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> Result:
    """Extract one PDF into `<name>_TSP/<name>.txt` plus page images.

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
    target = out_dir / f"{source.stem}_TSP"

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
        result.text_path = target / f"{source.stem}.txt"
        width = max(3, len(str(page_count)))
        flags = pymupdf.TEXTFLAGS_TEXT
        if settings.dehyphenate:
            flags |= pymupdf.TEXT_DEHYPHENATE

        # Pass 1: extract, clean and classify. Cleaning happens before
        # detection so the header keys match the text they are stripped from.
        clean_pages: list[str] = []
        visual_flags: list[bool] = []
        for index in range(page_count):
            if is_cancelled and is_cancelled():
                result.ok = False
                result.message = "Cancelled."
                return result
            if progress:
                progress(index, page_count)

            try:
                page = doc.load_page(index)
                raw = page.get_text("text", flags=flags, sort=True)
            except Exception as exc:  # isolate the page, keep the document
                result.warnings.append(f"page {index + 1}: {exc}")
                visual_flags.append(False)
                clean_pages.append("")
                continue

            result.chars_in += len(raw)
            clean_pages.append(clean_text(raw, settings))

            visual = False
            if settings.render_visual_pages and settings.image_threshold <= 1.0:
                coverage = _raster_coverage(page, settings)
                visual = coverage >= settings.image_threshold
                if not visual:
                    visual = _is_vector_heavy(page, len(raw.strip()), settings)
            visual_flags.append(visual)

        boilerplate = _boilerplate_lines(clean_pages, settings)

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

            marker = f"--- p.{index + 1}"
            if image_name:
                marker += f" | see {image_name}"
            if not text:
                marker += " | no text"
            marker += " ---"

            chunks.append(marker)
            if text:
                chunks.append(text)
            result.page_stats.append(
                PageStat(
                    number=index + 1,
                    chars=len(text),
                    visual=visual,
                    blank=not text,
                    image_name=image_name,
                )
            )

        body = "\n".join(chunks).rstrip() + "\n"
        result.chars_out = sum(s.chars for s in result.page_stats)
        result.pages = page_count

        result.text_path.write_text(body, encoding="utf-8")
        if settings.write_manifest:
            _write_manifest(target / "MANIFEST.txt", result, settings, boilerplate)

        result.message = (
            f"{page_count} pages, {result.images_saved} images, "
            f"~{result.tokens_out:,} tokens"
        )
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
