/* SQL: server connection policy, Dynamic Data Masking, Ledger and Maintenance pages — real ARM
 * resources (connectionPolicies/default, dataMaskingPolicies/Default[/rules], database properties),
 * round-tripped over the native wire; see core/capabilities/azure/sql.json for what is enforced. */
import { useState } from "react";
import { Button, Field, Input, Select } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { restJson } from "../../../common/wire.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ErrorBar, InfoBar, KV, Loading } from "../../kit/common.jsx";
import * as api from "./api.js";

const Q = { "api-version": api.API_VERSION };
export const getConnectionPolicy = async (serverId) => (await restJson("GET", `${serverId}/connectionPolicies/default`, { query: Q }).catch(() => null))?.properties?.connectionType || "Default";
export const putConnectionPolicy = (serverId, connectionType) => restJson("PUT", `${serverId}/connectionPolicies/default`, { query: Q, body: { properties: { connectionType } } });

export function ConnectionPolicy({ serverId }) {
  const notify = useNotify();
  const cur = useAsync(() => getConnectionPolicy(serverId), [serverId]);
  return (
    <CapabilityContainer id="azure.sql.connectivity" title="Connection policy">
      <ErrorBar error={cur.error} />
      {cur.loading ? <Loading /> : (
        <Field label="Connection policy" style={{ maxWidth: 360 }}>
          <Select value={cur.data} aria-label="Connection policy" onChange={async (_, d) => { try { await putConnectionPolicy(serverId, d.value); notify.success(`Connection policy set to ${d.value}.`, "Saved"); cur.reload(); } catch (e) { notify.error(e, "Saving failed"); } }}>
            <option value="Default">Default - Uses Redirect for Azure-hosted clients, Proxy otherwise</option><option value="Proxy">Proxy</option><option value="Redirect">Redirect</option>
          </Select>
        </Field>
      )}
    </CapabilityContainer>
  );
}

const FUNCS = { Default: "Default value", Text: "Text (XXXX)", Number: "Number (0)", Email: "Email (aXXX@XXXX.com)", CCN: "Credit card (XXXX-XXXX-XXXX-1234)", SSN: "Social security number", Custom: "Custom string" };
export function DataMasking({ a }) {
  const notify = useNotify();
  const base = `${a.id}/dataMaskingPolicies/Default`;
  const policy = useAsync(() => restJson("GET", base, { query: Q }).catch(() => null), [a.id]);
  const rules = useAsync(async () => (await restJson("GET", `${base}/rules`, { query: Q }).catch(() => ({ value: [] }))).value || [], [a.id]);
  const [f, setF] = useState({ name: "", schemaName: "dbo", tableName: "", columnName: "", maskingFunction: "Default" });
  const [exempt, setExempt] = useState("");
  const state = policy.data?.properties?.dataMaskingState || "Disabled";
  const setState = async (s) => { try { await restJson("PUT", base, { query: Q, body: { properties: { dataMaskingState: s, exemptPrincipals: exempt } } }); notify.success(`Dynamic data masking ${s === "Enabled" ? "enabled" : "disabled"}.`, "Saved"); policy.reload(); } catch (e) { notify.error(e, "Saving failed"); } };
  const add = async () => {
    try {
      await restJson("PUT", `${base}/rules/${encodeURIComponent(f.name || `${f.tableName}_${f.columnName}`)}`, { query: Q, body: { properties: { ...f, name: undefined, ruleState: "Enabled" } } });
      notify.success("Masking rule added.", "Saved"); setF({ ...f, name: "", tableName: "", columnName: "" }); rules.reload();
    } catch (e) { notify.error(e, "Adding the masking rule failed"); }
  };
  const del = async (n) => { try { await restJson("DELETE", `${base}/rules/${encodeURIComponent(n)}`, { query: Q }); rules.reload(); } catch (e) { notify.error(e, "Delete failed"); } };
  return (
    <CapabilityContainer id="azure.sql.datamasking" title={`${a.name} | Dynamic Data Masking`}>
      <ErrorBar error={policy.error || rules.error} />
      <InfoBar>Masking rules are stored on the database as dataMaskingPolicies/Default/rules and returned to the SDK / az CLI; the Vyomi query engine does not rewrite result sets.</InfoBar>
      <div style={{ display: "flex", gap: 8, alignItems: "flex-end", margin: "8px 0" }}>
        <Field label="Masking policy"><Select value={state} onChange={(_, d) => setState(d.value)} aria-label="Masking policy state"><option value="Enabled">Enabled</option><option value="Disabled">Disabled</option></Select></Field>
        <Field label="SQL users excluded from masking (semicolon separated)"><Input value={exempt} onChange={(_, d) => setExempt(d.value)} aria-label="Excluded SQL users" /></Field>
      </div>
      <table className="vy-grid" aria-label="Masking rules">
        <thead><tr><th>Rule</th><th>Schema</th><th>Table</th><th>Column</th><th>Mask function</th><th /></tr></thead>
        <tbody>{(rules.data || []).length ? rules.data.map((r) => (
          <tr key={r.name}><td>{r.name}</td><td>{r.properties?.schemaName}</td><td>{r.properties?.tableName}</td><td>{r.properties?.columnName}</td><td>{FUNCS[r.properties?.maskingFunction] || r.properties?.maskingFunction}</td>
            <td><Button size="small" aria-label={`Delete masking rule ${r.name}`} onClick={() => del(r.name)}>Delete</Button></td></tr>
        )) : <tr><td colSpan={6} className="vy-muted">No masking rules.</td></tr>}</tbody>
      </table>
      <div style={{ display: "flex", gap: 8, alignItems: "flex-end", marginTop: 12, flexWrap: "wrap" }}>
        <Field label="Schema"><Input value={f.schemaName} onChange={(_, d) => setF((x) => ({ ...x, schemaName: d.value }))} aria-label="Masking schema" /></Field>
        <Field label="Table"><Input value={f.tableName} onChange={(_, d) => setF((x) => ({ ...x, tableName: d.value }))} aria-label="Masking table" /></Field>
        <Field label="Column"><Input value={f.columnName} onChange={(_, d) => setF((x) => ({ ...x, columnName: d.value }))} aria-label="Masking column" /></Field>
        <Field label="Masking field format"><Select value={f.maskingFunction} onChange={(_, d) => setF((x) => ({ ...x, maskingFunction: d.value }))} aria-label="Masking function">{Object.entries(FUNCS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select></Field>
        <Button appearance="primary" disabled={!f.tableName || !f.columnName} onClick={add} aria-label="Add masking rule">Add masking rule</Button>
      </div>
    </CapabilityContainer>
  );
}

export function Ledger({ a }) {
  const p = a.properties || {};
  return (
    <CapabilityContainer id="azure.sql.ledger" title={`${a.name} | Ledger`}>
      <KV label="Ledger database" value={p.isLedgerOn ? "Yes (all tables are ledger tables)" : "No"} />
      <KV label="Digest storage" value={p.ledgerDigestStorage || "None"} />
      <p className="vy-muted" style={{ fontSize: 13 }}>As in Azure, a database's ledger setting can only be chosen when the database is created (Security tab of the create wizard).</p>
    </CapabilityContainer>
  );
}

export function Maintenance({ a }) {
  const id = a.properties?.maintenanceConfigurationId || "SQL_Default";
  return (
    <CapabilityContainer id="azure.sql.maintenance" title={`${a.name} | Maintenance`}>
      <KV label="Maintenance window" value={id === "SQL_Default" ? "System default (5pm to 8am)" : id} />
      <h3 style={{ marginTop: 12 }}>Maintenance event history</h3>
      <table className="vy-grid" aria-label="Maintenance event history"><thead><tr><th>Start</th><th>End</th><th>Type</th><th>Status</th></tr></thead>
        <tbody><tr><td colSpan={4} className="vy-muted">No maintenance events — Vyomi never applies platform maintenance to a database.</td></tr></tbody></table>
    </CapabilityContainer>
  );
}
