# TSP, Token Saving Protocol

Feed TSP a PDF and get back compact text, plus images of the pages that carry
their meaning in charts rather than words. Your files stay on your machine.

A 90-page report repeats its header on 90 pages, its footer on 90 pages, and
sets its quotation marks in curly glyphs that cost two tokens each. You pay for
all of it when you paste that report into an LLM. TSP strips the repetition,
rejoins words broken across line breaks, and prints the before and after count
so you can see what came off.

![The TSP icon](assets/icon.png)

## Install

```bash
git clone https://github.com/ddbxl/tsp.git
cd tsp
pip install -e .
```

Python 3.10 or later. The one dependency is [PyMuPDF](https://pymupdf.readthedocs.io).

## Use it

Open the window:

```bash
tsp-gui
```

Add PDFs, set a mode per file, press Process. The window stays responsive while
work happens on a background thread, and Cancel stops at the next page.

Or stay on the command line:

```bash
tsp report.pdf                      # 5% threshold, 144 dpi
tsp *.pdf --threshold 20 --dpi 200
tsp deck.pdf --text-only -o ./extracted
tsp report.pdf --keep-headers       # leave running headers alone
```

`tsp --help` lists the rest.

## Modes

The threshold sets how much of a page raster images must cover before TSP saves
that page as a PNG alongside its text.

| Mode | Threshold | Suits |
|---|---|---|
| Text documents | 5% | Reports, legislation, studies |
| Mixed reports | 20% | Prose with figures dropped between sections |
| Slide decks | 50% | Presentations where the slide *is* the graphic |
| Text only | 100% | Skip images and take the text |

Two cases the threshold alone misses, both handled: a corner logo repeating on
every page stays under a floor of 0.4% and triggers nothing, while a chart drawn
in vector paths holds no raster image at all and gets caught by a path count
instead.

## What comes out

```
report.pdf
report_TSP/
├── report.txt        text, page markers as --- p.4 ---
├── MANIFEST.txt      what got removed, and the token estimate
└── p007.png          only for pages above the threshold
```

`MANIFEST.txt` lists the headers and footers TSP dropped, so you can check its
judgement rather than trust it.

## Where the savings come from

- Running headers and footers, matched across pages even when a page number
  sits inside the line. `Page 4 of 90` and `Page 5 of 90` count as one header.
- Standalone page numbers.
- Words split by hyphens at line ends. `concen-\ntrate` becomes `concentrate`.
- Curly quotes, en dashes, ligatures and non-breaking spaces, mapped to ASCII.
  A curly apostrophe costs more than a straight one.
- Runs of spaces and blank lines.
- The explanation of image pages, written once at the top of the file instead of
  above each image page.

Measured on a synthetic 7-page report with a header and footer: 4,050 characters
down to 3,540, about 1,012 estimated tokens down to 885. Documents with heavier
furniture give up more.

## In the browser

The same `core.py` runs on GitHub Pages through Pyodide and a WebAssembly build
of PyMuPDF. No server sees your PDFs.

```bash
python web/serve.py
```

That stages the engine, serves `web/` and opens the page. First load pulls about
28 MB, which the browser then caches. A 100-page report takes about 2.3 seconds
in the browser against 1.0 second on the desktop.

[docs/BROWSER.md](docs/BROWSER.md) covers the version pinning rule, browser
support, measured timings and the test results.

Live at <https://ddbxl.github.io/tsp/>.

Push to `main` and `.github/workflows/pages.yml` assembles the site, copies
`src/tsp/core.py` in as the engine, and deploys. Every path in `index.html` and
`app.js` is relative, so the build works from the `/tsp/` subpath without
further configuration.

## Build a Windows executable

```bash
pip install pyinstaller
pyinstaller packaging/tsp.spec
```

`dist/TSP/` holds the result, about 40 MB. The spec excludes numpy, pandas and
lxml, which PyMuPDF imports when present and TSP does not use.

## Limits

- No OCR. A scanned PDF without a text layer gives you page images and empty
  text. Run [OCRmyPDF](https://ocrmypdf.readthedocs.io) over it first.
- Token figures estimate at four characters per token. Compare with them, do
  not bill from them.
- Tables lose their column structure. TSP extracts text in reading order.
- The browser build works on the main thread, so a long PDF freezes the
  tab. 100 pages takes about 2.3 seconds.

## Develop

```bash
pip install -e ".[dev]"
pytest -q          # 20 tests, fixture builds its own PDF
python packaging/make_icon.py
```

`src/tsp/core.py` imports nothing from tkinter, so you can call the engine from
a notebook, a script or WebAssembly. The GUI and the CLI both sit on top of it.

## Licence

GNU General Public License v3.0 or later. See [LICENSE](LICENSE).

PyMuPDF ships under the AGPL v3, or an Artifex commercial licence. That affects
what you owe people you hand a build to. [NOTICE](NOTICE) sets out the details.
