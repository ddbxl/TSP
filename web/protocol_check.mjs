/* Drive web/worker.js through every request the page can make, in a faked
 * worker environment, and check each one settles.
 *
 *     npm install pyodide
 *     node web/protocol_check.mjs path/to/any.pdf
 *
 * A request whose reply nobody settles leaves the interface waiting for ever,
 * which no static check catches. This runs the real protocol instead.
 *
 * Copyright (C) 2026 Daga D.
 * Licensed under the GNU General Public License v3.0 or later.
 */
import { loadPyodide } from "pyodide";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const WORKER = resolve(HERE, "worker.js");
const BRIDGE = resolve(HERE, "bridge.py");
const ENGINE = resolve(HERE, "..", "src", "tsp", "core.py");
const PDF = process.argv[2];
const WHEEL = process.env.TSP_WHEEL || "";

if (!PDF) {
  console.error("usage: node web/protocol_check.mjs path/to/any.pdf");
  process.exit(2);
}

const fromWorker = [];
const sandbox = {
  self: {
    postMessage: (m) => { fromWorker.push(m); dispatch(m); },
    onmessage: null,
  },
  importScripts: () => { sandbox.self.loadPyodide = loadPyodide; },
  fetch: async (url) => {
    const map = { core: ENGINE, bridge: BRIDGE };
    const key = String(url).includes("bridge") ? "bridge" : "core";
    return { ok: true, text: async () => readFileSync(map[key], "utf8"), json: async () => ({}) };
  },
  console,
  URL, TextDecoder, TextEncoder, Uint8Array, ArrayBuffer,
  structuredClone,
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

// pyodide loads from node_modules; patch the CDN import away
let src = readFileSync(WORKER, "utf8");
if (WHEEL) {
  // Skip the network and use a wheel already on disk.
  src = src.replace(/async function installPyMuPDF\(\) \{[\s\S]*?\n\}/,
    `async function installPyMuPDF() {
       await pyodide.loadPackage(${JSON.stringify(WHEEL)});
       return "local wheel";
     }`);
}
src = src.replace(/pyodide = await self\.loadPyodide\(\{[\s\S]*?\}\);/,
                  'pyodide = await self.loadPyodide({});');
vm.runInContext(src, sandbox);

const pending = new Map();
let nextId = 1;
function dispatch(m) {
  if (m.id !== undefined && pending.has(m.id)) {
    const { resolve, reject } = pending.get(m.id);
    pending.delete(m.id);
    m.failed ? reject(new Error(m.failed)) : resolve(m);
  }
}
function ask(type, payload = {}) {
  const id = nextId++;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    sandbox.self.onmessage({ data: { id, type, ...payload } });
  });
}

const boot = await ask("boot", { coreUrl: "x/tsp_core.py", bridgeUrl: "x/bridge.py" });
console.log("boot ->", boot.text.replace(/via.*/, "via <route>"));

const proc = await ask("process", {
  name: "sample.pdf", bytes: new Uint8Array(readFileSync(PDF)),
  threshold: 5, dpi: 144, tables: false, figures: false,
});
console.log("process ->", proc.report.message);

const text = await ask("text");
console.log("text -> settled;", text.text.length, "chars");

const textOne = await ask("text", { name: "sample.pdf" });
console.log("text (one document) -> settled;", textOne.text.length, "chars");

const out = await ask("deliver");
console.log("deliver ->", out.names.length, "files,", out.bytes.length, "bytes");

const outOne = await ask("deliver", { name: "sample.pdf" });
console.log("deliver (one document) ->", outOne.names.length, "files,",
            outOne.bytes.length, "bytes");

const one = await ask("read", { path: out.names[0] });
console.log("read ->", one.path, one.bytes.length, "bytes");

const applied = await ask("applyOcr", {
  name: "sample.pdf",
  ocrText: { 1: "words recognised elsewhere" },
});
console.log("applyOcr -> settled;", applied.report.message);

await ask("drop", { name: "sample.pdf" });
console.log("drop -> settled");
await ask("clear");
console.log("clear -> settled");

const bad = await ask("nonsense").catch((e) => e.message);
console.log("unknown request ->", bad);

console.log(`\nevery request settled. broadcasts seen: ${
  [...new Set(fromWorker.filter(m => m.id === undefined).map(m => m.type))].join(", ")}`);

if (pending.size) {
  console.error(`\n${pending.size} request(s) never settled`);
  process.exit(1);
}
console.log("all requests settled");
