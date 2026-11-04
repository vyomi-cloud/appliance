// Node driver for tests/conformance/test_rds_parquet_nano.py. Reads a spec JSON on
// stdin, writes the Parquet bytes base64 on stdout, using the VENDORED parquet-wasm +
// apache-arrow from wasm/parquet/.
//   (default)   the browser path itself: installParquet(base) + the lazy
//               globalThis.__nano_parquet_write, with `fetch` shimmed onto the vendored
//               files (Node's fetch has no file: scheme) — so loadEngines() runs as-is.
//   --direct    initSync + buildParquet (isolates the encoder from the loader).
import { readFileSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "wasm", "parquet");
const base = pathToFileURL(root + path.sep).href;
const spec = readFileSync(0, "utf8");
let bytes;
if (process.argv.includes("--direct")) {
  (new Function(readFileSync(path.join(root, "arrow.es2015.min.js"), "utf8"))).call(globalThis);
  const pq = await import(base + "parquet_wasm.js");
  pq.initSync({ module: readFileSync(path.join(root, "parquet_wasm_bg.wasm")) });
  const { buildParquet } = await import(base + "parquet-loader.js");
  bytes = buildParquet(globalThis.Arrow, pq, JSON.parse(spec));
} else {
  const seen = [];
  globalThis.fetch = async (url) => {
    const u = String(url && url.url ? url.url : url);
    seen.push(u);
    if (!u.startsWith(base)) throw new Error("loader tried to reach " + u);
    const data = readFileSync(fileURLToPath(u));
    return new Response(data, { status: 200, headers: u.endsWith(".wasm") ? { "content-type": "application/wasm" } : {} });
  };
  const { installParquet } = await import(base + "parquet-loader.js");
  installParquet(base);
  bytes = await globalThis.__nano_parquet_write(spec);
  process.stderr.write("fetched: " + seen.map((u) => u.slice(base.length)).join(",") + "\n");
}
process.stdout.write(Buffer.from(bytes).toString("base64"));
