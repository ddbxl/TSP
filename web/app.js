/* TSP in the browser.
 *
 * Boots Pyodide, installs PyMuPDF, fetches the engine from this deployment and
 * calls it. All extraction logic lives in src/tsp/core.py, so the browser and
 * the desktop run the same code.
 *
 * Copyright (C) 2026 TSP contributors
 * Licensed under the GNU General Public License v3.0 or later.
 */

const PYODIDE_VERSION = "0.29.4"; // verified against the wheel platform below
const WHEEL_PLATFORM = "pyemscripten_2025_0_wasm32"; // Python 3.13 == Pyodide 0.29.x
const PYODIDE_URL = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/pyodide.mjs`;
const PYPI_METADATA = "https://pypi.org/pypi/pymupdf/json";
const CORE_URL = new URL("./tsp_core.py", import.meta.url);

const MODES = [
  { label: "Text documents (5%)", value: 5 },
  { label: "Mixed reports (20%)", value: 20 },
  { label: "Slide decks (50%)", value: 50 },
  { label: "Text only (100%)", value: 100 },
];

const el = (id) => document.getElementById(id);
const ui = {
  engine: el("engine"),
  engineText: el("engine-text"),
  boot: el("boot"),
  drop: el("drop"),
  picker: el("picker"),
  queue: el("queue"),
  dpi: el("dpi"),
  run: el("run"),
  reset: el("reset"),
  keptBar: el("meter-kept"),
  statIn: el("stat-in"),
  statOut: el("stat-out"),
  statCut: el("stat-cut"),
  statImg: el("stat-img"),
  results: el("results"),
  download: el("download"),
  saveFolder: el("save-folder"),
  log: el("log"),
};

let pyodide = null;
let booting = null;
let queue = [];
let zipBytes = null;

/* -- Python glue ------------------------------------------------------- */

const GLUE = `
import io, json, zipfile
from pathlib import Path
from tsp.core import Settings, process_pdf

WORK = Path("/work")

def tsp_process(name, threshold_pct, dpi):
    pdf = WORK / "in" / name
    threshold = threshold_pct / 100.0
    settings = Settings(
        image_threshold=1.01 if threshold_pct >= 100 else threshold,
        render_zoom=max(0.25, dpi / 72.0),
        render_visual_pages=threshold_pct < 100,
        output_dir=WORK / "out",
    )
    result = process_pdf(pdf, settings)
    return json.dumps({
        "ok": result.ok,
        "message": result.message,
        "pages": result.pages,
        "images": result.images_saved,
        "tokens_in": result.tokens_in,
        "tokens_out": result.tokens_out,
        "saving": round(result.saving, 4),
        "warnings": result.warnings[:5],
        "folder": result.text_path.parent.name if result.text_path else None,
    })

def tsp_zip():
    root = WORK / "out"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(root).as_posix())
    return buffer.getvalue()

def tsp_files():
    root = WORK / "out"
    return json.dumps([
        p.relative_to(root).as_posix() for p in sorted(root.rglob("*")) if p.is_file()
    ])

def tsp_read(relative):
    return (WORK / "out" / relative).read_bytes()

def tsp_clear():
    import shutil
    for folder in ("in", "out"):
        target = WORK / folder
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)
`;

function setEngine(state, text) {
  ui.engine.className = `engine engine--${state}`;
  ui.engineText.textContent = text;
  ui.boot.hidden = state !== "waiting" && state !== "failed";
}

function log(line) {
  ui.log.textContent = line;
}

/* PyMuPDF publishes a WebAssembly wheel to PyPI under PEP 783. micropip
 * resolves it for this runtime; if that fails, PyPI's JSON API gives the wheel
 * URL directly. Either way the wheel's platform tag must match the running
 * Pyodide. */

async function findWasmWheel() {
  const meta = await fetch(PYPI_METADATA).then((response) => {
    if (!response.ok) throw new Error(`PyPI returned ${response.status}`);
    return response.json();
  });

  const match = (files) =>
    (files || []).find((file) => file.filename.includes(WHEEL_PLATFORM));

  const latest = match(meta.urls);
  if (latest) return latest.url;

  // The newest release may carry no wheel for this platform. Walk back.
  const versions = Object.keys(meta.releases || {}).reverse();
  for (const version of versions) {
    const older = match(meta.releases[version]);
    if (older) return older.url;
  }
  throw new Error(`PyPI has no ${WHEEL_PLATFORM} wheel for pymupdf`);
}

async function installPyMuPDF() {
  try {
    await pyodide.loadPackage("micropip");
    const micropip = pyodide.pyimport("micropip");
    await micropip.install("pymupdf");
    return "micropip";
  } catch (error) {
    console.warn("micropip route failed, trying the wheel URL directly", error);
  }
  await pyodide.loadPackage(await findWasmWheel());
  return "direct wheel";
}

async function boot() {
  if (pyodide) return pyodide;
  if (booting) return booting;

  booting = (async () => {
    setEngine("loading", "Downloading Python runtime, about 10 MB");
    const { loadPyodide } = await import(PYODIDE_URL);
    pyodide = await loadPyodide({
      indexURL: `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`,
    });

    setEngine("loading", "Installing PyMuPDF, about 18 MB");
    const route = await installPyMuPDF();

    setEngine("loading", "Loading the TSP engine");
    const source = await fetch(CORE_URL).then((response) => {
      if (!response.ok) {
        throw new Error(
          `tsp_core.py returned ${response.status}. Running locally? ` +
            `Start with "python web/serve.py", which stages the engine.`
        );
      }
      return response.text();
    });

    pyodide.FS.mkdirTree("/lib/tsp");
    pyodide.FS.writeFile("/lib/tsp/__init__.py", "");
    pyodide.FS.writeFile("/lib/tsp/core.py", source);
    pyodide.FS.mkdirTree("/work/in");
    pyodide.FS.mkdirTree("/work/out");

    await pyodide.runPythonAsync(`
import sys
sys.path.insert(0, "/lib")
`);
    await pyodide.runPythonAsync(GLUE);

    const version = pyodide.runPython("import pymupdf; pymupdf.__version__");
    setEngine(
      "ready",
      `Ready. PyMuPDF ${version} on Pyodide ${pyodide.version} via ${route}`
    );
    refresh();
    return pyodide;
  })().catch((error) => {
    booting = null;
    pyodide = null;
    setEngine("failed", "Engine failed to start");
    log(
      `${error}\n\nOpen the browser console for the full trace. A mismatch ` +
        `between Pyodide ${PYODIDE_VERSION} and the ${WHEEL_PLATFORM} wheel ` +
        `is the usual cause; see docs/BROWSER.md.`
    );
    throw error;
  });

  return booting;
}

/* -- queue ------------------------------------------------------------- */

function addFiles(files) {
  const known = new Set(queue.map((entry) => `${entry.file.name}:${entry.file.size}`));
  let added = 0;

  for (const file of files) {
    if (!/\.pdf$/i.test(file.name)) continue;
    const key = `${file.name}:${file.size}`;
    if (known.has(key)) continue;
    known.add(key);
    queue.push({ file, mode: MODES[0].value, state: "queued" });
    added += 1;
  }

  if (added) {
    render();
    log(`${queue.length} file${queue.length === 1 ? "" : "s"} ready`);
  }
}

function render() {
  ui.queue.replaceChildren();

  queue.forEach((entry, index) => {
    const row = document.createElement("li");

    const name = document.createElement("span");
    name.className = "name";
    name.textContent = entry.file.name;

    const size = document.createElement("span");
    size.className = "size";
    size.textContent = `${(entry.file.size / 1048576).toFixed(1)} MB`;

    const select = document.createElement("select");
    select.setAttribute("aria-label", `Picture threshold for ${entry.file.name}`);
    for (const mode of MODES) {
      const option = document.createElement("option");
      option.value = String(mode.value);
      option.textContent = mode.label;
      option.selected = mode.value === entry.mode;
      select.append(option);
    }
    select.addEventListener("change", () => {
      entry.mode = Number(select.value);
    });

    const state = document.createElement("span");
    state.className = "state";
    if (entry.state === "done") {
      state.classList.add("state--done");
      state.textContent = `${entry.pages}p, ${entry.images} img`;
    } else if (entry.state === "failed") {
      state.classList.add("state--failed");
      state.textContent = "failed";
    } else if (entry.state === "working") {
      state.textContent = "working";
    } else {
      const remove = document.createElement("button");
      remove.className = "link";
      remove.type = "button";
      remove.textContent = "Remove";
      remove.addEventListener("click", () => {
        queue.splice(index, 1);
        render();
        refresh();
      });
      state.append(remove);
    }

    row.append(name, size, select, state);
    ui.queue.append(row);
  });

  refresh();
}

function refresh() {
  const pending = queue.some((entry) => entry.state === "queued");
  ui.run.disabled = !pending;
  ui.run.textContent = pending
    ? `Process ${queue.filter((e) => e.state === "queued").length} file${
        queue.filter((e) => e.state === "queued").length === 1 ? "" : "s"
      }`
    : "Process files";
  ui.reset.hidden = queue.length === 0;
}

/* -- meter ------------------------------------------------------------- */

const totals = { in: 0, out: 0, images: 0 };

function updateMeter() {
  const cut = totals.in ? 1 - totals.out / totals.in : 0;
  ui.statIn.textContent = totals.in.toLocaleString();
  ui.statOut.textContent = totals.out.toLocaleString();
  ui.statCut.textContent = `${Math.round(cut * 100)}%`;
  ui.statImg.textContent = totals.images.toLocaleString();
  ui.keptBar.style.width = `${totals.in ? (totals.out / totals.in) * 100 : 0}%`;
}

/* -- run --------------------------------------------------------------- */

async function run() {
  ui.run.disabled = true;
  ui.results.hidden = true;
  zipBytes = null;

  try {
    await boot();
  } catch {
    return;
  }

  const dpi = Number(ui.dpi.value);
  const pending = queue.filter((entry) => entry.state === "queued");

  for (const entry of pending) {
    entry.state = "working";
    render();
    log(`Reading ${entry.file.name}`);
    await new Promise((resolve) => requestAnimationFrame(resolve));

    try {
      const bytes = new Uint8Array(await entry.file.arrayBuffer());
      pyodide.FS.writeFile(`/work/in/${entry.file.name}`, bytes);

      const report = JSON.parse(
        pyodide.globals.get("tsp_process")(entry.file.name, entry.mode, dpi)
      );

      if (report.ok) {
        entry.state = "done";
        entry.pages = report.pages;
        entry.images = report.images;
        totals.in += report.tokens_in;
        totals.out += report.tokens_out;
        totals.images += report.images;
        updateMeter();
        log(`${entry.file.name}: ${report.message}`);
      } else {
        entry.state = "failed";
        log(`${entry.file.name}: ${report.message}`);
      }
    } catch (error) {
      entry.state = "failed";
      log(`${entry.file.name}: ${error}`);
    }
    render();
  }

  await offerResults();
}

async function offerResults() {
  const names = JSON.parse(pyodide.globals.get("tsp_files")());
  if (!names.length) {
    log("Nothing produced.");
    return;
  }

  const proxy = pyodide.globals.get("tsp_zip")();
  zipBytes = proxy.toJs ? proxy.toJs() : proxy;
  if (proxy.destroy) proxy.destroy();

  const blob = new Blob([zipBytes], { type: "application/zip" });
  if (ui.download.dataset.url) URL.revokeObjectURL(ui.download.dataset.url);
  const url = URL.createObjectURL(blob);
  ui.download.href = url;
  ui.download.dataset.url = url;
  ui.download.textContent = `Download ${names.length} file${
    names.length === 1 ? "" : "s"
  } (${(blob.size / 1048576).toFixed(1)} MB)`;

  ui.results.hidden = false;
  ui.saveFolder.hidden = !("showDirectoryPicker" in window);
  log(`Done. ${names.length} files ready.`);
}

async function saveToFolder() {
  if (!("showDirectoryPicker" in window)) return;
  try {
    const root = await window.showDirectoryPicker({ mode: "readwrite" });
    const names = JSON.parse(pyodide.globals.get("tsp_files")());

    for (const name of names) {
      const parts = name.split("/");
      let folder = root;
      for (const part of parts.slice(0, -1)) {
        folder = await folder.getDirectoryHandle(part, { create: true });
      }
      const handle = await folder.getFileHandle(parts.at(-1), { create: true });
      const writable = await handle.createWritable();
      const proxy = pyodide.globals.get("tsp_read")(name);
      const data = proxy.toJs ? proxy.toJs() : proxy;
      if (proxy.destroy) proxy.destroy();
      await writable.write(data);
      await writable.close();
    }
    log(`Saved ${names.length} files to ${root.name}.`);
  } catch (error) {
    if (error && error.name !== "AbortError") log(`Could not save: ${error}`);
  }
}

function resetAll() {
  queue = [];
  totals.in = totals.out = totals.images = 0;
  zipBytes = null;
  ui.results.hidden = true;
  if (ui.download.dataset.url) {
    URL.revokeObjectURL(ui.download.dataset.url);
    delete ui.download.dataset.url;
  }
  if (pyodide) pyodide.globals.get("tsp_clear")();
  updateMeter();
  render();
  log("");
}

/* -- wiring ------------------------------------------------------------ */

ui.boot.addEventListener("click", () => boot().catch(() => {}));
ui.drop.addEventListener("click", () => ui.picker.click());
ui.drop.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    ui.picker.click();
  }
});
ui.picker.addEventListener("change", () => {
  addFiles(ui.picker.files);
  ui.picker.value = "";
});
["dragenter", "dragover"].forEach((name) =>
  ui.drop.addEventListener(name, (event) => {
    event.preventDefault();
    ui.drop.classList.add("is-over");
  })
);
["dragleave", "drop"].forEach((name) =>
  ui.drop.addEventListener(name, () => ui.drop.classList.remove("is-over"))
);
ui.drop.addEventListener("drop", (event) => {
  event.preventDefault();
  addFiles(event.dataTransfer.files);
});
ui.run.addEventListener("click", () => run());
ui.reset.addEventListener("click", resetAll);
ui.saveFolder.addEventListener("click", saveToFolder);

setEngine("waiting", "Engine idle, 28 MB to download on first use");
updateMeter();
