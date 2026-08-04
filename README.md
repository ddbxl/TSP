# TSP, Token Saving Protocol

Feed TSP a PDF and get back compact text, plus images of the pages that carry
their meaning in charts rather than words. Your files stay on your machine.

A 90-page report repeats its header on 90 pages, its footer on 90 pages, and
sets its quotation marks in curly glyphs that cost two tokens each. You pay for
all of it when you paste that report into an LLM. TSP strips the repetition,
rejoins words broken across line breaks, and prints the before and after count
so you can see what came off.

![TSP](assets/social-preview.png)

## Install

```bash
git clone https://github.com/ddbxl/TSP.git
cd TSP
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

Four ways to take the result away, in the order the page offers them:

| | Good for |
|---|---|
| **Copy text** | Pasting straight into a chat. No file, no unpacking. |
| **Download text** | One `.txt`, every document joined. Works everywhere. |
| **Save every file to a folder** | Text, manifests and page images onto disk. Chrome, Edge and Opera. |
| **Download as a zip** | The same, on browsers without folder access. |

Chrome refuses to write to certain folders, Downloads among them, and reports
that identically to a cancelled dialogue, so the page cannot tell the two apart.
It opens the picker in Documents for that reason and says so if nothing gets
saved.

Finished files stay in the queue. Change a setting on one and it queues again;
change nothing and the button offers Process again. Neither needs the file
re-picked.

[docs/BROWSER.md](docs/BROWSER.md) covers the version pinning rule, browser
support, measured timings and the test results.

Live at <https://ddbxl.github.io/TSP/>.

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

## Scanned pages

TSP spots a page holding an image and no text layer, counts them, and says so
rather than handing you an empty file.

Reading them needs OCR. On the desktop, tick **Read scans (OCR)** or pass
`--ocr`, which uses Tesseract through PyMuPDF at roughly 1.4 seconds a page.
Tesseract 5 and its language data install separately; TSP bundles neither.

The browser cannot OCR, so it points you at
[OCRmyPDF](https://ocrmypdf.readthedocs.io) instead.

## Tables

Off by default. Tick **Tables** on a file, or pass `--tables`, and detected
tables come out as markdown grids:

```
|Region|R&D|Patents|SMEs|Employ.|Index|
|---|---|---|---|---|---|
|Bratislavsky kraj|1.82|412|18,430|62.1|0.71|
```

Text blocks inside a table are dropped in favour of the grid, so cells appear
once rather than twice. Measured on a six-column indicator table, a grid costs
231 tokens against 224 for the same content in reading order, so about 3% more.

The cost is time. Detection made a 100-page report go from 1.4 to 4.3 seconds,
which is why it stays off unless asked for.

Reading order already handles simple grids. Reach for this when cells are empty,
wrap onto two lines, or sit under merged headers, because reading order then
misaligns columns without saying so.

## Limits

- Token figures estimate at four characters per token, which is the rule of
  thumb for English prose. No single true count exists, since every model
  tokenises differently. The figure runs low on tables and numbers, so treat it
  as a before-and-after ratio rather than a total.
- OCR needs Tesseract installed separately, and never runs in the browser.
- Very large documents in the browser hold the PDF, its text and every rendered
  page in memory at once. Mobile browsers will give up sooner than desktop.

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
