/* The full, paste-and-run connection string for a database (RDS, Cloud SQL; Postgres and MySQL families), shared by the consoles.
 *
 *   postgresql://user:password@127.0.0.1:5432/db        mysql://user:password@127.0.0.1:3306/db
 *
 * User, password and database come from the instance itself (GET /_wire/_vyomi/db-connect). The host is 127.0.0.1 and the port is the one
 * `vyomi-tunnel` really opened for THIS database (a Postgres record already carries it; MySQL ports are read from the tunnel's /health),
 * so what is shown connects as-is while the tunnel runs. If the tunnel is not running the string is still shown, with a one-line note. */
import { useEffect, useState } from "react";
import { WIRE_BASE } from "./wire.js";

const tunnelBase = () => {
  try { return (localStorage.getItem("nano_local_ext") || "http://127.0.0.1:8090").replace(/\/$/, ""); } catch { return "http://127.0.0.1:8090"; }
};
const SCHEME = { postgres: "postgresql", mysql: "mysql" };

/** The string for one database row + the tunnel's health (null when the tunnel is not reachable). Exported for tests. */
export function connectionString(row, health) {
  if (!row) return "";
  const hit = (health?.dbs || []).find((d) => d.db === "db:" + row.key || d.db === row.key);
  const port = row.port || hit?.host_port || row.default_port;
  const db = row.database || (row.engine === "postgres" ? "postgres" : "");
  const enc = encodeURIComponent;
  return `${SCHEME[row.engine] || row.engine}://${enc(row.user)}:${enc(row.password)}@127.0.0.1:${port}${db ? "/" + enc(db) : ""}`;
}

const BOX = { background: "var(--vy-code-bg, rgba(127,127,127,.14))", borderRadius: 4, padding: "8px 10px", margin: 0, fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace", fontSize: 13, whiteSpace: "pre-wrap", wordBreak: "break-all", flex: 1, minWidth: 0 };
const BTN = { cursor: "pointer", border: "1px solid var(--vy-line, #8a94a3)", background: "transparent", color: "inherit", borderRadius: 4, padding: "4px 10px", fontSize: 12, whiteSpace: "nowrap", height: 28 };
const MUTED = { color: "var(--vy-sub, #5f6b7a)", fontSize: 12, marginTop: 4 };

/** `cloud` aws|gcp, `id` the DB instance identifier (RDS) or instance name (Cloud SQL). */
export default function DbConnect({ cloud, id }) {
  const [row, setRow] = useState(null);
  const [health, setHealth] = useState(undefined);       // undefined = checking, null = tunnel not reachable
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    let live = true;
    const load = async () => {
      try {
        const j = await (await fetch(WIRE_BASE + "/_vyomi/db-connect", { cache: "no-store" })).json();
        const hit = (j.databases || []).find((d) => d.cloud === cloud && d.id === id);
        if (live) setRow(hit || null);
      } catch { if (live) setRow(null); }
      try { const h = await (await fetch(tunnelBase() + "/health", { signal: AbortSignal.timeout(1500) })).json(); if (live) setHealth(h); }
      catch { if (live) setHealth(null); }
    };
    load();
    const t = setInterval(load, 5000);                 // the tunnel publishes a port a moment after the database is available
    return () => { live = false; clearInterval(t); };
  }, [cloud, id]);
  if (!row) return null;
  const text = connectionString(row, health);
  const copy = async () => { try { await navigator.clipboard.writeText(text); } catch { /* selectable */ } setCopied(true); setTimeout(() => setCopied(false), 1500); };
  return (
    <div data-testid="db-connect" style={{ margin: "8px 0" }}>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>Connection string</div>
      <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
        <pre data-testid="db-connect-string" style={BOX}>{text}</pre>
        <button type="button" style={BTN} onClick={copy} aria-label="Copy connection string">{copied ? "Copied" : "Copy"}</button>
      </div>
      {health === null && <div style={MUTED}>Works while vyomi-tunnel is running on this computer.</div>}
    </div>
  );
}
