/* Deployment stacks (Microsoft.Resources/deploymentStacks, RG scope): a deployment that OWNS the
 * resources its template provisions — delete cascades (or detaches) them, and deny settings block
 * direct delete/write of the managed resources. Backed by core/azure_arm_core.py. */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Select, Textarea } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { restJson } from "../../../common/wire.js";
import { getSubscription } from "../../kit/arm.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ErrorBar } from "../../kit/common.jsx";

const AV = "2024-03-01";
const path = (rg, name) => `/subscriptions/${getSubscription()}/resourceGroups/${rg}/providers/Microsoft.Resources/deploymentStacks${name ? `/${encodeURIComponent(name)}` : ""}`;
const SAMPLE = JSON.stringify({
  $schema: "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#", contentVersion: "1.0.0.0",
  resources: [{ type: "Microsoft.Storage/storageAccounts", apiVersion: "2023-01-01", name: "stackstorage001", location: "eastus", sku: { name: "Standard_LRS" }, kind: "StorageV2", properties: {} }],
}, null, 2);

export default function DeploymentStacks({ rg }) {
  const notify = useNotify();
  const list = useAsync(async () => (await restJson("GET", path(rg), { query: { "api-version": AV } })).value || [], [rg]);
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ name: "", template: SAMPLE, unmanage: "delete", deny: "none" });
  const [del, setDel] = useState(null);
  const [delAction, setDelAction] = useState("delete");
  const create = async () => {
    try {
      await restJson("PUT", path(rg, f.name), { query: { "api-version": AV }, body: { properties: { template: JSON.parse(f.template), actionOnUnmanage: { resources: f.unmanage }, denySettings: { mode: f.deny } } } });
      notify.success(`Deployment stack '${f.name}' was created.`, "Create deployment stack"); setOpen(false); list.reload();
    } catch (e) { notify.error(e, "Creating the deployment stack failed"); }
  };
  const remove = async () => {
    try {
      await restJson("DELETE", path(rg, del), { query: { "api-version": AV, "unmanageAction.Resources": delAction } });
      notify.success(`Deployment stack '${del}' was deleted (${delAction === "delete" ? "managed resources deleted" : "managed resources detached"}).`, "Delete"); setDel(null); list.reload();
    } catch (e) { notify.error(e, "Deleting the deployment stack failed"); }
  };
  const rows = list.data || [];
  return (
    <CapabilityContainer id="azure.resourcegroups.deploymentstacks" title={`${rg} | Deployment stacks`}>
      <ErrorBar error={list.error} />
      <div style={{ display: "flex", gap: 8, margin: "8px 0" }}>
        <Button appearance="primary" onClick={() => setOpen(true)} aria-label="Create deployment stack">Create</Button>
        <Button onClick={list.reload}>Refresh</Button>
      </div>
      <table className="vy-grid" aria-label="Deployment stacks">
        <thead><tr><th>Name</th><th>Provisioning state</th><th>Managed resources</th><th>Deny settings</th><th>On unmanage</th><th /></tr></thead>
        <tbody>
          {rows.length ? rows.map((r) => (
            <tr key={r.name}><td>{r.name}</td><td>{r.properties?.provisioningState}</td>
              <td>{(r.properties?.resources || []).map((m) => m.resourceName || m.id?.split("/").pop()).join(", ") || "--"}</td>
              <td>{r.properties?.denySettings?.mode || "none"}</td><td>{r.properties?.actionOnUnmanage?.resources || "delete"}</td>
              <td><Button size="small" aria-label={`Delete deployment stack ${r.name}`} onClick={() => { setDel(r.name); setDelAction(r.properties?.actionOnUnmanage?.resources || "delete"); }}>Delete</Button></td></tr>
          )) : <tr><td colSpan={6} className="vy-muted">No deployment stacks.</td></tr>}
        </tbody>
      </table>
      <Dialog open={open} onOpenChange={(_, d) => !d.open && setOpen(false)}>
        <DialogSurface aria-label="Create deployment stack"><DialogBody>
          <DialogTitle>Create deployment stack</DialogTitle>
          <DialogContent><div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <Field label="Name" required><Input value={f.name} onChange={(_, d) => setF((x) => ({ ...x, name: d.value }))} aria-label="Deployment stack name" /></Field>
            <Field label="Template (JSON)"><Textarea rows={10} value={f.template} onChange={(_, d) => setF((x) => ({ ...x, template: d.value }))} aria-label="Stack template" /></Field>
            <Field label="Deny settings"><Select value={f.deny} onChange={(_, d) => setF((x) => ({ ...x, deny: d.value }))} aria-label="Deny settings mode">
              <option value="none">None</option><option value="denyDelete">Deny delete</option><option value="denyWriteAndDelete">Deny write and delete</option></Select></Field>
            <Field label="When the stack is deleted"><Select value={f.unmanage} onChange={(_, d) => setF((x) => ({ ...x, unmanage: d.value }))} aria-label="Action on unmanage">
              <option value="delete">Delete managed resources</option><option value="detach">Detach managed resources</option></Select></Field>
          </div></DialogContent>
          <DialogActions><Button appearance="primary" disabled={!f.name.trim()} onClick={create}>Create</Button><Button onClick={() => setOpen(false)}>Cancel</Button></DialogActions>
        </DialogBody></DialogSurface>
      </Dialog>
      <Dialog open={!!del} onOpenChange={(_, d) => !d.open && setDel(null)}>
        <DialogSurface aria-label="Delete deployment stack"><DialogBody>
          <DialogTitle>Delete deployment stack</DialogTitle>
          <DialogContent><Field label="Managed resources"><Select value={delAction} onChange={(_, d) => setDelAction(d.value)} aria-label="Unmanage action on delete">
            <option value="delete">Delete resources</option><option value="detach">Detach resources</option></Select></Field></DialogContent>
          <DialogActions><Button appearance="primary" onClick={remove}>Delete</Button><Button onClick={() => setDel(null)}>Cancel</Button></DialogActions>
        </DialogBody></DialogSurface>
      </Dialog>
    </CapabilityContainer>
  );
}
