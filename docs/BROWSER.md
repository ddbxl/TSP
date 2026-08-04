# Running TSP in a browser on GitHub Pages

How the browser build works, what it costs to load, and what the test run
covered. Current as of August 2026, against PyMuPDF 1.28.0 and Pyodide 0.29.4.

## The short version

It works, and the browser runs the same `src/tsp/core.py` as the desktop app.
Pyodide provides CPython compiled to WebAssembly, PyMuPDF now publishes a
WebAssembly wheel to PyPI, and `web/app.js` fetches the engine from the
deployment rather than reimplementing it. GitHub Pages serves the three static
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

To pin the wheel instead, drop the `.whl` into `web/` and pass the relative
path to `loadPackage`. Same-origin hosting sidesteps CORS and removes the PyPI
dependency, at the cost of 18 MB in the repository and on Pages bandwidth.

## What the visitor downloads

| Item | Size | From |
|---|---|---|
| Pyodide runtime and stdlib | about 10 MB | jsDelivr |
| PyMuPDF wheel | 18.4 MB | PyPI through micropip |
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
build at deploy time rather than at a visitor's first click.

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

One item stays open. `micropip.install("pymupdf")` reaches jsDelivr, which the
test environment blocks, so that route is untested. The app tries micropip
first and falls back to resolving the wheel URL from PyPI and calling
`loadPackage` on it, which the table above covers. Both routes fetch the same
file.

## Speed

A 100-page report, 7.6 MB, with a full-page figure every tenth page:

| Step | Time |
|---|---|
| Writing the PDF into the virtual filesystem | 52 ms |
| Processing, images rendered at 144 dpi | 2.3 s |
| Processing, text only | 1.3 s |
| The same file under native CPython | 1.0 s |
| Building the output zip, 88 KB | 17 ms |

WebAssembly costs a factor of two against native, a mild penalty for a tool
that spends its time inside MuPDF rather than in Python. The tab stops
repainting for those 2.3 seconds. A 500-page document holds it for about 11
seconds, which is where a Web Worker stops being optional.

## Open on real browsers

1. `micropip.install("pymupdf")` under Pyodide 0.29.4, untested because the
   test environment blocks jsDelivr.
2. A large document. MEMFS held a 7.6 MB PDF, its text and ten pixmaps without
   trouble. A 200 MB scan at 300 dpi may exhaust the tab.
3. The zip download on Safari, where Blob handling differs.

## Known gaps

**Processing blocks the tab.** Python runs on the main thread, so the page
cannot repaint while a page renders. A batch yields between files and no
further. Measured at 2.3 seconds for 100 pages, so a typical report gets away
with it and a 500-page one does not. Moving Pyodide into a Web Worker fixes it
and costs a message-passing layer: the worker owns the interpreter, the page
posts file bytes in and receives progress and output bytes back.

**No cancel button.** Cancellation needs the worker above, since the main
thread cannot interrupt a running Python call.

**Token estimates only.** Four characters per token, the same heuristic as the
desktop build. Nobody ships a WebAssembly tokeniser small enough to justify
the download here.

## The AGPL question

PyMuPDF carries the AGPL v3, or an Artifex commercial licence. Section 13
reaches users who interact with a modified version of the program over a
network. The Pages build runs PyMuPDF in the visitor's own browser, so the
visitor operates their own copy rather than talking to yours, which is a
weaker case than server-side hosting. Publishing the corresponding source at
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
