/* Azure Virtual Network Manager (Microsoft.Network/networkManagers): browse + create, and a manager blade with network groups (+ static members),
 * security admin configurations -> rule collections -> rules, and connectivity configurations over native ARM (core/azure_netcfg_core.py).
 * Configurations are stored and validated; there is no "deploy" that pushes peerings or security admin rules onto traffic. */
import { useEffect, useState } from "react";
import { Button, Checkbox, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Link, Select } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { restJson } from "../../../common/wire.js";
import { DEFAULT_RG, getSubscription, listResourceGroups, locationLabel } from "../../kit/arm.js";
import ArmChildren from "../../kit/ArmChildren.jsx";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import ResourceBlade, { TitleRow } from "../../kit/ResourceBlade.jsx";
import { ErrorBar, Essentials, Glyph, InfoBar, Loading } from "../../kit/common.jsx";
import { remember } from "../../kit/recent.js";
import { useSubscription } from "../../kit/subscription.js";

const V = "2023-09-01";
const sub = () => `/subscriptions/${getSubscription()}`;
const rgOf = (id = "") => (id.split("/resourceGroups/")[1] || "").split("/")[0];
const mPath = (rg, name) => `${sub()}/resourceGroups/${encodeURIComponent(rg)}/providers/Microsoft.Network/networkManagers/${encodeURIComponent(name)}`;
const ACCESS = ["Connectivity", "SecurityAdmin", "Routing"];

export function Managers() {
  const notify = useNotify();
  const s = useSubscription();
  const { data, loading, error, reload } = useAsync(async () => (await restJson("GET", `${sub()}/providers/Microsoft.Network/networkManagers`, { query: { "api-version": V } })).value || [], [s.id]);
  const rgs = useAsync(() => listResourceGroups(), [s.id]);
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ rg: DEFAULT_RG, name: "", access: ["Connectivity", "SecurityAdmin"] });
  const [err, setErr] = useState(null);
  const create = async () => {
    setErr(null);
    try {
      await restJson("PUT", mPath(f.rg, f.name), { query: { "api-version": V }, body: { location: "eastus", properties: { networkManagerScopes: { subscriptions: [`${sub()}`] }, networkManagerScopeAccesses: f.access } } });
      notify.success(`Network manager '${f.name}' created.`, "Create network manager"); setOpen(false); reload();
    } catch (e) { setErr(e); }
  };
  return (
    <>
      <TitleRow title="Network managers" subtitle="Vyomi simulator (default directory)" glyph={<Glyph id="vnets" />} closeHref="#/" />
      <div className="vy-page">
        <BrowseGrid tools resourceName="network manager" items={data || []} loading={loading} error={error} onRefresh={reload} onCreate={() => { setErr(null); setF({ rg: rgs.data?.[0]?.name || DEFAULT_RG, name: "", access: ["Connectivity", "SecurityAdmin"] }); setOpen(true); }}
          onDelete={async (rows) => { for (const r of rows) await restJson("DELETE", mPath(rgOf(r.id), r.name), { query: { "api-version": V } }); notify.success(`Deleted ${rows.length} network manager(s).`, "Delete succeeded"); reload(); }}
          subscriptionLabel={s.displayName || s.id} csvName="network-managers.csv"
          pills={[{ key: "rg", label: "Resource group", value: (r) => rgOf(r.id) }]}
          columns={[{ key: "name", label: "Name", render: (r) => <Link href={`#/networkmanagers/${encodeURIComponent(rgOf(r.id))}/${encodeURIComponent(r.name)}`}>{r.name}</Link> },
            { key: "rg", label: "Resource group", value: (r) => rgOf(r.id) }, { key: "location", label: "Location", value: (r) => locationLabel(r.location) },
            { key: "access", label: "Features", value: (r) => (r.properties?.networkManagerScopeAccesses || []).join(", ") }]}
          emptyAction={<Link as="button" onClick={() => setOpen(true)}>Create a network manager</Link>} />
      </div>
      <Dialog open={open} onOpenChange={(_, d) => !d.open && setOpen(false)}>
        <DialogSurface aria-label="Create network manager"><DialogBody><DialogTitle>Create a network manager</DialogTitle>
          <DialogContent><div style={{ display: "flex", flexDirection: "column", gap: 12 }}><ErrorBar error={err} title="Create failed" />
            <Field label="Resource group"><Select aria-label="Resource group" value={f.rg} onChange={(_, d) => setF({ ...f, rg: d.value })}>{(rgs.data || []).map((g) => <option key={g.name}>{g.name}</option>)}</Select></Field>
            <Field label="Network manager name" required><Input aria-label="Network manager name" value={f.name} onChange={(_, d) => setF({ ...f, name: d.value })} /></Field>
            {ACCESS.map((a) => <Checkbox key={a} label={a} checked={f.access.includes(a)} onChange={(_, d) => setF({ ...f, access: d.checked ? [...f.access, a] : f.access.filter((x) => x !== a) })} />)}
          </div></DialogContent>
          <DialogActions><Button appearance="primary" onClick={create}>Create</Button><Button onClick={() => setOpen(false)}>Cancel</Button></DialogActions></DialogBody></DialogSurface>
      </Dialog>
    </>
  );
}

export const MENU = [
  { id: "overview", label: "Overview" },
  { group: "Settings", items: [{ id: "groups", label: "Network groups" }, { id: "securityadmin", label: "Security admin configurations" }, { id: "connectivity", label: "Connectivity configurations" }] },
];
const DEPLOY_NOTE = "Configurations are stored and validated like Azure's, but there is no Deploy step: Vyomi does not push peerings or security admin rules onto virtual networks or evaluate them against traffic.";

export function ManagerBlade({ params }) {
  const { rg, name } = params;
  const panel = params.panel || "overview";
  const mgr = useAsync(() => restJson("GET", mPath(rg, name), { query: { "api-version": V } }), [rg, name]);
  const self = `#/networkmanagers/${encodeURIComponent(rg)}/${encodeURIComponent(name)}`;
  useEffect(() => { if (mgr.data) remember({ name, type: "Network manager", href: self }); }, [!!mgr.data, self]);
  const [grp, setGrp] = useState(null);
  const [cfg, setCfg] = useState(null);
  const [col, setCol] = useState(null);
  const base = mPath(rg, name);
  let body;
  if (mgr.loading && !mgr.data) body = <Loading />;
  else if (mgr.error) body = <><ErrorBar error={mgr.error} title="Failed to load the network manager" /><Link href="#/networkmanagers">Back to network managers</Link></>;
  else {
    const p = mgr.data.properties || {};
    body = {
      overview: () => (<>
        <div className="vy-panel-title">{name}</div>
        <Essentials left={[["Resource group", rgOf(mgr.data.id)], ["Location", locationLabel(mgr.data.location)]]} right={[["Features", (p.networkManagerScopeAccesses || []).join(", ")], ["Scope", (p.networkManagerScopes?.subscriptions || []).join(", ")]]} />
        <InfoBar title="Control plane only">{DEPLOY_NOTE}</InfoBar>
      </>),
      groups: () => (<>
        <div className="vy-panel-title">{name} | Network groups</div>
        <ArmChildren title="Network groups" noun="network group" path={`${base}/networkGroups`} version={V} onSelect={setGrp} selectedName={grp}
          fields={[{ key: "name", label: "Group name", required: true }, { key: "type", label: "Member type", options: ["VirtualNetwork", "Subnet"] }]} build={(v) => ({ name: v.name, body: { properties: { memberType: v.type } } })}
          columns={[{ label: "Member type", value: (r) => r.properties?.memberType }, { label: "State", value: (r) => r.properties?.provisioningState }]} />
        {grp ? <ArmChildren title={`Static members of ${grp}`} noun="static member" path={`${base}/networkGroups/${grp}/staticMembers`} version={V}
          fields={[{ key: "name", label: "Member name", required: true }, { key: "rid", label: "Virtual network resource id", required: true }]} build={(v) => ({ name: v.name, body: { properties: { resourceId: v.rid } } })}
          columns={[{ label: "Resource id", value: (r) => r.properties?.resourceId }]} /> : <p className="vy-muted">Select a group to manage its members.</p>}
      </>),
      securityadmin: () => (<>
        <div className="vy-panel-title">{name} | Security admin configurations</div>
        <InfoBar title="Not deployed">{DEPLOY_NOTE}</InfoBar>
        <ArmChildren title="Security admin configurations" noun="security admin configuration" path={`${base}/securityAdminConfigurations`} version={V} onSelect={(n) => { setCfg(n); setCol(null); }} selectedName={cfg}
          fields={[{ key: "name", label: "Configuration name", required: true }, { key: "desc", label: "Description" }]} build={(v) => ({ name: v.name, body: { properties: { description: v.desc, applyOnNetworkIntentPolicyBasedServices: ["None"] } } })}
          columns={[{ label: "Description", value: (r) => r.properties?.description }, { label: "State", value: (r) => r.properties?.provisioningState }]} />
        {cfg ? <ArmChildren title={`Rule collections of ${cfg}`} noun="rule collection" path={`${base}/securityAdminConfigurations/${cfg}/ruleCollections`} version={V} onSelect={setCol} selectedName={col}
          fields={[{ key: "name", label: "Collection name", required: true }, { key: "group", label: "Applies to network group", required: true }]}
          build={(v) => ({ name: v.name, body: { properties: { appliesToGroups: [{ networkGroupId: `${base}/networkGroups/${v.group}` }] } } })}
          columns={[{ label: "Applies to", value: (r) => (r.properties?.appliesToGroups || []).map((g) => String(g.networkGroupId).split("/").pop()).join(", ") }]} /> : <p className="vy-muted">Select a configuration to manage its rule collections.</p>}
        {cfg && col ? <ArmChildren title={`Admin rules of ${col}`} noun="admin rule" path={`${base}/securityAdminConfigurations/${cfg}/ruleCollections/${col}/rules`} version={V}
          fields={[{ key: "name", label: "Rule name", required: true }, { key: "priority", label: "Priority (1-4096)", type: "number", def: "100" }, { key: "access", label: "Action", options: ["Deny", "Allow", "AlwaysAllow"] }, { key: "direction", label: "Direction", options: ["Inbound", "Outbound"] }, { key: "protocol", label: "Protocol", options: ["Tcp", "Udp", "Icmp", "Esp", "Ah", "Any"] }, { key: "src", label: "Source address prefix", def: "*" }, { key: "dst", label: "Destination address prefix", def: "*" }, { key: "ports", label: "Destination ports", def: "22", type: "csv" }]}
          build={(v) => ({ name: v.name, body: { kind: "Custom", properties: { priority: v.priority, access: v.access, direction: v.direction, protocol: v.protocol, sources: [{ addressPrefixType: "IPPrefix", addressPrefix: v.src }], destinations: [{ addressPrefixType: "IPPrefix", addressPrefix: v.dst }], destinationPortRanges: v.ports } } })}
          columns={[{ label: "Priority", value: (r) => r.properties?.priority }, { label: "Action", value: (r) => r.properties?.access }, { label: "Direction", value: (r) => r.properties?.direction }, { label: "Protocol", value: (r) => r.properties?.protocol }, { label: "Ports", value: (r) => (r.properties?.destinationPortRanges || []).join(", ") }]} /> : null}
      </>),
      connectivity: () => (<>
        <div className="vy-panel-title">{name} | Connectivity configurations</div>
        <ArmChildren title="Connectivity configurations" noun="connectivity configuration" path={`${base}/connectivityConfigurations`} version={V} note={DEPLOY_NOTE}
          fields={[{ key: "name", label: "Configuration name", required: true }, { key: "topo", label: "Topology", options: ["Mesh", "HubAndSpoke"] }, { key: "group", label: "Network group", required: true }, { key: "hub", label: "Hub virtual network id (hub-and-spoke)" }]}
          build={(v) => ({ name: v.name, body: { properties: { connectivityTopology: v.topo, hubs: v.topo === "HubAndSpoke" && v.hub ? [{ resourceId: v.hub, resourceType: "Microsoft.Network/virtualNetworks" }] : [], appliesToGroups: [{ networkGroupId: `${base}/networkGroups/${v.group}`, groupConnectivity: "None", useHubGateway: "False", isGlobal: "False" }] } } })}
          columns={[{ label: "Topology", value: (r) => r.properties?.connectivityTopology }, { label: "Groups", value: (r) => (r.properties?.appliesToGroups || []).length }]} />
      </>),
    }[panel]?.();
  }
  return (
    <ResourceBlade title={name} subtitle="Network manager" glyph={<Glyph id="vnets" />} closeHref="#/networkmanagers" menu={MENU} active={panel} hrefFor={(id) => (id === "overview" ? self : `${self}/${id}`)}>{body}</ResourceBlade>
  );
}
