# TSP, Token Saving Protocol

**[Open it in your browser](https://ddbxl.github.io/TSP/)**, or install it and
work from the desktop.

Feed TSP a document and get back compact markdown, plus images of the pages that
carry their meaning in charts. Your files stay on your machine.

A 90-page report repeats its header on 90 pages, its footer on 90 pages, and
sets its quotation marks in curly glyphs that cost two tokens each. You pay for
all of it when you paste that report into an LLM. TSP strips the repetition,
rejoins words broken across line breaks, and prints the before and after count
so you can see what came off.

![TSP](assets/social-preview.png)

## In your browser

### <https://ddbxl.github.io/TSP/>

Nothing to install. Drop PDFs on the page and take the text away. Your documents
stay where they sit. No server sees them, and none needs to.

The same `core.py` that runs on the desktop runs there, as WebAssembly through
[Pyodide](https://pyodide.org). It loads as the page opens, on a worker thread,
so the 28 MB arrives while you are choosing files. On a
connection the browser reports as metered or very slow it waits, and adding a
file starts it.

A 100-page report takes about 2.3 seconds there against 1.0 second on the
desktop.

### Taking the result away

Each finished document carries its own actions, with the same actions for
everything at once beneath them:

| | Good for |
|---|---|
| **Copy text** | Pasting straight into a chat. No file, no unpacking. |
| **Download text** | One `.md`. Per document, or every document joined. |
| **Download files** | That document's text, manifest and page images as a zip. |
| **Save every file to a folder** | Everything onto disk. Chrome, Edge and Opera. |
| **Download everything as a zip** | The same, on browsers without folder access. |

Downloads keep the source name with a marker in front, so
`S3_Study_Final_Report.pdf` gives `optimised_S3_Study_Final_Report.md` and sorts
beside its original.

Chrome refuses to write to certain folders, Downloads among them, and reports
that the same way as a cancelled dialogue, so the page cannot tell the two apart.
It opens the picker in Documents for that reason and says so if nothing gets
saved.

With two files or more, a row above the list sets the mode, Tables and Figures
for all of them at once. It reads Mixed where the rows differ, so it never claims a setting the queue is
not in, and a single row can still be changed afterwards.

Finished files stay in the queue. Change a setting on one and it queues again;
change nothing and the button offers Process again. Neither needs the file
re-picked.

## On your desktop

Worth installing for large batches, for scripting, and for anywhere a 28 MB
download on each new machine is a nuisance.

```bash
git clone https://github.com/ddbxl/TSP.git
cd TSP
pip install -e .
```

Python 3.10 or later. The one dependency is [PyMuPDF](https://pymupdf.readthedocs.io).

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

## What it reads

Everything comes out as one `.md` file.

| | |
|---|---|
| **PDF** | The main path: page markers, tables, figures, scanned pages |
| **Word and OpenDocument** | `.docx`, `.odt` |
| **Images** | `.png`, `.jpg`, `.tiff`, `.bmp`, `.gif`, read through OCR |
| **Books and pages** | `.epub`, `.mobi`, `.fb2`, `.xps`, `.cbz`, `.svg` |
| **Plain text** | `.txt`, `.md` |

`tsp --formats` lists them.

A Word or OpenDocument file goes down a different path, and a better one. Both
are a zip of XML, so the standard library reads them and everything TSP has to
guess at in a PDF is stated outright: a heading carries a style name, a table is
an element, and running headers live in a separate part of the file so they never
enter the body at all.

Two habits of Commission templates get handled. Heading levels are read from the
style definitions, so a Slovenian author's `Naslov1`
and a German's `berschrift1` are found like any other. And a table whose cells
hold whole sections is treated as a layout frame and walked into, since reading
one as data turned a chapter into a single 59,000-character line.

A table of contents is dropped: its page numbers point at a pagination that no
longer exists.

Those formats have no pages, so page markers, the image threshold and the
scanned-page check do not apply to them.

Old `.doc` is not read. It is a binary format needing LibreOffice or `antiword`,
and it cannot be read in a browser at all. Save as `.docx`.

## Choosing for you

Leave the mode on **Automatic**, or pass `--auto`, and TSP reads ten pages spread
through a document and decides from what it finds. It says why, so you can
overrule it:

```
-> deck.pdf
   chose slide decks (50%)
     28 characters a page and pictures over 74% of it, which reads like slides
```

The signals separate cleanly. A slide deck measured 28 characters a page with
raster images over three quarters of it; a Commission country report 3,556
characters and no raster at all. It also turns Tables on when the sample holds
one worth keeping, and says when a document has no text layer and wants OCR.

Figures it reports but does not switch on, since replacing a table with a picture
is a choice to make for yourself.

Looking costs about a second on a 118-page report, against 24 to process it.

## Modes

The threshold sets how much of a page raster images must cover before TSP saves
that page as a PNG alongside its text.

| Mode | Threshold | Suits |
|---|---|---|
| Text documents | 5% | Reports, legislation, studies |
| Mixed reports | 20% | Prose with figures dropped between sections |
| Slide decks | 50% | Presentations where the slide *is* the graphic |
| Text only | 100% | Skip images and take the text |

Two cases the threshold alone misses, both handled. A corner logo repeating on
every page stays under a floor of 0.4% and triggers nothing. A chart drawn in
vector paths holds no raster image at all, so a path count catches it.

## Scanned pages

TSP spots a page holding an image and no text layer, counts them, and offers to
read them, so you never get an empty file with no explanation.

**In the browser**, a scanned page brings up a language picker and a button.
Tesseract arrives as WebAssembly the first time, about 7 MB for the engine and
one language model, then stays cached. Recognition takes about a second a
page. The page images never leave the machine: only the language model comes down
from Tesseract's own repository.

**On the desktop**, tick **Read scans (OCR)** or pass `--ocr`, which uses
Tesseract through PyMuPDF at about 1.4 seconds a page. Tesseract 5 and its
language data need their own install there, and TSP bundles neither.

Either way the recognised words go through the same cleaning as a text layer, so
a word Tesseract split across two lines comes back whole. In the browser the
words are folded into the document already written, so reading three pages of a
120-page report costs the recognition and nothing else.

No cloud service touches any of this, and none will. An online OCR API
would mean posting your documents to somebody else's server, which is the one
thing this tool exists to avoid.

## Tables

Off by default. Tick **Tables** on a file, or pass `--tables`, and detected
tables come out as markdown grids:

```
|Region|R&D|Patents|SMEs|Employ.|Index|
|---|---|---|---|---|---|
|Bratislavsky kraj|1.82|412|18,430|62.1|0.71|
```

TSP drops the text blocks inside a table in favour of the grid, so cells appear
exactly once. Measured on a six-column indicator table, a grid costs
231 tokens against 224 for the same content in reading order, so about 3% more.

The cost is time, and it falls on pages that hold no table at all. Detection
reads ruling lines, so TSP counts the lines and rectangles on a page first and
skips the ones carrying fewer than four. On a 120-page report with tables on ten
pages, that takes the penalty from five times the normal run down to one and a
half, finding the same ten tables:

| | 120 pages |
|---|---|
| Tables off | 1.0 s |
| Tables on | 1.5 s |
| Tables on, filter disabled | 5.0 s |

Reading order already handles simple grids. Reach for this when cells are empty,
wrap onto two lines, or sit under merged headers, because reading order then
misaligns columns without saying so.

### What it turns down

A bordered callout box, the shape Commission documents use for highlights, looks
like a table to a detector that reads lines. So does a chart's axis labelling.
Both come out as a grid of prose with half the columns blank.

TSP judges each grid before keeping it. A real table fills its columns down the
page; a box or a chart leaves most columns blank on most rows. Measured on a
Commission country report, real tables ran 0 to 33% thin columns and boxes and
charts 50 to 100%, so a grid with half its columns thin gets turned down, as does
one whose cells average more than 120 characters or hold a 600-character
paragraph.

On that 118-page report, 30 grids were detected and 7 kept. Pipe-table lines in
the output fell from 387 to 90, and `MANIFEST.txt` records how many grids were
turned down so you can check the judgement.

A rejected grid costs structure alone. Those words still arrive as reading-order
text.

### What it will not find

Only tables drawn as a grid of ruled cells. A table held together by three
horizontal rules and nothing else, the style most academic and Commission
reports use, goes undetected: the detector reads lines, and that layout gives it
almost none.

PyMuPDF offers a text-position strategy that does find those. It also reported a
table on all 120 pages of the test report, shredding ordinary paragraphs into
grids like `|The Smart|Spec|ialisation|Strategy|`, at four times the cost. Wrong
tables are worse than none, so TSP leaves it alone. Those tables come through as
reading-order text, which for a simple layout stays readable.

## Figures

Off by default. Tick **Figures** on a file, or pass `--figures`, and charts drawn
in vector paths come out as images with a marker where they sat:

```
Graph 1.2: HICP breakdown 2022-2026

[figure: p004_f1.png]
```

The reason is that a chart has no text worth reading. Its axis labels arrive as
orphan numbers with nothing to attach them to:

```
1.58
1.44
1.73
:
2.24
```

An LLM reading those has no idea what they measure and may pin them to the
nearest heading, which is worse than the chart being absent, because absence is
visible and this is not.

TSP groups the drawings on a page into the areas they occupy, grows each area to
take in the axis labels around it, and replaces the label text with a picture.
Two things survive: the caption, and any block of real sentences. Measured on a
Commission country report, a chart's labels run 1.5 to 4 words a line against 9
to 12 inside a bordered box of prose, which is how the two are told apart.

On that 118-page report: 100,444 tokens down to 93,336, 77 charts rendered,
orphan number lines down from 251 to 115, all 7 tables kept, and every distinct
caption still present.

### Why it stays off

A chart cannot be told from a sparse table by any measure of its text: both run
1.4 to 2.0 words a line. So replacing text with a picture can cost you a table
you would rather have read, and it only pays off if the images travel with the
markdown. With **Tables** also on, a grid the table gate recovered wins over a
picture.

## Two outputs

Markdown by default. Choose **Markdown and HTML**, or pass `--html`, and a
self-contained HTML copy lands beside it: one file, tables rendered, and every
page image carried inside it as a data URI, so it still works after you email it.

The markdown always stays, because the copy button, the OCR step and anything
pasting into a chat rely on it. HTML costs about 6% more tokens, measured at
87,272 against 92,271 on two partnership agreements, so it is for reading rather
than for pasting.

## What comes out

```
report.pdf
report_TSP/
├── report.md         the text, page markers as --- p.4 ---
├── MANIFEST.txt      what got removed, and the token estimate
└── p007.png          only for pages above the threshold
```

Markdown, so a table renders as a table wherever you open the file, and an LLM
reads the columns as columns. The markup stays minimal: a heading
for the filename, grids where tables were found, and nothing invented. Headings
and emphasis inside a PDF resist recovery, and guessing at them would cost
tokens for structure that might be wrong.

`MANIFEST.txt` lists the headers and footers TSP dropped, so you can check its
judgement.

## Where the savings come from

- Running headers and footers, matched across pages even when a page number
  sits inside the line. `Page 4 of 90` and `Page 5 of 90` count as one header.
- Standalone page numbers.
- Words split by hyphens at line ends. `concen-\ntrate` becomes `concentrate`.
- Curly quotes, en dashes, ligatures and non-breaking spaces, mapped to ASCII.
  A curly apostrophe costs more than a straight one.
- Runs of spaces and blank lines.
- The explanation of image pages, written once at the top of the file. It used
  to sit above every image page.

Measured on a synthetic 7-page report with a header and footer: 4,050 characters
down to 3,540, about 1,012 estimated tokens down to 885. Documents with heavier
furniture give up more.

## Limits

- Token figures estimate at four characters per token, which is the rule of
  thumb for English prose. No single true count exists, since every model
  tokenises its own way. The figure runs low on tables and numbers, so treat it
  as a before-and-after ratio, never as a total.
- Desktop OCR needs its own Tesseract install. The browser fetches a copy on
  demand.
- Very large documents in the browser hold the PDF, its text and every rendered
  page in memory at once. Mobile browsers will give up sooner than desktop.

## Releasing

Change `version` in `pyproject.toml`, match it in `src/tsp/__init__.py`, and add
a `## <version>` section to `CHANGELOG.md`. Pushing that to `main` builds the
archives, tags `v<version>`, and publishes a release whose notes are that
changelog section.

The workflow refuses to publish when the three disagree, when the tag exists
already, or when the tests fail. A test makes the same comparison on every
commit, so a mismatch surfaces before release time.

## Serving the browser build

```bash
python web/serve.py
```

That stages the engine, serves `web/` and opens the page on localhost.

Push to `main` and `.github/workflows/pages.yml` assembles the site, copies
`src/tsp/core.py` in as the engine, and deploys. Every path in `index.html` and
`app.js` is relative, so the build works from the `/TSP/` subpath without
further configuration.

[docs/BROWSER.md](docs/BROWSER.md) covers the version pinning rule, browser
support, measured timings and the test results.

## Build a Windows executable

```bash
pip install pyinstaller
pyinstaller packaging/tsp.spec
```

`dist/TSP/` holds the result, about 40 MB. The spec excludes numpy, pandas and
lxml, which PyMuPDF imports when present and TSP does not use.

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
