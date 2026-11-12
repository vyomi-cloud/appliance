/* Nano boot import-closure check: boots the vendored Pyodide in Node, mounts /core + /wasm exactly like
 * wasm/nano-boot.js (and the relay loaders' CORES lists), then imports EVERY listed core plus the console
 * router (Backends, providers, wire_adapter). Any ImportError / SyntaxError / missing stdlib module that
 * Pyodide lacks fails here instead of at a user's boot.
 *
 *   python3 wasm/fetch_pyodide.py && python3 wasm/build_cores.py
 *   node consoles/tests/nano-core-import-check.mjs
 */
import { readFileSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import { join, dirname } from "node:path";

const W = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "wasm");
const list = (file, name) => {
  const m = readFileSync(join(W, file), "utf8").match(new RegExp(`const ${name}\\s*=\\s*\\[(.*?)\\];`, "s"));
  return m ? [...m[1].matchAll(/"([^"]+)"/g)].map((x) => x[1]) : [];
};
const loaders = { "nano-boot.js": list("nano-boot.js", "CORES"), "relay/nano-endpoint.html": list("relay/nano-endpoint.html", "CORES"), "relay/relay-shared-worker.js": list("relay/relay-shared-worker.js", "CORES") };
const pkgs = list("nano-boot.js", "CORE_PKGS");
const modules = list("nano-boot.js", "MODULES");
const all = [...new Set(Object.values(loaders).flat())];
console.log(`cores: ${Object.entries(loaders).map(([k, v]) => `${k}=${v.length}`).join(" ")} union=${all.length}`);

const { loadPyodide } = await import(pathToFileURL(join(W, "vendor/pyodide/pyodide.mjs")).href);
const py = await loadPyodide({ indexURL: join(W, "vendor/pyodide") + "/" });
try { await py.loadPackage("sqlite3"); } catch (e) { console.log("sqlite3 package skipped:", String(e).slice(0, 100)); }
const put = (p, src) => { const d = dirname(p); py.FS.mkdirTree(d); py.FS.writeFile(p, src); };
py.FS.mkdirTree("/core"); py.FS.writeFile("/core/__init__.py", "");
for (const c of all) put("/core/" + c, readFileSync(join(W, "core", c), "utf8"));
for (const c of pkgs) put("/core/" + c, readFileSync(join(W, "core", c), "utf8"));
py.FS.mkdirTree("/wasm/backends"); py.FS.mkdirTree("/wasm/providers");
py.FS.writeFile("/wasm/__init__.py", ""); py.FS.writeFile("/wasm/backends/__init__.py", "");
for (const m of modules) put("/wasm/" + m, readFileSync(join(W, m), "utf8"));

const res = JSON.parse(py.runPython(`
import sys, json, importlib, traceback
sys.path.insert(0, "/")
bad = {}
names = ${JSON.stringify(all.map((c) => c.replace(/\.py$/, "").replace(/\//g, ".")))} + ${JSON.stringify(pkgs.filter((p) => !p.endsWith("__init__.py")).map((c) => c.replace(/\.py$/, "").replace(/\//g, ".")))}
for n in names:
    try: importlib.import_module("core." + n)
    except BaseException as e: bad["core." + n] = f"{type(e).__name__}: {e}"
for n in ["wasm.backends.store", "wasm.providers", "wasm.providers.console_next_adapter", "wasm.providers.wire_adapter"]:
    try: importlib.import_module(n)
    except BaseException as e: bad[n] = f"{type(e).__name__}: {e}"
try:
    from wasm.backends.store import Backends
    Backends()
except BaseException as e: bad["Backends()"] = f"{type(e).__name__}: {e}"
json.dumps({"n": len(names), "bad": bad})
`));
// Loader parity (informational): nano-boot.js also mounts the page-side console-adapter cores the relays do not.
const drift = all.filter((c) => Object.values(loaders).some((l) => !l.includes(c)));
console.log(`imported ${res.n} core modules + router: ${Object.keys(res.bad).length} failure(s); loader drift: ${drift.length}`);
for (const [k, v] of Object.entries(res.bad)) console.log("FAIL " + k + " -> " + v);
for (const c of drift) console.log("NOTE (page-side console adapters only; relays do not mount it) " + c + " missing from: " + Object.entries(loaders).filter(([, l]) => !l.includes(c)).map(([k]) => k).join(", "));
process.exit(Object.keys(res.bad).length ? 1 : 0);
