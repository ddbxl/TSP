# Changelog

Versions follow [Semantic Versioning](https://semver.org).

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
