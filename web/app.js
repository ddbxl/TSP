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
  log: el("log"),
};

let worker = null;
let booted = false;
let booting = null;
let running = false;
let queue = [];
let plainText = "";
const pending = new Map(); // request type -> resolver

/* -- worker plumbing ---------------------------------------------------- */

function spawn() {
  worker = new Worker(WORKER_URL);
  worker.onmessage = (event) => handle(event.data);
  worker.onerror = (event) => {
    setEngine("failed", "Engine crashed");
    log(String(event.message || "worker error"));
    finishRun();
  };
}

function ask(type, payload = {}) {
  return new Promise((resolve, reject) => {
    pending.set(type, { resolve, reject });
    worker.postMessage({ type, ...payload });
  });
}

function settle(type, value, failed = false) {
  const entry = pending.get(type);
  if (!entry) return;
  pending.delete(type);
  if (failed) {
    entry.reject(value);
  } else {
    entry.resolve(value);
  }
}

function handle(message) {
  switch (message.type) {
    case "status":
      setEngine(message.state, message.text);
      break;
    case "ready":
      booted = true;
      setEngine("ready", message.text);
      settle("boot", true);
      refresh();
      break;
    case "progress":
      showProgress(message.name, message.page, message.pages);
      break;
    case "result":
      settle("process", message.report);
      break;
    case "output":
      settle("deliver", message);
      break;
    case "file":
      settle("read", message);
      break;
    case "cleared":
      settle("clear", true);
      break;
    case "error":
      log(message.message);
      for (const type of [...pending.keys()]) {
        settle(type, new Error(message.message), true);
      }
      break;
  }
}

function boot() {
  if (booted) return Promise.resolve(true);
  if (booting) return booting;
  if (!worker) spawn();
  booting = ask("boot", { coreUrl: CORE_URL.href }).catch((error) => {
    booting = null;
    setEngine("failed", "Engine failed to start");
    log(
      `${error.message}\n\nOpen the console for the full trace. A mismatch ` +
        `between the pinned Pyodide version and the wheel platform is the ` +
        `usual cause; see docs/BROWSER.md.`
    );
    throw error;
  });
  return booting;
}

/* -- chrome ------------------------------------------------------------- */

function setEngine(state, text) {
  ui.engine.className = `engine engine--${state}`;
  ui.engineText.textContent = text;
  ui.boot.hidden = state !== "waiting" && state !== "failed";
}

function log(line) {
  ui.log.textContent = line;
}

function notice(html) {
  ui.notice.innerHTML = html;
  ui.notice.hidden = !html;
}

function showProgress(name, page, pages) {
  const share = pages ? (page / pages) * 100 : 0;
  ui.barFill.style.width = `${share}%`;
  ui.barLabel.textContent = `${name} \u2014 page ${page} of ${pages}`;
}

/* -- queue -------------------------------------------------------------- */

function addFiles(files) {
  const known = new Set(queue.map((e) => `${e.file.name}:${e.file.size}`));
  let added = 0;
  for (const file of files) {
    if (!/\.pdf$/i.test(file.name)) continue;
    const key = `${file.name}:${file.size}`;
    if (known.has(key)) continue;
    known.add(key);
    queue.push({ file, mode: MODES[0].value, tables: false, state: "queued" });
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
    select.disabled = running;
    select.addEventListener("change", () => {
      entry.mode = Number(select.value);
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
    });
    tables.append(box, document.createTextNode("Tables"));

    const state = document.createElement("span");
    state.className = "state";
    if (entry.state === "done") {
      state.classList.add("state--done");
      const bits = [`${entry.pages}p`];
      if (entry.images) bits.push(`${entry.images} img`);
      if (entry.tableCount) bits.push(`${entry.tableCount} tbl`);
      state.textContent = bits.join(", ");
    } else if (entry.state === "failed") {
      state.classList.add("state--failed");
      state.textContent = "failed";
    } else if (entry.state === "working") {
      state.textContent = "working";
    } else if (!running) {
      const remove = document.createElement("button");
      remove.className = "link";
      remove.type = "button";
      remove.textContent = "Remove";
      remove.addEventListener("click", () => {
        queue.splice(index, 1);
        render();
      });
      state.append(remove);
    }

    row.append(name, size, select, tables, state);
    ui.queue.append(row);
  });

  refresh();
}

function refresh() {
  const waiting = queue.filter((e) => e.state === "queued").length;
  ui.run.disabled = running || waiting === 0;
  ui.run.textContent = waiting
    ? `Process ${waiting} file${waiting === 1 ? "" : "s"}`
    : "Process files";
  ui.cancel.hidden = !running;
  ui.reset.hidden = running || queue.length === 0;
  ui.bar.hidden = !running;
}

/* -- meter -------------------------------------------------------------- */

const totals = { in: 0, out: 0, images: 0 };

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

  try {
    await boot();
  } catch {
    return;
  }

  running = true;
  render();

  const dpi = Number(ui.dpi.value);
  let scannedTotal = 0;

  for (const entry of queue.filter((e) => e.state === "queued")) {
    if (!running) break;
    entry.state = "working";
    render();
    showProgress(entry.file.name, 0, 1);

    try {
      const bytes = await entry.file.arrayBuffer();
      const report = await ask("process", {
        name: entry.file.name,
        bytes,
        threshold: entry.mode,
        dpi,
        tables: entry.tables,
      });

      if (report.ok) {
        entry.state = "done";
        entry.pages = report.pages;
        entry.images = report.images;
        entry.tableCount = report.tables;
        totals.in += report.tokens_in;
        totals.out += report.tokens_out;
        totals.images += report.images;
        if (report.needs_ocr) scannedTotal += report.scanned;
        updateMeter();
        log(`${entry.file.name}: ${report.message}`);
      } else {
        entry.state = "failed";
        log(`${entry.file.name}: ${report.message}`);
      }
    } catch (error) {
      entry.state = "failed";
      log(`${entry.file.name}: ${error.message}`);
    }
    render();
  }

  if (running) await offerResults(scannedTotal);
  finishRun();
}

function finishRun() {
  running = false;
  ui.barFill.style.width = "0%";
  render();
}

async function offerResults(scannedTotal) {
  let output;
  try {
    output = await ask("deliver");
  } catch (error) {
    log(error.message);
    return;
  }
  if (!output.names.length) {
    log("Nothing produced.");
    return;
  }

  // The zip carries everything, including page images.
  const blob = new Blob([output.bytes], { type: "application/zip" });
  if (ui.download.dataset.url) URL.revokeObjectURL(ui.download.dataset.url);
  const zipUrl = URL.createObjectURL(blob);
  ui.download.href = zipUrl;
  ui.download.dataset.url = zipUrl;
  ui.download.textContent = `Download everything as a zip (${
    output.names.length
  } files, ${(blob.size / 1048576).toFixed(1)} MB)`;

  // The text on its own is what most people are after.
  try {
    const answer = await ask("text");
    plainText = answer.text || "";
  } catch {
    plainText = "";
  }

  if (plainText) {
    const textBlob = new Blob([plainText], { type: "text/plain;charset=utf-8" });
    if (ui.downloadText.dataset.url) {
      URL.revokeObjectURL(ui.downloadText.dataset.url);
    }
    const textUrl = URL.createObjectURL(textBlob);
    const done = queue.filter((e) => e.state === "done");
    ui.downloadText.href = textUrl;
    ui.downloadText.dataset.url = textUrl;
    ui.downloadText.download =
      done.length === 1
        ? `${done[0].file.name.replace(/\.pdf$/i, "")}.txt`
        : "tsp.txt";
    const kb = plainText.length / 1024;
    ui.downloadText.textContent = `Download text (${
      kb < 1024 ? kb.toFixed(0) + " KB" : (kb / 1024).toFixed(1) + " MB"
    })`;
    ui.copy.textContent = `Copy text (~${Math.round(
      plainText.length / 4
    ).toLocaleString()} tokens)`;
  }
  ui.copy.hidden = !plainText;
  ui.downloadText.hidden = !plainText;

  ui.results.hidden = false;
  ui.saveFolder.hidden = !("showDirectoryPicker" in window);
  log(`Done. ${output.names.length} files ready.`);

  if (scannedTotal) {
    notice(
      `<strong>${scannedTotal} pages hold an image and no text layer</strong>, ` +
        `so they came out empty. Reading them needs OCR, which this page cannot ` +
        `do. Run <a href="https://ocrmypdf.readthedocs.io" target="_blank" ` +
        `rel="noopener">OCRmyPDF</a> over the file first, or use the desktop ` +
        `build with Tesseract installed.`
    );
  }
}

async function copyText() {
  if (!plainText) return;
  const label = ui.copy.textContent;
  try {
    await navigator.clipboard.writeText(plainText);
  } catch {
    // Older browsers, or a page without clipboard permission.
    const holder = document.createElement("textarea");
    holder.value = plainText;
    holder.setAttribute("readonly", "");
    holder.style.position = "fixed";
    holder.style.opacity = "0";
    document.body.append(holder);
    holder.select();
    const worked = document.execCommand && document.execCommand("copy");
    holder.remove();
    if (!worked) {
      log("Could not reach the clipboard. Use Download text instead.");
      return;
    }
  }
  ui.copy.textContent = "Copied";
  ui.copy.disabled = true;
  setTimeout(() => {
    ui.copy.textContent = label;
    ui.copy.disabled = false;
  }, 1600);
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
      log(`Could not save: ${error && error.message ? error.message : error}`);
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
  pending.clear();
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
  totals.in = totals.out = totals.images = 0;
  ui.results.hidden = true;
  notice("");
  plainText = "";
  ui.folderHint.hidden = true;
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
ui.cancel.addEventListener("click", cancel);
ui.reset.addEventListener("click", resetAll);
ui.saveFolder.addEventListener("click", saveToFolder);
ui.copy.addEventListener("click", copyText);

setEngine("waiting", "Engine idle, 28 MB to download on first use");
updateMeter();
render();
