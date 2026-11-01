/* UI-conformance fixtures for Cloud SQL (native Cloud SQL Admin REST v1beta4, no
 * SigV4 — svc: null). */
const PROJECT = "vyomi-project";   // consoles/src/gcp/project.js DEFAULT_PROJECT
const base = `/sql/v1beta4/projects/${PROJECT}/instances`;

async function ensureInstance(wire) {
  await wire("POST", base, { svc: null, body: { name: "uic-instance", databaseVersion: "POSTGRES_15" } }).catch(() => {});
}

export default {
  "sql-instance": async (wire) => { await ensureInstance(wire); return "uic-instance"; },
  "live-instance": async (wire, uniq) => { await wire("POST", base, { svc: null, body: { name: uniq, databaseVersion: "POSTGRES_15" } }); return uniq; },
  "live-database": async (wire, uniq) => { await ensureInstance(wire); await wire("POST", `${base}/uic-instance/databases`, { svc: null, body: { name: uniq } }); return uniq; },
  "live-user": async (wire, uniq) => { await ensureInstance(wire); await wire("POST", `${base}/uic-instance/users`, { svc: null, body: { name: uniq, password: "Password123!", host: "%" } }); return uniq; },
  "live-backup": async (wire, uniq) => { await ensureInstance(wire); await wire("POST", `${base}/uic-instance/backupRuns`, { svc: null, body: { description: uniq } }); return uniq; },
  "live-label": async (wire, uniq) => { await ensureInstance(wire); await wire("PATCH", `${base}/uic-instance`, { svc: null, body: { settings: { userLabels: { live: uniq } } } }); return uniq; },
  "live-replica": async (wire, uniq) => { await ensureInstance(wire); await wire("POST", base, { svc: null, body: { name: uniq, masterInstanceName: "uic-instance" } }); return uniq; },
  "live-operation": async (wire, uniq) => { await wire("POST", base, { svc: null, body: { name: uniq, databaseVersion: "POSTGRES_15" } }); return uniq; },
  // gcp.sql.insights: a REAL query run through Cloud SQL Studio's query RPC, logged by
  // core/gcp_cloudsql_core.py:_log_query — Query insights' "Recent queries" must show it.
  "live-query-insight": async (wire, uniq) => {
    await ensureInstance(wire);
    const sql = `SELECT '${uniq}' AS marker`;
    await wire("POST", `${base}/uic-instance/query`, { svc: null, body: { sql } });
    return sql;
  },
};
