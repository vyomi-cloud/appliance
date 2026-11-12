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
      <InfoBar>Masking is applied to query results for any login other than the server admin, the excluded SQL users below and logins granted UNMASK. Only direct column references are masked (as in Azure); stored data is unchanged. Identify the login with the "Run as" box below (TDS/Entra identities are not modelled).</InfoBar>
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
      <MaskTester a={a} />
    </CapabilityContainer>
  );
}

function MaskTester({ a }) {
  const [sql, setSql] = useState("SELECT * FROM Customer");
  const [login, setLogin] = useState("");
  const [out, setOut] = useState(null);
  const [err, setErr] = useState(null);
  const run = async (q) => { try { setErr(null); await api.ensureDataPlane(a.server, a.name); setOut(await api.runQuery(a.server, a.name, q, undefined, { login: login || undefined })); } catch (e) { setErr(e); setOut(null); } };
  return (
    <div style={{ marginTop: 16 }}>
      <h3>Test masking</h3>
      <div style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap" }}>
        <Field label="Run as SQL login (empty = server admin)"><Input value={login} onChange={(_, d) => setLogin(d.value)} aria-label="Run as login" /></Field>
        <Field label="Statement"><Input value={sql} onChange={(_, d) => setSql(d.value)} aria-label="Masking test statement" style={{ minWidth: 320 }} /></Field>
        <Button onClick={() => run(sql)} aria-label="Run masking test">Run</Button>
        <Button disabled={!login} onClick={() => run(`GRANT UNMASK TO ${login}`)} aria-label="Grant UNMASK">GRANT UNMASK</Button>
        <Button disabled={!login} onClick={() => run(`REVOKE UNMASK FROM ${login}`)} aria-label="Revoke UNMASK">REVOKE UNMASK</Button>
      </div>
      <ErrorBar error={err} />
      {out && out.columns?.length > 0 && (
        <table className="vy-grid" aria-label="Masking test result"><thead><tr>{out.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
          <tbody>{out.rows.map((r, i) => <tr key={i}>{r.map((v, j) => <td key={j}>{String(v)}</td>)}</tr>)}</tbody></table>
      )}
    </div>
  );
}

export function Ledger({ a }) {
  const p = a.properties || {};
  const notify = useNotify();
  const info = useAsync(async () => { await api.ensureDataPlane(a.server, a.name); return api.ledgerInfo(a.server, a.name); }, [a.id]);
  const [res, setRes] = useState(null);
  const [hist, setHist] = useState(null);
  const act = async (fn, label) => { try { setRes(await fn(a.server, a.name)); info.reload(); } catch (e) { notify.error(e, label); } };
  const d = info.data || { tables: [], blocks: [], digests: [] };
  return (
    <CapabilityContainer id="azure.sql.ledger" title={`${a.name} | Ledger`}>
      <ErrorBar error={info.error} />
      <KV label="Ledger database" value={p.isLedgerOn ? "Yes (all tables are ledger tables)" : "No"} />
      <KV label="Ledger tables" value={String(d.tables.length)} />
      <KV label="Blocks in the chain" value={String(d.blocks.length ? d.blocks[0].blockId + 1 : 0)} />
      <p className="vy-muted" style={{ fontSize: 13 }}>The ledger setting of a database is chosen at creation (Security tab); individual tables can opt in with CREATE TABLE ... WITH (LEDGER = ON [(APPEND_ONLY = ON)]). Every write appends a block to a SHA-256 hash chain stored in the database. Digests stay in the database (no immutable blob / Confidential ledger upload).</p>
      <div className="vy-cmdbar" style={{ margin: "8px 0" }}>
        <Button appearance="primary" aria-label="Generate digest" onClick={() => act(api.ledgerDigest, "Digest failed")}>Generate digest</Button>
        <Button aria-label="Verify ledger" onClick={() => act(api.ledgerVerify, "Verification failed")}>Verify ledger</Button>
        <Button onClick={() => info.reload()}>Refresh</Button>
      </div>
      {res && (res.ok === undefined
        ? <InfoBar>Digest generated: block {res.block_id}, hash {res.hash}</InfoBar>
        : <InfoBar>{res.result}: {res.blocksVerified} blocks, {res.digestsVerified} digests checked.{res.issues?.length ? ` Issues: ${res.issues.join(" | ")}` : ""}</InfoBar>)}
      <h3>Ledger tables</h3>
      <table className="vy-grid" aria-label="Ledger tables"><thead><tr><th>Table</th><th>Type</th><th /></tr></thead>
        <tbody>{d.tables.length ? d.tables.map((t) => (
          <tr key={t.name}><td>{t.name}</td><td>{t.appendOnly ? "Append-only" : "Updatable"}</td>
            <td><Button size="small" aria-label={`Ledger history ${t.name}`} onClick={async () => setHist({ table: t.name, rows: await api.ledgerHistory(a.server, a.name, t.name) })}>View ledger history</Button></td></tr>
        )) : <tr><td colSpan={3} className="vy-muted">No ledger tables yet.</td></tr>}</tbody></table>
      {hist && (<><h3>Ledger history: {hist.table}</h3><table className="vy-grid" aria-label="Ledger history"><thead><tr><th>#</th><th>Transaction (block)</th><th>Operation</th><th>Row</th></tr></thead>
        <tbody>{hist.rows.map((r) => <tr key={r.sequence}><td>{r.sequence}</td><td>{r.ledgerTransactionId}</td><td>{r.operation}</td><td style={{ fontFamily: "monospace" }}>{JSON.stringify(r.row)}</td></tr>)}</tbody></table></>)}
      <h3>Blocks (newest first)</h3>
      <table className="vy-grid" aria-label="Ledger blocks"><thead><tr><th>Block</th><th>Table</th><th>Operation</th><th>Hash</th></tr></thead>
        <tbody>{d.blocks.slice(0, 20).map((b) => <tr key={b.blockId}><td>{b.blockId}</td><td>{b.table}</td><td>{b.operation}</td><td style={{ fontFamily: "monospace" }}>{b.hash.slice(0, 16)}...</td></tr>)}</tbody></table>
    </CapabilityContainer>
  );
}

export function AlwaysEncrypted({ a }) {
  const notify = useNotify();
  const info = useAsync(async () => { await api.ensureDataPlane(a.server, a.name); return api.aeInfo(a.server, a.name); }, [a.id]);
  const [f, setF] = useState({ cmk: "CMK1", keyPath: "", cek: "CEK1", table: "", column: "", type: "Deterministic" });
  const d = info.data || { columnMasterKeys: [], columnEncryptionKeys: [], encryptedColumns: [] };
  const go = async (fn, ok) => { try { await fn(); notify.success(ok, "Saved"); info.reload(); } catch (e) { notify.error(e, "Failed"); } };
  return (
    <CapabilityContainer id="azure.sql.always_encrypted" title={`${a.name} | Always Encrypted`}>
      <ErrorBar error={info.error} />
      <InfoBar>The server stores ciphertext only. The client-side driver is emulated: queries sent with Column Encryption Setting enabled have parameters encrypted / results decrypted through Key Vault (a disabled column master key stops decryption). Randomized columns do not support equality; LIKE / range are rejected.</InfoBar>
      <h3>Column master keys</h3>
      <table className="vy-grid" aria-label="Column master keys"><thead><tr><th>Name</th><th>Key Vault key</th></tr></thead>
        <tbody>{d.columnMasterKeys.length ? d.columnMasterKeys.map((k) => <tr key={k.name}><td>{k.name}</td><td>{k.keyPath}</td></tr>) : <tr><td colSpan={2} className="vy-muted">None.</td></tr>}</tbody></table>
      <div style={{ display: "flex", gap: 8, alignItems: "flex-end", margin: "8px 0", flexWrap: "wrap" }}>
        <Field label="CMK name"><Input value={f.cmk} onChange={(_, x) => setF({ ...f, cmk: x.value })} aria-label="CMK name" /></Field>
        <Field label="Key Vault key URL"><Input value={f.keyPath} placeholder="https://vault.vault.azure.net/keys/name" onChange={(_, x) => setF({ ...f, keyPath: x.value })} aria-label="Key Vault key URL" style={{ minWidth: 320 }} /></Field>
        <Button appearance="primary" disabled={!f.keyPath} onClick={() => go(() => api.aeCreateCmk(a.server, a.name, f.cmk, f.keyPath), "Column master key created.")}>Create CMK</Button>
      </div>
      <h3>Column encryption keys</h3>
      <table className="vy-grid" aria-label="Column encryption keys"><thead><tr><th>Name</th><th>Column master key</th></tr></thead>
        <tbody>{d.columnEncryptionKeys.length ? d.columnEncryptionKeys.map((k) => <tr key={k.name}><td>{k.name}</td><td>{k.columnMasterKey}</td></tr>) : <tr><td colSpan={2} className="vy-muted">None.</td></tr>}</tbody></table>
      <div style={{ display: "flex", gap: 8, alignItems: "flex-end", margin: "8px 0" }}>
        <Field label="CEK name"><Input value={f.cek} onChange={(_, x) => setF({ ...f, cek: x.value })} aria-label="CEK name" /></Field>
        <Button disabled={!d.columnMasterKeys.length} onClick={() => go(() => api.aeCreateCek(a.server, a.name, f.cek, f.cmk), "Column encryption key created.")}>Create CEK</Button>
      </div>
      <h3>Encrypted columns</h3>
      <table className="vy-grid" aria-label="Encrypted columns"><thead><tr><th>Table</th><th>Column</th><th>Encryption type</th><th>CEK</th></tr></thead>
        <tbody>{d.encryptedColumns.length ? d.encryptedColumns.map((c) => <tr key={c.table + c.column}><td>{c.table}</td><td>{c.column}</td><td>{c.type}</td><td>{c.cek}</td></tr>) : <tr><td colSpan={4} className="vy-muted">None.</td></tr>}</tbody></table>
      <div style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap" }}>
        <Field label="Table"><Input value={f.table} onChange={(_, x) => setF({ ...f, table: x.value })} aria-label="Encrypt table" /></Field>
        <Field label="Column"><Input value={f.column} onChange={(_, x) => setF({ ...f, column: x.value })} aria-label="Encrypt column" /></Field>
        <Field label="Encryption type"><Select value={f.type} onChange={(_, x) => setF({ ...f, type: x.value })} aria-label="Encryption type"><option>Deterministic</option><option>Randomized</option></Select></Field>
        <Button appearance="primary" disabled={!f.table || !f.column || !d.columnEncryptionKeys.length} onClick={() => go(() => api.aeEncryptColumn(a.server, a.name, { table: f.table, column: f.column, cek: f.cek, encryptionType: f.type }), "Column encrypted in place.")}>Encrypt column</Button>
      </div>
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
    // The scan runs in the SQL engine over the database's real tables: column-name patterns AND sampled values.
    const scan = await api.discoveryScan(a.server, a.name);
    return scan.columns.map((c) => ({ table: c.table, column: c.column, label: c.label ? { ...c.label } : null, rec: c.recommendation }));
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
                <td>{r.label?.informationType || (r.rec ? <span className="vy-muted">{r.rec.informationType} (recommended from {r.rec.source === "data" ? `${Math.round((r.rec.matchRatio || 0) * 100)}% of sampled values` : "column name"})</span> : "--")}</td>
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
