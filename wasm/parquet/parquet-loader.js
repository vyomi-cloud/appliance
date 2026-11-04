/* Vyomi-Nano — Parquet writer (browser side of the RDS StartExportTask export).
 *
 * core/rds_core.py builds each exported table as (schema, columns) and awaits a
 * platform Parquet writer. Offline that is pyarrow (core/parquet_pyarrow.py); in
 * the browser it is THIS: parquet-wasm 0.7.1 (Rust arrow-rs/parquet compiled to
 * WASM) + apache-arrow 18.1.0 (JS), both VENDORED next to this file (never a CDN)
 * and LAZY-LOADED on the first export only. The Python side calls
 *
 *     globalThis.__nano_parquet_write(specJson) -> Promise<Uint8Array>
 *
 * with specJson = {"schema": [{"name", "type"}], "columns": [[...], ...]}, types
 * int64 | float64 | bool | string | binary (binary cells arrive as {"$b64": ...}).
 * The bytes are a gzip-compressed Parquet file; Python writes them into the
 * simulator's own S3 store. If the engine can't load, the promise REJECTS and the
 * export task FAILS with that cause (no fallback to another format).
 *
 * installParquet(baseUrl?) only defines the global (cheap, idempotent); nothing is
 * fetched until an export actually runs. buildParquet(Arrow, pq, spec) is exported
 * for the Node conformance test (tests/conformance/test_rds_parquet_nano.py).
 *
 * Vendored from npm (licenses alongside): parquet-wasm@0.7.1 esm/ build
 *   parquet_wasm.js       sha256 99d058b1aaf421415c0192b6ad39dffe440463f20decba9bca0c8f3e229fc094
 *   parquet_wasm_bg.wasm  sha256 e705bcfeecb5cb3cab61833692b7ebd4d019989b75951c35b2e5b0e49bb2779e
 * apache-arrow@18.1.0 Arrow.es2015.min.js -> arrow.es2015.min.js
 *                       sha256 c616f1d93e95cd11fe05dcf45a569a2b56834b55bd88bf8c562aa7c5a89fc6de
 */

const HERE = new URL("./", import.meta.url).href;

function b64ToBytes(s) {
  const bin = atob(s);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

function arrowType(Arrow, t) {
  switch (t) {
    case "int64": return new Arrow.Int64();
    case "float64": return new Arrow.Float64();
    case "bool": return new Arrow.Bool();
    case "binary": return new Arrow.Binary();
    default: return new Arrow.Utf8();
  }
}

function cell(v, t) {
  if (v === null || v === undefined) return null;
  if (t === "int64") return BigInt(v);
  if (t === "binary") return (v && typeof v === "object" && "$b64" in v) ? b64ToBytes(v.$b64) : null;
  return v;
}

/** spec -> gzip Parquet bytes, given loaded apache-arrow + parquet-wasm modules. */
export function buildParquet(Arrow, pq, spec) {
  const vectors = {};
  (spec.schema || []).forEach((f, i) => {
    const vals = ((spec.columns || [])[i] || []).map((v) => cell(v, f.type));
    vectors[f.name] = Arrow.vectorFromArray(vals, arrowType(Arrow, f.type));
  });
  let table = new Arrow.Table(vectors);
  if (!(spec.schema || []).length) table = new Arrow.Table();
  const ipc = Arrow.tableToIPC(table, "stream");
  const wasmTable = pq.Table.fromIPCStream(ipc);
  const props = new pq.WriterPropertiesBuilder().setCompression(pq.Compression.GZIP).build();
  return pq.writeParquet(wasmTable, props);
}

let _loading = null;

async function loadEngines(base) {
  // apache-arrow ships a self-contained UMD build; evaluated as a plain script it
  // defines globalThis.Arrow (works in tabs, workers and the SharedWorker alike).
  if (!globalThis.Arrow || !globalThis.Arrow.tableToIPC) {
    const r = await fetch(base + "arrow.es2015.min.js");
    if (!r.ok) throw new Error("apache-arrow not found (" + r.status + ")");
    (new Function(await r.text())).call(globalThis);
  }
  const pq = await import(base + "parquet_wasm.js");
  await pq.default({ module_or_path: base + "parquet_wasm_bg.wasm" });
  return { Arrow: globalThis.Arrow, pq };
}

export function installParquet(base = HERE) {
  if (typeof globalThis.__nano_parquet_write === "function") return true;   // idempotent
  globalThis.__nano_parquet_write = async (specJson) => {
    if (!_loading) _loading = loadEngines(base).catch((e) => { _loading = null; throw e; });
    let eng;
    try { eng = await _loading; }
    catch (e) { throw new Error("parquet-wasm failed to load: " + (e && e.message || e)); }
    return buildParquet(eng.Arrow, eng.pq, JSON.parse(specJson));
  };
  return true;
}
