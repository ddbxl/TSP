# Changelog

Versions follow [Semantic Versioning](https://semver.org).

## 0.2.0

### Added

- Scanned-page detection. A page holding an image and no text layer is counted
  and reported, in the summary, the manifest and the interface.
- OCR for those pages through PyMuPDF's Tesseract bridge, about 1.4 seconds a
  page. `--ocr` on the command line, a toggle in the window, and disabled when
  Tesseract is absent. The browser recommends OCRmyPDF instead.
- Table extraction as markdown grids, off by default. `--tables` or a per-file
  checkbox. Blocks inside a table are replaced by the grid, so contents appear
  once.
- A Web Worker owns the Python runtime in the browser, so the page keeps
  repainting, progress arrives per page, and Cancel works.
- A progress bar and a Cancel button in the browser build.

### Fixed

- The results panel appeared before anything had been processed. Its
  `display: flex` rule outweighed the `hidden` attribute.
- The Pages workflow copied web files by name and would have shipped a site
  without `worker.js`. It now copies the file and fails the build if any web
  file is missing from the artifact.

## 0.1.0

First release.

- Text extraction with running headers, footers and standalone page numbers
  removed, words rejoined across hyphenated line breaks, and curly quotes,
  dashes, ligatures and non-breaking spaces mapped to ASCII.
- Page images for pages whose raster coverage or vector path count puts their
  meaning in graphics rather than words.
- `MANIFEST.txt` per output folder recording pages, images, the lines removed
  and the token estimate before and after.
- Desktop window, with work on a background thread and a Cancel button.
- Command line interface with `--threshold`, `--dpi`, `--text-only`, `--out`,
  `--keep-headers` and `--raw-punctuation`.
- Browser build for GitHub Pages, running the same engine under Pyodide.
- PyInstaller spec for one-folder Windows builds.
