/* User-assigned managed identities for any ARM resource: attach / detach / create
 * Microsoft.ManagedIdentity/userAssignedIdentities. Shared by every service's Identity page.
 * The resource's identity block is PATCHed over the native ARM wire; principalId/clientId of each
 * attached identity are resolved server-side from the identity resource itself. */
import { useState } from "react";
import { Button, Checkbox, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Select } from "@fluentui/react-components";
import { useNotify } from "../../common/notify.jsx";
import { useAsync } from "../../common/useAsync.js";
import { restJson } from "../../common/wire.js";
import { getSubscription } from "./arm.js";
import { CapabilityContainer } from "./Capability.jsx";
import { ErrorBar, InfoBar, KV, Loading } from "./common.jsx";

const UAMI_AV = "2023-01-31";
const listIdentities = async () => (await restJson("GET", `/subscriptions/${getSubscription()}/providers/Microsoft.ManagedIdentity/userAssignedIdentities`, { query: { "api-version": UAMI_AV } })).value || [];

function typeOf(system, userCount) {
  if (system && userCount) return "SystemAssigned,UserAssigned";
  if (system) return "SystemAssigned";
  return userCount ? "UserAssigned" : "None";
}

/** `resourceId` = full ARM id of the resource, `apiVersion` = that resource type's api-version. */
export function UserAssignedIdentities({ resourceId, apiVersion, capabilityId, onChanged, title = "User assigned managed identities" }) {
  const notify = useNotify();
  const res = useAsync(() => restJson("GET", resourceId, { query: { "api-version": apiVersion } }), [resourceId]);
  const all = useAsync(listIdentities, [resourceId]);
  const [open, setOpen] = useState(false);
  const [pick, setPick] = useState(new Set());
  const [sel, setSel] = useState(new Set());
  const [create, setCreate] = useState({ name: "" });
  const ident = res.data?.identity || {};
  const attached = Object.entries(ident.userAssignedIdentities || {});
  const system = String(ident.type || "").toLowerCase().includes("systemassigned");
  const rg = resourceId.split("/")[4];
  const write = async (map) => {
    await restJson("PATCH", resourceId, { query: { "api-version": apiVersion }, body: { identity: { type: typeOf(system, Object.keys(map).length), userAssignedIdentities: map } } });
    await res.reload(); onChanged?.();
  };
  const attach = async () => {
    try {
      let ids = [...pick];
      if (create.name.trim()) {
        const body = { location: res.data?.location || "eastus" };
        const made = await restJson("PUT", `/subscriptions/${getSubscription()}/resourceGroups/${rg}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/${encodeURIComponent(create.name.trim())}`, { query: { "api-version": UAMI_AV }, body });
        ids.push(made.id);
      }
      const map = Object.fromEntries([...attached.map(([k]) => [k, {}]), ...ids.map((k) => [k, {}])]);
      await write(map);
      notify.success(`Attached ${ids.length} user assigned managed identit${ids.length === 1 ? "y" : "ies"}.`, "Add user assigned managed identity");
      setOpen(false); setPick(new Set()); setCreate({ name: "" }); all.reload();
    } catch (e) { notify.error(e, "Attaching the managed identity failed"); }
  };
  const remove = async () => {
    try {
      await write(Object.fromEntries(attached.filter(([k]) => !sel.has(k)).map(([k]) => [k, {}])));
      notify.success(`Removed ${sel.size} user assigned managed identit${sel.size === 1 ? "y" : "ies"}.`, "Remove"); setSel(new Set());
    } catch (e) { notify.error(e, "Removing the managed identity failed"); }
  };
  const toggle = (set, setter, k) => (_, d) => { const n = new Set(set); d.checked ? n.add(k) : n.delete(k); setter(n); };
  const available = (all.data || []).filter((m) => !attached.some(([k]) => k.toLowerCase() === m.id.toLowerCase()));
  const body = (
    <>
      <ErrorBar error={res.error} />
      {res.loading && !res.data ? <Loading /> : (
        <>
          <div style={{ display: "flex", gap: 8, margin: "8px 0" }}>
            <Button appearance="primary" onClick={() => setOpen(true)} aria-label="Add user assigned managed identity">Add</Button>
            <Button disabled={!sel.size} onClick={remove} aria-label="Remove user assigned managed identity">Remove</Button>
          </div>
          <table className="vy-grid" aria-label="User assigned managed identities">
            <thead><tr><th /><th>Name</th><th>Client ID</th><th>Principal (object) ID</th><th>Resource group</th></tr></thead>
            <tbody>
              {attached.length ? attached.map(([k, v]) => (
                <tr key={k}><td><Checkbox checked={sel.has(k)} onChange={toggle(sel, setSel, k)} aria-label={`Select ${k.split("/").pop()}`} /></td>
                  <td>{k.split("/").pop()}</td><td>{v?.clientId || "--"}</td><td>{v?.principalId || "--"}</td><td>{k.split("/")[4]}</td></tr>
              )) : <tr><td colSpan={5} className="vy-muted">No user assigned managed identities.</td></tr>}
            </tbody>
          </table>
        </>
      )}
      <Dialog open={open} onOpenChange={(_, d) => !d.open && setOpen(false)}>
        <DialogSurface aria-label="Add user assigned managed identity"><DialogBody>
          <DialogTitle>Add user assigned managed identity</DialogTitle>
          <DialogContent><div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {available.length ? available.map((m) => (
              <Checkbox key={m.id} checked={pick.has(m.id)} onChange={toggle(pick, setPick, m.id)} label={`${m.name} (${m.id.split("/")[4]})`} />
            )) : <span className="vy-muted">No unattached managed identities in this subscription.</span>}
            <Field label="Or create a new managed identity in this resource group" hint="Created as a Microsoft.ManagedIdentity/userAssignedIdentities resource.">
              <Input value={create.name} onChange={(_, d) => setCreate({ name: d.value })} placeholder="identity name" aria-label="New managed identity name" /></Field>
          </div></DialogContent>
          <DialogActions><Button appearance="primary" disabled={!pick.size && !create.name.trim()} onClick={attach}>Add</Button><Button onClick={() => setOpen(false)}>Cancel</Button></DialogActions>
        </DialogBody></DialogSurface>
      </Dialog>
    </>
  );
  return capabilityId ? <CapabilityContainer id={capabilityId} title={title}>{body}</CapabilityContainer> : <section className="vy-form-section"><h3>{title}</h3>{body}</section>;
}

/** A full Identity page (System assigned + User assigned) for resources whose blade had no real identity panel. */
export function ManagedIdentityPage({ resourceId, apiVersion, name, capabilityId = "azure.cosmos.identity", onChanged }) {
  const notify = useNotify();
  const res = useAsync(() => restJson("GET", resourceId, { query: { "api-version": apiVersion } }), [resourceId]);
  const [tab, setTab] = useState("system");
  const ident = res.data?.identity || {};
  const system = String(ident.type || "").toLowerCase().includes("systemassigned");
  const users = Object.keys(ident.userAssignedIdentities || {});
  const setSystem = async (on) => {
    try {
      await restJson("PATCH", resourceId, { query: { "api-version": apiVersion }, body: { identity: { type: typeOf(on, users.length), userAssignedIdentities: Object.fromEntries(users.map((k) => [k, {}])) } } });
      notify.success(`System assigned managed identity was turned ${on ? "on" : "off"} for '${name}'.`, "Save succeeded"); await res.reload(); onChanged?.();
    } catch (e) { notify.error(e, "Saving the identity failed"); }
  };
  return (
    <>
      <div className="vy-panel-title">{name} | Identity</div>
      <div role="tablist" style={{ display: "flex", gap: 12, margin: "8px 0" }}>
        <Button appearance={tab === "system" ? "primary" : "subtle"} role="tab" aria-selected={tab === "system"} onClick={() => setTab("system")}>System assigned</Button>
        <Button appearance={tab === "user" ? "primary" : "subtle"} role="tab" aria-selected={tab === "user"} onClick={() => setTab("user")}>User assigned</Button>
      </div>
      <ErrorBar error={res.error} />
      {tab === "system" && (
        <section className="vy-form-section"><h3>System assigned managed identity</h3>
          <Select value={system ? "on" : "off"} onChange={(_, d) => setSystem(d.value === "on")} aria-label="System assigned status" style={{ maxWidth: 200 }}>
            <option value="off">Off</option><option value="on">On</option></Select>
          {system && <><KV label="Object (principal) ID" value={ident.principalId} /><KV label="Tenant ID" value={ident.tenantId} /></>}
          <InfoBar>An identity can be the subject of a role assignment on Access control (IAM) of another resource.</InfoBar>
        </section>
      )}
      {tab === "user" && <UserAssignedIdentities resourceId={resourceId} apiVersion={apiVersion} capabilityId={capabilityId} onChanged={onChanged} />}
    </>
  );
}
