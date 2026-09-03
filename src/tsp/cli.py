"""Command-line front end for TSP.

    tsp report.pdf deck.pdf --threshold 20 --dpi 200
    tsp *.pdf --text-only --out ./extracted

Copyright (C) 2026 Daga D.
Licensed under the GNU General Public License v3.0 or later. See LICENSE.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from .core import (
    SUPPORTED_SUFFIXES,
    Settings,
    inspect_document,
    process_document,
    tesseract_available,
)

BANNER = "TSP - Token Saving Protocol"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tsp",
        description="Turn documents into token-efficient markdown.",
    )
    parser.add_argument(
        "files",
        nargs="*",
        type=Path,
        metavar="FILE",
        help="PDFs, images, Word or OpenDocument files, or plain text",
    )
    parser.add_argument(
        "-t",
        "--threshold",
        type=float,
        default=5.0,
        metavar="PCT",
        help="render a page as PNG when raster images cover at least this "
        "percentage of it (default: 5)",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=144,
        help="resolution for rendered pages (default: 144)",
    )
    parser.add_argument(
        "--text-only",
        action="store_true",
        help="never render page images",
    )
    parser.add_argument(
        "-o",
        "--out",
        type=Path,
        default=None,
        metavar="DIR",
        help="write output folders here instead of beside each PDF",
    )
    parser.add_argument(
        "-a",
        "--auto",
        action="store_true",
        help="look at each file and choose the threshold, and whether to keep "
        "tables, from what is in it",
    )
    parser.add_argument(
        "--html",
        action="store_true",
        help="also write a self-contained HTML copy for reading, with the page "
        "images inside it. Costs about 6%% more tokens than the markdown",
    )
    parser.add_argument(
        "--tables",
        action="store_true",
        help="keep table structure as markdown grids. Costs about four times "
        "the processing time and roughly the same tokens",
    )
    parser.add_argument(
        "--figures",
        action="store_true",
        help="render charts drawn in vector paths as images and drop the orphan "
        "axis labels they leave in the text",
    )
    parser.add_argument(
        "--ocr",
        action="store_true",
        help="read pages that hold an image and no text layer. Needs Tesseract "
        "installed separately",
    )
    parser.add_argument(
        "--ocr-lang",
        default="eng",
        metavar="LANG",
        help="Tesseract language code, or several joined by + (default: eng)",
    )
    parser.add_argument(
        "--keep-headers",
        action="store_true",
        help="keep running headers, footers and page numbers",
    )
    parser.add_argument(
        "--raw-punctuation",
        action="store_true",
        help="keep curly quotes, en dashes and ligatures as they appear",
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="errors only")
    parser.add_argument(
        "--formats",
        action="store_true",
        help="list the file types TSP will read, then exit",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.formats:
        print(" ".join(sorted(SUPPORTED_SUFFIXES)))
        return 0

    if args.ocr and not tesseract_available():
        print(
            "OCR needs Tesseract 5 and its language data. Install it, or run "
            "OCRmyPDF over the file first: https://ocrmypdf.readthedocs.io",
            file=sys.stderr,
        )
        return 2

    settings = Settings(
        image_threshold=1.01 if args.text_only else args.threshold / 100.0,
        render_zoom=max(0.25, args.dpi / 72.0),
        render_visual_pages=not args.text_only,
        strip_repeated_lines=not args.keep_headers,
        drop_page_numbers=not args.keep_headers,
        normalise_punctuation=not args.raw_punctuation,
        extract_tables=args.tables,
        chart_regions=args.figures,
        output_format="html" if args.html else "md",
        ocr=args.ocr,
        ocr_language=args.ocr_lang,
        output_dir=args.out,
    )

    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)

    failures = 0
    tokens_in = tokens_out = 0
    scans_unread = 0

    for pdf in args.files:
        if not args.quiet:
            print(f"-> {pdf.name}", flush=True)

        job = settings
        if args.auto:
            advice = inspect_document(pdf)
            job = replace(
                settings,
                image_threshold=advice.threshold,
                render_visual_pages=advice.threshold <= 1.0,
                extract_tables=settings.extract_tables or advice.tables,
                ocr=settings.ocr or (advice.ocr and tesseract_available()),
            )
            if not args.quiet:
                print(f"   chose {advice.mode.lower()}")
                for reason in advice.reasons:
                    print(f"     {reason}")
        result = process_document(pdf, job)
        tokens_in += result.tokens_in
        tokens_out += result.tokens_out

        if result.ok:
            if result.needs_ocr:
                scans_unread += result.scanned_pages
            if not args.quiet:
                extra = f", {result.tables_found} tables" if result.tables_found else ""
                if result.ocr_pages:
                    extra += f", {result.ocr_pages} by OCR"
                print(
                    f"   {result.message} ({result.saving:.0%} lighter)"
                    f" -> {result.text_path}"
                )
            for warning in result.warnings:
                print(f"   warning: {warning}", file=sys.stderr)
        else:
            failures += 1
            print(f"   failed: {result.message}", file=sys.stderr)

    if not args.quiet and len(args.files) > 1:
        saved = tokens_in - tokens_out
        print(f"\ntotal: ~{tokens_out:,} tokens, ~{saved:,} removed")

    if scans_unread and not args.ocr:
        print(
            f"\n{scans_unread} pages hold an image and no text layer. "
            f"Add --ocr to read them"
            + ("." if tesseract_available() else ", after installing Tesseract."),
            file=sys.stderr,
        )

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
