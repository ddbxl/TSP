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

def tsp_drop(name):
    """Forget one document's output."""
    import shutil
    shutil.rmtree(tsp_target(name), ignore_errors=True)

def tsp_process(name, threshold_pct, dpi, tables, report):
    """Process one PDF. 'report' is a JS callback taking (page, pages).

    Clears this document's previous output first, so running it again at a
    different threshold cannot leave stale page images behind.
    """
    tsp_drop(name)
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
    )
    return json.dumps({
        "ok": result.ok,
        "message": result.message,
        "pages": result.pages,
        "images": result.images_saved,
        "tables": result.tables_found,
        "scanned": result.scanned_pages,
        "needs_ocr": result.needs_ocr,
        "tokens_in": result.tokens_in,
        "tokens_out": result.tokens_out,
        "saving": round(result.saving, 4),
        "warnings": result.warnings[:5],
    })

def tsp_zip():
    root = WORK / "out"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(root).as_posix())
    return buffer.getvalue()

def tsp_text():
    """Every document's text, joined. Manifests are left out."""
    root = WORK / "out"
    parts = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        for txt in sorted(folder.glob("*.txt")):
            if txt.name != "MANIFEST.txt":
                parts.append(txt.read_text(encoding="utf-8"))
    return "\n\n".join(parts)

def tsp_files():
    root = WORK / "out"
    return json.dumps([
        p.relative_to(root).as_posix() for p in sorted(root.rglob("*")) if p.is_file()
    ])

def tsp_read(relative):
    return (WORK / "out" / relative).read_bytes()

def tsp_clear():
    import shutil
    for folder in ("in", "out"):
        target = WORK / folder
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)
