/* Entra pages backed by real engines (core/azure_graph_ext_core.py): Licenses (SKU units are consumed by assignment),
 * Security > Conditional Access (policy rule engine + What If; the password-grant token endpoint enforces it),
 * Custom security attributes (definitions validate user assignments), BitLocker recovery-key escrow (no disk behind it). */
import { useState } from "react";
import { Button, Field, Input, Select, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { ErrorBar, Loading } from "../../kit/common.jsx";
import EntraShell from "./EntraShell.jsx";
import * as api from "./api.js";

const Grid = ({ cols, rows, empty = "Nothing here yet.", label }) => (
  <Table size="small" aria-label={label}>
    <TableHeader><TableRow>{cols.map((c) => <TableHeaderCell key={c.label}>{c.label}</TableHeaderCell>)}</TableRow></TableHeader>
    <TableBody>
      {rows.length === 0 && <TableRow><TableCell colSpan={cols.length}>{empty}</TableCell></TableRow>}
      {rows.map((r, i) => <TableRow key={r.id || i}>{cols.map((c) => <TableCell key={c.label}>{c.value(r)}</TableCell>)}</TableRow>)}
    </TableBody>
  </Table>
);
const Wrap = ({ active, title, state, children }) => (
  <EntraShell active={active} title={title}><div className="vy-page">{state.error && <ErrorBar error={state.error} title="Request failed" />}{state.loading && !state.data ? <Loading /> : children}</div></EntraShell>
);

export function Licenses() {
  const notify = useNotify();
  const skus = useAsync(() => api.listSkus(), []);
  const users = useAsync(() => api.listUsers(), []);
  const [uid, setUid] = useState(""); const [sku, setSku] = useState("");
  const details = useAsync(() => (uid ? api.licenseDetails(uid) : Promise.resolve([])), [uid]);
  const act = async (add) => {
    try { await api.assignLicense(uid, add ? [sku] : [], add ? [] : [sku]); notify.success(add ? "License assigned." : "License removed.", "Licenses"); skus.reload(); details.reload(); }
    catch (e) { notify.error(e, "License change failed"); }
  };
  return (
    <Wrap active="licenses" title="Licenses | All products" state={skus}>
      <p>Each assignment consumes a unit of the product; assignment fails when none are free or the user has no usage location.</p>
      <Grid label="Products" cols={[{ label: "Product", value: (r) => r.skuPartNumber }, { label: "Total", value: (r) => r.prepaidUnits.enabled }, { label: "Assigned", value: (r) => r.consumedUnits }, { label: "Available", value: (r) => r.prepaidUnits.enabled - r.consumedUnits }]} rows={skus.data || []} />
      <h3>Assign or remove</h3>
      <Field label="User"><Select value={uid} onChange={(_, d) => setUid(d.value)}><option value="">Select…</option>{(users.data || []).map((u) => <option key={u.id} value={u.id}>{u.userPrincipalName}</option>)}</Select></Field>
      <Field label="Product"><Select value={sku} onChange={(_, d) => setSku(d.value)}><option value="">Select…</option>{(skus.data || []).map((s) => <option key={s.skuId} value={s.skuId}>{s.skuPartNumber}</option>)}</Select></Field>
      <div style={{ display: "flex", gap: 8, marginTop: 8 }}><Button appearance="primary" disabled={!uid || !sku} onClick={() => act(true)}>Assign</Button><Button disabled={!uid || !sku} onClick={() => act(false)}>Remove</Button></div>
      {uid && <><h3>License details</h3><Grid label="License details" cols={[{ label: "Product", value: (r) => r.skuPartNumber }, { label: "Service plans", value: (r) => r.servicePlans.map((p) => p.servicePlanName).join(", ") }]} rows={details.data || []} empty="No licenses assigned." /></>}
    </Wrap>
  );
}

export function CustomSecurityAttributes() {
  const notify = useNotify();
  const sets = useAsync(() => api.listAttributeSets(), []);
  const defs = useAsync(() => api.listAttributeDefs(), []);
  const [s, setS] = useState({ id: "", description: "" });
  const [d, setD] = useState({ attributeSet: "", name: "", type: "String", values: "" });
  const go = async (fn, ok) => { try { await fn(); notify.success(ok, "Custom security attributes"); sets.reload(); defs.reload(); } catch (e) { notify.error(e, "Request failed"); } };
  return (
    <Wrap active="customsecurityattributes" title="Custom security attributes" state={sets}>
      <p>Definitions are enforced when attributes are assigned to a user (type, collection and allowed values are validated).</p>
      <h3>Attribute sets</h3>
      <Grid label="Attribute sets" cols={[{ label: "Name", value: (r) => r.id }, { label: "Description", value: (r) => r.description || "--" }, { label: "Max attributes", value: (r) => r.maxAttributesPerSet }]} rows={sets.data || []} />
      <div style={{ display: "flex", gap: 8, alignItems: "end" }}>
        <Field label="Name"><Input value={s.id} onChange={(_, v) => setS({ ...s, id: v.value })} /></Field>
        <Field label="Description"><Input value={s.description} onChange={(_, v) => setS({ ...s, description: v.value })} /></Field>
        <Button disabled={!s.id} onClick={() => go(() => api.createAttributeSet(s), `Attribute set ${s.id} created.`)}>Add attribute set</Button>
      </div>
      <h3>Attribute definitions</h3>
      <Grid label="Attribute definitions" cols={[{ label: "Attribute", value: (r) => r.id }, { label: "Type", value: (r) => r.type }, { label: "Allowed values", value: (r) => (r.usePreDefinedValuesOnly ? r.allowedValues.map((a) => a.id).join(", ") : "any") }, { label: "Status", value: (r) => r.status }]} rows={defs.data || []} />
      <div style={{ display: "flex", gap: 8, alignItems: "end", flexWrap: "wrap" }}>
        <Field label="Set"><Select value={d.attributeSet} onChange={(_, v) => setD({ ...d, attributeSet: v.value })}><option value="">Select…</option>{(sets.data || []).map((x) => <option key={x.id}>{x.id}</option>)}</Select></Field>
        <Field label="Name"><Input value={d.name} onChange={(_, v) => setD({ ...d, name: v.value })} /></Field>
        <Field label="Type"><Select value={d.type} onChange={(_, v) => setD({ ...d, type: v.value })}><option>String</option><option>Integer</option><option>Boolean</option></Select></Field>
        <Field label="Predefined values (comma separated, optional)"><Input value={d.values} onChange={(_, v) => setD({ ...d, values: v.value })} /></Field>
        <Button disabled={!d.attributeSet || !d.name} onClick={() => { const vals = d.values.split(",").map((x) => x.trim()).filter(Boolean); go(() => api.createAttributeDef({ attributeSet: d.attributeSet, name: d.name, type: d.type, usePreDefinedValuesOnly: vals.length > 0, allowedValues: vals }), `Attribute ${d.attributeSet}_${d.name} created.`); }}>Add definition</Button>
      </div>
    </Wrap>
  );
}

export function ConditionalAccess() {
  const notify = useNotify();
  const pols = useAsync(() => api.listCaPolicies(), []);
  const users = useAsync(() => api.listUsers(), []);
  const [p, setP] = useState({ name: "", user: "All", control: "block", state: "enabled", cidr: "" });
  const [w, setW] = useState({ userId: "", ip: "" });
  const [res, setRes] = useState(null);
  const go = async (fn, ok) => { try { await fn(); notify.success(ok, "Conditional Access"); pols.reload(); } catch (e) { notify.error(e, "Request failed"); } };
  const create = () => go(async () => {
    let locs;
    if (p.cidr.trim()) { const l = await api.createNamedLocation({ displayName: `${p.name} location`, isTrusted: true, ipRanges: p.cidr.split(",").map((c) => ({ "@odata.type": "#microsoft.graph.iPv4CidrRange", cidrAddress: c.trim() })) }); locs = { includeLocations: ["All"], excludeLocations: [l.id] }; }
    await api.createCaPolicy({ displayName: p.name, state: p.state, conditions: { users: { includeUsers: [p.user] }, applications: { includeApplications: ["All"] }, ...(locs ? { locations: locs } : {}) }, grantControls: { operator: "OR", builtInControls: [p.control] } });
  }, `Policy ${p.name} created.`);
  const run = async () => { try { setRes(await api.whatIf({ userId: w.userId, ipAddress: w.ip || undefined })); } catch (e) { notify.error(e, "What If failed"); } };
  return (
    <Wrap active="security" title="Security | Conditional Access" state={pols}>
      <p>Enabled policies are evaluated for real by the sign-in (password grant) endpoint: <b>block</b> returns AADSTS53003; MFA and device controls return an interaction-required error because there is no interactive flow to satisfy them. Report-only policies are evaluated but never enforced.</p>
      <Grid label="Policies" cols={[{ label: "Name", value: (r) => r.displayName }, { label: "State", value: (r) => (<Select value={r.state} onChange={(_, d) => go(() => api.updateCaPolicy(r.id, { state: d.value }), "Policy state updated.")}><option>enabled</option><option>disabled</option><option>enabledForReportingButNotEnforced</option></Select>) }, { label: "Grant", value: (r) => (r.grantControls?.builtInControls || []).join(", ") }, { label: "", value: (r) => <Button size="small" onClick={() => go(() => api.deleteCaPolicy(r.id), "Policy deleted.")}>Delete</Button> }]} rows={pols.data || []} empty="No policies." />
      <h3>New policy</h3>
      <div style={{ display: "flex", gap: 8, alignItems: "end", flexWrap: "wrap" }}>
        <Field label="Name"><Input value={p.name} onChange={(_, v) => setP({ ...p, name: v.value })} /></Field>
        <Field label="Users"><Select value={p.user} onChange={(_, v) => setP({ ...p, user: v.value })}><option value="All">All users</option>{(users.data || []).map((u) => <option key={u.id} value={u.id}>{u.userPrincipalName}</option>)}</Select></Field>
        <Field label="Except from trusted IP ranges (CIDR, comma separated)"><Input value={p.cidr} onChange={(_, v) => setP({ ...p, cidr: v.value })} placeholder="10.0.0.0/8" /></Field>
        <Field label="Grant"><Select value={p.control} onChange={(_, v) => setP({ ...p, control: v.value })}><option value="block">Block access</option><option value="mfa">Require MFA</option><option value="compliantDevice">Require compliant device</option></Select></Field>
        <Field label="State"><Select value={p.state} onChange={(_, v) => setP({ ...p, state: v.value })}><option>enabled</option><option>enabledForReportingButNotEnforced</option><option>disabled</option></Select></Field>
        <Button appearance="primary" disabled={!p.name} onClick={create}>Create</Button>
      </div>
      <h3>What If</h3>
      <div style={{ display: "flex", gap: 8, alignItems: "end" }}>
        <Field label="User"><Select value={w.userId} onChange={(_, v) => setW({ ...w, userId: v.value })}><option value="">Select…</option>{(users.data || []).map((u) => <option key={u.id} value={u.id}>{u.userPrincipalName}</option>)}</Select></Field>
        <Field label="IP address"><Input value={w.ip} onChange={(_, v) => setW({ ...w, ip: v.value })} placeholder="8.8.8.8" /></Field>
        <Button disabled={!w.userId} onClick={run}>Evaluate</Button>
      </div>
      {res && <><p><b>Result: {res.result}</b>{res.requiredControls.length ? ` (requires ${res.requiredControls.join(", ")})` : ""}</p>
        <Grid label="What If result" cols={[{ label: "Policy", value: (r) => r.displayName }, { label: "Applies", value: (r) => (r.applied ? "Yes" : r.reportOnly ? "Report-only" : "No") }, { label: "Why", value: (r) => r.reasons.join("; ") }]} rows={res.policies} /></>}
    </Wrap>
  );
}

/** BitLocker recovery keys for the Devices page: escrow for a registered device, reveal (audited), delete. */
export function BitlockerKeys({ devices }) {
  const notify = useNotify();
  const keys = useAsync(() => api.listBitlockerKeys(), []);
  const [dev, setDev] = useState(""); const [shown, setShown] = useState({});
  const go = async (fn, ok) => { try { await fn(); if (ok) notify.success(ok, "BitLocker keys"); keys.reload(); } catch (e) { notify.error(e, "Request failed"); } };
  const name = (k) => (devices || []).find((d) => d.deviceId === k.deviceId)?.displayName || k.deviceId;
  return (
    <div>
      <h3>BitLocker keys</h3>
      <p>Escrow store only: keys use the real recovery-password format and every reveal is written to the audit log, but no disk is encrypted by Vyomi.</p>
      <Grid label="BitLocker keys" cols={[{ label: "Device", value: name }, { label: "Volume", value: (k) => k.volumeType }, { label: "Created", value: (k) => k.createdDateTime }, { label: "Recovery key", value: (k) => (shown[k.id] ? <code>{shown[k.id]}</code> : <Button size="small" onClick={async () => { const r = await api.readBitlockerKey(k.id); setShown({ ...shown, [k.id]: r.key }); }}>Show recovery key</Button>) }, { label: "", value: (k) => <Button size="small" onClick={() => go(() => api.deleteBitlockerKey(k.id), "Key deleted.")}>Delete</Button> }]} rows={keys.data || []} empty="No keys escrowed." />
      <div style={{ display: "flex", gap: 8, alignItems: "end" }}>
        <Field label="Escrow a new key for device"><Select value={dev} onChange={(_, d) => setDev(d.value)}><option value="">Select…</option>{(devices || []).map((d) => <option key={d.id} value={d.id}>{d.displayName}</option>)}</Select></Field>
        <Button disabled={!dev} onClick={() => go(() => api.escrowBitlockerKey(dev), "Recovery key escrowed.")}>Escrow</Button>
      </div>
    </div>
  );
}
