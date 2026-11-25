/* Add custom role wizard: Basics | Permissions | Assignable scopes | JSON | Review + create.
 * Baseline permissions: Clone a role / Start from scratch / Start from JSON. Permissions come from the provider catalogs. */
import { useMemo, useState } from "react";
import { Button, Field, Input, Radio, RadioGroup, Tab, TabList, Textarea } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import Blade from "./Blade.jsx";
import RolePicker from "./RolePicker.jsx";
import PermissionPicker from "./PermissionPicker.jsx";
import ScopePicker from "./ScopePicker.jsx";
import { getSubscription } from "../arm.js";
import { reloadRoles } from "./data.js";
import * as iam from "../iam.js";

const uniq = (a) => [...new Set(a)];
export default function AddCustomRoleWizard({ scope, onClose, onAdded }) {
  const notify = useNotify();
  const sub = `/subscriptions/${getSubscription()}`;
  const [tab, setTab] = useState("basics");
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [base, setBase] = useState("scratch");
  const [clone, setClone] = useState(null);
  const [json, setJson] = useState("");
  const [perm, setPerm] = useState({ actions: [], notActions: [], dataActions: [], notDataActions: [] });
  const [scopes, setScopes] = useState([scope || sub]);
  const [pickPerm, setPickPerm] = useState(false);
  const [pickScope, setPickScope] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const role = useMemo(() => ({ properties: { roleName: name, description: desc, type: "CustomRole", permissions: [perm], assignableScopes: scopes } }), [name, desc, perm, scopes]);
  const order = ["basics", "permissions", "scopes", "json", "review"];
  const applyBase = () => {
    setErr("");
    if (base === "clone" && clone) setPerm({ actions: clone.actions, notActions: clone.notActions, dataActions: clone.dataActions, notDataActions: clone.notDataActions });
    if (base === "json") {
      try { const j = JSON.parse(json); const p = j.properties || j; const pm = p.permissions?.[0] || {};
        if (p.roleName || j.Name) setName(p.roleName || j.Name); if (p.description || j.Description) setDesc(p.description || j.Description);
        setPerm({ actions: pm.actions || pm.Actions || p.Actions || [], notActions: pm.notActions || p.NotActions || [], dataActions: pm.dataActions || p.DataActions || [], notDataActions: pm.notDataActions || p.NotDataActions || [] });
        if (p.assignableScopes?.length) setScopes(p.assignableScopes);
      } catch (e) { setErr("The JSON is not valid: " + e.message); return false; }
    }
    return true;
  };
  const go = async () => {
    setBusy(true);
    try { await iam.putRoleDefinition(crypto.randomUUID(), role); await reloadRoles(); notify.success(`Custom role '${name}' created.`, "Add custom role"); onAdded?.(); onClose(); }
    catch (e) { notify.error(e, "Failed to create custom role"); } finally { setBusy(false); }
  };
  const empty = !perm.actions.length && !perm.dataActions.length && !perm.notActions.length && !perm.notDataActions.length;
  const remove = (k, a) => setPerm((p) => ({ ...p, [k]: p[k].filter((x) => x !== a) }));
  const list = (k, title) => perm[k].length > 0 && (
    <section className="vy-section" key={k}><h3>{title} ({perm[k].length})</h3>
      <table className="vy-pick-grid"><tbody>{perm[k].map((a) => <tr key={a}><td><code>{a}</code></td><td style={{ width: 80 }}><Button size="small" appearance="subtle" onClick={() => remove(k, a)}>Remove</Button></td></tr>)}</tbody></table></section>);
  return (
    <Blade title="Create a custom role" onClose={onClose} testid="add-custom-role"
      footer={<>
        {tab === "review" ? <Button appearance="primary" disabled={!name || empty || busy} onClick={go}>Create</Button> : <Button appearance="primary" disabled={!name} onClick={() => setTab("review")}>Review + create</Button>}
        <Button disabled={tab === "basics"} onClick={() => setTab(order[order.indexOf(tab) - 1])}>Previous</Button>
        <Button disabled={tab === "review"} onClick={() => { if (tab === "basics" && !applyBase()) return; setTab(order[order.indexOf(tab) + 1]); }}>Next</Button>
      </>}>
      <TabList selectedValue={tab} onTabSelect={(_, d) => { if (tab === "basics" && !applyBase()) return; setTab(d.value); }} style={{ marginTop: 8 }} aria-label="Custom role steps">
        <Tab value="basics">Basics</Tab><Tab value="permissions">Permissions</Tab><Tab value="scopes">Assignable scopes</Tab><Tab value="json">JSON</Tab><Tab value="review">Review + create</Tab>
      </TabList>
      <div style={{ paddingTop: 12, maxWidth: 940 }}>
        {tab === "basics" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <Field label="Custom role name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Custom role name" /></Field>
            <Field label="Description"><Textarea value={desc} onChange={(_, d) => setDesc(d.value)} aria-label="Description" /></Field>
            <Field label="Baseline permissions">
              <RadioGroup value={base} onChange={(_, d) => setBase(d.value)} aria-label="Baseline permissions">
                <Radio value="clone" label="Clone a role" /><Radio value="scratch" label="Start from scratch" /><Radio value="json" label="Start from JSON" />
              </RadioGroup>
            </Field>
            {base === "clone" && <div><p style={{ fontSize: 13 }}>Role to clone: <b>{clone?.roleName || "none selected"}</b></p><RolePicker value={clone} onChange={setClone} /></div>}
            {base === "json" && <Field label="JSON"><Textarea rows={10} value={json} onChange={(_, d) => setJson(d.value)} aria-label="Role JSON" placeholder='{"properties": {"roleName": "...", "permissions": [{"actions": []}]}}' /></Field>}
            {err && <div className="vy-info" role="alert">{err}</div>}
          </div>)}
        {tab === "permissions" && (
          <div>
            <Button appearance="primary" onClick={() => setPickPerm(true)} data-testid="add-permissions">+ Add permissions</Button>
            {empty && <p className="vy-muted">No permissions added yet.</p>}
            {list("actions", "Actions")}{list("notActions", "NotActions")}{list("dataActions", "DataActions")}{list("notDataActions", "NotDataActions")}
          </div>)}
        {tab === "scopes" && (
          <div><Button onClick={() => setPickScope(true)}>+ Add assignable scopes</Button>
            <table className="vy-pick-grid" style={{ marginTop: 8 }}><tbody>{scopes.map((s) => <tr key={s}><td><code>{s}</code></td><td style={{ width: 80 }}><Button size="small" appearance="subtle" disabled={scopes.length < 2} onClick={() => setScopes((x) => x.filter((y) => y !== s))}>Remove</Button></td></tr>)}</tbody></table></div>)}
        {tab === "json" && <pre className="vy-code" data-testid="custom-role-json">{JSON.stringify({ properties: { ...role.properties } }, null, 2)}</pre>}
        {tab === "review" && (
          <table className="vy-pick-grid" data-testid="cr-review"><tbody>
            <tr><th style={{ width: 200 }}>Role name</th><td>{name}</td></tr><tr><th>Description</th><td>{desc || "--"}</td></tr>
            <tr><th>Actions</th><td>{perm.actions.length}</td></tr><tr><th>Data actions</th><td>{perm.dataActions.length}</td></tr>
            <tr><th>Assignable scopes</th><td>{scopes.join(", ")}</td></tr></tbody></table>)}
      </div>
      {pickPerm && <PermissionPicker onClose={() => setPickPerm(false)} onAdd={(s) => { setPerm((p) => ({ ...p, actions: uniq([...p.actions, ...s.actions]), dataActions: uniq([...p.dataActions, ...s.data]) })); setPickPerm(false); }} />}
      {pickScope && <ScopePicker title="Add assignable scope" value={scopes[0]} onClose={() => setPickScope(false)} onChange={(v) => { setScopes((x) => uniq([...x, v])); setPickScope(false); }} />}
    </Blade>
  );
}
