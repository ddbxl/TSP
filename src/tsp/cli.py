"""Command-line front end for TSP.

    tsp report.pdf deck.pdf --threshold 20 --dpi 200
    tsp *.pdf --text-only --out ./extracted

Copyright (C) 2026 Daga D.
Licensed under the GNU General Public License v3.0 or later. See LICENSE.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .core import Settings, process_pdf, tesseract_available

BANNER = "TSP - Token Saving Protocol"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tsp",
        description="Extract PDFs into token-efficient text plus page images.",
    )
    parser.add_argument("pdfs", nargs="+", type=Path, help="one or more PDF files")
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
        "--tables",
        action="store_true",
        help="keep table structure as markdown grids. Costs about four times "
        "the processing time and roughly the same tokens",
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

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
        ocr=args.ocr,
        ocr_language=args.ocr_lang,
        output_dir=args.out,
    )

    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)

    failures = 0
    tokens_in = tokens_out = 0
    scans_unread = 0

    for pdf in args.pdfs:
        if not args.quiet:
            print(f"-> {pdf.name}", flush=True)
        result = process_pdf(pdf, settings)
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
                    f"   {result.pages} pages, {result.images_saved} images"
                    f"{extra}, ~{result.tokens_out:,} tokens "
                    f"({result.saving:.0%} lighter) -> {result.text_path}"
                )
            for warning in result.warnings:
                print(f"   warning: {warning}", file=sys.stderr)
        else:
            failures += 1
            print(f"   failed: {result.message}", file=sys.stderr)

    if not args.quiet and len(args.pdfs) > 1:
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
