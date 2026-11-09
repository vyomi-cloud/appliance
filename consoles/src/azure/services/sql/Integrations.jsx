/* SQL database "Mirror database in Fabric" + "Power BI": Dev Simplified. Mirroring is a configuration record
 * (Microsoft.Vyomi/fabricMirrors, core/azure_devsimplified_core.py) with a SIMULATED sync status: no Microsoft Fabric workspace
 * is contacted and no data is replicated. Power BI offers the connection details a Power BI Desktop user would type in. */
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

export function FabricMirror({ a }) {
  const notify = useNotify();
  const mirrorName = `${a.server}-${a.name}`.slice(0, 63);
  const m = useAsync(async () => (await restJson("GET", base(a.resourceGroup), { query: Q })).value
    .find((x) => x.properties.sqlServerName === a.server && x.properties.databaseName === a.name) || null, [a.id]);
  const [form, setForm] = useState({ ws: "", tables: "" });
  const act = async (fn, ok) => { try { await fn(); if (ok) notify.success(ok, "Done"); m.reload(); } catch (e) { notify.error(e, "Mirroring request failed"); } };
  const rec = m.data, p = rec?.properties;
  return (
    <>
      <div className="vy-panel-title">{a.name} | Mirror database in Fabric</div>
      <CapabilityContainer id="azure.sql.integrations" title="Mirror database in Fabric">
        <ErrorBar error={m.error} />
        {m.loading && !m.data ? <Loading /> : !rec ? (
          <section className="vy-form-section" aria-label="Configure mirroring">
            <h3>Configure mirroring</h3>
            <Field label="Fabric workspace name"><Input value={form.ws} onChange={(_, d) => setForm({ ...form, ws: d.value })} aria-label="Fabric workspace" /></Field>
            <Field label="Tables (comma separated, empty = all tables)"><Input value={form.tables} onChange={(_, d) => setForm({ ...form, tables: d.value })} aria-label="Tables" /></Field>
            <div className="vy-cmdbar"><Button appearance="primary" disabled={!form.ws}
              onClick={() => act(() => restJson("PUT", `${base(a.resourceGroup)}/${mirrorName}`, { query: Q, body: { location: a.location, properties: {
                sqlServerName: a.server, databaseName: a.name, fabricWorkspace: form.ws, tables: form.tables.split(",").map((t) => t.trim()).filter(Boolean) } } }), "Mirroring configuration saved.")}>Start mirroring</Button></div>
          </section>
        ) : (
          <>
            <div className="vy-cmdbar" role="toolbar" aria-label="Mirroring commands">
              <Button icon={<ArrowClockwise20Regular />} onClick={m.reload}>Refresh</Button>
              {p.state === "Running"
                ? <Button onClick={() => act(() => restJson("POST", `${base(a.resourceGroup)}/${rec.name}/stop`, { query: Q }), "Mirroring stopped.")}>Stop mirroring</Button>
                : <Button onClick={() => act(() => restJson("POST", `${base(a.resourceGroup)}/${rec.name}/start`, { query: Q }), "Mirroring started.")}>Start mirroring</Button>}
              <Button disabled={p.state !== "Running"} onClick={() => act(() => restJson("POST", `${base(a.resourceGroup)}/${rec.name}/sync`, { query: Q }), "Sync requested (Dev Simplified).")}>Sync now</Button>
              <Button onClick={() => act(() => restJson("DELETE", `${base(a.resourceGroup)}/${rec.name}`, { query: Q }), "Mirroring configuration removed.")}>Remove mirroring</Button>
            </div>
            <div style={{ display: "flex", gap: 24, flexWrap: "wrap", margin: "12px 0" }}>
              <KV label="Status" value={p.state} />
              <KV label="Fabric workspace" value={p.fabricWorkspace} />
              <KV label="Tables" value={p.tables.length ? p.tables.join(", ") : "All tables"} />
              <KV label="Simulated syncs" value={p.simulatedSync.syncCount} />
              <KV label="Last simulated sync" value={p.simulatedSync.lastSyncTime ? fmtDate(p.simulatedSync.lastSyncTime) : "--"} />
            </div>
          </>
        )}
        <InfoBar>Dev Simplified: the mirroring settings and run state are stored, and the sync status is simulated. No Microsoft Fabric workspace is contacted and no data is replicated or readable anywhere.</InfoBar>
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
        <InfoBar>Dev Simplified: Vyomi offers the connection details only. There is no Power BI service, dataset publishing or embedded report designer.</InfoBar>
      </CapabilityContainer>
    </>
  );
}
