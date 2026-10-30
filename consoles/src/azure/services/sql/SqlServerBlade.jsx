/* SQL server (logical server) blade: a minimal Overview plus the Networking panel (public
 * network access + firewall rules), which is what "Set server firewall" on a database and the
 * ui-spec's sql-server-networking page both need. Firewall rules are a real nested ARM
 * resource (Microsoft.Sql/servers/firewallRules); private access / connectivity are honest gaps. */
import { useEffect, useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Link, Radio, RadioGroup, Tab, TabList, ToolbarButton } from "@fluentui/react-components";
import { Add20Regular, ArrowClockwise20Regular, Save20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { locationLabel } from "../../kit/arm.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import ResourceBlade from "../../kit/ResourceBlade.jsx";
import { Essentials, ErrorBar, Glyph, Loading, NotSimulatedContainer } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

export const MENU = [{ id: "overview", label: "Overview" }, { id: "networking", label: "Networking" }];
const LABEL = { overview: "Overview", networking: "Networking" };

export default function SqlServerBlade({ params }) {
  const { rg, server } = params;
  const panel = params.panel || "overview";
  const data = useAsync(() => api.getServer(rg, server), [rg, server]);
  const self = `#/sql/servers/${encodeURIComponent(rg)}/${encodeURIComponent(server)}`;

  let body;
  if (data.loading && !data.data) body = <Loading />;
  else if (data.error) body = <><ErrorBar error={data.error} title="Failed to load the server" /><Link href="#/sql">Back to SQL databases</Link></>;
  else {
    const a = data.data, reload = data.reload;
    body = panel === "networking" ? <Networking a={a} /> : <Overview a={a} reload={reload} />;
  }

  return (
    <ResourceBlade
      title={panel === "overview" ? server : `${server} | ${LABEL[panel] || panel}`} subtitle="SQL server" glyph={<Glyph id="sql" />} closeHref="#/sql"
      menu={MENU} active={panel} hrefFor={(id) => (id === "overview" ? self : `${self}/${id}`)}
    >
      {body}
    </ResourceBlade>
  );
}

function Overview({ a, reload }) {
  return (
    <>
      <div className="vy-cmdbar" role="toolbar" aria-label="Overview commands">
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
      </div>
      <Essentials
        left={[
          ["Resource group", <Link href="#/resourcegroups">{a.resourceGroup}</Link>],
          ["Server name", api.serverFqdn(a.name)],
          ["Location", locationLabel(a.location)],
        ]}
        right={[
          ["Server admin login", a.properties?.administratorLogin || "(Microsoft Entra-only authentication)"],
          ["Public network access", a.properties?.publicNetworkAccess === "Disabled" ? "Disabled" : "Enabled"],
        ]}
      />
    </>
  );
}

function Networking({ a }) {
  const notify = useNotify();
  const [tab, setTab] = useState("public");
  const rules = useAsync(() => api.listFirewallRules(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const [allow, setAllow] = useState(a.properties?.publicNetworkAccess !== "Disabled" ? "Selected networks" : "Disable");
  const [exceptions, setExceptions] = useState(false);
  const [add, setAdd] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setAllow(a.properties?.publicNetworkAccess !== "Disabled" ? "Selected networks" : "Disable");
    setExceptions((rules.data || []).some((r) => r.properties?.startIpAddress === "0.0.0.0" && r.properties?.endIpAddress === "0.0.0.0"));
  }, [a, rules.data]);

  const save = async () => {
    setBusy(true);
    try {
      await api.updateServer(a.resourceGroup, a.name, { properties: { publicNetworkAccess: allow === "Disable" ? "Disabled" : "Enabled" } });
      if (exceptions) await api.putFirewallRule(a.resourceGroup, a.name, "AllowAllWindowsAzureIps", { properties: { startIpAddress: "0.0.0.0", endIpAddress: "0.0.0.0" } });
      else await api.deleteFirewallRule(a.resourceGroup, a.name, "AllowAllWindowsAzureIps").catch(() => {});
      notify.success(`Networking for '${a.name}' was saved.`, "Saved");
      rules.reload();
    } catch (e) { notify.error(e, "Saving networking failed"); }
    finally { setBusy(false); }
  };

  return (
    <>
      <div className="vy-panel-title">Networking</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Networking commands">
        <ToolbarButton icon={<Save20Regular />} disabled={busy} onClick={save}>Save</ToolbarButton>
        <ToolbarButton disabled={busy} onClick={rules.reload}>Discard</ToolbarButton>
      </div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Networking tabs">
        <Tab value="public">Public access</Tab><Tab value="private">Private access</Tab><Tab value="connectivity">Connectivity</Tab>
      </TabList>
      {tab === "public" && (
        <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 16 }}>
          <CapabilityContainer id="azure.sql.networking" title="Public network access">
            <RadioGroup value={allow} onChange={(_, d) => setAllow(d.value)} aria-label="Public network access">
              <Radio value="Disable" label="Disable" /><Radio value="Selected networks" label="Selected networks" />
            </RadioGroup>
          </CapabilityContainer>
          <NotSimulatedContainer title="Virtual networks" feature="Virtual network rules" />
          <section className="vy-section"><h3>Firewall rules</h3>
            <BrowseGrid
              resourceName="firewall rule" rowKey={(r) => r.name} filterPlaceholder="Filter for any field..."
              items={rules.data || []} loading={rules.loading} error={rules.error} onRefresh={rules.reload}
              extraCommands={<>
                <ToolbarButton onClick={() => setAdd("client")}>Add your client IPv4 address</ToolbarButton>
                <ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add a firewall rule</ToolbarButton>
              </>}
              onDelete={async (sel) => { for (const r of sel) await api.deleteFirewallRule(a.resourceGroup, a.name, r.name); rules.reload(); }}
              csvName="firewall-rules.csv"
              columns={[{ key: "name", label: "Rule name" }, { key: "start", label: "Start IPv4 address", value: (r) => r.properties?.startIpAddress }, { key: "end", label: "End IPv4 address", value: (r) => r.properties?.endIpAddress }]}
            />
          </section>
          <section className="vy-section"><h3>Exceptions</h3>
            <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
              <input type="checkbox" checked={exceptions} onChange={(e) => setExceptions(e.target.checked)} />
              Allow Azure services and resources to access this server
            </label>
          </section>
        </div>
      )}
      {tab === "private" && <NotSimulatedContainer title="Private endpoint connections" feature="Private endpoint connections for a SQL server" />}
      {tab === "connectivity" && <NotSimulatedContainer title="Connectivity" feature="Connection policy (Default / Proxy / Redirect) and minimum TLS version enforcement" />}

      <AddFirewallRuleDialog open={!!add} client={add === "client"} onClose={() => setAdd(false)}
        onCreate={async (name, start, end) => { await api.putFirewallRule(a.resourceGroup, a.name, name, { properties: { startIpAddress: start, endIpAddress: end } }); rules.reload(); }} />
    </>
  );
}

function AddFirewallRuleDialog({ open, client, onClose, onCreate }) {
  const notify = useNotify();
  const [name, setName] = useState(client ? "ClientIPAddress" : "");
  const [start, setStart] = useState(client ? "203.0.113.4" : "");
  const [end, setEnd] = useState(client ? "203.0.113.4" : "");
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (open) { setName(client ? "ClientIPAddress" : ""); setStart(client ? "203.0.113.4" : ""); setEnd(client ? "203.0.113.4" : ""); } }, [open, client]);
  const valid = /^[a-zA-Z0-9._-]{1,128}$/.test(name) && start && end;
  const go = async () => {
    setBusy(true);
    try { await onCreate(name, start, end); notify.success(`Firewall rule '${name}' was added.`, "Rule added"); onClose(); }
    catch (e) { notify.error(e, "Failed to add firewall rule"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Add a firewall rule">
        <DialogBody>
          <DialogTitle>Add a firewall rule</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Rule name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Rule name" /></Field>
              <Field label="Start IPv4 address" required><Input value={start} onChange={(_, d) => setStart(d.value)} aria-label="Start IPv4 address" /></Field>
              <Field label="End IPv4 address" required><Input value={end} onChange={(_, d) => setEnd(d.value)} aria-label="End IPv4 address" /></Field>
              {client && <p className="vy-muted" style={{ fontSize: 12 }}>Vyomi can't see the browser's real public IP — this is a placeholder address.</p>}
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!valid || busy} onClick={go}>OK</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
