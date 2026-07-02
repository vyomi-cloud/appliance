/* Vyomi-Nano — PGlite engine loader (browser side of the RDS data-plane swap).
 *
 * The RDS data plane runs behind the SqlStore seam (core/sql_store.py). The Nano
 * default engine is stdlib sqlite3 (real SQL, runs in Pyodide). PGliteSqlStore
 * swaps in REAL Postgres (Postgres compiled to WASM) for genuine dialect/wire
 * fidelity — `$1` placeholders, SERIAL, RETURNING, ILIKE, real types — so an
 * unmodified Postgres-SQL app validates against the in-browser sim faithfully.
 *
 * PGlite is async; the Python engine (PGliteSqlStore.aexecute_sql) awaits a
 * factory the page must install on `globalThis`:
 *
 *     globalThis.__nano_pglite_new : async () => <a fresh PGlite database>
 *
 * This is the EXACT contract proven by tests/conformance/test_rds_pglite_core.py
 * (run_pglite) on real Pyodide. Call installPGlite() once during boot BEFORE the
 * RDS data plane runs; it's idempotent and lazy (the heavy WASM only loads when a
 * database is actually created).
 *
 * Returns true if the factory is installed, false if PGlite couldn't be loaded
 * (the caller should then keep the sqlite3 engine — never a hard failure).
 */
const PGLITE_URL = "https://cdn.jsdelivr.net/npm/@electric-sql/pglite/dist/index.js";

export async function installPGlite(url = PGLITE_URL) {
  if (typeof globalThis.__nano_pglite_new === "function") return true;  // idempotent
  try {
    const { PGlite } = await import(url);
    // One PGlite database per RDS instance id (the engine calls this per-instance).
    globalThis.__nano_pglite_new = async () => await PGlite.create();
    return true;
  } catch (e) {
    console.warn("[nano] PGlite unavailable, RDS keeps the sqlite3 engine:", String(e));
    return false;
  }
}
