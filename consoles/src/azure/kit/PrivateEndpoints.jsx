/* Shared private-endpoint UI for services that support Private Link (storage, Key Vault, SQL, Cosmos DB, ...):
 *  - PrivateEndpointConnectionsPanel: the target's privateEndpointConnections (approve / reject / remove) + "+ Private endpoint"
 *  - PeWizardSection / usePeWizard: optional "Add a private endpoint" block on create wizards (deployed after the resource)
 * Backed by core/azure_netsvc_core.py over real ARM calls. */
import { useState } from "react";
import { Button, Checkbox, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Select, ToolbarButton } from "@fluentui/react-components";
import { Add20Regular } from "@fluentui/react-icons";
import { restJson } from "../../common/wire.js";
import { useNotify } from "../../common/notify.jsx";
import { useAsync } from "../../common/useAsync.js";
import BrowseGrid from "./BrowseGrid.jsx";
import { CapabilityContainer } from "./Capability.jsx";
import { FormRow, FormSection } from "./CreateWizard.jsx";
import { armType, getSubscription } from "./arm.js";
import * as ns from "../services/vnets/netsvc.js";

const VNET = armType("Microsoft.Network", "virtualNetworks", "2023-11-01");
export async function listAllSubnets() {
  const out = [];
  for (const v of await VNET.list()) {
    const subs = (await restJson("GET", `${VNET.path(ns.rgOf(v.id), v.name)}/subnets`, { query: { "api-version": "2023-11-01" } })).value || [];
    subs.forEach((s) => out.push({ id: s.id, label: `${v.name}/${s.name}`, location: v.location, vnet: v.name, rg: ns.rgOf(v.id) }));
  }
  return out;
}
const PEC_API = { "Microsoft.Storage": "2023-01-01", "Microsoft.KeyVault": "2023-07-01", "Microsoft.Sql": "2023-05-01-preview", "Microsoft.DocumentDB": "2024-05-15", "Microsoft.AppConfiguration": "2023-03-01", "Microsoft.CognitiveServices": "2023-05-01" };
const apiOf = (type) => PEC_API[type.split("/")[0]] || "2023-01-01";

export function PrivateEndpointConnectionsPanel({ target, title }) {
  // target: { id, name, type: "Microsoft.Storage/storageAccounts", location }
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(
    async () => (await restJson("GET", `${target.id}/privateEndpointConnections`, { query: { "api-version": apiOf(target.type) } })).value || [], [target.id]);
  const [add, setAdd] = useState(false);
  const setState = async (r, status) => {
    try {
      await restJson("PUT", r.id, { query: { "api-version": apiOf(target.type) }, body: { properties: { privateLinkServiceConnectionState: { status, description: status === "Approved" ? "Approved by an administrator" : "Rejected by an administrator" } } } });
      notify.success(`Connection ${r.name} was ${status.toLowerCase()}.`, status); reload();
    } catch (e) { notify.error(e, `Failed to set connection to ${status}`); }
  };
  return (
    <CapabilityContainer id="azure.vnets.private_endpoints" title={title || "Private endpoint connections"}>
      <BrowseGrid
        resourceName="private endpoint connection" rowKey={(r) => r.id} filterPlaceholder="Filter by name..."
        items={data || []} loading={loading} error={error} onRefresh={reload} csvName="private-endpoint-connections.csv"
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Private endpoint</ToolbarButton>}
        onDelete={async (rows) => { for (const r of rows) await restJson("DELETE", r.id, { query: { "api-version": apiOf(target.type) } }); notify.success(`Removed ${rows.length} connection(s).`, "Remove succeeded"); reload(); }}
        columns={[
          { key: "name", label: "Connection name" },
          { key: "state", label: "Connection state", value: (r) => r.properties?.privateLinkServiceConnectionState?.status },
          { key: "pe", label: "Private endpoint", value: (r) => (r.properties?.privateEndpoint?.id || "").split("/").pop() },
          { key: "desc", label: "Description", value: (r) => r.properties?.privateLinkServiceConnectionState?.description || "--" },
          { key: "group", label: "Sub-resource", value: (r) => (r.properties?.groupIds || []).join(", ") },
          { key: "actions", label: "Actions", value: () => "", render: (r) => (
            <span style={{ display: "flex", gap: 4 }}>
              <Button size="small" aria-label={`Approve ${r.name}`} disabled={r.properties?.privateLinkServiceConnectionState?.status === "Approved"} onClick={() => setState(r, "Approved")}>Approve</Button>
              <Button size="small" aria-label={`Reject ${r.name}`} disabled={r.properties?.privateLinkServiceConnectionState?.status === "Rejected"} onClick={() => setState(r, "Rejected")}>Reject</Button>
            </span>) },
        ]}
      />
      {add && <AddPe target={target} onClose={() => setAdd(false)} onDone={reload} />}
    </CapabilityContainer>
  );
}

function AddPe({ target, onClose, onDone }) {
  const notify = useNotify();
  const subnets = useAsync(listAllSubnets, []);
  const groups = ns.GROUPS[target.type] || [];
  const [name, setName] = useState(`pe-${target.name}`);
  const [subnet, setSubnet] = useState("");
  const [group, setGroup] = useState(groups[0] || "");
  const [busy, setBusy] = useState(false);
  const sn = (subnets.data || []).find((s) => s.id === (subnet || subnets.data?.[0]?.id));
  const go = async () => {
    setBusy(true);
    try { await ns.createPrivateEndpoint(sn.rg, name, sn.location, sn.id, target.id, group, false); notify.success(`Private endpoint '${name}' was created.`, "Private endpoint created"); onDone(); onClose(); }
    catch (e) { notify.error(e, "Failed to create private endpoint"); } finally { setBusy(false); }
  };
  return (
    <Dialog open onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Create a private endpoint">
        <DialogBody>
          <DialogTitle>Create a private endpoint</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Private endpoint name" /></Field>
              <Field label="Virtual network / subnet" required>
                <Select value={sn?.id || ""} onChange={(_, d) => setSubnet(d.value)} aria-label="Subnet">{(subnets.data || []).map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}</Select>
              </Field>
              <Field label="Target sub-resource" required>
                <Select value={group} onChange={(_, d) => setGroup(d.value)} aria-label="Target sub-resource">{groups.map((g) => <option key={g}>{g}</option>)}</Select>
              </Field>
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={busy || !name || !sn} onClick={go}>Create</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

/** Wizard state + section. usage: const pe = usePeWizard("Microsoft.Storage/storageAccounts"); <PeWizardSection pe={pe} />; after create: await pe.deploy(target). */
export function usePeWizard(type) {
  const [on, setOn] = useState(false);
  const [subnet, setSubnet] = useState("");
  const [group, setGroup] = useState((ns.GROUPS[type] || [])[0] || "");
  const subnets = useAsync(listAllSubnets, []);
  const sn = (subnets.data || []).find((s) => s.id === (subnet || subnets.data?.[0]?.id));
  return {
    type, on, setOn, subnet: sn?.id || "", setSubnet, group, setGroup, subnets: subnets.data || [],
    deploy: async (target) => { if (on && sn) await ns.createPrivateEndpoint(sn.rg, `pe-${target.name}`, sn.location, sn.id, target.id, group, false); },
  };
}
export function PeWizardSection({ pe }) {
  const groups = ns.GROUPS[pe.type] || [];
  return (
    <FormSection title="Private endpoint" description="Create a private endpoint after the resource is created.">
      <FormRow label="Add a private endpoint">
        <Checkbox checked={pe.on} onChange={(_, d) => pe.setOn(!!d.checked)} aria-label="Add a private endpoint" />
      </FormRow>
      {pe.on && <>
        <FormRow label="Subnet" htmlFor="pe-wiz-subnet">
          <Select id="pe-wiz-subnet" value={pe.subnet} onChange={(_, d) => pe.setSubnet(d.value)} aria-label="Private endpoint subnet">
            {pe.subnets.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
          </Select>
          {!pe.subnets.length && <div style={{ fontSize: 12 }}>No virtual network subnets exist yet - create a virtual network first.</div>}
        </FormRow>
        <FormRow label="Target sub-resource" htmlFor="pe-wiz-group">
          <Select id="pe-wiz-group" value={pe.group} onChange={(_, d) => pe.setGroup(d.value)} aria-label="Private endpoint target sub-resource">{groups.map((g) => <option key={g}>{g}</option>)}</Select>
        </FormRow>
      </>}
    </FormSection>
  );
}
