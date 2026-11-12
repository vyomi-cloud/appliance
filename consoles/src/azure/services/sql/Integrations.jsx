/* SQL database "Mirror database in Fabric" + "Power BI".
 * Mirroring is REAL replication: a worker (core/azure_sql_mirror_core.py) reads the tables from the real SQL engine and writes
 * Parquet files into the simulator's Blob store, incrementally (changed tables only, row-level insert/remove counts), with the
 * sync status kept next to the files. Microsoft Fabric itself is not in scope. Power BI shows the SQL connection details only. */
import { useState } from "react";
import { Button, Field, Input } from "@fluentui/react-components";
import { ArrowClockwise20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { restJson } from "../../../common/wire.js";
import { getSubscription } from "../../kit/arm.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ErrorBar, InfoBar, KV, Loading, fmtDate } from "../../kit/common.jsx";
import * as api from "./api.js";

const Q = { "api-version": "2024-01-01" };
const base = (rg) => `/subscriptions/${getSubscription()}/resourceGroups/${rg}/providers/Microsoft.Vyomi/fabricMirrors`;
const plane = (a) => `/azure-sql/servers/${encodeURIComponent(a.server)}/databases/${encodeURIComponent(a.name)}/mirror`;

export function FabricMirror({ a }) {
  const notify = useNotify();
  const mirrorName = `${a.server}-${a.name}`.slice(0, 63);
  const m = useAsync(async () => {
    const rec = (await restJson("GET", base(a.resourceGroup), { query: Q })).value
      .find((x) => x.properties.sqlServerName === a.server && x.properties.databaseName === a.name) || null;
    if (!rec) return null;
    const st = await restJson("GET", `${plane(a)}/status`, { query: { container: rec.properties.destinationContainer, prefix: rec.properties.destinationPrefix } });
    return { rec, st };
  }, [a.id]);
  const [form, setForm] = useState({ ws: "", tables: "" });
  const act = async (fn, ok) => { try { await fn(); if (ok) notify.success(ok, "Done"); m.reload(); } catch (e) { notify.error(e, "Mirroring request failed"); } };
  const rec = m.data?.rec, st = m.data?.st, p = rec?.properties;
  const tables = Object.entries(st?.tables || {});
  return (
    <>
      <div className="vy-panel-title">{a.name} | Mirror database in Fabric</div>
      <CapabilityContainer id="azure.sql.integrations" title="Mirror database in Fabric">
        <ErrorBar error={m.error} />
        {m.loading && !m.data && !m.error ? <Loading /> : !rec ? (
          <section className="vy-form-section" aria-label="Configure mirroring">
            <h3>Configure mirroring</h3>
            <Field label="Fabric workspace label"><Input value={form.ws} onChange={(_, d) => setForm({ ...form, ws: d.value })} aria-label="Fabric workspace" /></Field>
            <Field label="Tables (comma separated, empty = all tables)"><Input value={form.tables} onChange={(_, d) => setForm({ ...form, tables: d.value })} aria-label="Tables" /></Field>
            <div className="vy-cmdbar"><Button appearance="primary" disabled={!form.ws}
              onClick={() => act(() => restJson("PUT", `${base(a.resourceGroup)}/${mirrorName}`, { query: Q, body: { location: a.location, properties: {
                sqlServerName: a.server, databaseName: a.name, fabricWorkspace: form.ws, tables: form.tables.split(",").map((t) => t.trim()).filter(Boolean) } } }), "Mirroring configured.")}>Create mirror</Button></div>
          </section>
        ) : (
          <>
            <div className="vy-cmdbar" role="toolbar" aria-label="Mirroring commands">
              <Button icon={<ArrowClockwise20Regular />} onClick={m.reload}>Refresh</Button>
              <Button appearance="primary" disabled={p.state !== "Running"}
                onClick={() => act(() => restJson("POST", `${plane(a)}/sync`, { body: { container: p.destinationContainer, prefix: p.destinationPrefix, tables: p.tables } }), "Sync completed.")}>Sync now</Button>
              {p.state === "Running"
                ? <Button onClick={() => act(() => restJson("POST", `${base(a.resourceGroup)}/${rec.name}/stop`, { query: Q }), "Mirroring stopped.")}>Stop mirroring</Button>
                : <Button onClick={() => act(() => restJson("POST", `${base(a.resourceGroup)}/${rec.name}/start`, { query: Q }), "Mirroring started.")}>Start mirroring</Button>}
              <Button onClick={() => act(() => restJson("DELETE", `${base(a.resourceGroup)}/${rec.name}`, { query: Q }), "Mirror configuration removed (replicated files are kept).")}>Remove mirror</Button>
            </div>
            <div style={{ display: "flex", gap: 24, flexWrap: "wrap", margin: "12px 0" }}>
              <KV label="Status" value={p.state} />
              <KV label="Workspace label" value={p.fabricWorkspace} />
              <KV label="Landing zone" value={`${p.destinationContainer}/${p.destinationPrefix}`} />
              <KV label="Syncs" value={st?.syncCount ?? 0} />
              <KV label="Last sync" value={st?.completedAt ? fmtDate(st.completedAt) : "Never"} />
            </div>
            <table className="vy-grid" style={{ width: "100%" }} aria-label="Mirrored tables">
              <thead><tr><th>Table</th><th>State</th><th>Rows</th><th>Inserted</th><th>Removed</th><th>Parquet file</th></tr></thead>
              <tbody>
                {tables.length === 0 && <tr><td colSpan={6}>Nothing replicated yet. Choose Sync now.</td></tr>}
                {tables.map(([k, v]) => <tr key={k}><td>{k}</td><td>{v.state}</td><td>{v.rows}</td><td>{v.rowsInserted}</td><td>{v.rowsRemoved}</td><td>{v.file}</td></tr>)}
              </tbody>
            </table>
          </>
        )}
        <InfoBar>Tables are really copied from this database into Parquet files in Blob storage (container above), changed tables only. Syncs run when you choose Sync now. Microsoft Fabric itself is not in scope for Vyomi: there is no OneLake, workspace or SQL analytics endpoint, only the Parquet landing zone.</InfoBar>
      </CapabilityContainer>
    </>
  );
}

export function PowerBiInfo({ a }) {
  const cs = `Server=tcp:${api.serverFqdn(a.server)},1433;Database=${a.name};`;
  return (
    <>
      <div className="vy-panel-title">{a.name} | Power BI</div>
      <CapabilityContainer id="azure.sql.integrations" title="Power BI">
        <p>Power BI Desktop connects to this database with its SQL Server connector. Use these values:</p>
        <div style={{ display: "flex", gap: 24, flexWrap: "wrap", margin: "12px 0" }}>
          <KV label="Server" value={api.serverFqdn(a.server)} />
          <KV label="Database" value={a.name} />
          <KV label="Connection string" value={cs} />
        </div>
        <InfoBar title="Not in scope">The Power BI service is not in scope for Vyomi; the connection details above are what Power BI Desktop needs.</InfoBar>
      </CapabilityContainer>
    </>
  );
}
