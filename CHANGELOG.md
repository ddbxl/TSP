# Changelog

Versions follow [Semantic Versioning](https://semver.org).

## 0.4.1

### Fixed

- The browser built its list of readable suffixes into a regular expression,
  escaping dots but not backslashes. The list is hardcoded and holds neither, so
  nothing was exploitable, but the suffix is compared against a set now and no
  pattern is built at all. Flagged by CodeQL as `js/incomplete-sanitization`.

## 0.4.0

### Added

- A release workflow. Changing the version in `pyproject.toml` on `main` builds
  the archives, tags the commit and publishes a release with that version's
  changelog section as its notes. It refuses to publish when the version
  disagrees between `pyproject.toml`, the package and the changelog, when the tag
  exists already, or when the tests fail.

- Word and OpenDocument files, read from their XML by the standard library, so
  it works in the browser too. Headings, paragraphs, lists and tables come
  through as markdown, and because both formats state their structure there is
  nothing to detect: a table is exact and a running header never reaches the
  body.
- Images: `.png`, `.jpg`, `.tiff`, `.bmp` and `.gif` open as a one-page document
  with no text layer, which is the shape the scanned-page check already looks
  for, so OCR reads them.
- `.epub`, `.mobi`, `.fb2`, `.xps`, `.cbz` and `.svg`, which the same reader
  opens, and `.txt` and `.md`, which pass through the cleaner.
- `tsp --formats` lists what will be read. The file pickers accept all of it, and
  a test fails if the page turns away something the engine could have handled.

- One control for every document, in the browser and in the window: a row above
  the list sets the mode, Tables and Figures for the whole queue. It reads Mixed
  where the rows differ, and re-queues anything already finished.

- Figures, off by default. Charts drawn in vector paths are rendered as images
  and the orphan axis labels they leave in the text are dropped. Drawings are
  grouped into the areas of a page they cover, each area grows to take in the
  labels around it, and captions and sentences inside it are kept. On a
  118-page Commission report: 77 charts rendered, orphan number lines down from
  251 to 115, tokens from 100,444 to 93,336, every caption still present.

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
- OCR in the browser, through Tesseract compiled to WebAssembly. A scanned page
  brings up a language picker and a button; the engine and one language model,
  about 7 MB, arrive on demand and stay cached. Page images are never uploaded.
- The engine accepts text recognised outside it, page by page, so an OCR engine
  in another language or another runtime can fill in a scanned page without the
  engine knowing where the words came from. Those words get the same cleaning as
  a text layer.
- Finished files stay in the queue. Change a mode, a Tables box or the image
  quality and that file queues again; with nothing queued the button reads
  Process again. The browser keeps hold of the files, so nothing is re-picked.
- A failure panel that leads with a plain sentence, guesses the cause, keeps the
  trace collapsed and offers a prefilled issue on the repository.
- Copy text and Download text in the browser, so the common case needs neither
  a zip nor unpacking. The zip stays for page images and batches.
- Per-document actions on each finished row: copy its text, download its text,
  and download its own files as a zip when it produced page images.
- The batch actions sit directly under the documents rather than below the token
  meter, and read "all" so they cannot be mistaken for the buttons on the rows
  above.
- Downloads are named after the source with a marker in front,
  `optimised_<source>.txt` and `optimised_<source>.zip`, so an optimised copy
  sorts beside its original.
- The folder picker opens in Documents and remembers where it was last used.

### Changed

- Output is markdown, `<name>.md` rather than `<name>.txt`, so tables render
  wherever the file is opened. The markup stays minimal: nothing is invented
  where a PDF cannot say what it meant.
- The browser engine loads as the page opens instead of waiting for a button.
  It runs on a worker thread, so the download costs the interface nothing. A
  connection the browser reports as metered or very slow still waits, and
  choosing a file starts it either way.

- Every GitHub action moved to its current major: checkout v7, setup-python v7,
  upload-pages-artifact v5, deploy-pages v5. All of them declare Node 24, which
  clears the Node 20 deprecation warning the older ones raised on each run.
- Continuous integration runs the message-protocol check on Node 24, so a
  request the page cannot settle fails the build rather than reaching the site.

### Fixed

- Word headings were missed whenever the author wrote in another language. The
  style identifier was matched against the word "heading", so a Slovenian
  document's `Naslov1` and `Naslov2` came through as plain paragraphs: 1 heading
  found where 24 were present. Levels are read from the style definitions now,
  which name themselves in English whatever the author's language.
- A Word table holding whole sections was read as data, which turned a chapter
  into a single 58,979-character row. Commission templates use one-cell tables as
  layout frames, so a table whose cells run past 300 characters is walked into
  instead. On a partnership agreement that took the longest line from 58,979
  characters to 5,269, the rest being the document's own paragraphs.
- A Word table of contents is dropped, since its page numbers point at a
  pagination that no longer exists.
- Two files sharing a stem, `report.docx` and `report.odt` say, wrote over each
  other's output. The suffix joins the folder name only when that would happen.

- The test workflow declared no permissions, so its token inherited the
  repository default, which on repositories created before February 2023 is read
  and write. Both workflows are read-only now, with write access to Pages scoped
  to the job that deploys. Flagged by CodeQL as
  `actions/missing-workflow-permissions`.

- Reading the scanned pages reprocessed the whole document. Three scanned pages
  in a 120-page report cost a full 4.2 s re-extraction of the other 117. The
  recognised text is folded into the finished markdown instead, which takes 9 ms.
  A run leaves notes beside its output, holding the running headers it found and
  each page's length, so the OCR step never opens the PDF again.
- The engine exposes `prepare_page_text`, so text recognised outside it gets the
  same cleaning without duplicating the logic.

- Bordered callout boxes and chart labelling came through as tables, filling the
  output with grids of prose and empty columns. Each detected grid is now judged
  on how consistently its columns are filled and how much text its cells hold.
  On a 118-page Commission report that took 30 detected grids down to 7 kept, and
  pipe-table lines from 387 to 90. `MANIFEST.txt` records the count turned down.
- Line breaks inside a cell arrived as `<br>` tags, which cost tokens and read no
  better than a space.
- OCR in the browser failed with the WebAssembly core pinned to
  `tesseract.js-core` 6.1.2 while `tesseract.js` 7.0.0 requires 7.x. The version
  came from npm's latest tag, which lags behind what the wrapper depends on. Both
  the worker and the core path are left to the library now, since it derives them
  from its own version and cannot disagree with itself.
- A failure reported "no detail captured" and nothing else. tesseract.js rejects
  with plain strings rather than Error objects, so reading `.message` off the
  rejection gave undefined. Every failure path normalises what it caught, an
  error handler is passed to the OCR engine so library errors are reachable
  rather than thrown inside a message callback, and a failed start names the URLs
  it used.
- OCR in the browser failed with "createWorker is not a function". The
  tesseract.js ESM build carries a single default export and no named ones, so
  a named import gave undefined.
- Table detection ran on every page, including the ones holding nothing but
  prose, at about 24 ms each. TSP now counts the lines and rectangles on a page
  and skips detection below four, which takes a 120-page report with ten tables
  from 5.0 s to 1.5 s and finds the same ten. One call for a page's drawings now
  serves both the table filter and the chart check.

- A markdown grid touching prose or a page marker was read as a paragraph of
  pipes rather than a table, which hit every table opening a page or sitting
  under a caption. Grids are padded with a blank line on each side and page
  markers stand alone. A test runs the output through a markdown parser and
  counts the header cells.
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
