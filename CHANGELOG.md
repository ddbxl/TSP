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
- Finished files stay in the queue. Change a mode, a Tables box or the image
  quality and that file queues again; with nothing queued the button reads
  Process again. The browser keeps hold of the files, so nothing is re-picked.
- A failure panel that leads with a plain sentence, guesses the cause, keeps the
  trace collapsed and offers a prefilled issue on the repository.
- Copy text and Download text in the browser, so the common case needs neither
  a zip nor unpacking. The zip stays for page images and batches.
- The folder picker opens in Documents and remembers where it was last used.

### Fixed

- The browser hung after processing, with no download offered. The page matched
  replies to requests by name and had no entry for two of them, so a request
  waited for ever and everything after it stalled. Requests now carry an id the
  worker echoes, a failed request rejects rather than hanging, a stopped worker
  rejects whatever was outstanding, and `web/protocol_check.mjs` drives every
  request through the real worker to prove each one settles.
- The download depended on the text step succeeding. The zip is offered first,
  so a failure preparing the text no longer hides it.
- The browser engine would not start. The bridge Python sat inside a JavaScript
  template literal, which rewrote `\n` into a real newline and broke a string
  literal. The bridge is now `web/bridge.py`, a real file the worker fetches, so
  nothing rewrites it on the way in. Three checks guard the class of bug: the
  file must parse, no Python may hide in a template literal, and the workflow
  compiles both Python files before deploying.
- Reprocessing a document left the previous run's page images behind, in the
  browser and on disk. Both clear what the last run wrote, and on disk only
  files TSP itself creates are removed.
- The token meter added each run to the last, so processing one file twice
  counted it twice. Totals are derived from the queue now.
- Removing a processed file from the browser queue left its output in the zip.
- The results panel appeared before anything had been processed. Its
  `display: flex` rule outweighed the `hidden` attribute.
- Saving to a folder failed silently when Chrome refused the folder. Chrome
  reports a refused folder identically to a cancelled dialogue, so the page now
  explains the likely cause instead of saying nothing.
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
