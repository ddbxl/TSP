/* TSP worker: owns the Python runtime.
 *
 * Everything heavy happens here, off the page's thread, so the interface keeps
 * repainting and reporting progress while a document is read. The engine is the
 * same src/tsp/core.py the desktop app runs.
 *
 * Copyright (C) 2026 Daga D.
 * Licensed under the GNU General Public License v3.0 or later.
 */

const PYODIDE_VERSION = "0.29.4";
const WHEEL_PLATFORM = "pyemscripten_2025_0_wasm32";
const PYPI_METADATA = "https://pypi.org/pypi/pymupdf/json";

let pyodide = null;

function say(type, payload = {}) {
  self.postMessage({ type, ...payload });
}

async function findWasmWheel() {
  const meta = await fetch(PYPI_METADATA).then((response) => {
    if (!response.ok) throw new Error(`PyPI returned ${response.status}`);
    return response.json();
  });
  const match = (files) =>
    (files || []).find((file) => file.filename.includes(WHEEL_PLATFORM));

  const latest = match(meta.urls);
  if (latest) return latest.url;
  for (const version of Object.keys(meta.releases || {}).reverse()) {
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

async function fetchText(url, what) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(
      `${what} returned ${response.status}. Running locally? Start with ` +
        `"python web/serve.py", which stages the engine.`
    );
  }
  return response.text();
}

async function boot(coreUrl, bridgeUrl) {
  if (pyodide) return;

  say("status", { state: "loading", text: "Downloading Python runtime, about 10 MB" });
  importScripts(
    `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/pyodide.js`
  );
  pyodide = await self.loadPyodide({
    indexURL: `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`,
  });

  say("status", { state: "loading", text: "Installing PyMuPDF, about 18 MB" });
  const route = await installPyMuPDF();

  say("status", { state: "loading", text: "Loading the TSP engine" });
  const [engine, bridge] = await Promise.all([
    fetchText(coreUrl, "tsp_core.py"),
    fetchText(bridgeUrl, "bridge.py"),
  ]);

  pyodide.FS.mkdirTree("/lib/tsp");
  pyodide.FS.writeFile("/lib/tsp/__init__.py", "");
  pyodide.FS.writeFile("/lib/tsp/core.py", engine);
  pyodide.FS.mkdirTree("/work/in");
  pyodide.FS.mkdirTree("/work/out");

  await pyodide.runPythonAsync('import sys; sys.path.insert(0, "/lib")');
  // bridge.py is a real file rather than a string in this one, so nothing
  // rewrites its escape sequences on the way in.
  await pyodide.runPythonAsync(bridge);

  const version = pyodide.runPython("import pymupdf; pymupdf.__version__");
  say("ready", {
    text: `Ready. PyMuPDF ${version} on Pyodide ${pyodide.version} via ${route}`,
  });
}

function process({ name, bytes, threshold, dpi, tables }) {
  pyodide.FS.writeFile(`/work/in/${name}`, new Uint8Array(bytes));

  // Reaches Python as a callable, so progress arrives per page rather than
  // per file.
  const report = (page, pages) => say("progress", { name, page, pages });

  const report_json = pyodide.globals.get("tsp_process")(
    name,
    threshold,
    dpi,
    tables,
    report
  );
  say("result", { name, report: JSON.parse(report_json) });
}

function deliver() {
  const names = JSON.parse(pyodide.globals.get("tsp_files")());
  if (!names.length) {
    say("output", { names: [], bytes: null });
    return;
  }
  const proxy = pyodide.globals.get("tsp_zip")();
  const bytes = proxy.toJs ? proxy.toJs() : proxy;
  if (proxy.destroy) proxy.destroy();
  self.postMessage({ type: "output", names, bytes }, [bytes.buffer]);
}

function readOne(path) {
  const proxy = pyodide.globals.get("tsp_read")(path);
  const bytes = proxy.toJs ? proxy.toJs() : proxy;
  if (proxy.destroy) proxy.destroy();
  self.postMessage({ type: "file", path, bytes }, [bytes.buffer]);
}

self.onmessage = async (event) => {
  const message = event.data;
  try {
    switch (message.type) {
      case "boot":
        await boot(message.coreUrl, message.bridgeUrl);
        break;
      case "process":
        process(message);
        break;
      case "deliver":
        deliver();
        break;
      case "text":
        say("text", { text: pyodide.globals.get("tsp_text")() });
        break;
      case "drop":
        pyodide.globals.get("tsp_drop")(message.name);
        say("dropped", { name: message.name });
        break;
      case "read":
        readOne(message.path);
        break;
      case "clear":
        pyodide.globals.get("tsp_clear")();
        say("cleared");
        break;
      default:
        say("error", { message: `unknown request: ${message.type}` });
    }
  } catch (error) {
    say("error", {
      name: message.name,
      message: String((error && error.message) || error),
    });
  }
};
