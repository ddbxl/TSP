"""Bridge between the browser and the TSP engine.

Real Python, fetched by web/worker.js and run inside Pyodide. It lived inside a
JavaScript template literal until an escape sequence there was rewritten before
Python could see it, so it has a file of its own now.

Copyright (C) 2026 Daga D.
Licensed under the GNU General Public License v3.0 or later.
"""

import io, json, zipfile
from pathlib import Path
from tsp.core import Settings, process_pdf, tesseract_available

WORK = Path("/work")

def tsp_target(name):
    return WORK / "out" / f"{Path(name).stem}_TSP"


def _folders(name=None):
    """One document's output folder, or every one of them."""
    root = WORK / "out"
    if name:
        target = tsp_target(name)
        return [target] if target.is_dir() else []
    return sorted(p for p in root.iterdir() if p.is_dir())

def tsp_drop(name):
    """Forget one document's output."""
    import shutil
    shutil.rmtree(tsp_target(name), ignore_errors=True)

def tsp_process(name, threshold_pct, dpi, tables, report, ocr_json=None):
    """Process one PDF. 'report' is a JS callback taking (page, pages).

    'ocr_json' maps a page number to text recognised elsewhere.

    Clears this document's previous output first, so running it again at a
    different threshold cannot leave stale page images behind.
    """
    tsp_drop(name)
    # Pages read by an OCR engine outside Python, keyed by page number.
    supplied = None
    if ocr_json:
        supplied = {int(page): text for page, text in json.loads(ocr_json).items()}
    settings = Settings(
        image_threshold=1.01 if threshold_pct >= 100 else threshold_pct / 100.0,
        render_zoom=max(0.25, dpi / 72.0),
        render_visual_pages=threshold_pct < 100,
        extract_tables=bool(tables),
        output_dir=WORK / "out",
    )
    result = process_pdf(
        WORK / "in" / name,
        settings,
        progress=lambda done, total: report(done, total),
        supplied_text=supplied,
    )
    return json.dumps({
        "ok": result.ok,
        "message": result.message,
        "pages": result.pages,
        "images": result.images_saved,
        "tables": result.tables_found,
        "scanned": result.scanned_pages,
        "needs_ocr": result.needs_ocr,
        # Which pages hold no text, and the image rendered for each, so an OCR
        # engine on the other side knows exactly what to read.
        "scans": [
            {"page": stat.number, "image": f"{tsp_target(name).name}/{stat.image_name}"}
            for stat in result.page_stats
            if stat.scanned and not stat.ocr and stat.image_name
        ],
        "tokens_in": result.tokens_in,
        "tokens_out": result.tokens_out,
        "saving": round(result.saving, 4),
        "warnings": result.warnings[:5],
    })

def tsp_zip(name=None):
    """A zip of everything written, or of one document's folder."""
    root = WORK / "out"
    only = tsp_target(name).name if name else None
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            if only and relative.parts[0] != only:
                continue
            archive.write(path, relative.as_posix())
    return buffer.getvalue()

def tsp_text(name=None):
    """Extracted markdown, joined. One document when named, otherwise all.

    Only the .md files, so manifests stay out of a paste.
    """
    parts = []
    for folder in _folders(name):
        for page in sorted(folder.glob("*.md")):
            parts.append(page.read_text(encoding="utf-8"))
    return "\n\n".join(parts)

def tsp_files(name=None):
    root = WORK / "out"
    only = tsp_target(name).name if name else None
    found = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if only and relative.parts[0] != only:
            continue
        found.append(relative.as_posix())
    return json.dumps(found)

def tsp_read(relative):
    return (WORK / "out" / relative).read_bytes()

def tsp_clear():
    import shutil
    for folder in ("in", "out"):
        target = WORK / folder
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)
