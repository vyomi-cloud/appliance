/* Management groups over the native ARM wire (Microsoft.Management/managementGroups, core/azure_mgmt_groups_core.py):
 *   tree (tenant root group > groups > subscriptions)  GET  /providers/Microsoft.Management/managementGroups/{root}?$expand=children&$recurse=true
 *   create / move / rename                            PUT|PATCH /providers/Microsoft.Management/managementGroups/{id}
 *   subscription membership                           PUT|DELETE .../managementGroups/{id}/subscriptions/{sub}
 *   role assignment at the group scope                PUT .../managementGroups/{id}/providers/Microsoft.Authorization/roleAssignments/{guid}
 *   policy assignment at the group scope              PUT .../managementGroups/{id}/providers/Microsoft.Authorization/policyAssignments/{name}
 *   effective access at a scope                       GET /api/iam/azure/governance/effective?scope=   (the engine's inheritance chain)
 * The scope picker (Access control tab) offers every management group and the subscription. */
import { useState } from "react";
import { Badge, Button, Field, Input, Select, Tab, TabList } from "@fluentui/react-components";
import { useAsync } from "../../../common/useAsync.js";
import { restJson } from "../../../common/wire.js";
import { gov } from "../../../common/governanceApi.js";
import { ErrorBar, Glyph, InfoBar, Loading } from "../../kit/common.jsx";
import { TitleRow } from "../../kit/ResourceBlade.jsx";
import { getSubscription } from "../../kit/arm.js";

const MG = "/providers/Microsoft.Management/managementGroups";
const V = { "api-version": "2021-04-01" };
const ROLES = [["Reader", "acdd72a7-3385-48ef-bd42-f606fba81ae7"], ["Contributor", "b24988ac-6180-42a0-ab88-20f7382dd24c"], ["Owner", "8e3af657-a8ff-443c-a75c-2fe8c4bcb635"]];
const ALLOWED_LOCATIONS = "/providers/Microsoft.Authorization/policyDefinitions/e56962a6-4747-49cd-b67b-bf8b01975c4c";
const uuid = () => (crypto.randomUUID ? crypto.randomUUID() : "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => ((Math.random() * 16) | 0).toString(16)));
const flat = (n, out = []) => { if (n.kind === "managementGroup") { out.push(n); n.children.forEach((c) => flat(c, out)); } return out; };

function Node({ n, depth, sel, onSel }) {
  const isSub = n.kind === "subscription";
  const id = isSub ? n.id : n.name;
  return (
    <div>
      <div role="treeitem" data-mg={id} aria-selected={sel === id} onClick={() => onSel(n)}
        style={{ paddingLeft: depth * 18, cursor: "pointer", padding: "4px 6px 4px " + (6 + depth * 18) + "px", fontWeight: sel === id ? 600 : 400, background: sel === id ? "var(--colorNeutralBackground1Selected, #e6f0fa)" : "transparent" }}>
        {isSub ? "▫ " : n.root ? "▾ " : "▸ "}{n.displayName}{" "}
        <span style={{ opacity: 0.6, fontSize: 12 }}>{isSub ? "subscription" : n.root ? "Tenant root group" : n.name}{n.policyAssignments ? ` · ${n.policyAssignments} policy assignment(s)` : ""}</span>
      </div>
      {n.children.map((c) => <Node key={c.id} n={c} depth={depth + 1} sel={sel} onSel={onSel} />)}
    </div>
  );
}

function Panel({ title, children }) { return <section className="vy-section" style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 10, maxWidth: 560 }}><h3 style={{ margin: 0 }}>{title}</h3>{children}</section>; }

export default function ManagementGroups() {
  const h = useAsync(() => gov("azure", "hierarchy"), []);
  const [sel, setSel] = useState(null);
  const [tab, setTab] = useState("details");
  const [err, setErr] = useState(null);
  const [note, setNote] = useState(null);
  const [form, setForm] = useState({ name: "", display: "", parent: "" });
  const [rbac, setRbac] = useState({ principal: "", role: ROLES[0][1], scope: "" });
  const [loc, setLoc] = useState("westeurope");
  const groups = h.data ? flat(h.data.root) : [];
  const selGroup = sel && groups.find((g) => g.name === sel);
  const current = selGroup || groups[0];
  const scopes = [...groups.map((g) => ({ id: `${MG}/${g.name}`, label: `Management group: ${g.displayName}` })), { id: `/subscriptions/${getSubscription()}`, label: "Subscription: Vyomi Subscription" }];
  const effScope = rbac.scope || (current ? `${MG}/${current.name}` : "");
  const eff = useAsync(() => (tab === "access" && effScope ? gov("azure", "effective", { query: { scope: effScope } }) : Promise.resolve(null)), [tab, effScope, h.data]);
  const run = async (fn, msg) => { setErr(null); setNote(null); try { await fn(); setNote(msg); h.reload(); eff.reload?.(); } catch (e) { setErr(e); } };
  const sub = h.data && flat(h.data.root).flatMap((g) => g.children.filter((c) => c.kind === "subscription").map((s) => ({ ...s, parent: g.name })));
  return (
    <>
      <TitleRow title="Management groups" subtitle="Tenant root group" glyph={<Glyph id="subscriptions" />} closeHref="#/" />
      <div className="vy-page" style={{ display: "flex", gap: 16, alignItems: "flex-start", flexWrap: "wrap" }}>
        <div style={{ minWidth: 320, maxWidth: 420, flex: "0 0 360px" }}>
          <ErrorBar error={h.error} title="Failed to load management groups" />
          {h.loading ? <Loading /> : h.data && <div role="tree" aria-label="Management group hierarchy"><Node n={h.data.root} depth={0} sel={selGroup ? selGroup.name : sel} onSel={(n) => { setSel(n.kind === "subscription" ? n.id : n.name); }} /></div>}
          <Panel title="Create management group">
            <Field label="Management group ID"><Input value={form.name} onChange={(_, d) => setForm({ ...form, name: d.value })} aria-label="Management group ID" /></Field>
            <Field label="Display name"><Input value={form.display} onChange={(_, d) => setForm({ ...form, display: d.value })} aria-label="Display name" /></Field>
            <Field label="Parent management group"><Select style={{ maxWidth: "100%" }} value={form.parent || (groups[0]?.name || "")} onChange={(_, d) => setForm({ ...form, parent: d.value })} aria-label="Parent management group">
              {groups.map((g) => <option key={g.name} value={g.name}>{g.displayName} ({g.name})</option>)}</Select></Field>
            <Button appearance="primary" disabled={!form.name} style={{ marginTop: 8 }} onClick={() => run(() => restJson("PUT", `${MG}/${form.name}`, { query: V, body: { properties: { displayName: form.display || form.name, details: { parent: { id: `${MG}/${form.parent || groups[0]?.name}` } } } } }), `Management group ${form.name} created.`)}>Create</Button>
          </Panel>
        </div>
        <div style={{ flex: 1, minWidth: 360 }}>
          {err && <ErrorBar error={err} title="Request failed" />}
          {note && <InfoBar intent="success">{note}</InfoBar>}
          {current && (<>
            <h2 data-testid="mg-title">{current.displayName} {current.root && <Badge appearance="outline">Tenant root</Badge>}</h2>
            <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)}>
              <Tab value="details">Details</Tab><Tab value="access">Access control (IAM)</Tab><Tab value="policy">Policy</Tab></TabList>
            {tab === "details" && (<>
              <Panel title="Children">
                {current.children.length === 0 ? <p>No child groups or subscriptions.</p> : <ul>{current.children.map((c) => <li key={c.id}>{c.displayName} ({c.kind === "subscription" ? "subscription" : c.name})</li>)}</ul>}
                {!current.root && current.children.length === 0 && <Button aria-label="Delete management group" onClick={() => run(() => restJson("DELETE", `${MG}/${current.name}`, { query: V }), `Management group ${current.name} deleted.`).then(() => setSel(null))}>Delete</Button>}
              </Panel>
              <Panel title="Subscriptions">
                {(sub || []).map((s) => (
                  <div key={s.id} style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6 }} data-sub={s.name}>
                    <span style={{ minWidth: 300 }}>{s.displayName} ({s.name}) in <b>{s.parent === h.data.root.name ? "Tenant root group" : s.parent}</b></span>
                    <Select aria-label="Move subscription to" value="" onChange={(_, d) => d.value && run(() => restJson("PUT", `${MG}/${d.value}/subscriptions/${s.name}`, { query: V }), `Subscription moved to ${d.value}.`)}>
                      <option value="">Move to...</option>{groups.filter((g) => g.name !== s.parent).map((g) => <option key={g.name} value={g.name}>{g.displayName}</option>)}</Select>
                  </div>))}
              </Panel>
            </>)}
            {tab === "access" && (<>
              <Panel title="Add role assignment">
                <Field label="Scope"><Select aria-label="Scope" value={effScope} onChange={(_, d) => setRbac({ ...rbac, scope: d.value })}>{scopes.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}</Select></Field>
                <Field label="Role"><Select aria-label="Role" value={rbac.role} onChange={(_, d) => setRbac({ ...rbac, role: d.value })}>{ROLES.map(([n, g]) => <option key={g} value={g}>{n}</option>)}</Select></Field>
                <Field label="Principal object ID"><Input aria-label="Principal object ID" value={rbac.principal} onChange={(_, d) => setRbac({ ...rbac, principal: d.value })} /></Field>
                <Button appearance="primary" disabled={!rbac.principal} style={{ marginTop: 8 }} onClick={() => run(() => restJson("PUT", `${effScope}/providers/Microsoft.Authorization/roleAssignments/${uuid()}`, { query: { "api-version": "2022-04-01" }, body: { properties: { principalId: rbac.principal, roleDefinitionId: `/providers/Microsoft.Authorization/roleDefinitions/${rbac.role}` } } }), "Role assignment added.")}>Add</Button>
              </Panel>
              <Panel title={`Effective at ${effScope.split("/").slice(-1)[0]}`}>
                {eff.loading ? <Loading /> : eff.data && (<>
                  <table style={{ width: "100%" }}><thead><tr><th align="left">Principal</th><th align="left">Role</th><th align="left">Inherited from</th></tr></thead>
                    <tbody>{eff.data.roleAssignments.map((r) => <tr key={r.id} data-ra={r.principalId}><td>{r.principalId}</td><td>{(ROLES.find(([, g]) => g === String(r.roleDefinitionId).split("/").pop()) || [])[0] || String(r.roleDefinitionId).split("/").pop()}</td><td>{r.inheritedFrom || "This scope"}</td></tr>)}</tbody></table>
                  {eff.data.roleAssignments.length === 0 && <p>No role assignments apply at this scope.</p>}
                </>)}
              </Panel>
            </>)}
            {tab === "policy" && (<>
              <Panel title="Assign the Allowed locations policy at this group">
                <p>Resources created in any subscription under this group are checked against the policy (enforced by the ARM engine).</p>
                <Field label="Allowed location"><Input aria-label="Allowed location" value={loc} onChange={(_, d) => setLoc(d.value)} /></Field>
                <Button appearance="primary" style={{ marginTop: 8 }} onClick={() => run(() => restJson("PUT", `${MG}/${current.name}/providers/Microsoft.Authorization/policyAssignments/allowed-locations`, { query: { "api-version": "2021-06-01" }, body: { properties: { displayName: "Allowed locations", policyDefinitionId: ALLOWED_LOCATIONS, parameters: { listOfAllowedLocations: { value: [loc] } } } } }), "Policy assigned.")}>Assign policy</Button>
                {current.policyAssignments > 0 && <Button style={{ marginLeft: 8 }} onClick={() => run(() => restJson("DELETE", `${MG}/${current.name}/providers/Microsoft.Authorization/policyAssignments/allowed-locations`, { query: { "api-version": "2021-06-01" } }), "Policy assignment removed.")}>Remove assignment</Button>}
              </Panel>
              <Panel title="Policy assignments in force"><PolicyList scope={effScope || `${MG}/${current.name}`} dep={h.data} /></Panel>
            </>)}
          </>)}
        </div>
      </div>
    </>
  );
}

function PolicyList({ scope, dep }) {
  const e = useAsync(() => gov("azure", "effective", { query: { scope } }), [scope, dep]);
  if (e.loading) return <Loading />;
  const p = e.data?.policyAssignments || [];
  return p.length === 0 ? <p>No policy assignments apply here.</p> : <ul>{p.map((x) => <li key={x.name + x.scope} data-pa={x.name}>{x.name} <span style={{ opacity: 0.6 }}>(assigned at {String(x.scope).split("/").slice(-1)[0]}, {x.enforcementMode})</span></li>)}</ul>;
}
