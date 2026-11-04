/* App Service Networking: regional VNet integration, access restrictions, hybrid connections.
 * Real ARM calls against core/azure_webnet_core.py (see core/capabilities/azure/appservices.json for the honest limits). */
import { useState } from "react";
import { Button, Checkbox, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Select, Tab, TabList, ToolbarButton } from "@fluentui/react-components";
import { Add20Regular } from "@fluentui/react-icons";
import { restJson } from "../../../common/wire.js";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { listAllSubnets } from "../../kit/PrivateEndpoints.jsx";
import { Loading } from "../../kit/common.jsx";

const q = { "api-version": "2023-12-01" };
const call = (method, path, body) => restJson(method, path, { query: q, body });

export default function Networking({ a, reload }) {
  const [tab, setTab] = useState("vnet");
  return (
    <>
      <div className="vy-panel-title">{a.name} | Networking</div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Networking tabs">
        <Tab value="vnet">Virtual network integration</Tab><Tab value="access">Access restrictions</Tab><Tab value="hybrid">Hybrid connections</Tab>
      </TabList>
      <div style={{ marginTop: 12 }}>
        <CapabilityContainer id="azure.appservices.webapp.networking" title={{ vnet: "Virtual network integration", access: "Access restrictions", hybrid: "Hybrid connections" }[tab]}>
          {tab === "vnet" && <VnetIntegration a={a} reload={reload} />}
          {tab === "access" && <AccessRestrictions a={a} reload={reload} />}
          {tab === "hybrid" && <HybridConnections a={a} />}
        </CapabilityContainer>
      </div>
    </>
  );
}

function VnetIntegration({ a, reload }) {
  const notify = useNotify();
  const cur = useAsync(async () => { try { return (await call("GET", `${a.id}/networkConfig/virtualNetwork`)).properties; } catch { return null; } }, [a.id]);
  const subnets = useAsync(listAllSubnets, []);
  const [subnet, setSubnet] = useState("");
  const [busy, setBusy] = useState(false);
  const run = async (fn, ok, fail) => { setBusy(true); try { await fn(); notify.success(ok, "Succeeded"); cur.reload(); reload && reload(); } catch (e) { notify.error(e, fail); } finally { setBusy(false); } };
  if (cur.loading && cur.data === undefined) return <Loading />;
  const sn = subnet || subnets.data?.[0]?.id || "";
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 640 }}>
      {cur.data ? <>
        <Field label="Virtual network"><Input readOnly value={cur.data.subnetResourceId.split("/virtualNetworks/")[1].split("/")[0]} aria-label="Integrated virtual network" /></Field>
        <Field label="Subnet"><Input readOnly value={cur.data.subnetResourceId.split("/").pop()} aria-label="Integrated subnet" /></Field>
        <Checkbox checked={!!cur.data.vnetRouteAllEnabled} disabled={busy} label="Route all outbound traffic through the virtual network"
          onChange={(_, d) => run(() => call("PUT", `${a.id}/config/web`, { properties: { vnetRouteAllEnabled: !!d.checked } }), "Outbound routing was updated.", "Failed to update outbound routing")} />
        <div><Button disabled={busy} onClick={() => run(() => call("DELETE", `${a.id}/networkConfig/virtualNetwork`), "Virtual network integration was removed.", "Failed to disconnect")}>Disconnect</Button></div>
      </> : <>
        <p style={{ fontSize: 13 }}>Not configured. The subnet must be delegated to Microsoft.Web/serverFarms, be at least a /28 and be in the app's region.</p>
        <Field label="Subnet" required>
          <Select value={sn} onChange={(_, d) => setSubnet(d.value)} aria-label="Integration subnet">{(subnets.data || []).map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}</Select>
        </Field>
        <div><Button appearance="primary" disabled={busy || !sn} onClick={() => run(() => call("PUT", `${a.id}/networkConfig/virtualNetwork`, { properties: { subnetResourceId: sn } }), "Virtual network integration was added.", "Failed to add virtual network integration")}>Add virtual network integration</Button></div>
      </>}
    </div>
  );
}

function AccessRestrictions({ a, reload }) {
  const notify = useNotify();
  const cfg = useAsync(async () => (await call("GET", `${a.id}/config/web`)).properties, [a.id]);
  const [add, setAdd] = useState(null);
  const [scm, setScm] = useState(false);
  if (cfg.loading && !cfg.data) return <Loading />;
  const key = scm ? "scmIpSecurityRestrictions" : "ipSecurityRestrictions";
  const dkey = key + "DefaultAction";
  const rules = (cfg.data?.[key] || []);
  const real = rules.filter((r) => r.priority !== 2147483647);
  const save = async (next, extra = {}) => {
    try { await call("PATCH", `${a.id}/config/web`, { properties: { [key]: next, ...extra } }); cfg.reload(); reload && reload(); }
    catch (e) { notify.error(e, "Failed to save access restrictions"); }
  };
  return (
    <>
      <Checkbox checked={scm} onChange={(_, d) => setScm(!!d.checked)} label="Advanced tool site (SCM) rules" />
      <BrowseGrid
        resourceName="access restriction" rowKey={(r) => r.name + r.priority} items={rules} loading={cfg.loading} error={cfg.error} onRefresh={cfg.reload} csvName="access-restrictions.csv"
        extraCommands={<>
          <ToolbarButton icon={<Add20Regular />} onClick={() => setAdd({ name: "", action: "Allow", priority: String((real.length + 1) * 100), kind: "ip", ip: "" })}>Add</ToolbarButton>
          <Select size="small" value={cfg.data?.[dkey] || "Allow"} aria-label="Unmatched rule action" onChange={(_, d) => save(real, { [dkey]: d.value })}>
            <option value="Allow">Unmatched rule action: Allow</option><option value="Deny">Unmatched rule action: Deny</option>
          </Select>
        </>}
        onDelete={async (sel) => save(real.filter((r) => !sel.some((s) => s.name === r.name && s.priority === r.priority)))}
        columns={[
          { key: "priority", label: "Priority" }, { key: "name", label: "Name" },
          { key: "action", label: "Action" },
          { key: "source", label: "Source", value: (r) => r.ipAddress || (r.vnetSubnetResourceId || "").split("/virtualNetworks/")[1] || "--" },
          { key: "tag", label: "Type", value: (r) => (r.tag === "ServiceTag" ? "Service tag" : r.vnetSubnetResourceId ? "Virtual network" : "IPv4/IPv6") },
        ]}
      />
      {add && (
        <Dialog open onOpenChange={(_, d) => !d.open && setAdd(null)}>
          <DialogSurface aria-label="Add access restriction"><DialogBody>
            <DialogTitle>Add access restriction</DialogTitle>
            <DialogContent><div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Name" required><Input value={add.name} onChange={(_, d) => setAdd({ ...add, name: d.value })} aria-label="Rule name" /></Field>
              <Field label="Action"><Select value={add.action} onChange={(_, d) => setAdd({ ...add, action: d.value })} aria-label="Rule action"><option>Allow</option><option>Deny</option></Select></Field>
              <Field label="Priority" required><Input type="number" value={add.priority} onChange={(_, d) => setAdd({ ...add, priority: d.value })} aria-label="Rule priority" /></Field>
              <Field label="Type"><Select value={add.kind} onChange={(_, d) => setAdd({ ...add, kind: d.value })} aria-label="Rule type"><option value="ip">IPv4/IPv6 (CIDR)</option><option value="tag">Service tag</option></Select></Field>
              <Field label={add.kind === "tag" ? "Service tag" : "IP address block"} required><Input value={add.ip} placeholder={add.kind === "tag" ? "AzureFrontDoor.Backend" : "203.0.113.0/24"} onChange={(_, d) => setAdd({ ...add, ip: d.value })} aria-label="Rule source" /></Field>
            </div></DialogContent>
            <DialogActions>
              <Button appearance="primary" disabled={!add.name || !add.ip} onClick={async () => {
                await save([...real, { name: add.name, action: add.action, priority: Number(add.priority), ipAddress: add.ip, ...(add.kind === "tag" ? { tag: "ServiceTag" } : {}) }]);
                setAdd(null);
              }}>Add rule</Button>
              <Button onClick={() => setAdd(null)}>Cancel</Button>
            </DialogActions>
          </DialogBody></DialogSurface>
        </Dialog>
      )}
    </>
  );
}

function HybridConnections({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(async () => (await call("GET", `${a.id}/hybridConnectionRelays`)).value || [], [a.id]);
  const [add, setAdd] = useState(null);
  const rg = a.id.split("/resourceGroups/")[1].split("/")[0];
  const sub = a.id.split("/")[2];
  return (
    <>
      <BrowseGrid
        resourceName="hybrid connection" rowKey={(r) => r.id} items={data || []} loading={loading} error={error} onRefresh={reload} csvName="hybrid-connections.csv"
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd({ ns: "", name: "", host: "", port: "1433", key: "defaultSender" })}>Add hybrid connection</ToolbarButton>}
        onDelete={async (sel) => { for (const r of sel) await call("DELETE", r.id); notify.success(`Removed ${sel.length} hybrid connection(s).`, "Delete succeeded"); reload(); }}
        columns={[
          { key: "name", label: "Name" }, { key: "ns", label: "Namespace", value: (r) => r.properties?.serviceBusNamespace },
          { key: "endpoint", label: "Endpoint", value: (r) => `${r.properties?.hostname}:${r.properties?.port}` },
          { key: "status", label: "Status", value: () => "NotConnected" },
        ]}
      />
      {add && (
        <Dialog open onOpenChange={(_, d) => !d.open && setAdd(null)}>
          <DialogSurface aria-label="Add hybrid connection"><DialogBody>
            <DialogTitle>Add hybrid connection</DialogTitle>
            <DialogContent><div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Relay namespace" required><Input value={add.ns} onChange={(_, d) => setAdd({ ...add, ns: d.value })} aria-label="Relay namespace" /></Field>
              <Field label="Hybrid connection name" required><Input value={add.name} onChange={(_, d) => setAdd({ ...add, name: d.value })} aria-label="Hybrid connection name" /></Field>
              <Field label="Endpoint host" required><Input value={add.host} onChange={(_, d) => setAdd({ ...add, host: d.value })} aria-label="Endpoint host" /></Field>
              <Field label="Endpoint port" required><Input type="number" value={add.port} onChange={(_, d) => setAdd({ ...add, port: d.value })} aria-label="Endpoint port" /></Field>
              <Field label="Send key name" required><Input value={add.key} onChange={(_, d) => setAdd({ ...add, key: d.value })} aria-label="Send key name" /></Field>
            </div></DialogContent>
            <DialogActions>
              <Button appearance="primary" disabled={!add.ns || !add.name || !add.host} onClick={async () => {
                try {
                  await call("PUT", `${a.id}/hybridConnectionNamespaces/${add.ns}/relays/${add.name}`, { properties: {
                    relayArmUri: `/subscriptions/${sub}/resourceGroups/${rg}/providers/Microsoft.Relay/namespaces/${add.ns}/hybridConnections/${add.name}`,
                    hostname: add.host, port: Number(add.port), sendKeyName: add.key } });
                  notify.success(`Hybrid connection '${add.name}' was added.`, "Succeeded"); setAdd(null); reload();
                } catch (e) { notify.error(e, "Failed to add hybrid connection"); }
              }}>Add</Button>
              <Button onClick={() => setAdd(null)}>Cancel</Button>
            </DialogActions>
          </DialogBody></DialogSurface>
        </Dialog>
      )}
    </>
  );
}
