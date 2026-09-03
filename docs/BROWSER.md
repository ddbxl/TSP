# Running TSP in a browser on GitHub Pages

How the browser build works, what it costs to load, and what the test run
covered. Current as of August 2026, against PyMuPDF 1.28.0 and Pyodide 0.29.4.

## The short version

It works, and the browser runs the same `src/tsp/core.py` as the desktop app.
Pyodide provides CPython compiled to WebAssembly, PyMuPDF now publishes a
WebAssembly wheel to PyPI, and `web/app.js` fetches the engine from the
deployment, so nothing is reimplemented. GitHub Pages serves the three static
files. PDFs stay in the tab.

Tkinter has no WebAssembly path, so the desktop window cannot ship. The web
front end is a separate 400-line interface over a shared engine.

## Three routes, and the one this repository takes

**Pyodide plus the PyMuPDF WebAssembly wheel.** Chosen. PEP 783 standardised the
PyEmscripten platform and PyPI now accepts wheels built for it, so
`micropip.install("pymupdf")` resolves a real 18.4 MB wheel. One engine serves
both targets, and a bug fixed on the desktop reaches the browser on the next
deploy.

**A PDF.js rewrite.** Mozilla's PDF.js sits under Apache 2.0, weighs about 1 MB
against 28 MB, and extracts text through `getTextContent()`. The cost lands on
maintenance: page classification, header detection, dehyphenation and the token
meter all get written twice, in two languages, and drift apart. Image coverage
detection needs `getOperatorList()` and manual matrix arithmetic to recover
bounding boxes that PyMuPDF hands over in one call. Worth revisiting if the
28 MB download becomes the blocker.

**The `mupdf` or `@bentopdf/pymupdf-wasm` npm packages.** Both wrap MuPDF for
WebAssembly. Neither removes the AGPL obligation, and the npm route drops the
Python API that `core.py` already targets.

## Version pinning, the part that breaks

The wheel PyPI serves is
`pymupdf-1.28.0-cp313-abi3-pyemscripten_2025_0_wasm32.whl`. That platform tag
pins the pairing:

| Platform tag | Python | Pyodide |
|---|---|---|
| `pyemscripten_2025_0` | 3.13 | 0.29.x |
| `pyemscripten_2026_0` | 3.14 | 314.x |

PyMuPDF 1.28.0 publishes only the 2025 tag, so `web/app.js` pins
`PYODIDE_VERSION = "0.29.4"`, the newest 0.29 release, tested against that
wheel. Loading Pyodide 314.x leaves nothing to resolve, because no PyMuPDF wheel
carries the 2026 tag. When PyMuPDF publishes one, raise the pin, change
`WHEEL_PLATFORM` to match, and rerun the checks below.

Some PyMuPDF documentation states that `micropip.install()` cannot install it
because of its shared libraries, and prescribes `loadPackage(url)` against a
self-hosted wheel. That guidance predates PEP 783 and the
`auditwheel-emscripten` repair step, which copies shared libraries into the
wheel and patches the runtime search path. The wheel carries `_mupdf.so`,
`libmupdf.so`, `libmupdfcpp.so` and `_extra.so`, and `loadPackage` resolves all
four.

`web/app.js` keeps both routes. It calls `micropip.install("pymupdf")` first,
and on any failure it reads PyPI's JSON API, picks the file whose name carries
`WHEEL_PLATFORM`, and hands that URL to `loadPackage`. The fallback walks back
through older releases if the newest one lacks a wheel for the platform, so a
PyMuPDF release that skips WebAssembly does not take the page down. Nothing is
hardcoded to a version or a content hash.

To pin the wheel, drop the `.whl` into `web/` and pass the relative path to
`loadPackage`. Same-origin hosting sidesteps CORS and removes the PyPI
dependency, at the cost of 18 MB in the repository and on Pages bandwidth.

## Which PyMuPDF the browser gets

Pyodide ships a curated distribution of several hundred packages, and PyMuPDF
sits in it. `micropip.install("pymupdf")` resolves that lockfile before it
considers PyPI, so Pyodide 0.29.4 installs PyMuPDF 1.26.3 from the same CDN as
the runtime. PyPI's 1.28.0 is never consulted.

That pairing is the tested one, and it keeps the download on a single origin.
Every API the engine calls predates 1.26, so nothing breaks. Text extraction
output can differ in small ways from a desktop install running a later MuPDF,
which matters only when diffing browser output against desktop output on the
same file.

Forcing a version, `micropip.install("pymupdf==1.28.0")`, sends micropip to PyPI
for it. That trades a tested pairing and a warm CDN for a larger download, so
the app leaves it alone.

## What the visitor downloads

| Item | Size | From |
|---|---|---|
| Pyodide runtime and stdlib | about 10 MB | jsDelivr |
| PyMuPDF wheel | about 18 MB | the Pyodide distribution, or PyPI as a fallback |
| `index.html`, `style.css`, `app.js`, `tsp_core.py` | about 60 KB | GitHub Pages |

The browser caches the first two after the first run. Nothing large sits in the
repository, so Pages bandwidth and file size limits never come into it. The
engine loads on demand behind a Start engine button, which keeps a visitor who
only wants to read the page from pulling 28 MB.

Pyodide needs no `Cross-Origin-Opener-Policy` or `Cross-Origin-Embedder-Policy`
headers unless you enable threads. That matters because Pages cannot set custom
headers, and it rules out anything depending on `SharedArrayBuffer`.

## Getting the output back off the page

Two mechanisms, picked by feature detection.

**A zip download, everywhere.** Python's stdlib `zipfile` builds the archive
inside Pyodide, JavaScript wraps the bytes in a Blob, and the anchor downloads
it. No JSZip, no extra CDN, no extra licence.

**A folder, on Chromium.** `showDirectoryPicker({ mode: "readwrite" })` writes
the `_TSP` folder straight to disk, which matches how the desktop app behaves.

| Browser | `showDirectoryPicker` |
|---|---|
| Chrome, Edge, Opera desktop 86+ | Yes |
| Firefox, any version | No, OPFS only |
| Safari, macOS and iOS | No, OPFS only |
| Chrome and Firefox on Android | No |

Firefox and Safari get the zip. The button hides itself where the API is absent.

## Deployment

`.github/workflows/pages.yml` runs on pushes touching `web/`,
`src/tsp/core.py` or `assets/`. It copies the three web files, the icons and
`src/tsp/core.py` (as `tsp_core.py`) into `_site`, then uploads and deploys.

The build also parses `core.py` and fails if it imports a module outside a
known-portable set. Adding `import requests` to the engine breaks the browser
build at deploy time, well before a visitor's first click.

Enable Pages in repository settings with GitHub Actions as the source.

## Test results

The deployment path runs under Node against the same Pyodide build and the same
wheel resolution a browser uses:

| Check | Result |
|---|---|
| Pyodide 0.29.4 starts | yes, 2.4 s |
| PyMuPDF `pyemscripten_2025_0_wasm32` wheel loads | yes, 2.1 s, shared libraries resolve |
| Runtime reports | PyMuPDF 1.28.0, Python 3.13.2, platform emscripten |
| Unmodified `src/tsp/core.py` runs | yes |
| Output matches the desktop run | identical: 7 pages, 1 image, 885 tokens, 12.6% lighter, page 7 flagged visual |
| Header and footer removal works in WASM | yes |
| `zipfile` output crosses into JavaScript | yes, `Uint8Array` with a valid PK signature |
| PyPI JSON API resolves the wheel URL | yes |
| `loadPackage(remoteWheelUrl)` works | yes |
| CORS on the PyPI JSON API and on the wheel host | `access-control-allow-origin: *` on GET |

Both install routes work. micropip is confirmed on a deployed Pages site,
reporting `PyMuPDF 1.26.3 on Pyodide 0.29.4 via micropip`, and the PyPI fallback
is confirmed in the table above.

## Speed

A 100-page report, 7.6 MB, with a full-page figure every tenth page:

| Step | Time |
|---|---|
| Writing the PDF into the virtual filesystem | 52 ms |
| Processing, images rendered at 144 dpi | 2.3 s |
| Processing, text only | 1.3 s |
| Processing with table detection, 120 pages | 1.5 s, against 5.0 s unfiltered |
| The same file under native CPython | 1.0 s |
| Building the output zip, 88 KB | 17 ms |

WebAssembly costs a factor of two against native, a mild penalty for a tool
that spends its time inside MuPDF. The tab stops
repainting for those 2.3 seconds. A 500-page document holds it for about 11
seconds, which is where a Web Worker stops being optional.

## Field results

A deployed Pages site processed three EU study reports in one batch: 409 pages,
2.9 MB, 8.6 MB and 0.7 MB, at the 5% threshold and 144 dpi. 51 pages rendered as
images, 331,964 estimated tokens extracted, 275,685 kept, 17% trimmed. The 17%
against 7 to 13% on synthetic fixtures reflects how much furniture real
institutional reports carry on every page.

That run also covered the memory question for documents of that size. MEMFS held
an 8.6 MB PDF, its text and 29 pixmaps at once without trouble.

## Checking the protocol

The page and the worker exchange messages. A request whose reply nothing settles
leaves the interface waiting for ever, and no static check finds that, so
`web/protocol_check.mjs` drives every request through the real worker in a faked
worker environment:

```bash
npm install pyodide
node web/protocol_check.mjs any.pdf
```

It exits non-zero if a request goes unanswered. Set `TSP_WHEEL` to a wheel on
disk to skip the download. The `protocol` job in `.github/workflows/test.yml`
runs the same check on Node 24 for every push.

Requests carry an id and the worker echoes it, so adding one needs no change to
the page's message handler. Matching replies by name was how a reply once went
unhandled.

## Open on real browsers

1. A very large document. A 200 MB scan at 300 dpi may still exhaust the tab.
2. The zip download on Safari, where Blob handling differs.

## The worker

`web/worker.js` owns the Python runtime. The page posts file bytes in and
receives progress and output back, so nothing heavy touches the thread that
draws the interface.

Progress arrives per page. The engine's existing `progress` callback is handed a
JavaScript function, which posts a message the page turns into a bar. A
100-page document produced 101 monotonic progress events in testing.

Cancel terminates the worker outright. A worker running synchronous Python
cannot be interrupted politely: Pyodide's interrupt buffer needs
`SharedArrayBuffer`, which needs COOP and COEP headers, which Pages cannot set.
Terminating is immediate and certain, and booting again takes a few seconds
because the runtime is already cached. Files that were mid-flight return to the
queue.

Output crosses back as a transferable `ArrayBuffer`, so a 13 MB zip moves
without being copied.

## Known gaps

**Memory on long documents.** The runtime holds the PDF, its extracted text and
every rendered page at once. An 8.6 MB, 308-page report was fine. Mobile
browsers give up sooner than desktop ones.

**OCR is a separate download.** Tesseract is not in the Pyodide distribution, so
the page uses tesseract.js: 62 KB of JavaScript, a 2.9 MB WebAssembly core and a
language model from tessdata_fast, 1.1 MB for French up to 6.1 MB for Dutch. All
of it is fetched the first time a scanned page appears and cached afterwards, so
a run with no scans costs nothing.

The flow is two passes. The first reports which pages hold an image and no text,
along with the PNG already rendered for each. JavaScript reads those images out
of the virtual filesystem, recognises them, and hands the words back for a second
pass, where they are cleaned like any other page. Measured at about 1.1 seconds a
page at 200 dpi with 93% confidence on a clean scan.

tesseract.js runs its own worker, so recognition does not block the page either.
Nothing is uploaded: the language model is downloaded, the document is not.

**Token estimates only.** Four characters per token, the same heuristic as the
desktop build. Nobody ships a WebAssembly tokeniser small enough to justify
the download here.

## The AGPL question

PyMuPDF carries the AGPL v3, or an Artifex commercial licence. Section 13
reaches users who interact with a modified version of the program over a
network. The Pages build runs PyMuPDF in the visitor's own browser, so the
visitor operates their own copy and never talks to yours, which is a weaker case
than server-side hosting. Publishing the corresponding source at
the same origin closes the question at no cost, so the workflow copies
`LICENSE` into the site and the page footer links the source. See
[NOTICE](../NOTICE).

## References

- PyMuPDF on Pyodide: <https://pymupdf.readthedocs.io/en/latest/pyodide.html>
- PyMuPDF releases and platform tags: <https://pypi.org/project/pymupdf/>
- PEP 783 and platform tags: <https://blog.pyodide.org/posts/314-release/>
- Building PyEmscripten wheels:
  <https://pydantic.dev/articles/emscripten-wheels-pydantic>
- Loading packages in Pyodide:
  <https://pyodide.org/en/stable/usage/loading-packages.html>
- File System Access API:
  <https://developer.mozilla.org/en-US/docs/Web/API/Window/showDirectoryPicker>
