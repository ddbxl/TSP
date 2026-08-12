"""Tests for the TSP engine.

    pip install pytest pymupdf pillow
    pytest -q

The fixture builds its own PDF, so the suite needs no sample files.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

pymupdf = pytest.importorskip("pymupdf")

from tsp.core import (  # noqa: E402
    Settings,
    clean_text,
    estimate_tokens,
    process_pdf,
    tesseract_available,
)

W, H = 595.0, 842.0

BODY = (
    "The Smart Specialisation Strategy framework requires regional author-\n"
    "ities to identify a limited number of priority domains where local\n"
    "capabilities and market opportunity coincide.    Wide    gaps    here.\n"
)


def _furniture(page, number: int) -> None:
    """A running header and a footer carrying the page number."""
    page.insert_text((60, 40), "Regional Innovation Monitor - Country Report 2026", fontsize=8)
    page.insert_text((60, H - 40), f"Page {number} of 11", fontsize=8)


def _png(size: int, colour: tuple[int, int, int]) -> bytes:
    Image = pytest.importorskip("PIL.Image", reason="Pillow needed for image pages")
    image = Image.new("RGB", (size, size), colour)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture(scope="module")
def sample(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("pdfs") / "monitor.pdf"
    doc = pymupdf.open()

    # 1-6: plain text with furniture and a paragraph repeated down the page
    for number in range(1, 7):
        page = doc.new_page(width=W, height=H)
        _furniture(page, number)
        page.insert_textbox(pymupdf.Rect(60, 70, W - 60, H - 60), BODY * 3, fontsize=10)

    # 7: raster image covering most of the page
    page = doc.new_page(width=W, height=H)
    _furniture(page, 7)
    page.insert_image(pymupdf.Rect(60, 110, W - 60, 700), stream=_png(600, (40, 90, 160)))
    page.insert_text((60, 730), "Figure 1: innovation index", fontsize=9)

    # 8: a small logo only. Must stay in text mode.
    page = doc.new_page(width=W, height=H)
    _furniture(page, 8)
    page.insert_image(pymupdf.Rect(60, 55, 105, 100), stream=_png(80, (200, 30, 90)))
    page.insert_textbox(pymupdf.Rect(60, 120, W - 60, H - 60), BODY * 3, fontsize=10)

    # 9: a chart drawn in vectors, little text
    page = doc.new_page(width=W, height=H)
    _furniture(page, 9)
    for index in range(90):
        x = 60 + index * 5
        page.draw_rect(
            pymupdf.Rect(x, 400 - (index % 17) * 18, x + 4, 400),
            color=(0.1, 0.3, 0.7),
            fill=(0.2, 0.5, 0.9),
        )
    page.insert_text((60, 430), "Chart 2: vector bars", fontsize=9)

    # 10: blank apart from the furniture
    page = doc.new_page(width=W, height=H)
    _furniture(page, 10)

    # 11: entirely blank
    doc.new_page(width=W, height=H)

    doc.save(path)
    doc.close()
    return path


# -- text cleaning -------------------------------------------------------


def test_punctuation_normalised():
    dirty = "\u201cS3\u201d \u2014 the \u2018frontier\u2019 regions\u2026 \ufb01ne\u00a0print"
    assert clean_text(dirty, Settings()) == '"S3" - the \'frontier\' regions... fine print'


def test_dehyphenation_joins_words():
    assert "concentrate" in clean_text("concen-\ntrate resources", Settings())


def test_dehyphenation_leaves_real_hyphens():
    out = clean_text("macro-region\nand co-operation", Settings())
    assert "macro-region" in out and "co-operation" in out


def test_whitespace_collapsed():
    out = clean_text("a    b\n\n\n\n\nc   \n", Settings())
    assert out == "a b\n\nc"


def test_raw_punctuation_setting_preserves_glyphs():
    out = clean_text("\u201cquoted\u201d", Settings(normalise_punctuation=False))
    assert "\u201c" in out


def test_token_estimate_scales():
    assert estimate_tokens("x" * 400) == 100


# -- document processing -------------------------------------------------


def test_processes_and_writes_output(sample: Path):
    result = process_pdf(sample)
    assert result.ok, result.message
    assert result.pages == 11
    assert result.text_path is not None and result.text_path.is_file()
    assert result.text_path.suffix == ".md"
    assert (result.text_path.parent / "MANIFEST.txt").is_file()


def test_running_header_and_footer_removed(sample: Path):
    text = process_pdf(sample).text_path.read_text(encoding="utf-8")
    assert "Regional Innovation Monitor" not in text
    assert "Page 4 of 11" not in text


def test_repeated_body_paragraph_survives(sample: Path):
    """The paragraph repeats on every page. Frequency alone would delete it,
    so the once-per-page condition has to keep it."""
    text = process_pdf(sample).text_path.read_text(encoding="utf-8")
    assert text.count("market opportunity coincide") >= 6


def test_image_page_detected_and_logo_ignored(sample: Path):
    result = process_pdf(sample, Settings(image_threshold=0.05))
    by_number = {stat.number: stat for stat in result.page_stats}
    assert by_number[7].visual, "a page-filling image should render"
    assert not by_number[8].visual, "a small logo should not trigger a render"


def test_vector_chart_page_detected(sample: Path):
    result = process_pdf(sample, Settings(image_threshold=0.05))
    assert result.page_stats[8].visual, "vector charts hold no raster image"


def test_text_only_mode_writes_no_images(sample: Path, tmp_path: Path):
    result = process_pdf(
        sample,
        Settings(image_threshold=1.01, render_visual_pages=False, output_dir=tmp_path),
    )
    assert result.images_saved == 0
    assert not list(result.text_path.parent.glob("*.png"))


def test_output_dir_respected(sample: Path, tmp_path: Path):
    result = process_pdf(sample, Settings(output_dir=tmp_path))
    assert tmp_path in result.text_path.parents


def test_saving_reported(sample: Path):
    result = process_pdf(sample)
    assert 0.0 < result.saving < 1.0
    assert result.tokens_out < result.tokens_in


def test_higher_threshold_renders_fewer_pages(sample: Path, tmp_path: Path):
    low = process_pdf(sample, Settings(image_threshold=0.05, output_dir=tmp_path / "a"))
    high = process_pdf(sample, Settings(image_threshold=0.95, output_dir=tmp_path / "b"))
    assert high.images_saved <= low.images_saved


def test_dpi_changes_image_size(sample: Path, tmp_path: Path):
    small = process_pdf(sample, Settings(render_zoom=1.0, output_dir=tmp_path / "s"))
    large = process_pdf(sample, Settings(render_zoom=3.0, output_dir=tmp_path / "l"))
    first_small = sorted(small.text_path.parent.glob("*.png"))[0]
    first_large = sorted(large.text_path.parent.glob("*.png"))[0]
    assert first_large.stat().st_size > first_small.stat().st_size


# -- failure paths -------------------------------------------------------


def test_missing_file_reports_cleanly(tmp_path: Path):
    result = process_pdf(tmp_path / "nope.pdf")
    assert not result.ok and "not found" in result.message.lower()


def test_not_a_pdf_reports_cleanly(tmp_path: Path):
    junk = tmp_path / "junk.pdf"
    junk.write_bytes(b"this is not a pdf")
    result = process_pdf(junk)
    assert not result.ok and result.message


def test_encrypted_pdf_reports_cleanly(tmp_path: Path, sample: Path):
    locked = tmp_path / "locked.pdf"
    doc = pymupdf.open(sample)
    doc.save(locked, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="secret")
    doc.close()
    result = process_pdf(locked)
    assert not result.ok and "password" in result.message.lower()


def test_cancellation_stops_early(sample: Path, tmp_path: Path):
    result = process_pdf(
        sample, Settings(output_dir=tmp_path), is_cancelled=lambda: True
    )
    assert not result.ok and "cancel" in result.message.lower()


# -- tables --------------------------------------------------------------


@pytest.fixture(scope="module")
def table_pdf(tmp_path_factory) -> Path:
    """A page holding a caption and a six-column indicator table."""
    path = tmp_path_factory.mktemp("pdfs") / "indicators.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=W, height=H)
    page.insert_text((60, 50), "Table 4.2  Regional innovation indicators", fontsize=10)

    cols = ["Region", "R&D", "Patents", "SMEs", "Employ.", "Index"]
    rows = [
        ("Bratislavsky kraj", "1.82", "412", "18,430", "62.1", "0.71"),
        ("Zapadne Slovensko", "0.61", "97", "24,118", "58.4", "0.42"),
        ("Stredne Slovensko", "0.54", "63", "19,802", "55.9", "0.38"),
        ("Vychodne Slovensko", "0.49", "51", "21,447", "53.2", "0.34"),
    ]
    x0, y0, cw, rh = 60, 75, 78, 26
    for column, name in enumerate(cols):
        page.draw_rect(
            pymupdf.Rect(x0 + column * cw, y0, x0 + (column + 1) * cw, y0 + rh),
            color=(0, 0, 0), width=0.6,
        )
        page.insert_text((x0 + column * cw + 4, y0 + 17), name, fontsize=7.5)
    for row, values in enumerate(rows, start=1):
        for column, cell in enumerate(values):
            page.draw_rect(
                pymupdf.Rect(
                    x0 + column * cw, y0 + row * rh,
                    x0 + (column + 1) * cw, y0 + (row + 1) * rh,
                ),
                color=(0, 0, 0), width=0.4,
            )
            page.insert_text(
                (x0 + column * cw + 4, y0 + row * rh + 17), cell, fontsize=7.5
            )
    doc.save(path)
    doc.close()
    return path


def test_tables_off_by_default(table_pdf: Path, tmp_path: Path):
    result = process_pdf(table_pdf, Settings(output_dir=tmp_path))
    assert result.tables_found == 0
    assert "|Region|" not in result.text_path.read_text(encoding="utf-8")


def test_tables_become_markdown_grids(table_pdf: Path, tmp_path: Path):
    result = process_pdf(
        table_pdf, Settings(extract_tables=True, output_dir=tmp_path)
    )
    text = result.text_path.read_text(encoding="utf-8")
    assert result.tables_found == 1
    assert "|Region|" in text
    assert "|---|" in text
    assert "|Bratislavsky kraj|1.82|412|18,430|62.1|0.71|" in text


def test_table_contents_appear_once(table_pdf: Path, tmp_path: Path):
    """Blocks inside a table are dropped in favour of the grid, so a cell must
    not appear both as loose text and inside the grid."""
    result = process_pdf(
        table_pdf, Settings(extract_tables=True, output_dir=tmp_path)
    )
    text = result.text_path.read_text(encoding="utf-8")
    assert text.count("Bratislavsky kraj") == 1


def test_caption_outside_the_table_survives(table_pdf: Path, tmp_path: Path):
    result = process_pdf(
        table_pdf, Settings(extract_tables=True, output_dir=tmp_path)
    )
    assert "Table 4.2" in result.text_path.read_text(encoding="utf-8")


def test_markdown_grids_cost_about_the_same(table_pdf: Path, tmp_path: Path):
    """Grids replace the reading-order text rather than adding to it, so the
    token count should stay within a few per cent."""
    plain = process_pdf(table_pdf, Settings(output_dir=tmp_path / "a"))
    grids = process_pdf(
        table_pdf, Settings(extract_tables=True, output_dir=tmp_path / "b")
    )
    assert grids.tokens_out < plain.tokens_out * 1.15


def test_find_tables_notice_does_not_reach_stdout(table_pdf, tmp_path, capsys):
    process_pdf(table_pdf, Settings(extract_tables=True, output_dir=tmp_path))
    assert "pymupdf_layout" not in capsys.readouterr().out


# -- scanned pages -------------------------------------------------------


@pytest.fixture(scope="module")
def scanned_pdf(sample: Path, tmp_path_factory) -> Path:
    """Pages rendered to images, so no text layer survives."""
    path = tmp_path_factory.mktemp("pdfs") / "scan.pdf"
    source = pymupdf.open(sample)
    out = pymupdf.open()
    for index in range(3):
        pix = source.load_page(index).get_pixmap(matrix=pymupdf.Matrix(2, 2))
        page = out.new_page(width=W, height=H)
        page.insert_image(pymupdf.Rect(0, 0, W, H), stream=pix.tobytes("png"))
    out.save(path)
    out.close()
    source.close()
    return path


def test_scanned_pages_detected(scanned_pdf: Path, tmp_path: Path):
    result = process_pdf(scanned_pdf, Settings(output_dir=tmp_path))
    assert result.scanned_pages == 3
    assert result.needs_ocr
    assert any("no text layer" in w for w in result.warnings)


def test_normal_pages_are_not_flagged_as_scans(sample: Path, tmp_path: Path):
    result = process_pdf(sample, Settings(output_dir=tmp_path))
    assert result.scanned_pages == 0
    assert not result.needs_ocr


def test_ocr_reads_a_scan_when_tesseract_is_present(
    scanned_pdf: Path, tmp_path: Path
):
    if not tesseract_available():
        pytest.skip("Tesseract not installed")
    result = process_pdf(scanned_pdf, Settings(ocr=True, output_dir=tmp_path))
    assert result.ocr_pages == 3
    assert not result.needs_ocr
    assert "Smart Specialisation" in result.text_path.read_text(encoding="utf-8")


def test_ocr_request_without_tesseract_warns_and_continues(
    scanned_pdf: Path, tmp_path: Path, monkeypatch
):
    monkeypatch.setattr("tsp.core.tesseract_available", lambda: False)
    result = process_pdf(scanned_pdf, Settings(ocr=True, output_dir=tmp_path))
    assert result.ok
    assert result.ocr_pages == 0
    assert any("Tesseract was not found" in w for w in result.warnings)


# -- reprocessing --------------------------------------------------------


def test_rerun_at_a_higher_threshold_clears_old_images(sample: Path, tmp_path: Path):
    """Rendering fewer pages the second time must not leave the first run's
    images behind."""
    first = process_pdf(sample, Settings(image_threshold=0.05, output_dir=tmp_path))
    assert first.images_saved > 0
    folder = first.text_path.parent

    second = process_pdf(
        sample,
        Settings(image_threshold=1.01, render_visual_pages=False, output_dir=tmp_path),
    )
    assert second.images_saved == 0
    assert list(folder.glob("*.png")) == []


def test_clearing_leaves_unrelated_files_alone(sample: Path, tmp_path: Path):
    result = process_pdf(sample, Settings(output_dir=tmp_path))
    bystander = result.text_path.parent / "notes.md"
    bystander.write_text("keep me", encoding="utf-8")

    process_pdf(sample, Settings(output_dir=tmp_path))
    assert bystander.read_text(encoding="utf-8") == "keep me"


def test_clean_target_can_be_switched_off(sample: Path, tmp_path: Path):
    process_pdf(sample, Settings(image_threshold=0.05, output_dir=tmp_path))
    folder = tmp_path / f"{sample.stem}_TSP"
    before = len(list(folder.glob("*.png")))
    process_pdf(
        sample,
        Settings(
            image_threshold=1.01,
            render_visual_pages=False,
            clean_target=False,
            output_dir=tmp_path,
        ),
    )
    assert len(list(folder.glob("*.png"))) == before


# -- the browser build ---------------------------------------------------


WEB = Path(__file__).resolve().parent.parent / "web"


def test_bridge_is_valid_python():
    """web/bridge.py runs inside Pyodide. It used to live in a JavaScript
    template literal, where an escape sequence was rewritten before Python saw
    it. Parsing the real file is what catches that."""
    import ast

    ast.parse((WEB / "bridge.py").read_text(encoding="utf-8"))


def test_no_python_hides_inside_a_javascript_string():
    """A template literal processes backslash escapes, so Python embedded in one
    arrives corrupted. Keep the Python in .py files."""
    import re

    for script in WEB.glob("*.js"):
        source = script.read_text(encoding="utf-8")
        for literal in re.findall(r"`([^`]*)`", source):
            looks_like_python = (
                "def " in literal and ":" in literal and "import " in literal
            )
            assert not looks_like_python, (
                f"{script.name} embeds Python in a template literal; "
                f"put it in a .py file instead"
            )


def test_bridge_only_imports_what_pyodide_provides():
    import ast

    tree = ast.parse((WEB / "bridge.py").read_text(encoding="utf-8"))
    allowed = {"io", "json", "zipfile", "shutil", "pathlib", "tsp"}
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    assert not found - allowed, f"unexpected imports: {sorted(found - allowed)}"


def test_every_request_the_page_makes_has_a_handler_in_the_worker():
    """The page hung once because it sent a request the worker answered with a
    reply nothing was listening for. Requests and cases must line up."""
    import re

    app = (WEB / "app.js").read_text(encoding="utf-8")
    worker = (WEB / "worker.js").read_text(encoding="utf-8")

    asked = set(re.findall(r'ask\("(\w+)"', app))
    handled = set(re.findall(r'case "(\w+)":', worker))
    assert asked <= handled, f"worker has no case for: {sorted(asked - handled)}"


def test_replies_are_keyed_by_request_id():
    """Matching replies to requests by name is what broke. The page must settle
    on the echoed id instead."""
    app = (WEB / "app.js").read_text(encoding="utf-8")
    worker = (WEB / "worker.js").read_text(encoding="utf-8")

    assert "message.id !== undefined" in app, "the page must settle replies by id"
    assert "function reply(id" in worker, "the worker must echo the request id"


def test_a_failed_request_rejects_rather_than_hanging():
    worker = (WEB / "worker.js").read_text(encoding="utf-8")
    app = (WEB / "app.js").read_text(encoding="utf-8")

    assert "failed: detail" in worker, "errors must come back against the id"
    assert "message.failed" in app, "the page must turn a failure into a rejection"
    assert "rejectAll" in app, "a dead worker must not leave promises waiting"


# -- markdown ------------------------------------------------------------


def test_output_is_markdown(table_pdf: Path, tmp_path: Path):
    result = process_pdf(table_pdf, Settings(output_dir=tmp_path))
    assert result.text_path.suffix == ".md"


def test_a_grid_is_padded_so_a_parser_reads_it_as_a_table(
    table_pdf: Path, tmp_path: Path
):
    """A grid touching prose or a page marker is read as a paragraph of pipes,
    so each one needs a blank line on either side."""
    result = process_pdf(
        table_pdf, Settings(extract_tables=True, output_dir=tmp_path)
    )
    lines = result.text_path.read_text(encoding="utf-8").split("\n")
    first = next(i for i, line in enumerate(lines) if line.startswith("|"))
    assert lines[first - 1].strip() == "", "a grid needs a blank line above it"


def test_page_markers_stand_alone(sample: Path, tmp_path: Path):
    """A marker followed straight away by a grid would stop the grid parsing."""
    result = process_pdf(sample, Settings(output_dir=tmp_path))
    lines = result.text_path.read_text(encoding="utf-8").split("\n")
    for index, line in enumerate(lines[:-1]):
        if line.startswith("--- p."):
            assert lines[index + 1].strip() == "", f"no blank line after {line}"


def test_tables_survive_a_real_markdown_parser(table_pdf: Path, tmp_path: Path):
    markdown = pytest.importorskip("markdown")
    result = process_pdf(
        table_pdf, Settings(extract_tables=True, output_dir=tmp_path)
    )
    html = markdown.markdown(
        result.text_path.read_text(encoding="utf-8"), extensions=["tables"]
    )
    assert "<table>" in html
    assert html.count("<th>") == 6, "every column should become a header cell"


# -- text recognised elsewhere -------------------------------------------


def test_supplied_text_fills_a_page_with_no_layer(scanned_pdf: Path, tmp_path: Path):
    """An OCR engine outside this module hands back words per page."""
    result = process_pdf(
        scanned_pdf,
        Settings(output_dir=tmp_path),
        supplied_text={1: "Recognised words for page one.", 2: "And page two."},
    )
    text = result.text_path.read_text(encoding="utf-8")
    assert result.ocr_pages == 2
    assert not result.needs_ocr
    assert "Recognised words for page one" in text


def test_supplied_text_is_cleaned_like_any_other(scanned_pdf: Path, tmp_path: Path):
    """OCR output arrives with line-broken words and curly punctuation, and gets
    the same treatment as a text layer."""
    result = process_pdf(
        scanned_pdf,
        Settings(output_dir=tmp_path),
        supplied_text={1: "regional author-\nities said \u201cyes\u201d"},
    )
    text = result.text_path.read_text(encoding="utf-8")
    assert "authorities" in text
    assert '"yes"' in text


def test_pages_left_unread_still_report_as_scanned(
    scanned_pdf: Path, tmp_path: Path
):
    result = process_pdf(
        scanned_pdf, Settings(output_dir=tmp_path), supplied_text={1: "only this one"}
    )
    assert result.scanned_pages == 3
    assert result.ocr_pages == 1
    assert result.needs_ocr is False or result.ocr_pages > 0


def test_empty_supplied_text_is_ignored(scanned_pdf: Path, tmp_path: Path):
    result = process_pdf(
        scanned_pdf, Settings(output_dir=tmp_path), supplied_text={1: "   \n  "}
    )
    assert result.ocr_pages == 0


def test_the_bridge_reports_which_pages_need_reading():
    """The browser needs the page number and the rendered image for each page
    with no text layer, or it cannot hand anything to an OCR engine."""
    source = (WEB / "bridge.py").read_text(encoding="utf-8")
    assert '"scans"' in source
    assert "stat.scanned and not stat.ocr" in source
    assert "ocr_json" in source, "the bridge must accept recognised text back"
