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

// ── Data Discovery & Classification: sensitivity labels on real columns of the database ──────────────
// Recommendations come from the same column-name patterns Azure uses; labels are real
// .../columns/{c}/sensitivityLabels/current ARM children (validated in core/azure_cfgext_core.py).
const PATTERNS = [
  [/email|e_mail/i, "Contact Info", "Confidential", "Medium"], [/phone|mobile|fax/i, "Contact Info", "Confidential", "Medium"],
  [/address|street|zip|postal/i, "Contact Info", "Confidential", "Medium"], [/ssn|social_?sec|national_?id|passport/i, "National ID", "Highly Confidential", "High"],
  [/credit|card_?n|cvv|iban|account_?n/i, "Credit Card", "Highly Confidential", "Critical"], [/passw|pwd|secret|token/i, "Credentials", "Highly Confidential", "Critical"],
  [/first_?name|last_?name|full_?name|surname/i, "Name", "Confidential - GDPR", "Medium"], [/birth|dob/i, "Date Of Birth", "Confidential - GDPR", "Medium"],
  [/salary|wage|income|totaldue|price/i, "Financial", "Confidential", "Low"],
];
const LABELS = ["Public", "General", "Confidential", "Confidential - GDPR", "Highly Confidential", "Highly Confidential - GDPR"];
const RANKS = ["None", "Low", "Medium", "High", "Critical"];

export function DataDiscovery({ a }) {
  const notify = useNotify();
  const labelPath = (t, c) => `${a.id}/schemas/dbo/tables/${encodeURIComponent(t)}/columns/${encodeURIComponent(c)}/sensitivityLabels/current`;
  const LQ = { "api-version": "2020-11-01-preview" };
  const cols = useAsync(async () => {
    await api.ensureDataPlane(a.server, a.name);
    const tables = (await api.listTables(a.server, a.name)).rows?.map((r) => r[0]) || [];
    const out = [];
    for (const t of tables) {
      const info = await api.runQuery(a.server, a.name, `PRAGMA table_info("${t.replace(/"/g, "")}")`);
      const idx = (info.columns || []).indexOf("name");
      for (const r of info.rows || []) {
        const c = r[idx];
        const cur = await restJson("GET", labelPath(t, c), { query: LQ }).catch(() => null);
        const rec = PATTERNS.find(([re]) => re.test(c));
        out.push({ table: t, column: c, label: cur?.properties || null, rec: rec ? { informationType: rec[1], labelName: rec[2], rank: rec[3] } : null });
      }
    }
    return out;
  }, [a.id]);
  const apply = async (row, p) => {
    try { await restJson("PUT", labelPath(row.table, row.column), { query: LQ, body: { properties: p } }); notify.success(`Classified ${row.table}.${row.column}.`, "Saved"); cols.reload(); }
    catch (e) { notify.error(e, "Classification failed"); }
  };
  const clear = async (row) => { try { await restJson("DELETE", labelPath(row.table, row.column), { query: LQ }); cols.reload(); } catch (e) { notify.error(e, "Removing the classification failed"); } };
  const rows = cols.data || [];
  const classified = rows.filter((r) => r.label);
  const pending = rows.filter((r) => !r.label && r.rec);
  return (
    <CapabilityContainer id="azure.sql.datadiscovery" title={`${a.name} | Data Discovery & Classification`}>
      <ErrorBar error={cols.error} />
      {cols.loading && !cols.data ? <Loading /> : (
        <>
          <KV label="Classified columns" value={String(classified.length)} />
          <KV label="Recommended, not yet applied" value={String(pending.length)} />
          <div className="vy-cmdbar" style={{ margin: "8px 0" }}>
            <Button appearance="primary" disabled={!pending.length} aria-label="Accept all recommendations" onClick={async () => { for (const r of pending) await apply(r, r.rec); }}>Accept all recommendations</Button>
          </div>
          <table className="vy-grid" aria-label="Columns">
            <thead><tr><th>Table</th><th>Column</th><th>Information type</th><th>Sensitivity label</th><th>Rank</th><th /></tr></thead>
            <tbody>{rows.length ? rows.map((r) => (
              <tr key={`${r.table}.${r.column}`}>
                <td>{r.table}</td><td>{r.column}</td>
                <td>{r.label?.informationType || (r.rec ? <span className="vy-muted">{r.rec.informationType} (recommended)</span> : "--")}</td>
                <td>{r.label?.labelName || (r.rec ? <span className="vy-muted">{r.rec.labelName} (recommended)</span> : "--")}</td>
                <td>{r.label?.rank || "--"}</td>
                <td>{r.label
                  ? <Button size="small" aria-label={`Remove classification ${r.table}.${r.column}`} onClick={() => clear(r)}>Remove</Button>
                  : <Button size="small" aria-label={`Classify ${r.table}.${r.column}`} onClick={() => apply(r, r.rec || { informationType: "Other", labelName: "General", rank: "None" })}>{r.rec ? "Accept" : "Classify"}</Button>}</td>
              </tr>
            )) : <tr><td colSpan={6} className="vy-muted">This database has no tables yet. Create tables from the Query editor and come back.</td></tr>}</tbody>
          </table>
        </>
      )}
    </CapabilityContainer>
  );
}
