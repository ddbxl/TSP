"""Bridge between the browser and the TSP engine.

Real Python, fetched by web/worker.js and run inside Pyodide. It lived inside a
JavaScript template literal until an escape sequence there was rewritten before
Python could see it, so it has a file of its own now.

Copyright (C) 2026 Daga D.
Licensed under the GNU General Public License v3.0 or later.
"""

import io, json, zipfile
from pathlib import Path
from tsp.core import (
    Settings,
    estimate_tokens_from_chars,
    process_document,
    prepare_page_text,
    tesseract_available,
)

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

def _sidecar(name):
    return tsp_target(name) / "run.json"


def _report(result, name):
    return {
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
        "scans": [
            {"page": stat.number, "image": f"{tsp_target(name).name}/{stat.image_name}"}
            for stat in result.page_stats
            if stat.scanned and not stat.ocr and stat.image_name
        ],
    }


def tsp_apply_ocr(name, ocr_json):
    """Fold recognised text into a document already processed.

    Reprocessing the whole file to place a handful of pages meant re-extracting
    every other page for nothing, so this edits the finished markdown in place.
    """
    target = tsp_target(name)
    page = target / f"{Path(name).stem}.md"
    notes = json.loads(_sidecar(name).read_text(encoding="utf-8"))
    recognised = {int(number): text for number, text in json.loads(ocr_json).items()}

    settings = Settings()
    chars = {int(k): v for k, v in notes["chars"].items()}
    body = page.read_text(encoding="utf-8")
    lines = body.split("\n")

    read_now = 0
    for number, raw in recognised.items():
        text = prepare_page_text(raw, notes["boilerplate"], settings)
        if not text:
            continue

        marker = f"--- p.{number}"
        start = next(
            (i for i, line in enumerate(lines) if line.startswith(marker)), None
        )
        if start is None:
            continue
        end = next(
            (
                i
                for i in range(start + 1, len(lines))
                if lines[i].startswith("--- p.")
            ),
            len(lines),
        )

        rebuilt = lines[start].replace(" | no text", "")
        lines[start:end] = [rebuilt, "", text, ""]
        chars[number] = len(text)
        read_now += 1

    page.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    notes["chars"] = {str(k): v for k, v in chars.items()}
    notes["ocr_pages"] = notes.get("ocr_pages", 0) + read_now
    _sidecar(name).write_text(json.dumps(notes), encoding="utf-8")

    kept = sum(chars.values())
    still_unread = notes["scanned"] - notes["ocr_pages"]
    manifest = target / "MANIFEST.txt"
    if manifest.is_file():
        manifest.write_text(
            manifest.read_text(encoding="utf-8")
            + f"\nread by OCR in the browser: {notes['ocr_pages']} pages\n",
            encoding="utf-8",
        )

    return json.dumps({
        "ok": True,
        "message": f"{notes['pages']} pages, {read_now} read by OCR, "
                   f"~{estimate_tokens_from_chars(kept):,} tokens",
        "pages": notes["pages"],
        "images": notes["images"],
        "tables": notes["tables"],
        "scanned": notes["scanned"],
        "needs_ocr": still_unread > 0,
        "tokens_in": estimate_tokens_from_chars(notes["chars_in"]),
        "tokens_out": estimate_tokens_from_chars(kept),
        "saving": round(1 - kept / notes["chars_in"], 4) if notes["chars_in"] else 0.0,
        "warnings": [],
        "scans": [s for s in notes["scans"] if s["page"] not in recognised],
    })


def tsp_process(name, threshold_pct, dpi, tables, figures, report, ocr_json=None):
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
        chart_regions=bool(figures),
        output_dir=WORK / "out",
    )
    result = process_document(
        WORK / "in" / name,
        settings,
        progress=lambda done, total: report(done, total),
        supplied_text=supplied,
    )
    payload = _report(result, name)
    if result.ok and result.text_path:
        # Notes for a later OCR pass, so it never has to read the PDF again.
        _sidecar(name).write_text(
            json.dumps({
                "boilerplate": result.boilerplate,
                "chars": {str(st.number): st.chars for st in result.page_stats},
                "chars_in": result.chars_in,
                "pages": result.pages,
                "images": result.images_saved,
                "tables": result.tables_found,
                "scanned": result.scanned_pages,
                "ocr_pages": result.ocr_pages,
                "scans": payload["scans"],
            }),
            encoding="utf-8",
        )
    return json.dumps(payload)

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
            if relative.name == "run.json":
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
        if relative.name == "run.json":
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
