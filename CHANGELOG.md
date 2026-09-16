# Changelog

Versions follow [Semantic Versioning](https://semver.org).

## 1.0.0

First release.

### Reading

- PDF, with page markers, and a threshold deciding which pages come back as
  images.
- Word and OpenDocument text, `.docx` and `.odt`, read from their XML. Heading
  levels come from the style definitions, so a style named in any language is
  found. A table whose cells hold whole sections is treated as a layout frame
  and walked into. A table of contents is dropped along with its title.
- Slides, `.pptx` and `.odp`, with speaker notes.
- Images, `.png`, `.jpg`, `.tiff`, `.bmp` and `.gif`, read by OCR.
- `.epub`, `.mobi`, `.fb2`, `.xps`, `.cbz`, `.svg`, `.txt` and `.md`.

### Making the text lighter

- Running headers and footers, matched across pages with digits collapsed, so
  `Page 4 of 90` and `Page 5 of 90` count as one. A line appearing more than
  once on a single page is prose and stays.
- Standalone page numbers.
- Words split by a hyphen at a line end.
- Curly quotes, dashes, ligatures and non-breaking spaces, mapped to ASCII.
- Runs of spaces and blank lines.

### Tables, figures and scans

- Tables kept as Markdown grids, opt-in. Each grid is judged before it is used:
  one whose columns are thin down the page, or whose cells hold paragraphs, is a
  bordered box or a chart and its text is left alone. Detection skips pages
  carrying too few ruling lines to hold a table.
- Charts drawn in vector paths rendered as images, opt-in, with the orphan axis
  labels they leave in the text dropped. Captions and sentences inside the area
  are kept.
- Pages holding an image and no text layer are counted and reported. OCR reads
  them: in the browser through Tesseract compiled to WebAssembly, on the desktop
  through Tesseract by way of PyMuPDF. The recognised words are cleaned like any
  other page.

### Working with it

- A browser build on GitHub Pages running the same engine as the desktop,
  compiled to WebAssembly. Documents are read where they sit.
- A desktop window and a command line interface.
- Automatic mode, which reads ten pages spread through a document, chooses the
  threshold and whether to keep tables, and reports its reasons.
- One control setting the mode for a whole queue.
- Output as Markdown, with a self-contained HTML copy for reading.
- Copy text, download text, download HTML and download files, per document and
  for everything at once. The archive gathers the Markdown in one folder and the
  HTML in another, with the full per-document folders behind them.
- `MANIFEST.txt` per document recording pages, images, the lines removed and the
  token estimate before and after.
- The page carries a folded note in its footer saying what TSP does and which
  formats it reads.
- The interface is dark by default, in the register of the editors markdown
  tends to end up in, so the output and the place it goes look related. Inter
  for the controls, a serif for the title and the figures, both shipped with the
  site so it works offline. The mark is four lines of a page with the running
  head struck through.
- Light and dark. A switch in the footer names both ends and sets it, starting
  wherever the system says and remembering the first time it is touched. The theme is settled in the
  head before anything paints, so neither appears first by mistake.
- A bar tracks the runtime as it arrives, in three stages, and goes once it is
  ready. Which component is downloading is the engine's business; the failure
  panel carries the versions, where they matter.
- What TSP does is said once, in the folded note, leaving the masthead to the
  title.
