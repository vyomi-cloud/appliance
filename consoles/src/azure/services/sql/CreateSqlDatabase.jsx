/* Create SQL Database: Basics, Networking, Security, Additional settings, Tags, Review +
 * create → one native ARM PUT for the database (+ the server, if new) plus the native
 * firewall-rule PUTs for the two "allow access" switches. */
import { useState } from "react";
import { Button, Input, Link, Radio, RadioGroup, Select, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow } from "@fluentui/react-components";
import { Delete20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { DEFAULT_RG, LOCATIONS, listResourceGroups, locationLabel } from "../../kit/arm.js";
import CreateWizard, { FormRow, FormSection } from "../../kit/CreateWizard.jsx";
import { Glyph, NotSimulatedContainer } from "../../kit/common.jsx";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";
import ConfigureDatabaseDialog, { DEFAULT_COMPUTE_STORAGE } from "./ConfigureDatabaseDialog.jsx";
import CreateSqlServerDialog from "./CreateSqlServerDialog.jsx";

const NAME_RE = /^[^<>*%&:\\/?]{1,128}$/;
const RG_RE = /^[-\w._()]{1,90}$/;
const BACKUP_OPTIONS = ["Locally-redundant backup storage", "Zone-redundant backup storage", "Geo-redundant backup storage", "Geo-zone-redundant backup storage"];
const COLLATIONS = ["SQL_Latin1_General_CP1_CI_AS", "SQL_Latin1_General_CP1_CS_AS", "Latin1_General_100_CI_AS_SC_UTF8", "Japanese_CI_AS"];
const MAINTENANCE_WINDOWS = ["System default (5pm to 8am)", "Weekday window (10pm to 6am)", "Weekend window (Fri 10pm to Mon 6am)"];
const BACKUP_TO_CODE = { "Locally-redundant backup storage": "Local", "Zone-redundant backup storage": "Zone", "Geo-redundant backup storage": "Geo", "Geo-zone-redundant backup storage": "GeoZone" };

function TagRows({ tags, onChange }) {
  const upd = (i, k, v) => {
    const xs = tags.map((t, j) => (j === i ? { ...t, [k]: v } : t));
    if (xs[xs.length - 1].name || xs[xs.length - 1].value) xs.push({ name: "", value: "" });
    onChange(xs);
  };
  return (
    <Table size="small" aria-label="Tags" style={{ maxWidth: 760 }}>
      <TableHeader><TableRow><TableHeaderCell>Name</TableHeaderCell><TableHeaderCell>Value</TableHeaderCell><TableHeaderCell>Resource</TableHeaderCell><TableHeaderCell style={{ width: 48 }} /></TableRow></TableHeader>
      <TableBody>
        {tags.map((t, i) => (
          <TableRow key={i}>
            <TableCell><Input size="small" value={t.name} onChange={(_, d) => upd(i, "name", d.value)} aria-label={`Tag name ${i + 1}`} /></TableCell>
            <TableCell><Input size="small" value={t.value} onChange={(_, d) => upd(i, "value", d.value)} aria-label={`Tag value ${i + 1}`} /></TableCell>
            <TableCell>SQL database</TableCell>
            <TableCell>{i < tags.length - 1 && <Button appearance="subtle" size="small" icon={<Delete20Regular />} aria-label="Delete tag" onClick={() => onChange(tags.filter((_, j) => j !== i))} />}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

export default function CreateSqlDatabase() {
  const notify = useNotify();
  const sub = useSubscription();
  const rgs = useAsync(() => listResourceGroups(), [sub.id]);
  const servers = useAsync(() => api.listServers(), [sub.id]);
  const existingDbs = useAsync(() => api.listAllDatabases(), [sub.id]);
  const [newRg, setNewRg] = useState(null);
  const [newServer, setNewServer] = useState(false);
  const [configure, setConfigure] = useState(false);
  const [f, setF] = useState({
    name: "", resourceGroup: DEFAULT_RG, server: "",
    elasticPool: "No", workload: "Production",
    compute: DEFAULT_COMPUTE_STORAGE,
    backupRedundancy: "Geo-redundant backup storage",
    allowAzureServices: "No", addClientIp: "No", connectionPolicy: "Default",
    dataSource: "None", collation: COLLATIONS[0], maintenanceWindow: MAINTENANCE_WINDOWS[0],
    tags: [{ name: "", value: "" }],
  });
  const rg = newRg ?? f.resourceGroup;
  const set = (k) => (_, d) => setF((x) => ({ ...x, [k]: d.value }));

  const basicsErrors = () => {
    const e = [];
    if (!rg) e.push("Resource group is required.");
    else if (!RG_RE.test(rg)) e.push("Resource group names can only include alphanumeric, underscore, parentheses, hyphen and period characters.");
    if (!NAME_RE.test(f.name)) e.push("Database name can't contain <>*%&:\\/? and must be 1-128 characters.");
    if (!f.server) e.push("Server is required.");
    else if ((existingDbs.data || []).some((d) => d.server.toLowerCase() === f.server.toLowerCase() && d.name.toLowerCase() === f.name.toLowerCase()))
      e.push(`A database named "${f.name}" already exists on server "${f.server}".`);
    return e;
  };

  const basics = (
    <>
      <FormSection title="Project details">
        <FormRow label="Subscription" required htmlFor="sql-sub">
          <Select id="sql-sub" value={sub.id} aria-label="Subscription"><option value={sub.id}>{sub.displayName || sub.id}</option></Select>
        </FormRow>
        <FormRow label="Resource group" required htmlFor="sql-rg">
          {newRg === null ? (
            <>
              <Select id="sql-rg" value={f.resourceGroup} onChange={set("resourceGroup")} aria-label="Resource group">
                {[...new Set([DEFAULT_RG, ...(rgs.data || []).map((r) => r.name)])].map((n) => <option key={n} value={n}>{n}</option>)}
              </Select>
              <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewRg("")}>Create new</Link>
            </>
          ) : (
            <>
              <Input id="sql-rg" value={newRg} placeholder="Name of the new resource group" onChange={(_, d) => setNewRg(d.value)} aria-label="New resource group name" />
              <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewRg(null)}>Use existing</Link>
            </>
          )}
        </FormRow>
      </FormSection>
      <FormSection title="Database details">
        <FormRow label="Database name" required htmlFor="sql-name">
          <Input id="sql-name" value={f.name} onChange={set("name")} placeholder="Enter database name" aria-label="Database name" style={{ width: "100%" }} />
        </FormRow>
        <FormRow label="Server" required htmlFor="sql-server">
          <Select id="sql-server" value={f.server} onChange={set("server")} aria-label="Select a server">
            <option value="">Select a server</option>
            {(servers.data || []).map((s) => <option key={s.name} value={s.name}>{s.name} ({locationLabel(s.location)})</option>)}
          </Select>
          <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewServer(true)}>Create new</Link>
        </FormRow>
        <FormRow label="Want to use SQL elastic pool?">
          <RadioGroup layout="horizontal" value={f.elasticPool} onChange={set("elasticPool")} aria-label="Want to use SQL elastic pool?">
            <Radio value="Yes" label="Yes" /><Radio value="No" label="No" />
          </RadioGroup>
          {f.elasticPool === "Yes" && <NotSimulatedContainer feature="SQL elastic pools" note="The database will be created as a standalone database instead." />}
        </FormRow>
        <FormRow label="Workload environment">
          <RadioGroup layout="horizontal" value={f.workload} onChange={set("workload")} aria-label="Workload environment">
            <Radio value="Development" label="Development" /><Radio value="Production" label="Production" />
          </RadioGroup>
        </FormRow>
        <FormRow label="Compute + storage">
          <div>
            {f.compute.tier} {f.compute.serverless ? "Serverless" : "Provisioned"} · {f.compute.maxVCores} vCores · {f.compute.dataMaxSizeGb} GB
            <Button style={{ marginLeft: 8 }} onClick={() => setConfigure(true)}>Configure database</Button>
          </div>
        </FormRow>
      </FormSection>
      <FormSection title="Backup storage redundancy">
        <FormRow label="Backup storage redundancy">
          <RadioGroup value={f.backupRedundancy} onChange={set("backupRedundancy")} aria-label="Backup storage redundancy">
            {BACKUP_OPTIONS.map((o) => <Radio key={o} value={o} label={o} />)}
          </RadioGroup>
        </FormRow>
      </FormSection>
    </>
  );

  const networking = (
    <>
      <FormSection title="Firewall rules">
        <FormRow label="Allow Azure services and resources to access this server">
          <RadioGroup layout="horizontal" value={f.allowAzureServices} onChange={set("allowAzureServices")} aria-label="Allow Azure services and resources to access this server">
            <Radio value="No" label="No" /><Radio value="Yes" label="Yes" />
          </RadioGroup>
        </FormRow>
        <FormRow label="Add current client IP address">
          <RadioGroup layout="horizontal" value={f.addClientIp} onChange={set("addClientIp")} aria-label="Add current client IP address">
            <Radio value="No" label="No" /><Radio value="Yes" label="Yes" />
          </RadioGroup>
          {f.addClientIp === "Yes" && <p style={{ fontSize: 12, marginTop: 4 }} className="vy-muted">Vyomi adds a placeholder address (203.0.113.4/32) — it cannot see the browser's real public IP.</p>}
        </FormRow>
      </FormSection>
      <NotSimulatedContainer title="Private endpoints" feature="Private endpoints for a SQL database" />
      <NotSimulatedContainer title="Connection policy" feature="Server connection policy (Default / Proxy / Redirect)" />
      <FormSection title="Encrypted connections">
        <FormRow label="Minimum TLS version"><Input readOnly value="TLS 1.2" aria-label="Minimum TLS version" /></FormRow>
      </FormSection>
    </>
  );

  const security = (
    <>
      <NotSimulatedContainer title="Microsoft Defender for SQL" feature="Enable Microsoft Defender for SQL" />
      <NotSimulatedContainer title="Ledger" feature="Database ledger" />
      <NotSimulatedContainer title="Server identity" feature="Server managed identity assignment at create time" note="A database-level identity can be configured after creation from Identity." />
      <NotSimulatedContainer title="Transparent data encryption key management" feature="Customer-managed key configuration at create time" note="Toggle TDE after creation from Transparent data encryption." />
      <NotSimulatedContainer title="Always Encrypted" feature="Enable secure enclaves" />
    </>
  );

  const additional = (
    <>
      <FormSection title="Data source">
        <FormRow label="Use existing data">
          <RadioGroup value={f.dataSource} onChange={set("dataSource")} aria-label="Use existing data">
            <Radio value="None" label="None" /><Radio value="Backup" label="Backup" /><Radio value="Sample" label="Sample" />
          </RadioGroup>
          {f.dataSource === "Backup" && <NotSimulatedContainer feature="Restoring from a backup" note="The database will be created empty instead." />}
          {f.dataSource === "Sample" && <p style={{ fontSize: 12, marginTop: 4 }} className="vy-muted">Loads a small canned Customer/Product/SalesOrderHeader schema with sample rows via the query data plane.</p>}
        </FormRow>
      </FormSection>
      <FormSection title="Database collation">
        <FormRow label="Collation">
          <Select value={f.collation} onChange={set("collation")} aria-label="Collation">
            {COLLATIONS.map((c) => <option key={c} value={c}>{c}</option>)}
          </Select>
        </FormRow>
      </FormSection>
      <FormSection title="Maintenance window">
        <FormRow label="Maintenance window">
          <Select value={f.maintenanceWindow} onChange={set("maintenanceWindow")} aria-label="Maintenance window">
            {MAINTENANCE_WINDOWS.map((w) => <option key={w} value={w}>{w}</option>)}
          </Select>
        </FormRow>
      </FormSection>
    </>
  );

  const tags = (
    <>
      <p style={{ fontSize: 13 }}>Tags are name/value pairs that enable you to categorize resources and view consolidated billing by applying the same tag to multiple resources and resource groups.</p>
      <TagRows tags={f.tags} onChange={(t) => setF((x) => ({ ...x, tags: t }))} />
    </>
  );

  const body = () => {
    const cs = api.computeStorageBody(f.compute);
    const server = (servers.data || []).find((s) => s.name === f.server);
    return {
      location: server?.location || "eastus",
      sku: cs.sku,
      properties: {
        ...cs.properties,
        collation: f.collation,
        requestedBackupStorageRedundancy: BACKUP_TO_CODE[f.backupRedundancy],
        maintenanceConfigurationId: f.maintenanceWindow === MAINTENANCE_WINDOWS[0] ? "SQL_Default" : "SQL_CustomWindow",
        creationDate: new Date().toISOString(),
        status: "Online",
      },
      tags: Object.fromEntries(f.tags.filter((t) => t.name).map((t) => [t.name, t.value])),
    };
  };

  const review = () => {
    const b = body();
    const dl = (rows) => <dl>{rows.map(([k, v]) => [<dt key={k + "t"}>{k}</dt>, <dd key={k + "d"}>{v}</dd>])}</dl>;
    return (
      <>
        <h3>Product details</h3>
        {dl([["SQL database", "Standard pricing tier"], ["Estimated cost per month", f.compute && b.sku.capacity ? `~$${api.estimateMonthlyCost(f.compute)}` : "--"]])}
        <h3>Terms</h3>
        <p style={{ fontSize: 12 }} className="vy-muted">By clicking "Create", I (and the organization I represent) agree to the Vyomi simulator terms for this deployment.</p>
        <h3>Basics</h3>
        {dl([["Subscription", sub.displayName || sub.id], ["Resource group", rg || "--"], ["Region", locationLabel(b.location)], ["Database name", f.name || "--"],
          ["Server", f.server || "--"], ["Compute + storage", `${f.compute.tier} ${f.compute.serverless ? "Serverless" : "Provisioned"}, ${f.compute.maxVCores} vCores`], ["Backup storage redundancy", f.backupRedundancy]])}
        <h3>Networking</h3>
        {dl([["Allow Azure services and resources to access this server", f.allowAzureServices], ["Private endpoint", "None"]])}
        <h3>Security</h3>
        {dl([["Transparent data encryption (Server level)", "On"], ["Database level customer-managed key", "None"], ["Database level user assigned managed identity", "None"],
          ["Advanced data security", "Not now"], ["Always Encrypted with secure enclaves", "OFF"], ["Sql Ledger(Database)", "Not configured"], ["Digest Storage", "None"]])}
        <h3>Additional settings</h3>
        {dl([["Use existing data", f.dataSource], ["Collation", f.collation]])}
        <h3>Tags</h3>
        {dl(Object.keys(b.tags).length ? Object.entries(b.tags).map(([k, v]) => [k, v || "(empty)"]) : [["Tags", "None"]])}
      </>
    );
  };

  const onCreate = async () => {
    try {
      await api.createDatabase(rg, f.server, f.name, body());
      if (f.allowAzureServices === "Yes") await api.putFirewallRule(rg, f.server, "AllowAllWindowsAzureIps", { properties: { startIpAddress: "0.0.0.0", endIpAddress: "0.0.0.0" } });
      if (f.addClientIp === "Yes") await api.putFirewallRule(rg, f.server, `ClientIPAddress-${f.name}`, { properties: { startIpAddress: "203.0.113.4", endIpAddress: "203.0.113.4" } });
      if (f.dataSource === "Sample") { await api.ensureDataPlane(f.server, f.name); await api.loadSampleData(f.server, f.name); }
      notify.success(`Deployment of database '${f.name}' to resource group '${rg}' was successful.`, "Deployment succeeded");
      navigate("sql", rg, f.server, f.name);
    } catch (e) { notify.error(e, "Deployment failed"); }
  };

  return (
    <>
      <CreateWizard
        title="Create SQL Database" closeHref="#/sql" glyph={<Glyph id="sql" />}
        tabs={[
          { id: "basics", label: "Basics", content: basics, validate: basicsErrors },
          { id: "networking", label: "Networking", content: networking },
          { id: "security", label: "Security", content: security },
          { id: "additional", label: "Additional settings", content: additional },
          { id: "tags", label: "Tags", content: tags },
        ]}
        review={review}
        onCreate={onCreate}
      />
      <CreateSqlServerDialog open={newServer} onClose={() => setNewServer(false)}
        onCreated={async (payload) => {
          await api.createServer(rg, payload.name, { location: payload.location, properties: payload.properties });
          setF((x) => ({ ...x, server: payload.name }));
          servers.reload();
        }} />
      <ConfigureDatabaseDialog open={configure} initial={f.compute} onClose={() => setConfigure(false)} onApply={(v) => setF((x) => ({ ...x, compute: v }))} />
    </>
  );
}
