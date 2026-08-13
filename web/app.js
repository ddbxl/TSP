/* TSP in the browser.
 *
 * This file draws the interface and talks to web/worker.js, which owns the
 * Python runtime. Keeping the engine on a worker thread lets the page report
 * progress per page and cancel a run in flight.
 *
 * Copyright (C) 2026 Daga D.
 * Licensed under the GNU General Public License v3.0 or later.
 */

const WORKER_URL = new URL("./worker.js", import.meta.url);
const CORE_URL = new URL("./tsp_core.py", import.meta.url);
const BRIDGE_URL = new URL("./bridge.py", import.meta.url);

/* Output keeps the source name with a marker in front, so an optimised copy
   sits beside its original and sorts next to it. */
function optimisedName(pdfName, extension) {
  return `optimised_${pdfName.replace(/\.pdf$/i, "")}.${extension}`;
}

function humanSize(bytes) {
  const kb = bytes / 1024;
  return kb < 1024 ? `${Math.round(kb)} KB` : `${(kb / 1024).toFixed(1)} MB`;
}

function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

async function toClipboard(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const holder = document.createElement("textarea");
    holder.value = text;
    holder.setAttribute("readonly", "");
    holder.style.position = "fixed";
    holder.style.opacity = "0";
    document.body.append(holder);
    holder.select();
    const worked = document.execCommand && document.execCommand("copy");
    holder.remove();
    return Boolean(worked);
  }
}

function flash(button, word) {
  const original = button.textContent;
  button.textContent = word;
  button.disabled = true;
  setTimeout(() => {
    button.textContent = original;
    button.disabled = false;
  }, 1500);
}

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
  bulk: el("bulk"),
  bulkMode: el("bulk-mode"),
  bulkTables: el("bulk-tables"),
  bulkFigures: el("bulk-figures"),
  dpi: el("dpi"),
  run: el("run"),
  cancel: el("cancel"),
  reset: el("reset"),
  bar: el("progress"),
  barFill: el("progress-fill"),
  barLabel: el("progress-label"),
  keptBar: el("meter-kept"),
  statIn: el("stat-in"),
  statOut: el("stat-out"),
  statCut: el("stat-cut"),
  statImg: el("stat-img"),
  results: el("results"),
  copy: el("copy"),
  downloadText: el("download-text"),
  download: el("download"),
  saveFolder: el("save-folder"),
  folderHint: el("folder-hint"),
  notice: el("notice"),
  noticeText: el("notice-text"),
  ocrOffer: el("ocr-offer"),
  ocrLang: el("ocr-lang"),
  ocrRun: el("ocr-run"),
  ocrNote: el("ocr-note"),
  log: el("log"),
  failure: el("failure"),
  failureLead: el("failure-lead"),
  failureHint: el("failure-hint"),
  failureTrace: el("failure-trace"),
  failureCopy: el("failure-copy"),
  failureReport: el("failure-report"),
};

const REPO = "https://github.com/ddbxl/TSP";

/* OCR arrives only when a scanned page turns up: about 7 MB for the engine and
   one language model, fetched then and cached by the browser afterwards. The
   language data comes from Tesseract's own repository and the page images never
   leave this machine. */
const TESSERACT = "7.0.0";
const TESSERACT_MODULE = `https://cdn.jsdelivr.net/npm/tesseract.js@${TESSERACT}/dist/tesseract.esm.min.js`;
const TESSDATA = "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main";
/* workerPath and corePath are left to tesseract.js, which derives them from its
   own bundled version. Pinning the core by hand pointed at a major version the
   wrapper could not use, because npm's latest tag for tesseract.js-core lags
   behind the version tesseract.js depends on. */
const PYODIDE_PINNED = "0.29.4";
const WHEEL_PLATFORM = "pyemscripten_2025_0_wasm32";

let worker = null;
let booted = false;
let booting = null;
let running = false;
let queue = [];
let plainText = "";
const pending = new Map(); // request id -> resolver
let nextId = 1;

/* -- worker plumbing ---------------------------------------------------- */

function spawn() {
  worker = new Worker(WORKER_URL);
  worker.onmessage = (event) => handle(event.data);
  worker.onerror = (event) => {
    setEngine("failed", "Engine stopped");
    log("");
    showFailure("The engine stopped unexpectedly.", describe(event.message || event));
    rejectAll("the engine stopped");
    finishRun();
  };
}

/* Every request carries an id and the worker echoes it back, so a new request
   needs no matching entry anywhere in here. Keying replies by name instead is
   how a reply once went unhandled and left the interface waiting for ever. */

function ask(type, payload = {}) {
  const id = nextId++;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject, type });
    worker.postMessage({ id, type, ...payload });
  });
}

function settle(id, value, failed = false) {
  const entry = pending.get(id);
  if (!entry) return;
  pending.delete(id);
  if (failed) {
    entry.reject(value);
  } else {
    entry.resolve(value);
  }
}

function rejectAll(reason) {
  for (const id of [...pending.keys()]) {
    settle(id, new Error(reason), true);
  }
}

function handle(message) {
  // A reply: settle whichever request produced it.
  if (message.id !== undefined) {
    if (message.failed) {
      settle(message.id, new Error(message.failed), true);
    } else {
      settle(message.id, message);
    }
    return;
  }

  // A broadcast.
  switch (message.type) {
    case "status":
      setEngine(message.state, message.text);
      break;
    case "progress":
      showProgress(message.name, message.page, message.pages);
      break;
    case "error":
      showFailure("The engine reported a problem.", message.message);
      rejectAll(message.message);
      break;
  }
}

function boot() {
  if (booted) return Promise.resolve(true);
  if (booting) return booting;
  if (!worker) spawn();
  booting = ask("boot", {
    coreUrl: CORE_URL.href,
    bridgeUrl: BRIDGE_URL.href,
  }).then((answer) => {
    booted = true;
    setEngine("ready", answer.text);
    refresh();
    return true;
  }).catch((error) => {
    booting = null;
    setEngine("failed", "Engine failed to start");
    log("");
    showFailure("The engine did not start.", describe(error));
    throw error;
  });
  return booting;
}

/* -- chrome ------------------------------------------------------------- */

function setEngine(state, text) {
  ui.engine.className = `engine engine--${state}`;
  ui.engineText.textContent = text;
  ui.boot.hidden = state !== "waiting" && state !== "failed";
  ui.boot.textContent = state === "failed" ? "Try again" : "Start engine";
}

function log(line) {
  ui.log.textContent = line;
}

/* Turns whatever went wrong into something a person can act on, keeps the
   trace collapsed, and offers to file it. */

/* A rejected promise can carry anything. tesseract.js rejects with plain
   strings, which is how a failure reached the report as "no detail captured". */
function describe(error) {
  if (error === null || error === undefined) return "";
  if (typeof error === "string") return error;
  if (error instanceof Error) return error.stack || error.message;
  if (error.message) return String(error.message);
  if (error.reason) return describe(error.reason);
  try {
    return JSON.stringify(error);
  } catch {
    return String(error);
  }
}

function guessCause(detail) {
  const text = String(detail || "");
  if (/tsp_core\.py|bridge\.py|returned 404/i.test(text)) {
    return "A file the engine needs did not load. If you are running this " +
      "locally, start it with \u201cpython web/serve.py\u201d.";
  }
  if (/SyntaxError|unterminated|invalid syntax/i.test(text)) {
    return "The engine loaded but would not compile. That is a bug in TSP " +
      "rather than anything you did.";
  }
  if (/micropip|wheel|pymupdf|no matching distribution/i.test(text)) {
    return "PyMuPDF would not install. The pinned Pyodide version and the " +
      "wheel it expects may have drifted apart.";
  }
  if (/NetworkError|Failed to fetch|ERR_|offline/i.test(text)) {
    return "Something blocked the download. A firewall, an extension or a " +
      "dropped connection would each do it.";
  }
  if (/memory|allocat|RangeError/i.test(text)) {
    return "The tab ran out of memory. A smaller document, or a desktop " +
      "browser, should get further.";
  }
  return "Reporting it with the details below is the most useful thing you " +
    "can do next.";
}

function diagnostics(detail) {
  return [
    `TSP browser build`,
    `page: ${location.href}`,
    `pinned pyodide: ${PYODIDE_PINNED}`,
    `wheel platform: ${WHEEL_PLATFORM}`,
    `browser: ${navigator.userAgent}`,
    `when: ${new Date().toISOString()}`,
    ``,
    String(detail || "no detail captured"),
  ].join("\n");
}

function showFailure(lead, detail) {
  const report = diagnostics(detail);
  ui.failureLead.textContent = lead;
  ui.failureHint.textContent = guessCause(detail);
  ui.failureTrace.textContent = report;

  const body = report.length > 1600 ? `${report.slice(0, 1600)}\n[truncated]` : report;
  ui.failureReport.href =
    `${REPO}/issues/new?labels=bug` +
    `&title=${encodeURIComponent(lead)}` +
    `&body=${encodeURIComponent("What happened:\n\n\n---\n\n```\n" + body + "\n```")}`;

  ui.failureCopy.onclick = async () => {
    if (await toClipboard(report)) {
      flash(ui.failureCopy, "Copied");
    } else {
      ui.failureTrace.parentElement.open = true;
    }
  };

  ui.failure.hidden = false;
}

function clearFailure() {
  ui.failure.hidden = true;
}

function notice(html, { ocr = false } = {}) {
  ui.noticeText.innerHTML = html;
  ui.ocrOffer.hidden = !ocr;
  ui.notice.hidden = !html;
}

function showProgress(name, page, pages) {
  const share = pages ? (page / pages) * 100 : 0;
  ui.barFill.style.width = `${share}%`;
  ui.barLabel.textContent = `${name} \u2014 page ${page} of ${pages}`;
}

/* -- queue -------------------------------------------------------------- */

/* One control for every row. It reflects the shared setting where the rows
   agree and reads Mixed where they do not, so it never claims a state the queue
   is not in. */

function buildBulkOptions() {
  const mixed = document.createElement("option");
  mixed.value = "";
  mixed.textContent = "Mixed";
  ui.bulkMode.append(mixed);
  for (const mode of MODES) {
    const option = document.createElement("option");
    option.value = String(mode.value);
    option.textContent = mode.label;
    ui.bulkMode.append(option);
  }
}

function shared(read) {
  if (!queue.length) return undefined;
  const first = read(queue[0]);
  return queue.every((entry) => read(entry) === first) ? first : undefined;
}

function syncBulk() {
  ui.bulk.hidden = queue.length < 2;
  if (ui.bulk.hidden) return;

  const mode = shared((entry) => entry.mode);
  ui.bulkMode.value = mode === undefined ? "" : String(mode);
  ui.bulkMode.disabled = running;

  for (const [box, read] of [
    [ui.bulkTables, (entry) => entry.tables],
    [ui.bulkFigures, (entry) => entry.figures],
  ]) {
    const value = shared(read);
    box.indeterminate = value === undefined;
    box.checked = value === true;
    box.disabled = running;
  }
}

function applyToAll(change) {
  for (const entry of queue) {
    change(entry);
    if (entry.state === "done" || entry.state === "failed") {
      entry.state = "queued";
      entry.report = null;
    }
  }
  recomputeTotals();
  render();
}

function markStale(entry) {
  if (entry.state === "done" || entry.state === "failed") {
    entry.state = "queued";
    entry.report = null;
    recomputeTotals();
    render();
  }
}

function staleAll() {
  let touched = false;
  for (const entry of queue) {
    if (entry.state === "done" || entry.state === "failed") {
      entry.state = "queued";
      entry.report = null;
      touched = true;
    }
  }
  if (touched) {
    recomputeTotals();
    render();
  }
}

function drop(index) {
  const [entry] = queue.splice(index, 1);
  if (entry && entry.report && booted) {
    ask("drop", { name: entry.file.name }).catch(() => {});
  }
  recomputeTotals();
  render();
}

function addFiles(files) {
  const known = new Set(queue.map((e) => `${e.file.name}:${e.file.size}`));
  let added = 0;
  for (const file of files) {
    if (!/\.pdf$/i.test(file.name)) continue;
    const key = `${file.name}:${file.size}`;
    if (known.has(key)) continue;
    known.add(key);
    queue.push({
      file,
      mode: MODES[0].value,
      tables: false,
      figures: false,
      state: "queued",
      report: null,
    });
    added += 1;
  }
  if (added) {
    render();
    log(`${queue.length} file${queue.length === 1 ? "" : "s"} ready`);
    // Choosing a file is unambiguous intent, so make sure the engine is coming.
    if (!booted) boot().catch(() => {});
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
    select.disabled = running;
    select.addEventListener("change", () => {
      entry.mode = Number(select.value);
      markStale(entry);
    });

    const tables = document.createElement("label");
    tables.className = "toggle";
    tables.title =
      "Keep table structure as markdown grids. Slower, costs about the same tokens.";
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = entry.tables;
    box.disabled = running;
    box.addEventListener("change", () => {
      entry.tables = box.checked;
      markStale(entry);
    });
    tables.append(box, document.createTextNode("Tables"));

    const figures = document.createElement("label");
    figures.className = "toggle";
    figures.title =
      "Render charts as images and drop the orphan axis labels they leave behind.";
    const figureBox = document.createElement("input");
    figureBox.type = "checkbox";
    figureBox.checked = entry.figures;
    figureBox.disabled = running;
    figureBox.addEventListener("change", () => {
      entry.figures = figureBox.checked;
      markStale(entry);
    });
    figures.append(figureBox, document.createTextNode("Figures"));

    const state = document.createElement("span");
    state.className = "state";
    if (entry.state === "done" && entry.report) {
      state.classList.add("state--done");
      const bits = [`${entry.report.pages}p`];
      if (entry.report.images) bits.push(`${entry.report.images} img`);
      if (entry.report.tables) bits.push(`${entry.report.tables} tbl`);
      state.textContent = bits.join(", ");
    } else if (entry.state === "failed") {
      state.classList.add("state--failed");
      state.textContent = "failed";
    } else if (entry.state === "working") {
      state.textContent = "working";
    } else {
      state.textContent = "ready";
    }

    const remove = document.createElement("button");
    remove.className = "link remove";
    remove.type = "button";
    remove.textContent = "\u00d7";
    remove.title = `Remove ${entry.file.name}`;
    remove.setAttribute("aria-label", `Remove ${entry.file.name}`);
    remove.disabled = running;
    remove.addEventListener("click", () => drop(index));

    const main = document.createElement("div");
    main.className = "row__main";
    main.append(name, size, select, tables, figures, state, remove);
    row.append(main);

    if (entry.state === "done" && entry.report) {
      row.append(rowActions(entry));
    }

    ui.queue.append(row);
  });

  syncBulk();
  refresh();
}

function scanQueue() {
  return queue
    .filter((entry) => entry.state === "done" && entry.report)
    .map((entry) => ({ entry, scans: entry.report.scans || [] }))
    .filter((job) => job.scans.length);
}

/* Copy, text and files, for this document alone. */
function rowActions(entry) {
  const bar = document.createElement("div");
  bar.className = "row__actions";

  const copy = document.createElement("button");
  copy.type = "button";
  copy.className = "link";
  copy.textContent = "Copy text";
  copy.addEventListener("click", async () => {
    try {
      const answer = await ask("text", { name: entry.file.name });
      flash(copy, (await toClipboard(answer.text)) ? "Copied" : "Blocked");
    } catch (error) {
      log(`${entry.file.name}: ${describe(error)}`);
    }
  });

  const text = document.createElement("button");
  text.type = "button";
  text.className = "link";
  text.textContent = "Download text";
  text.addEventListener("click", async () => {
    try {
      const answer = await ask("text", { name: entry.file.name });
      saveBlob(
        new Blob([answer.text], { type: "text/markdown;charset=utf-8" }),
        optimisedName(entry.file.name, "md")
      );
    } catch (error) {
      log(`${entry.file.name}: ${describe(error)}`);
    }
  });

  bar.append(copy, text);

  // A zip only adds anything when there are page images alongside the text.
  if (entry.report.images) {
    const files = document.createElement("button");
    files.type = "button";
    files.className = "link";
    files.textContent = `Download files (${entry.report.images} images)`;
    files.addEventListener("click", async () => {
      try {
        const answer = await ask("deliver", { name: entry.file.name });
        saveBlob(
          new Blob([answer.bytes], { type: "application/zip" }),
          optimisedName(entry.file.name, "zip")
        );
      } catch (error) {
        log(`${entry.file.name}: ${describe(error)}`);
      }
    });
    bar.append(files);
  }

  return bar;
}

function refresh() {
  const waiting = queue.filter((e) => e.state === "queued").length;
  const finished = queue.filter((e) => e.state === "done").length;

  ui.run.disabled = running || (waiting === 0 && finished === 0);
  if (waiting) {
    ui.run.textContent = `Process ${waiting} file${waiting === 1 ? "" : "s"}`;
  } else if (finished) {
    ui.run.textContent = `Process again`;
  } else {
    ui.run.textContent = "Process files";
  }
  ui.cancel.hidden = !running;
  ui.reset.hidden = running || queue.length === 0;
  ui.bar.hidden = !running;
}

/* -- meter -------------------------------------------------------------- */

const totals = { in: 0, out: 0, images: 0 };

function recomputeTotals() {
  totals.in = 0;
  totals.out = 0;
  totals.images = 0;
  for (const entry of queue) {
    if (entry.state === "done" && entry.report) {
      totals.in += entry.report.tokens_in;
      totals.out += entry.report.tokens_out;
      totals.images += entry.report.images;
    }
  }
  updateMeter();
}

function updateMeter() {
  const cut = totals.in ? 1 - totals.out / totals.in : 0;
  ui.statIn.textContent = totals.in.toLocaleString();
  ui.statOut.textContent = totals.out.toLocaleString();
  ui.statCut.textContent = `${Math.round(cut * 100)}%`;
  ui.statImg.textContent = totals.images.toLocaleString();
  ui.keptBar.style.width = `${totals.in ? (totals.out / totals.in) * 100 : 0}%`;
}

/* -- run ---------------------------------------------------------------- */

async function run() {
  ui.results.hidden = true;
  notice("");
  clearFailure();

  try {
    await boot();
  } catch {
    return;
  }

  // Nothing queued means "Process again": rerun the lot with whatever the
  // settings say now. The File objects are still held, so no re-picking.
  if (!queue.some((entry) => entry.state === "queued")) {
    staleAll();
  }

  running = true;
  render();

  const dpi = Number(ui.dpi.value);

  for (const entry of queue.filter((e) => e.state === "queued")) {
    if (!running) break;
    entry.state = "working";
    render();
    showProgress(entry.file.name, 0, 1);

    try {
      const bytes = await entry.file.arrayBuffer();
      const answer = await ask("process", {
        name: entry.file.name,
        bytes,
        threshold: entry.mode,
        dpi,
        tables: entry.tables,
        figures: entry.figures,
      });
      const report = answer.report;

      if (report.ok) {
        entry.state = "done";
        entry.report = report;
        recomputeTotals();
        log(`${entry.file.name}: ${report.message}`);
      } else {
        entry.state = "failed";
        entry.report = null;
        recomputeTotals();
        log(`${entry.file.name}: ${report.message}`);
      }
    } catch (error) {
      entry.state = "failed";
      log(`${entry.file.name} could not be read.`);
      showFailure(`${entry.file.name} could not be read.`, describe(error));
    }
    render();
  }

  if (running) await offerResults();
  finishRun();
}

function finishRun() {
  running = false;
  ui.barFill.style.width = "0%";
  render();
}

async function offerResults() {
  let output;
  try {
    output = await ask("deliver");
  } catch (error) {
    log(describe(error));
    return;
  }
  if (!output.names.length) {
    log("Nothing produced.");
    return;
  }

  const done = queue.filter((entry) => entry.state === "done");
  const single = done.length === 1 ? done[0].file.name : null;

  // The zip carries everything, including page images.
  const blob = new Blob([output.bytes], { type: "application/zip" });
  if (ui.download.dataset.url) URL.revokeObjectURL(ui.download.dataset.url);
  const zipUrl = URL.createObjectURL(blob);
  ui.download.href = zipUrl;
  ui.download.dataset.url = zipUrl;
  ui.download.download = single
    ? optimisedName(single, "zip")
    : "optimised_documents.zip";
  ui.download.textContent = `Download all files as a zip (${
    output.names.length
  } files, ${humanSize(blob.size)})`;

  // Reveal the zip before fetching the text, so a failure in the step below
  // still leaves a working download.
  ui.results.hidden = false;
  ui.saveFolder.hidden = !("showDirectoryPicker" in window);

  try {
    const answer = await ask("text");
    plainText = answer.text || "";
  } catch (error) {
    plainText = "";
    log(`Text could not be prepared: ${describe(error)}`);
  }

  if (plainText) {
    const textBlob = new Blob([plainText], { type: "text/markdown;charset=utf-8" });
    if (ui.downloadText.dataset.url) {
      URL.revokeObjectURL(ui.downloadText.dataset.url);
    }
    const textUrl = URL.createObjectURL(textBlob);
    ui.downloadText.href = textUrl;
    ui.downloadText.dataset.url = textUrl;
    ui.downloadText.download = single
      ? optimisedName(single, "md")
      : "optimised_documents.md";
    ui.downloadText.textContent = `Download all text (${humanSize(plainText.length)})`;
    ui.copy.textContent = `Copy all text (~${Math.round(
      plainText.length / 4
    ).toLocaleString()} tokens)`;
  }
  ui.copy.hidden = !plainText;
  ui.downloadText.hidden = !plainText;
  log(`Done. ${output.names.length} files ready.`);

  const pending = scanQueue();
  if (pending.length) {
    const pages = pending.reduce((total, job) => total + job.scans.length, 0);
    ui.ocrRun.textContent = `Read ${pages} scanned page${pages === 1 ? "" : "s"}`;
    ui.ocrNote.textContent = ocrReady
      ? "Already loaded."
      : "About 7 MB the first time, then cached. Pages stay on this machine.";
    notice(
      `<strong>${pages} page${pages === 1 ? "" : "s"} hold an image and no text ` +
        `layer</strong>, so nothing was extracted from ${
          pending.length === 1 ? "it" : "them"
        }. Reading ${pages === 1 ? "it" : "them"} takes about a second a page.`,
      { ocr: true }
    );
  }
}

async function copyText() {
  if (!plainText) return;
  if (await toClipboard(plainText)) {
    flash(ui.copy, "Copied");
  } else {
    log("Could not reach the clipboard. Use Download text instead.");
  }
}

/* -- OCR ---------------------------------------------------------------- */

let ocrReady = false;
let ocrEngine = null;

async function startOcr(language) {
  // The ESM build carries a single default export, so a named import of
  // createWorker gives undefined. Accept either shape.
  const loaded = await import(TESSERACT_MODULE);
  const api =
    loaded && typeof loaded.createWorker === "function" ? loaded : loaded.default;
  if (!api || typeof api.createWorker !== "function") {
    throw new Error(
      `tesseract.js loaded but exposed no createWorker. Exports seen: ${Object.keys(
        loaded || {}
      ).join(", ") || "none"}`
    );
  }

  let reported = "";
  const engine = await api.createWorker(language, 1, {
    langPath: TESSDATA,
    gzip: false, // the tessdata repository serves plain .traineddata
    logger: (event) => {
      if (event.status && event.progress !== undefined) {
        ui.barLabel.textContent = `${event.status} \u2014 ${Math.round(
          event.progress * 100
        )}%`;
        ui.barFill.style.width = `${event.progress * 100}%`;
      }
    },
    // Without this the library throws inside a message callback, where nothing
    // can catch it and the reason is lost.
    errorHandler: (problem) => {
      reported = describe(problem);
      log(`OCR engine: ${reported}`);
    },
  }).catch((problem) => {
    throw new Error(
      [
        describe(problem) || reported || "createWorker rejected without a reason",
        `module: ${TESSERACT_MODULE}`,
        `language data: ${TESSDATA}/${language}.traineddata`,
      ].join("\n")
    );
  });
  ocrReady = true;
  return engine;
}

async function runOcr() {
  const jobs = scanQueue();
  if (!jobs.length || running) return;

  const language = ui.ocrLang.value;
  running = true;
  ui.ocrOffer.hidden = true;
  ui.results.hidden = true;
  clearFailure();
  render();

  const total = jobs.reduce((sum, job) => sum + job.scans.length, 0);
  let done = 0;

  try {
    // A change of language needs a fresh engine, so keep it simple and build
    // one per run. Startup is fast once the model is cached.
    if (ocrEngine) {
      await ocrEngine.terminate();
      ocrEngine = null;
    }
    ui.barLabel.textContent = "Fetching the OCR engine";
    ui.barFill.style.width = "0%";
    ocrEngine = await startOcr(language);

    for (const job of jobs) {
      const recognised = {};
      for (const scan of job.scans) {
        if (!running) break;
        done += 1;
        ui.barLabel.textContent = `Reading page ${scan.page} of ${job.entry.file.name} (${done} of ${total})`;
        ui.barFill.style.width = `${(done / total) * 100}%`;

        const answer = await ask("read", { path: scan.image });
        const { data } = await ocrEngine.recognize(
          new Blob([answer.bytes], { type: "image/png" })
        );
        if (data.text && data.text.trim()) {
          recognised[scan.page] = data.text;
        }
      }
      if (!running) break;

      // Fold the words into the document already written. Reprocessing the
      // whole file to place a few pages re-extracted every other page for
      // nothing.
      ui.barLabel.textContent = `Placing the text in ${job.entry.file.name}`;
      const answer = await ask("applyOcr", {
        name: job.entry.file.name,
        ocrText: recognised,
      });
      if (answer.report.ok) {
        job.entry.report = answer.report;
        recomputeTotals();
      }
      render();
    }

    log(`Read ${done} page${done === 1 ? "" : "s"} with OCR.`);
  } catch (error) {
    showFailure("The scanned pages could not be read.", describe(error));
  } finally {
    running = false;
    finishRun();
  }

  await offerResults();
}

async function saveToFolder() {
  if (!("showDirectoryPicker" in window)) return;
  try {
    const root = await window.showDirectoryPicker({
      mode: "readwrite",
      id: "tsp-output", // the browser reopens where you saved last
      startIn: "documents", // Chrome refuses Downloads itself
    });
    ui.folderHint.hidden = true;
    const output = await ask("deliver");
    for (const name of output.names) {
      const answer = await ask("read", { path: name });
      const parts = name.split("/");
      let folder = root;
      for (const part of parts.slice(0, -1)) {
        folder = await folder.getDirectoryHandle(part, { create: true });
      }
      const handle = await folder.getFileHandle(parts.at(-1), { create: true });
      const writable = await handle.createWritable();
      await writable.write(answer.bytes);
      await writable.close();
    }
    log(`Saved ${output.names.length} files to ${root.name}.`);
  } catch (error) {
    // Chrome raises AbortError both when the picker is dismissed and when it
    // judges the chosen folder too sensitive to write to, so the two cases
    // cannot be told apart. Show the hint either way.
    if (error && error.name === "AbortError") {
      ui.folderHint.hidden = false;
      log("No folder saved to.");
    } else {
      log(`Could not save: ${describe(error)}`);
    }
  }
}

/* -- cancel ------------------------------------------------------------- */

function cancel() {
  if (!running) return;
  running = false;

  // A worker running Python cannot be interrupted politely, so end it and start
  // a fresh one. The runtime is cached, so booting again is quick.
  worker.terminate();
  rejectAll("cancelled");
  worker = null;
  booted = false;
  booting = null;

  for (const entry of queue) {
    if (entry.state === "working") entry.state = "queued";
  }
  finishRun();
  log("Cancelled. Restarting the engine.");
  setEngine("loading", "Restarting");
  boot().catch(() => {});
}

function resetAll() {
  queue = [];
  recomputeTotals();
  ui.results.hidden = true;
  notice("");
  plainText = "";
  ui.folderHint.hidden = true;
  clearFailure();
  for (const anchor of [ui.download, ui.downloadText]) {
    if (anchor.dataset.url) {
      URL.revokeObjectURL(anchor.dataset.url);
      delete anchor.dataset.url;
    }
  }
  if (booted) ask("clear").catch(() => {});
  updateMeter();
  render();
  log("");
}

/* -- wiring ------------------------------------------------------------- */

ui.boot.addEventListener("click", () => {
  clearFailure();
  boot().catch(() => {});
});
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
buildBulkOptions();
ui.bulkMode.addEventListener("change", () => {
  const chosen = ui.bulkMode.value;
  if (!chosen) return; // Mixed is a report, not a request
  applyToAll((entry) => {
    entry.mode = Number(chosen);
  });
});
ui.bulkTables.addEventListener("change", () => {
  const wanted = ui.bulkTables.checked;
  applyToAll((entry) => {
    entry.tables = wanted;
  });
});
ui.bulkFigures.addEventListener("change", () => {
  const wanted = ui.bulkFigures.checked;
  applyToAll((entry) => {
    entry.figures = wanted;
  });
});
ui.dpi.addEventListener("change", staleAll);
ui.run.addEventListener("click", () => run());
ui.cancel.addEventListener("click", cancel);
ui.reset.addEventListener("click", resetAll);
ui.saveFolder.addEventListener("click", saveToFolder);
ui.copy.addEventListener("click", copyText);
ui.ocrRun.addEventListener("click", () => runOcr());

/* The engine warms itself as soon as the page opens. It lives on a worker
   thread, so the download and the WebAssembly compile cost the interface
   nothing, and by the time a file is chosen it is usually ready.

   A metered or very slow connection is the exception: 28 MB uninvited is rude,
   so there the button stays and adding a file starts it. */
function metered() {
  const link = navigator.connection;
  if (!link) return false;
  return (
    link.saveData === true ||
    ["slow-2g", "2g"].includes(link.effectiveType)
  );
}

updateMeter();
render();

if (metered()) {
  setEngine("waiting", "Engine idle. 28 MB, so it waits for you on this connection");
} else {
  setEngine("waiting", "Starting the engine");
  boot().catch(() => {});
}
