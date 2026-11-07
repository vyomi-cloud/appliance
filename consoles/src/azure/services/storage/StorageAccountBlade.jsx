/* Storage account resource blade: left resource menu + panels. Most panels are backed by
 * native ARM / Blob calls (including, since the v4 WAVE 5b gap sweep, Redundancy's RA
 * secondary endpoint, Encryption's CMK validation, Data protection's soft delete/
 * versioning/change feed, Access control (IAM), Blob inventory, Data Lake Gen2 upgrade and
 * the Monitoring group — Metrics/Insights/Alerts/Diagnostic settings/Logs/Workbooks); a
 * remaining handful (separate products, or genuinely unmodellable telemetry/hardware) are
 * honest NotSimulated panels — see NS_NOTES. */
import { ResourceMetrics } from "../../kit/ResourceMonitoring.jsx";
import ResourceEvents from "../../kit/ResourceEvents.jsx";
import { useEffect, useState } from "react";
import {
  Button, Checkbox, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Link,
  Radio, RadioGroup, Select, Spinner, Tab, TabList, Textarea, ToolbarButton,
} from "@fluentui/react-components";
import { Add20Regular, ArrowClockwise20Regular, ArrowDownload20Regular, ArrowUpload20Regular, Copy16Regular, Delete20Regular, Eye16Regular, EyeOff16Regular, Save20Regular, Dismiss20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { href, navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { locationLabel } from "../../kit/arm.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { StorageVnetRules, StorageIpRules } from "../../kit/NetworkRules.jsx";
import { PrivateEndpointConnectionsPanel, PeWizardSection, usePeWizard } from "../../kit/PrivateEndpoints.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import ResourceBlade from "../../kit/ResourceBlade.jsx";
import TasksPanel from "../../kit/TasksPanel.jsx";
import Diagnose from "../../kit/Diagnose.jsx";
import ResourceIam from "../../kit/ResourceIam.jsx";
import { ErrorBar, Essentials, fmtBytes, fmtDate, Glyph, InfoBar, KV, Loading, NotSimulated, NotSimulatedContainer } from "../../kit/common.jsx";
import { remember, forget } from "../../kit/recent.js";
import { useSubscription } from "../../kit/subscription.js";
import { TagRows } from "./CreateStorageAccount.jsx";
import * as api from "./api.js";
import SharedExportTemplate from "../../kit/ExportTemplate.jsx";
import SharedActivityLog from "../../kit/ActivityLog.jsx";
import SharedAdvisor from "../../kit/Advisor.jsx";
import SharedSupportPanel from "../../kit/SupportPanel.jsx";
import { ResourceRecommendations } from "../defender/Pages.jsx";
import AiSearchIntegration from "../../kit/AiSearchIntegration.jsx";
import MarketplaceBrowser from "../../kit/MarketplaceBrowser.jsx";
import { FileServiceSettings, FileShares, ServiceCors } from "./FileShares.jsx";
import { ServiceMonitoring } from "./StorageServiceProps.jsx";
import { DataMigration, StorageMover } from "./StorageMover.jsx";
import StorageEdge from "./StorageEdge.jsx";

const ENFORCEMENT = "These settings are stored on the storage account (ARM) and returned to your SDKs and the az CLI. The Vyomi Blob data plane does not enforce them.";

/** Resource menu: [id, label, real?]. Items without a real panel render NotSimulated. */
export const MENU = [
  { id: "overview", label: "Overview" },
  { id: "activitylog", label: "Activity log" },
  { id: "tags", label: "Tags" },
  { id: "diagnose", label: "Diagnose and solve problems" },
  { id: "iam", label: "Access control (IAM)" },
  { id: "datamigration", label: "Data migration" },
  { id: "events", label: "Events" },
  { id: "storagebrowser", label: "Storage browser" },
  { id: "storagemover", label: "Storage Mover" },
  { id: "partnersolutions", label: "Partner solutions" },
  { group: "Data storage", items: [{ id: "containers", label: "Containers" }, { id: "fileshares", label: "File shares" }, { id: "queues", label: "Queues" }, { id: "tables", label: "Tables" }] },
  { group: "Security + networking", items: [{ id: "networking", label: "Networking" }, { id: "frontdoorcdn", label: "Front Door and CDN" }, { id: "accesskeys", label: "Access keys" }, { id: "sas", label: "Shared access signature" }, { id: "encryption", label: "Encryption" }, { id: "defender", label: "Microsoft Defender for Cloud" }] },
  { group: "Data management", items: [{ id: "redundancy", label: "Redundancy" }, { id: "dataprotection", label: "Data protection" }, { id: "objectreplication", label: "Object replication" }, { id: "inventory", label: "Blob inventory" }, { id: "staticwebsite", label: "Static website" }, { id: "lifecycle", label: "Lifecycle management" }, { id: "azureaisearch", label: "Azure AI Search" }] },
  { group: "Settings", items: [{ id: "configuration", label: "Configuration" }, { id: "datalakegen2upgrade", label: "Data Lake Gen2 upgrade" }, { id: "cors", label: "Resource sharing (CORS)" }, { id: "advisor", label: "Advisor recommendations" }, { id: "endpoints", label: "Endpoints" }, { id: "locks", label: "Locks" }] },
  { group: "Monitoring", items: [{ id: "insights", label: "Insights" }, { id: "alerts", label: "Alerts" }, { id: "metrics", label: "Metrics" }, { id: "workbooks", label: "Workbooks" }, { id: "diagnostics", label: "Diagnostic settings" }, { id: "logs", label: "Logs" }] },
  { group: "Automation", items: [{ id: "tasks", label: "Tasks" }, { id: "exporttemplate", label: "Export template" }] },
  { group: "Help", items: [{ id: "support", label: "Support + Troubleshooting" }] },
];
const LABEL = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
const NS_NOTES = {
  diagnose: "Diagnose and solve problems",
  datamigration: "Data migration tools",
  events: "Event Grid subscriptions on storage events",
  storagemover: "Storage Mover",
  partnersolutions: "Partner solutions",
  fileshares: "Azure Files (file shares)",
  frontdoorcdn: "Front Door and CDN",
  sas: "Shared access signature (SAS) generation",
  defender: "Microsoft Defender for Cloud",
  staticwebsite: "Static website hosting",
  lifecycle: "Lifecycle management policies",
  azureaisearch: "Azure AI Search",
  cors: "Resource sharing (CORS) rules",
  advisor: "Advisor recommendations",
  tasks: "Tasks",
  exporttemplate: "Export template",
  support: "Support + Troubleshooting",
};

export default function StorageAccountBlade({ params, query }) {
  const { rg, name } = params;
  const panel = params.panel || "overview";
  const acct = useAsync(() => api.getStorageAccount(rg, name), [rg, name]);
  const self = `#/storage/${encodeURIComponent(rg)}/${encodeURIComponent(name)}`;
  useEffect(() => { if (acct.data) remember({ name, type: "Storage account", href: self }); }, [!!acct.data, self]);

  let body;
  if (acct.loading && !acct.data) body = <Loading />;
  else if (acct.error) body = <><ErrorBar error={acct.error} title="Failed to load the storage account" /><Link href="#/storage">Back to Storage accounts</Link></>;
  else {
    const a = acct.data, reload = acct.reload;
    const P = {
      frontdoorcdn: () => <StorageEdge a={a} />,
      tasks: () => <TasksPanel a={a} />,
      diagnose: () => <Diagnose id={a.id} name={a.name} />,
      overview: () => <Overview a={a} reload={reload} self={self} />,
      defender: () => <ResourceRecommendations resourceId={a.id} />,
      support: () => <SharedSupportPanel resourceId={a.id} name={a.name} service="storage" />,
      tags: () => <Tags a={a} reload={reload} />,
      containers: () => (query.container ? <Container account={name} container={query.container} self={self} /> : <Containers account={name} self={self} />),
      events: () => <ResourceEvents scopeId={a.id} kind="storage" title={`${a.name} | Events`} />,
      accesskeys: () => <AccessKeys a={a} reload={reload} />,
      configuration: () => <Configuration a={a} reload={reload} />,
      endpoints: () => <Endpoints a={a} />,
      redundancy: () => <Redundancy a={a} self={self} reload={reload} />,
      networking: () => <Networking a={a} reload={reload} />,
      encryption: () => <Encryption a={a} reload={reload} />,
      dataprotection: () => <DataProtection a={a} />,
      objectreplication: () => <ObjectReplication a={a} />,
      staticwebsite: () => <StaticWebsite a={a} />,
      exporttemplate: () => <SharedExportTemplate id={a.id} name={a.name} resourceGroup={a.resourceGroup} />,
      advisor: () => <SharedAdvisor scope={a.id} name={a.name} />,
      iam: () => <Iam a={a} />,
      cors: () => <Cors a={a} />,
      lifecycle: () => <Lifecycle a={a} />,
      sas: () => <Sas a={a} />,
      activitylog: () => <SharedActivityLog scope={a.id} name={a.name} />,
      locks: () => <Locks a={a} />,
      queues: () => (query.queue ? <QueueDetail name={query.queue} self={self} /> : <Queues self={self} />),
      tables: () => (query.table ? <TableDetail name={query.table} self={self} /> : <Tables self={self} />),
      storagebrowser: () => <StorageBrowser account={name} self={self} />,
      inventory: () => <Inventory a={a} />,
      datalakegen2upgrade: () => <DataLakeGen2Upgrade a={a} reload={reload} />,
      metrics: () => <Metrics a={a} />,
      insights: () => <Insights a={a} />,
      alerts: () => <Alerts a={a} />,
      diagnostics: () => <Diagnostics a={a} />,
      logs: () => <LogsPage a={a} />,
      workbooks: () => <Workbooks a={a} />,
      fileshares: () => <FileShares a={a} self={self} query={query} />,
      storagemover: () => <StorageMover a={a} />,
      datamigration: () => <DataMigration a={a} />,
      partnersolutions: () => <MarketplaceBrowser capId="azure.storage.partnersolutions" title={`${a.name} | Partner solutions`} categories={["Storage", "Observability"]} />,
      azureaisearch: () => <AzureAiSearch a={a} />,
    }[panel];
    body = P ? P() : <NotSimulatedContainer title={`${a.name} | ${LABEL[panel] || panel}`} feature={NS_NOTES[panel] || `The ${LABEL[panel] || panel} panel`} />;
  }

  return (
    <ResourceBlade
      title={name} subtitle="Storage account" glyph={<Glyph id="storage" />} closeHref="#/storage"
      menu={MENU} active={panel} hrefFor={(id) => (id === "overview" ? self : `${self}/${id}`)}
    >
      {body}
    </ResourceBlade>
  );
}

// ── Overview ───────────────────────────────────────────────────────────────────────────
function Overview({ a, reload, self }) {
  const notify = useNotify();
  const sub = useSubscription();
  const [tab, setTab] = useState("properties");
  const [del, setDel] = useState(false);
  const [json, setJson] = useState(false);
  const p = a.properties || {};
  const tags = Object.entries(a.tags || {});
  const perf = (a.sku?.tier || (a.sku?.name || "").split("_")[0]) || "--";
  return (
    <>
      <div className="vy-cmdbar" role="toolbar" aria-label="Overview commands">
        <ToolbarButton icon={<ArrowUpload20Regular />} as="a" href={`${self}/containers`}>Upload</ToolbarButton>
        <ToolbarButton icon={<Delete20Regular />} onClick={() => setDel(true)}>Delete</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
      </div>
      <Essentials
        actions={<Link as="button" onClick={() => setJson(true)}>JSON View</Link>}
        left={[
          ["Resource group", <Link href="#/resourcegroups">{a.resourceGroup}</Link>],
          ["Location", locationLabel(a.location)],
          ["Primary/Secondary Location", `Primary: ${locationLabel(a.location)}`],
          ["Subscription", sub.displayName || sub.id],
          ["Subscription ID", sub.id],
          ["Disk state", p.provisioningState === "Succeeded" ? "Primary: Available" : p.provisioningState],
          ["Tags", <span>{tags.length ? tags.map(([k, v]) => `${k} : ${v}`).join(", ") : ""} <Link href={`${self}/tags`}>{tags.length ? "Edit" : "Add tags"}</Link></span>],
        ]}
        right={[
          ["Performance", perf],
          ["Replication", api.skuLabel(a.sku?.name)],
          ["Account kind", a.kind === "StorageV2" ? "StorageV2 (general purpose v2)" : a.kind],
          ["Provisioning state", p.provisioningState],
          ["Created", p.creationTime ? fmtDate(p.creationTime) : undefined],
        ]}
      />
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Overview tabs">
        <Tab value="properties">Properties</Tab>
        <Tab value="monitoring">Monitoring</Tab>
        <Tab value="capabilities">Capabilities</Tab>
        <Tab value="recommendations">Recommendations</Tab>
        <Tab value="tutorials">Tutorials</Tab>
        <Tab value="toolsandsdks">Tools + SDKs</Tab>
      </TabList>
      {tab === "properties" && <Properties a={a} reload={reload} />}
      {tab === "monitoring" && <ResourceMetrics id={a.id} name={a.name} title="Monitoring" />}
      {tab === "capabilities" && <NotSimulatedContainer feature="The capabilities overview" />}
      {tab === "recommendations" && <SharedAdvisor bare scope={a.id} />}
      {tab === "tutorials" && <NotSimulatedContainer feature="Tutorials" />}
      {tab === "toolsandsdks" && <NotSimulatedContainer feature="Tools + SDKs" />}

      <DeleteDialog open={del} onClose={() => setDel(false)} resourceType="storage account" names={[a.name]}
        onConfirm={async () => {
          await api.deleteStorageAccount(a.resourceGroup, a.name);
          forget(self);
          notify.success(`Storage account '${a.name}' was deleted.`, "Delete succeeded");
          navigate("storage");
        }} />
      <Dialog open={json} onOpenChange={(_, d) => setJson(d.open)}>
        <DialogSurface style={{ maxWidth: 820 }} aria-label="Resource JSON">
          <DialogBody>
            <DialogTitle>Resource JSON</DialogTitle>
            <DialogContent>
              <Field label="Resource ID"><Input readOnly value={a.id} /></Field>
              <pre className="vy-mono" style={{ maxHeight: 420, overflow: "auto", background: "var(--colorNeutralBackground3)", padding: 12, borderRadius: 4 }}>{JSON.stringify(Object.fromEntries(Object.entries(a).filter(([k]) => k !== "resourceGroup")), null, 2)}</pre>
            </DialogContent>
            <DialogActions><Button onClick={() => setJson(false)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

const ns = (what) => <span data-vyomi-not-simulated={what} className="vy-muted">Not simulated</span>;
const onoff = (v, dflt) => ((v ?? dflt) ? "Enabled" : "Disabled");

function Properties({ a, reload }) {
  const notify = useNotify();
  const p = a.properties || {};
  const svcQ = useAsync(() => api.getBlobServiceProperties(a.resourceGroup, a.name), [a.id]);
  const sv = svcQ.data || {};
  const days = (x) => (x?.enabled ? `Enabled (${x.days ?? 7} days)` : "Disabled");
  const net = p.publicNetworkAccess === "Disabled" ? "Disabled" : p.networkAcls?.defaultAction === "Deny" ? "Selected networks" : "All networks";
  return (
    <div className="vy-props" style={{ marginTop: 12 }}>
      <section className="vy-section"><h3>Blob service</h3>
        <KV label="Hierarchical namespace" value={onoff(p.isHnsEnabled, false)} />
        <KV label="Default access tier" value={p.accessTier || "--"} />
        <KV label="Blob anonymous access" value={onoff(p.allowBlobPublicAccess, false)} />
        <KV label="Blob soft delete" value={svcQ.loading ? "…" : days(sv.deleteRetentionPolicy)} />
        <KV label="Container soft delete" value={svcQ.loading ? "…" : days(sv.containerDeleteRetentionPolicy)} />
        <KV label="Versioning" value={svcQ.loading ? "…" : onoff(sv.isVersioningEnabled, false)} />
        <KV label="Change feed" value={svcQ.loading ? "…" : onoff(sv.changeFeed?.enabled, false)} />
        <KV label="NFS v3" value={onoff(p.isNfsV3Enabled, false)} />
        <KV label="SFTP" value={onoff(p.isSftpEnabled, false)} />
        <KV label="Allow cross-tenant replication" value={onoff(p.allowCrossTenantReplication, false)} />
      </section>
      <section className="vy-section"><h3>Security</h3>
        <KV label="Require secure transfer for REST API operations" value={onoff(p.supportsHttpsTrafficOnly, true)} />
        <KV label="Storage account key access" value={onoff(p.allowSharedKeyAccess, true)} />
        <KV label="Minimum TLS version" value={(p.minimumTlsVersion || "TLS1_0").replace("TLS", "Version ").replace("_", ".")} />
        <KV label="Infrastructure encryption" value={onoff(p.encryption?.requireInfrastructureEncryption, false)} />
      </section>
      <section className="vy-section"><h3>Networking</h3>
        <KV label="Allow access from" value={net} />
        <KV label="Number of private endpoint connections" value={ns("Private endpoints")} />
        <KV label="Network routing" value={p.routingPreference?.routingChoice === "InternetRouting" ? "Internet routing" : "Microsoft network routing"} />
        <KV label="Endpoint type" value="Standard" />
      </section>
      <section className="vy-section"><h3>File service</h3>
        <KV label="Large file share" value={onoff(p.largeFileSharesState === "Enabled", false)} />
        <KV label="Identity-based access" value={
          <Select value={p.azureFilesIdentityBasedAuthentication?.directoryServiceOptions || "None"} aria-label="Azure Files identity-based access" style={{ maxWidth: 320 }}
            onChange={async (_, d) => { try { await api.updateStorageAccount(a.resourceGroup, a.name, { properties: { azureFilesIdentityBasedAuthentication: { directoryServiceOptions: d.value } } }); notify.success(`Identity-based access set to ${d.value}.`, "Saved"); reload?.(); } catch (e) { notify.error(e, "Saving failed"); } }}>
            <option value="None">Not configured</option><option value="AADKERB">Microsoft Entra Kerberos</option><option value="AADDS">Microsoft Entra Domain Services</option><option value="AD">Active Directory</option>
          </Select>} />
      </section>
      <section className="vy-section"><h3>Queue service</h3>
        <KV label="Approximate messaging" value="Shared across every storage account on this Vyomi — see Queues." />
      </section>
      <section className="vy-section"><h3>Table service</h3>
        <KV label="Table storage" value="A single namespace shared by every storage account — see Tables." />
      </section>
    </div>
  );
}

// ── Tags ───────────────────────────────────────────────────────────────────────────────
function Tags({ a, reload }) {
  const notify = useNotify();
  const init = () => [...Object.entries(a.tags || {}).map(([name, value]) => ({ name, value })), { name: "", value: "" }];
  const [rows, setRows] = useState(init);
  const [busy, setBusy] = useState(false);
  useEffect(() => setRows(init()), [a]);
  const apply = async () => {
    setBusy(true);
    try {
      // ARM PUT replaces the resource's tag set exactly (a PATCH would merge and keep removed keys).
      const { id, name, type, resourceGroup, ...rest } = a;
      await api.createStorageAccount(a.resourceGroup, a.name, { ...rest, tags: Object.fromEntries(rows.filter((t) => t.name).map((t) => [t.name, t.value])) });
      notify.success(`Tags on '${a.name}' were updated.`, "Tags saved");
      reload();
    } catch (e) { notify.error(e, "Saving tags failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">{a.name} | Tags</div>
      <p style={{ fontSize: 13 }}>Tags are name/value pairs that enable you to categorize resources and view consolidated billing by applying the same tag to multiple resources and resource groups.</p>
      <TagRows tags={rows} onChange={setRows} resource={a.name} />
      <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <Button appearance="primary" disabled={busy} onClick={apply}>Apply</Button>
        <Button onClick={() => setRows(init())}>Discard changes</Button>
      </div>
    </>
  );
}

// ── Containers ─────────────────────────────────────────────────────────────────────────
function Containers({ account, self }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listContainers(account), [account]);
  const [create, setCreate] = useState(false);
  const [gap, setGap] = useState(null); // "Change access level" | "Restore containers" | "Give feedback"
  return (
    <>
      <div className="vy-panel-title">{account} | Containers</div>
      <BrowseGrid
        resourceName="container" rowKey={(r) => r.name} filterPlaceholder="Search containers by prefix"
        items={data || []} loading={loading} error={error} onRefresh={reload}
        onCreate={() => setCreate(true)}
        extraCommands={<>
          <ToolbarButton onClick={() => setGap("Change access level")}>Change access level</ToolbarButton>
          <ToolbarButton onClick={() => setGap("Restore containers")}>Restore containers</ToolbarButton>
          <ToolbarButton onClick={() => setGap("Give feedback")}>Give feedback</ToolbarButton>
        </>}
        onDelete={async (rows) => {
          for (const r of rows) await api.deleteContainer(account, r.name);
          notify.success(`Deleted ${rows.length} container${rows.length === 1 ? "" : "s"}.`, "Delete succeeded");
          reload();
        }}
        csvName={`${account}-containers.csv`}
        columns={[
          { key: "name", label: "Name", render: (r) => <Link href={`${self}/containers?container=${encodeURIComponent(r.name)}`}>{r.name}</Link> },
          { key: "modified", label: "Last modified", value: (r) => fmtDate(r.modified) },
          { key: "publicAccess", label: "Anonymous access level" },
          { key: "lease", label: "Lease state", value: (r) => (r.lease ? r.lease[0].toUpperCase() + r.lease.slice(1) : "--") },
        ]}
      />
      <NewContainer open={create} onClose={() => setCreate(false)} account={account} onCreated={reload} />
      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label={gap || "Not simulated"}>
          <DialogBody>
            <DialogTitle>{gap}</DialogTitle>
            <DialogContent><NotSimulated feature={gap === "Give feedback" ? "Sending product feedback" : gap} /></DialogContent>
            <DialogActions><Button onClick={() => setGap(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

function NewContainer({ open, onClose, account, onCreated }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [access, setAccess] = useState("private");
  const [busy, setBusy] = useState(false);
  const [scope, setScope] = useState("");
  const [deny, setDeny] = useState(false);
  const [worm, setWorm] = useState(false);
  const opts = useAsync(async () => (open ? { scopes: (await api.listEncryptionScopes(account)).filter((x) => x.properties?.state === "Enabled"), wormOk: await api.accountSupportsContainerWorm(account) } : { scopes: [], wormOk: false }), [account, open]);
  const valid = /^(?!-)(?!.*--)[a-z0-9-]{3,63}(?<!-)$/.test(name);
  const go = async () => {
    setBusy(true);
    try {
      await api.createContainer(account, name, access, { scope, denyOverride: deny });
      if (worm) await api.putContainerArm(account, name, { immutableStorageWithVersioning: { enabled: true }, ...(scope ? { defaultEncryptionScope: scope, denyEncryptionScopeOverride: deny } : {}) });
      notify.success(`Successfully created storage container '${name}'.`, "Container created");
      setName(""); setAccess("private"); setScope(""); setDeny(false); setWorm(false); onClose(); onCreated();
    } catch (e) { notify.error(e, "Failed to create container"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="New container">
        <DialogBody>
          <DialogTitle action={<Button appearance="subtle" icon={<Dismiss20Regular />} aria-label="Close" onClick={onClose} />}>New container</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Name" required validationMessage={name && !valid ? "Container names must be 3-63 characters: lowercase letters, numbers and single hyphens, starting and ending with a letter or number." : undefined}>
                <Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Container name" />
              </Field>
              <Field label="Anonymous access level">
                <Select value={access} onChange={(_, d) => setAccess(d.value)} aria-label="Anonymous access level">
                  <option value="private">Private (no anonymous access)</option>
                  <option value="blob">Blob (anonymous read access for blobs only)</option>
                  <option value="container">Container (anonymous read access for containers and blobs)</option>
                </Select>
              </Field>
              <Field label="Encryption scope" hint="Defaults to the account's encryption (Microsoft-managed keys) unless an Enabled encryption scope is chosen.">
                <Select value={scope} onChange={(_, d) => setScope(d.value)} aria-label="Default encryption scope">
                  <option value="">Use this account's encryption scope (default)</option>
                  {(opts.data?.scopes || []).map((x) => <option key={x.name} value={x.name}>{x.name}</option>)}
                </Select>
              </Field>
              <Checkbox checked={deny} disabled={!scope} onChange={(_, d) => setDeny(!!d.checked)} label="Use this encryption scope for all blobs in the container" aria-label="Deny encryption scope override" />
              <Checkbox checked={worm} disabled={!opts.data?.wormOk} onChange={(_, d) => setWorm(!!d.checked)} label="Enable version-level immutability support" aria-label="Enable version-level immutability support for this container" />
              {!opts.data?.wormOk && <p className="vy-muted" style={{ fontSize: 12 }}>Version-level immutability must be enabled on the storage account (Data protection) first.</p>}
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!valid || busy} onClick={go}>Create</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

function DeletedBlobsDialog({ open, onClose, account, container, onChanged }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => (open ? api.listDeletedBlobs(account, container) : Promise.resolve([])), [open, account, container]);
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface style={{ maxWidth: 640 }} aria-label="Deleted blobs">
        <DialogBody>
          <DialogTitle>Deleted blobs (soft delete)</DialogTitle>
          <DialogContent>
            <ErrorBar error={error} />
            {loading ? <Loading /> : (data || []).length ? (
              <table className="vy-grid">
                <thead><tr><th>Name</th><th>Deleted at</th><th /></tr></thead>
                <tbody>{data.map((b) => <tr key={b.name}><td>{b.name}</td><td>{fmtDate(b.modified)}</td>
                  <td><Button size="small" onClick={async () => { await api.undeleteBlob(account, container, b.name); notify.success(`Blob '${b.name}' was restored.`, "Undelete succeeded"); reload(); onChanged(); }}>Undelete</Button></td></tr>)}</tbody>
              </table>
            ) : <p className="vy-muted">No soft-deleted blobs within the retention window.</p>}
          </DialogContent>
          <DialogActions><Button onClick={onClose}>Close</Button></DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

function VersionsDialog({ open, onClose, account, container, name }) {
  const { data, loading, error } = useAsync(() => (open && name ? api.listBlobVersions(account, container, name) : Promise.resolve([])), [open, account, container, name]);
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface style={{ maxWidth: 640 }} aria-label="Versions">
        <DialogBody>
          <DialogTitle>Versions — {name}</DialogTitle>
          <DialogContent>
            <ErrorBar error={error} />
            {loading ? <Loading /> : (data || []).length ? (
              <table className="vy-grid">
                <thead><tr><th>Last modified</th><th>Size</th><th>Current</th><th /></tr></thead>
                <tbody>{data.map((v) => <tr key={v.versionId}><td>{fmtDate(v.modified)}</td><td>{fmtBytes(v.size)}</td><td>{v.isCurrent ? "Yes" : ""}</td>
                  <td><Button size="small" onClick={() => api.downloadBlobVersion(account, container, name, v.versionId)}>Download</Button></td></tr>)}</tbody>
              </table>
            ) : <p className="vy-muted">No prior versions — enable Versioning in Data protection.</p>}
          </DialogContent>
          <DialogActions><Button onClick={onClose}>Close</Button></DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

function Container({ account, container, self }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listBlobs(account, container), [account, container]);
  const [upload, setUpload] = useState(false);
  const [deleted, setDeleted] = useState(false);
  const [versionsOf, setVersionsOf] = useState(null);
  return (
    <>
      <div style={{ fontSize: 13, marginTop: 12 }}><Link href={`${self}/containers`}>Containers</Link> <span className="vy-muted">&gt;</span> {container}</div>
      <div className="vy-panel-title">{container} <span className="vy-muted" style={{ fontWeight: 400, fontSize: 13 }}>Container</span></div>
      <section className="vy-section"><h3>Authentication method</h3>
        <KV label="Authentication method" value="Access key (SharedKey) — Microsoft Entra User Account is not simulated" />
      </section>
      <BrowseGrid
        resourceName="blob" rowKey={(r) => r.name} filterPlaceholder="Search blobs by prefix (case-sensitive)"
        items={data || []} loading={loading} error={error} onRefresh={reload}
        extraCommands={<>
          <ToolbarButton icon={<ArrowUpload20Regular />} onClick={() => setUpload(true)}>Upload</ToolbarButton>
          <ToolbarButton onClick={() => setDeleted(true)}>Show deleted blobs</ToolbarButton>
        </>}
        onDelete={async (rows) => {
          for (const r of rows) await api.deleteBlob(account, container, r.name);
          notify.success(`Deleted ${rows.length} blob${rows.length === 1 ? "" : "s"}.`, "Delete succeeded");
          reload();
        }}
        csvName={`${container}-blobs.csv`}
        columns={[
          { key: "name", label: "Name", render: (r) => <Link as="button" onClick={() => api.downloadBlob(account, container, r.name).catch((e) => notify.error(e))}>{r.name}</Link> },
          { key: "modified", label: "Modified", value: (r) => fmtDate(r.modified) },
          { key: "tier", label: "Access tier" },
          { key: "archiveStatus", label: "Archive status", value: () => "--" },
          { key: "type", label: "Blob type" },
          { key: "size", label: "Size", value: (r) => fmtBytes(r.size) },
          { key: "leaseState", label: "Lease state", value: () => "Available" },
          { key: "versions", label: "Versions", value: () => "", render: (r) => <Link as="button" onClick={() => setVersionsOf(r.name)}>Versions</Link> },
          { key: "contentType", label: "Content type", hidden: true },
          { key: "md5", label: "Content-MD5", hidden: true },
        ]}
      />
      <UploadBlob open={upload} onClose={() => setUpload(false)} account={account} container={container} existing={(data || []).map((b) => b.name)} onDone={reload} />
      <DeletedBlobsDialog open={deleted} onClose={() => setDeleted(false)} account={account} container={container} onChanged={reload} />
      <VersionsDialog open={!!versionsOf} onClose={() => setVersionsOf(null)} account={account} container={container} name={versionsOf} />
    </>
  );
}

function UploadBlob({ open, onClose, account, container, existing, onDone }) {
  const notify = useNotify();
  const [files, setFiles] = useState([]);
  const [overwrite, setOverwrite] = useState(false);
  const [busy, setBusy] = useState(false);
  const clash = files.filter((f) => existing.includes(f.name)).map((f) => f.name);
  const go = async () => {
    setBusy(true);
    try {
      for (const f of files) await api.uploadBlob(account, container, f.name, f);
      notify.success(`Successfully uploaded ${files.length} blob${files.length === 1 ? "" : "s"} to '${container}'.`, "Upload completed");
      setFiles([]); onClose(); onDone();
    } catch (e) { notify.error(e, "Upload failed"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Upload blob">
        <DialogBody>
          <DialogTitle>Upload blob</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Files">
                <input type="file" multiple aria-label="Select files" onChange={(e) => setFiles([...e.target.files])} />
              </Field>
              {files.length > 0 && <div style={{ fontSize: 12 }}>{files.length} file(s) selected: {files.map((f) => `${f.name} (${fmtBytes(f.size)})`).join(", ")}</div>}
              <Checkbox checked={overwrite} onChange={(_, d) => setOverwrite(!!d.checked)} label="Overwrite if files already exist" />
              {clash.length > 0 && !overwrite && <InfoBar intent="warning">{clash.join(", ")} already exist{clash.length === 1 ? "s" : ""}. Select "Overwrite" to replace.</InfoBar>}
              <NotSimulatedContainer title="Advanced"
                feature="Authentication type, Blob type, Block size, Access tier, Upload to folder, Blob index tags and Encryption scope"
                note="Files upload as block blobs." />
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!files.length || busy || (clash.length > 0 && !overwrite)} onClick={go}>{busy ? "Uploading..." : "Upload"}</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

// ── Security + networking / settings ───────────────────────────────────────────────────
function Secret({ label, value }) {
  const [show, setShow] = useState(false);
  const notify = useNotify();
  return (
    <Field label={label}>
      <div style={{ display: "flex", gap: 4 }}>
        <Input readOnly type={show ? "text" : "password"} value={value} style={{ flex: 1 }} aria-label={label} />
        <Button icon={show ? <EyeOff16Regular /> : <Eye16Regular />} onClick={() => setShow((v) => !v)}>{show ? "Hide" : "Show"}</Button>
        <Button icon={<Copy16Regular />} aria-label={`Copy ${label}`} onClick={() => navigator.clipboard?.writeText(value).then(() => notify.info(`${label} copied to clipboard.`))} />
      </div>
    </Field>
  );
}

function AccessKeys({ a, reload }) {
  const notify = useNotify();
  const keys = useAsync(() => api.listKeys(a.resourceGroup, a.name), [a.id]);
  const [days, setDays] = useState(String(a.properties?.keyPolicy?.keyExpirationPeriodInDays ?? ""));
  const rotate = async (keyName) => {
    try { await api.regenerateKey(a.resourceGroup, a.name, keyName); notify.success(`${keyName} was regenerated.`, "Rotate key"); keys.reload(); reload?.(); }
    catch (e) { notify.error(e, "Rotating the key failed"); }
  };
  const saveDays = async () => {
    try {
      await api.updateStorageAccount(a.resourceGroup, a.name, { properties: { keyPolicy: days ? { keyExpirationPeriodInDays: Number(days) } : undefined } });
      notify.success("Key expiration policy saved.", "Saved"); keys.reload(); reload?.();
    } catch (e) { notify.error(e, "Saving the key expiration policy failed"); }
  };
  const nowMs = Date.now();
  const ep = api.blobEndpoint(a.name);
  return (
    <>
      <div className="vy-panel-title">{a.name} | Access keys</div>
      <p style={{ fontSize: 13 }}>Access keys authenticate your applications' requests to this storage account. Use the connection string with the azure-storage-blob SDK or <span className="vy-mono">az storage</span>.</p>
      <InfoBar>Keys come from the native <span className="vy-mono">listKeys</span> ARM action. Vyomi issues fixed simulator keys and does not verify SharedKey signatures.</InfoBar>
      <ErrorBar error={keys.error} />
      <Field label="Storage account name" style={{ maxWidth: 760 }}><Input readOnly value={a.name} /></Field>
      {keys.loading ? <Loading /> : (keys.data || []).map((k) => (
        <section className="vy-section" key={k.keyName} style={{ maxWidth: 760, display: "flex", flexDirection: "column", gap: 8 }}>
          <h3>{k.keyName}</h3>
          <KV label="Last rotated" value={fmtDate(k.creationTime)} />
          {k.keyExpirationTime && <KV label="Key expires" value={`${fmtDate(k.keyExpirationTime)}${Date.parse(k.keyExpirationTime) < nowMs ? " (expired — rotate this key)" : ""}`} />}
          <div><Button size="small" onClick={() => rotate(k.keyName)} aria-label={`Rotate key ${k.keyName}`}>Rotate key</Button></div>
          <Secret label="Key" value={k.value} />
          <Secret label="Connection string" value={`DefaultEndpointsProtocol=${location.protocol.replace(":", "")};AccountName=${a.name};AccountKey=${k.value};BlobEndpoint=${ep};`} />
        </section>
      ))}
      <CapabilityContainer id="azure.storage.accesskeys" title="Set rotation reminder">
        <Field label="Set a reminder to rotate access keys (days; blank = off)" style={{ maxWidth: 360 }}>
          <Input type="number" value={days} onChange={(_, d) => setDays(d.value)} aria-label="Key expiration period in days" /></Field>
        <div style={{ marginTop: 8 }}><Button onClick={saveDays} aria-label="Save key expiration policy">Save</Button></div>
      </CapabilityContainer>
    </>
  );
}

function Configuration({ a, reload }) {
  const notify = useNotify();
  const p = a.properties || {};
  const init = () => ({
    supportsHttpsTrafficOnly: p.supportsHttpsTrafficOnly ?? true, allowBlobPublicAccess: p.allowBlobPublicAccess ?? false,
    allowSharedKeyAccess: p.allowSharedKeyAccess ?? true, defaultToOAuthAuthentication: p.defaultToOAuthAuthentication ?? false,
    minimumTlsVersion: p.minimumTlsVersion || "TLS1_2", accessTier: p.accessTier || "Hot", allowCrossTenantReplication: p.allowCrossTenantReplication ?? false,
    copyScope: p.allowedCopyScope || "any",
    sku: a.sku?.name || "Standard_LRS",
  });
  const [f, setF] = useState(init);
  const [busy, setBusy] = useState(false);
  useEffect(() => setF(init()), [a]);
  const dirty = JSON.stringify(f) !== JSON.stringify(init());
  const en = (k, label) => (
    <div className="vy-form-row"><span className="vy-label">{label}</span>
      <RadioGroup layout="horizontal" value={f[k] ? "on" : "off"} onChange={(_, d) => setF((x) => ({ ...x, [k]: d.value === "on" }))} aria-label={label}>
        <Radio value="off" label="Disabled" /><Radio value="on" label="Enabled" />
      </RadioGroup>
    </div>
  );
  const save = async () => {
    setBusy(true);
    try {
      const { sku, copyScope, ...props } = f;
      await api.updateStorageAccount(a.resourceGroup, a.name, { sku: { name: sku }, properties: { ...props, allowedCopyScope: copyScope === "any" ? undefined : copyScope } });
      notify.success(`Configuration of '${a.name}' was saved.`, "Saved");
      reload();
    } catch (e) { notify.error(e, "Saving configuration failed"); }
    finally { setBusy(false); }
  };
  const perf = (f.sku.split("_")[0]) || "Standard";
  const skus = perf === "Premium" ? ["Premium_LRS", "Premium_ZRS"] : ["Standard_LRS", "Standard_ZRS", "Standard_GRS", "Standard_RAGRS", "Standard_GZRS", "Standard_RAGZRS"];
  return (
    <>
      <div className="vy-panel-title">{a.name} | Configuration</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Configuration commands">
        <ToolbarButton icon={<Save20Regular />} disabled={!dirty || busy} onClick={save}>Save</ToolbarButton>
        <ToolbarButton icon={<Dismiss20Regular />} disabled={!dirty} onClick={() => setF(init())}>Discard</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
      </div>
      <InfoBar>{ENFORCEMENT}</InfoBar>
      <div className="vy-kv" style={{ maxWidth: 700 }}><span>Account kind</span><span>{a.kind}</span></div>
      <div className="vy-kv" style={{ maxWidth: 700 }}><span>Performance</span><span>{perf}</span></div>
      {en("supportsHttpsTrafficOnly", "Secure transfer required")}
      {en("allowBlobPublicAccess", "Allow Blob anonymous access")}
      {en("allowSharedKeyAccess", "Allow storage account key access")}
      {en("defaultToOAuthAuthentication", "Default to Microsoft Entra authorization in the Azure portal")}
      <div className="vy-form-row"><label htmlFor="cfg-tls">Minimum TLS version</label>
        <Select id="cfg-tls" value={f.minimumTlsVersion} onChange={(_, d) => setF((x) => ({ ...x, minimumTlsVersion: d.value }))}>
          <option value="TLS1_0">Version 1.0</option><option value="TLS1_1">Version 1.1</option><option value="TLS1_2">Version 1.2</option>
        </Select></div>
      {perf === "Standard" && (
        <div className="vy-form-row"><span className="vy-label">Blob access tier (default)</span>
          <RadioGroup layout="horizontal" value={f.accessTier} onChange={(_, d) => setF((x) => ({ ...x, accessTier: d.value }))} aria-label="Blob access tier (default)">
            <Radio value="Hot" label="Hot" /><Radio value="Cool" label="Cool" /><Radio value="Cold" label="Cold" />
          </RadioGroup></div>
      )}
      <div className="vy-form-row"><label htmlFor="cfg-red">Replication</label>
        <Select id="cfg-red" value={f.sku} onChange={(_, d) => setF((x) => ({ ...x, sku: d.value }))}>
          {skus.map((s) => <option key={s} value={s}>{api.skuLabel(s)}</option>)}
        </Select></div>
      {en("allowCrossTenantReplication", "Allow cross-tenant replication")}
      <div className="vy-form-row"><label htmlFor="cfg-copyscope">Permitted scope for copy operations (preview)</label>
        <Select id="cfg-copyscope" value={f.copyScope} onChange={(_, d) => setF((x) => ({ ...x, copyScope: d.value }))}>
          <option value="any">From any storage account</option>
          <option value="AAD">From storage accounts with the same Microsoft Entra tenant</option>
          <option value="PrivateLink">Into storage accounts with private link connections</option>
        </Select></div>
      <LargeFileShares a={a} reload={reload} />
    </>
  );
}

function Endpoints({ a }) {
  const ep = api.blobEndpoint(a.name);
  const p = a.properties?.primaryEndpoints || {};
  return (
    <>
      <div className="vy-panel-title">{a.name} | Endpoints</div>
      <section className="vy-section" style={{ maxWidth: 760, display: "flex", flexDirection: "column", gap: 10 }}>
        <h3>Blob service</h3>
        <Field label="Blob service (path-style, this Vyomi)" hint="Point azure-storage-blob / az storage at this URL; it is the endpoint this portal uses."><Input readOnly value={ep} /></Field>
        {p.blob && <Field label="Primary endpoint (from ARM)"><Input readOnly value={p.blob} /></Field>}
        <Field label="Storage account resource ID"><Input readOnly value={a.id} /></Field>
      </section>
      <section className="vy-section" style={{ maxWidth: 760, display: "flex", flexDirection: "column", gap: 10 }}>
        <h3>Queue service</h3>
        <Field label="Queue service (this Vyomi)" hint="The Queue data plane is a single namespace shared by every storage account — see Queues."><Input readOnly value={api.queueUrl("")} /></Field>
      </section>
      <section className="vy-section" style={{ maxWidth: 760, display: "flex", flexDirection: "column", gap: 10 }}>
        <h3>Table service</h3>
        <Field label="Table service (this Vyomi)" hint="The Table data plane is a single namespace shared by every storage account — see Tables."><Input readOnly value={api.tableUrl("")} /></Field>
      </section>
      <section className="vy-section" style={{ maxWidth: 760, display: "flex", flexDirection: "column", gap: 10 }}>
        <h3>Static website</h3>
        <Field label="Primary endpoint" hint="Enabled on the Static website page."><Input readOnly value={api.websiteEndpoint(a.name)} /></Field>
      </section>
      <section className="vy-section" style={{ maxWidth: 760, display: "flex", flexDirection: "column", gap: 10 }}>
        <h3>File service</h3>
        <Field label="File shares (ARM)" hint="Browse and manage shares under File shares; the SMB / NFS protocols themselves are not served."><Input readOnly value={`${a.id}/fileServices/default/shares`} /></Field>
        <Field label="Primary endpoint (from ARM)"><Input readOnly value={p.file || "--"} /></Field>
      </section>
      <section className="vy-section" style={{ maxWidth: 760, display: "flex", flexDirection: "column", gap: 10 }}>
        <h3>Other services</h3>
        <Field label="Data Lake Storage Gen2 (dfs)" hint={a.properties?.isHnsEnabled ? "Hierarchical namespace is enabled." : "Enable hierarchical namespace (Data Lake Gen2 upgrade) to use the dfs endpoint."}>
          <Input readOnly value={a.properties?.isHnsEnabled ? (p.dfs || `${api.blobEndpoint(a.name)}/__dfs__`) : "Not enabled"} /></Field>
        <Field label="NFS v3 (blob)"><Input readOnly value={a.properties?.isNfsV3Enabled ? "Enabled" : "Disabled"} /></Field>
        <Field label="SFTP"><Input readOnly value={a.properties?.isSftpEnabled ? "Enabled" : "Disabled"} /></Field>
      </section>
    </>
  );
}

function Redundancy({ a, self, reload }) {
  const notify = useNotify();
  const [fo, setFo] = useState(false);
  const ra = api.isReadAccessSku(a.sku?.name);
  const sec = useAsync(() => (ra ? api.listContainersSecondary(a.name) : Promise.resolve(null)), [a.sku?.name, ra]);
  return (
    <CapabilityContainer id="azure.storage.redundancy" title={`${a.name} | Redundancy`}>
      <KV label="Redundancy" value={api.skuLabel(a.sku?.name)} />
      <KV label="Primary location" value={locationLabel(a.location)} />
      <p style={{ fontSize: 13 }}>Change redundancy in <Link href={`${self}/configuration`}>Configuration</Link>.</p>
      <section className="vy-section"><h3>Storage endpoints</h3>
        <p style={{ fontSize: 13 }}>See <Link href={`${self}/endpoints`}>Endpoints</Link> for this account's service URLs.</p>
      </section>
      <section className="vy-section"><h3>Secondary (read-access) endpoint</h3>
        <KV label="Read access to data in the secondary region" value={ra ? "Enabled" : "Disabled"} />
        {ra ? <>
          <KV label="Secondary Blob endpoint" value={api.secondaryBlobEndpoint(a.name)} />
          <p style={{ fontSize: 13 }}>A real, read-only alias of this account's own data (Vyomi stores data once, locally — there is no second region).
            {" "}{sec.loading ? "Checking the secondary endpoint…" : sec.error ? `Secondary endpoint error: ${sec.error.message}` : `Secondary endpoint reachable — ${sec.data?.length ?? 0} container(s) visible.`}</p>
        </> : <p style={{ fontSize: 13 }}>Enable RA-GRS or RA-GZRS in Configuration to turn this on.</p>}
      </section>
      <section className="vy-section"><h3>Geo-replication</h3>
        {a.properties?.secondaryLocation ? <>
          <KV label="Primary region" value={locationLabel(a.location)} />
          <KV label="Secondary region (paired)" value={locationLabel(a.properties.secondaryLocation)} />
          <KV label="Replication status" value={a.properties.geoReplicationStats?.status || "Live"} />
          <KV label="Last sync time" value={a.properties.geoReplicationStats?.lastSyncTime ? fmtDate(a.properties.geoReplicationStats.lastSyncTime) : "--"} />
          <KV label="Can fail over" value={a.properties.geoReplicationStats?.canFailover === false ? "No" : "Yes"} />
          <div style={{ marginTop: 8 }}><Button disabled={a.properties.geoReplicationStats?.canFailover === false} onClick={() => setFo(true)}>Prepare for failover</Button></div>
          <p style={{ fontSize: 13 }}>Failover swaps the primary and secondary regions and converts the account to locally-redundant storage, like Azure. Vyomi stores the data once, so there is no replication lag and the last sync time tracks the present.</p>
        </> : <p style={{ fontSize: 13 }}>This account uses {api.skuLabel(a.sku?.name)}. Geo-replication and customer-managed failover need GRS, RA-GRS, GZRS or RA-GZRS (change it in Configuration).</p>}
      </section>
      <DeleteDialog open={fo} onClose={() => setFo(false)} resourceType="failover" title="Prepare for failover" confirmLabel="Failover" names={[a.name]} confirmText={a.name}
        warning={<>Failing over <b>{a.name}</b> makes {locationLabel(a.properties?.secondaryLocation)} the primary region and converts the account to LRS. You will need to reconfigure geo-redundancy afterwards.</>}
        onConfirm={async () => { await api.ARM.action(a.resourceGroup, a.name, "failover"); notify.success(`Failover of '${a.name}' completed.`, "Failover"); reload(); }} />
    </CapabilityContainer>
  );
}

function Networking({ a, reload }) {
  const notify = useNotify();
  const p = a.properties || {};
  const patch = async (props, msg) => { try { await api.updateStorageAccount(a.resourceGroup, a.name, { properties: props }); notify.success(msg, "Saved"); reload?.(); } catch (e) { notify.error(e, "Saving failed"); } };
  const [ri, setRi] = useState({ tenantId: "", resourceId: "" });
  const [domain, setDomain] = useState({ name: p.customDomain?.name || "", useSubDomainName: !!p.customDomain?.useSubDomainName });
  const rules = p.networkAcls?.resourceAccessRules || [];
  const [tab, setTab] = useState("public");
  const net = p.publicNetworkAccess === "Disabled" ? "Disabled" : p.networkAcls?.defaultAction === "Deny" ? "Enable from selected networks" : "Enable from all networks";
  return (
    <>
      <div className="vy-panel-title">{a.name} | Networking</div>
      <InfoBar>{ENFORCEMENT}</InfoBar>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Networking tabs">
        <Tab value="public">Public access</Tab>
        <Tab value="private">Private access</Tab>
        <Tab value="advanced">Advanced</Tab>
      </TabList>
      {tab === "public" && <div style={{ display: "flex", flexDirection: "column", gap: 16, marginTop: 12 }}>
        <section className="vy-section"><h3>Public network access</h3>
          <KV label="Public network access" value={p.publicNetworkAccess === "Disabled" ? "Disabled" : "Enabled"} />
          <KV label="Public network access scope" value={net} />
        </section>
        <StorageVnetRules a={a} reload={reload} />
        <StorageIpRules a={a} reload={reload} />
        <CapabilityContainer id="azure.storage.networking" title="Resource instances">
          <table className="vy-grid"><thead><tr><th>Resource ID</th><th>Tenant ID</th><th /></tr></thead><tbody>
            {rules.length ? rules.map((r, i) => (
              <tr key={i}><td>{r.resourceId}</td><td>{r.tenantId}</td>
                <td><Button size="small" aria-label={`Remove resource instance ${i + 1}`} onClick={() => patch({ networkAcls: { ...p.networkAcls, resourceAccessRules: rules.filter((_, j) => j !== i) } }, "Resource instance removed.")}>Remove</Button></td></tr>
            )) : <tr><td colSpan={3} className="vy-muted">No resource instances.</td></tr>}
          </tbody></table>
          <div style={{ display: "flex", gap: 8, marginTop: 8, alignItems: "flex-end" }}>
            <Field label="Resource ID" style={{ flex: 2 }}><Input value={ri.resourceId} onChange={(_, d) => setRi((x) => ({ ...x, resourceId: d.value }))} aria-label="Resource instance resource ID" /></Field>
            <Field label="Tenant ID" style={{ flex: 1 }}><Input value={ri.tenantId} onChange={(_, d) => setRi((x) => ({ ...x, tenantId: d.value }))} aria-label="Resource instance tenant ID" /></Field>
            <Button disabled={!ri.resourceId.trim()} aria-label="Add resource instance"
              onClick={() => { patch({ networkAcls: { ...p.networkAcls, resourceAccessRules: [...rules, { tenantId: ri.tenantId || "00000000-0000-0000-0000-000000000000", resourceId: ri.resourceId.trim() }] } }, "Resource instance added."); setRi({ tenantId: "", resourceId: "" }); }}>Add</Button>
          </div>
        </CapabilityContainer>
        <CapabilityContainer id="azure.storage.exceptions" title="Exceptions">
          {["AzureServices", "Logging", "Metrics"].map((k) => {
            const cur = String(p.networkAcls?.bypass || "AzureServices").split(",").map((x) => x.trim()).filter((x) => x && x !== "None");
            const label = { AzureServices: "Allow Azure services on the trusted services list to access this storage account", Logging: "Allow read access to storage logging from any network", Metrics: "Allow read access to storage metrics from any network" }[k];
            return <Checkbox key={k} label={label} checked={cur.includes(k)} aria-label={label}
              onChange={(_, d) => { const next = d.checked ? [...new Set([...cur, k])] : cur.filter((x) => x !== k); patch({ networkAcls: { ...p.networkAcls, bypass: next.length ? next.join(",") : "None" } }, "Exceptions were saved."); }} />;
          })}
        </CapabilityContainer>
      </div>}
      {tab === "private" && <PrivateEndpointConnectionsPanel target={{ id: a.id, name: a.name, type: "Microsoft.Storage/storageAccounts", location: a.location }} />}
      {tab === "advanced" && <div style={{ display: "flex", flexDirection: "column", gap: 16, marginTop: 12 }}>
        <section className="vy-section"><h3>Network routing</h3>
          <KV label="Routing preference" value={p.routingPreference?.routingChoice === "InternetRouting" ? "Internet routing" : "Microsoft network routing"} />
          <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 8 }}>
            <Checkbox checked={!!p.routingPreference?.publishMicrosoftEndpoints} label="Publish Microsoft network routing endpoints"
              onChange={(_, d) => patch({ routingPreference: { ...p.routingPreference, publishMicrosoftEndpoints: !!d.checked } }, "Routing endpoints updated.")} />
            <Checkbox checked={!!p.routingPreference?.publishInternetEndpoints} label="Publish Internet routing endpoints"
              onChange={(_, d) => patch({ routingPreference: { ...p.routingPreference, publishInternetEndpoints: !!d.checked } }, "Routing endpoints updated.")} />
            {p.primaryEndpoints?.microsoftEndpoints && <KV label="Microsoft routing blob endpoint" value={`${location.origin}${p.primaryEndpoints.microsoftEndpoints.blob}`} />}
            {p.primaryEndpoints?.internetEndpoints && <KV label="Internet routing blob endpoint" value={`${location.origin}${p.primaryEndpoints.internetEndpoints.blob}`} />}
            <p className="vy-muted" style={{ fontSize: 12 }}>Vyomi is single-origin: both route-specific endpoints resolve to this account's one data path.</p>
          </div>
        </section>
        <CapabilityContainer id="azure.storage.networking" title="Custom domain">
          <Field label="Domain name" style={{ maxWidth: 420 }}><Input value={domain.name} onChange={(_, d) => setDomain((x) => ({ ...x, name: d.value }))} aria-label="Custom domain name" /></Field>
          <Checkbox checked={domain.useSubDomainName} label="Use indirect CNAME validation" onChange={(_, d) => setDomain((x) => ({ ...x, useSubDomainName: !!d.checked }))} />
          <div style={{ marginTop: 8 }}><Button aria-label="Save custom domain" onClick={() => patch({ customDomain: domain.name ? { name: domain.name, useSubDomainName: domain.useSubDomainName } : null }, "Custom domain saved.")}>Save</Button></div>
        </CapabilityContainer>
      </div>}
    </>
  );
}

function Encryption({ a, reload }) {
  const notify = useNotify();
  const enc = a.properties?.encryption || {};
  const init = () => ({
    cmk: enc.keySource === "Microsoft.Keyvault",
    keyvaulturi: enc.keyvaultproperties?.keyvaulturi || "", keyname: enc.keyvaultproperties?.keyname || "",
  });
  const [f, setF] = useState(init);
  const [busy, setBusy] = useState(false);
  useEffect(() => setF(init()), [a]);
  const dirty = JSON.stringify(f) !== JSON.stringify(init());
  const save = async () => {
    setBusy(true);
    try {
      await api.updateStorageAccount(a.resourceGroup, a.name, { properties: { encryption: f.cmk
        ? { keySource: "Microsoft.Keyvault", keyvaultproperties: { keyvaulturi: f.keyvaulturi, keyname: f.keyname } }
        : { keySource: "Microsoft.Storage" } } });
      notify.success(`Encryption settings on '${a.name}' were saved.`, "Saved");
      reload();
    } catch (e) { notify.error(e, "Saving encryption settings failed"); }
    finally { setBusy(false); }
  };
  return (
    <CapabilityContainer id="azure.storage.encryption" title={`${a.name} | Encryption`}
      actions={<>
        <ToolbarButton icon={<Save20Regular />} disabled={!dirty || busy} onClick={save}>Save</ToolbarButton>
        <ToolbarButton icon={<Dismiss20Regular />} disabled={!dirty} onClick={() => setF(init())}>Discard</ToolbarButton>
      </>}>
      <section className="vy-section"><h3>Encryption selection</h3>
        <div className="vy-form-row"><span className="vy-label">Encryption type</span>
          <RadioGroup layout="horizontal" value={f.cmk ? "cmk" : "mmk"} onChange={(_, d) => setF((x) => ({ ...x, cmk: d.value === "cmk" }))} aria-label="Encryption type">
            <Radio value="mmk" label="Microsoft-managed keys" /><Radio value="cmk" label="Customer-managed keys" />
          </RadioGroup>
        </div>
        {f.cmk && <>
          <Field label="Key vault URI" hint="https://{vault-name}.vault.azure.net/ — must be a Key Vault that exists in this subscription.">
            <Input value={f.keyvaulturi} onChange={(_, d) => setF((x) => ({ ...x, keyvaulturi: d.value }))} /></Field>
          <Field label="Key name"><Input value={f.keyname} onChange={(_, d) => setF((x) => ({ ...x, keyname: d.value }))} /></Field>
        </>}
      </section>
      <section className="vy-section"><h3>Infrastructure encryption</h3>
        <KV label="Enable infrastructure encryption" value={enc.requireInfrastructureEncryption ? "Enabled" : "Disabled"} />
        <p className="vy-muted" style={{ fontSize: 12 }}>Set at account creation only, as in Azure (immutable afterwards). Stored and reported; Vyomi does not layer a second encryption pass. The named key's own existence inside the vault is not checked — only that the vault exists.</p>
      </section>
      <EncryptionScopes a={a} />
    </CapabilityContainer>
  );
}

// Encryption scopes: Microsoft.Storage/storageAccounts/encryptionScopes ARM children; containers and blobs
// reference them (x-ms-default-encryption-scope / x-ms-encryption-scope), validated by core/azure_blob_core.py.
function EncryptionScopes({ a }) {
  const notify = useNotify();
  const list = useAsync(() => api.listEncryptionScopes(a.name), [a.id]);
  const [f, setF] = useState({ name: "", source: "Microsoft.Storage", keyUri: "", infra: false });
  const add = async () => {
    try {
      await api.putEncryptionScope(a.name, f.name, { source: f.source, state: "Enabled", requireInfrastructureEncryption: f.infra, ...(f.source === "Microsoft.KeyVault" ? { keyVaultProperties: { keyUri: f.keyUri } } : {}) });
      notify.success(`Encryption scope '${f.name}' was created.`, "Created");
      setF({ name: "", source: "Microsoft.Storage", keyUri: "", infra: false }); list.reload();
    } catch (e) { notify.error(e, "Creating the encryption scope failed"); }
  };
  const toggle = async (x) => {
    try { await api.putEncryptionScope(a.name, x.name, { state: x.properties.state === "Enabled" ? "Disabled" : "Enabled" }); list.reload(); }
    catch (e) { notify.error(e, "Updating the encryption scope failed"); }
  };
  return (
    <section className="vy-section"><h3>Encryption scopes</h3>
      <ErrorBar error={list.error} />
      <table className="vy-grid" aria-label="Encryption scopes">
        <thead><tr><th>Name</th><th>Encryption type</th><th>Infrastructure encryption</th><th>Status</th><th /></tr></thead>
        <tbody>{(list.data || []).length ? list.data.map((x) => (
          <tr key={x.name}><td>{x.name}</td><td>{x.properties.source === "Microsoft.KeyVault" ? "Customer-managed key" : "Microsoft-managed key"}</td>
            <td>{x.properties.requireInfrastructureEncryption ? "Enabled" : "Disabled"}</td><td>{x.properties.state}</td>
            <td><Button size="small" aria-label={`${x.properties.state === "Enabled" ? "Disable" : "Enable"} ${x.name}`} onClick={() => toggle(x)}>{x.properties.state === "Enabled" ? "Disable" : "Enable"}</Button></td></tr>
        )) : <tr><td colSpan={5} className="vy-muted">No encryption scopes yet.</td></tr>}</tbody>
      </table>
      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 12, maxWidth: 520 }}>
        <Field label="Encryption scope name"><Input value={f.name} onChange={(_, d) => setF((x) => ({ ...x, name: d.value }))} aria-label="Encryption scope name" /></Field>
        <Field label="Encryption type">
          <Select value={f.source} onChange={(_, d) => setF((x) => ({ ...x, source: d.value }))} aria-label="Scope encryption type">
            <option value="Microsoft.Storage">Microsoft-managed key</option><option value="Microsoft.KeyVault">Customer-managed key</option>
          </Select></Field>
        {f.source === "Microsoft.KeyVault" && <Field label="Key URI" hint="https://{vault}.vault.azure.net/keys/{name}"><Input value={f.keyUri} onChange={(_, d) => setF((x) => ({ ...x, keyUri: d.value }))} aria-label="Scope key URI" /></Field>}
        <Checkbox checked={f.infra} onChange={(_, d) => setF((x) => ({ ...x, infra: !!d.checked }))} label="Enable infrastructure encryption (immutable)" />
        <div><Button appearance="primary" disabled={!f.name} onClick={add} aria-label="Create encryption scope">Create</Button></div>
      </div>
    </section>
  );
}

// ── Static website (Microsoft.Storage/storageAccounts/blobServices/default, properties.staticWebsite) ──
// ── Access control (IAM) — tabs are real; every panel is an honest gap ────────────────
// ── Object replication — ENFORCED by core/azure_blob_core.py: a blob written to the source
// container (matching the prefix filter) is copied to the destination container, and deleting
// it removes the replica. Synchronous here; Azure replicates asynchronously (minutes).
function ObjectReplication({ a }) {
  const notify = useNotify();
  const [open, setOpen] = useState(false);
  const { data, loading, error, reload } = useAsync(async () => {
    const [own, accounts] = await Promise.all([api.listReplicationPolicies(a.resourceGroup, a.name), api.listStorageAccounts()]);
    return { accounts, rules: own.flatMap((p) => (p.properties?.rules || []).map((r) => ({ ...r, policy: p, key: `${p.name}/${r.ruleId || r.sourceContainer}` }))) };
  }, [a.id]);
  const rules = data?.rules || [];
  return (
    <CapabilityContainer id="azure.storage.objectreplication" title={`${a.name} | Object replication`}
      actions={<>
        <ToolbarButton icon={<Add20Regular />} onClick={() => setOpen(true)}>Create replication rules</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
      </>}>
      <ErrorBar error={error} />
      <BrowseGrid
        resourceName="replication rule" rowKey={(r) => r.key}
        items={rules} loading={loading} onRefresh={reload}
        onDelete={async (sel) => {
          for (const pol of new Set(sel.map((r) => r.policy))) await api.deleteReplicationPolicy(pol);
          notify.success(`Deleted ${sel.length} replication rule${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
          reload();
        }}
        csvName="object-replication-rules.csv"
        columns={[
          { key: "source", label: "Source account", value: (r) => r.policy.properties.sourceAccount },
          { key: "sc", label: "Source container", value: (r) => r.sourceContainer },
          { key: "dest", label: "Destination account", value: (r) => r.policy.properties.destinationAccount },
          { key: "dc", label: "Destination container", value: (r) => r.destinationContainer },
          { key: "filter", label: "Prefix filter", value: (r) => (r.filters?.prefixMatch || []).join(", ") || "--" },
        ]}
      />
      <NewReplicationDialog open={open} onClose={() => setOpen(false)} a={a} accounts={data?.accounts || []} onDone={() => { setOpen(false); reload(); }} />
    </CapabilityContainer>
  );
}

function NewReplicationDialog({ open, onClose, a, accounts, onDone }) {
  const notify = useNotify();
  const [dest, setDest] = useState("");
  const [sc, setSc] = useState("");
  const [dc, setDc] = useState("");
  const [prefix, setPrefix] = useState("");
  const [busy, setBusy] = useState(false);
  const valid = dest && sc && dc;
  const go = async () => {
    setBusy(true);
    try {
      const dst = accounts.find((x) => x.name === dest);
      const rule = { ruleId: `rule-${Date.now().toString(36)}`, sourceContainer: sc, destinationContainer: dc,
        filters: { prefixMatch: prefix.split(",").map((s) => s.trim()).filter(Boolean) } };
      await api.putReplicationPolicy(a, dst, [rule]);
      notify.success(`Blobs written to '${sc}' now replicate to '${dest}/${dc}'.`, "Replication rule created");
      setDest(""); setSc(""); setDc(""); setPrefix(""); onDone();
    } catch (e) { notify.error(e, "Failed to create the replication rule"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Create replication rules">
        <DialogBody>
          <DialogTitle action={<Button appearance="subtle" icon={<Dismiss20Regular />} aria-label="Close" onClick={onClose} />}>Create replication rules</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Destination storage account" required>
                <Select value={dest} onChange={(_, d) => setDest(d.value)} aria-label="Destination storage account">
                  <option value="">Select an account</option>
                  {accounts.filter((x) => x.name !== a.name).map((x) => <option key={x.id} value={x.name}>{x.name}</option>)}
                </Select>
              </Field>
              <Field label="Source container" required><Input value={sc} onChange={(_, d) => setSc(d.value)} aria-label="Source container" /></Field>
              <Field label="Destination container" required hint="The container must already exist in the destination account."><Input value={dc} onChange={(_, d) => setDc(d.value)} aria-label="Destination container" /></Field>
              <Field label="Prefix match (comma-separated)" hint="Leave blank to replicate every blob."><Input value={prefix} onChange={(_, d) => setPrefix(d.value)} aria-label="Prefix match" /></Field>
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!valid || busy} onClick={go}>Create</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

// ── Lifecycle management (Microsoft.Storage/storageAccounts/managementPolicies/default) —
// ENFORCED lazily by core/azure_blob_core.py on every blob list/get (see its module
// docstring): tierToCool/tierToArchive/delete really retier or expire a blob once it is
// older than the rule's threshold, evaluated on access rather than a daily background job.
function ruleSummary(rule) {
  const a = rule.definition?.actions?.baseBlob || {};
  const parts = [];
  if (a.tierToCool) parts.push(`Tier to cool after ${a.tierToCool.daysAfterModificationGreaterThan} days`);
  if (a.tierToArchive) parts.push(`Tier to archive after ${a.tierToArchive.daysAfterModificationGreaterThan} days`);
  if (a.delete) parts.push(`Delete after ${a.delete.daysAfterModificationGreaterThan} days`);
  return parts.join(", ") || "--";
}

function Lifecycle({ a }) {
  const [tab, setTab] = useState("list");
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.getManagementPolicy(a.resourceGroup, a.name), [a.id]);
  const rules = data || [];
  const [add, setAdd] = useState(false);
  const save = async (next) => {
    try { await api.putManagementPolicy(a.resourceGroup, a.name, next); reload(); }
    catch (e) { notify.error(e, "Saving the lifecycle policy failed"); }
  };
  return (
    <CapabilityContainer id="azure.storage.lifecycle" title={`${a.name} | Lifecycle management`}
      actions={<>
        <ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add a rule</ToolbarButton>
        <ToolbarButton onClick={() => save(rules.map((r) => ({ ...r, enabled: true })))} disabled={!rules.length}>Enable</ToolbarButton>
        <ToolbarButton onClick={() => save(rules.map((r) => ({ ...r, enabled: false })))} disabled={!rules.length}>Disable</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
      </>}>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Lifecycle management tabs">
        <Tab value="list">List View</Tab>
        <Tab value="code">Code View</Tab>
      </TabList>
      <ErrorBar error={error} />
      {tab === "list" && (
        <BrowseGrid
          resourceName="rule" rowKey={(r) => r.name}
          items={rules} loading={loading} onRefresh={reload}
          onDelete={async (sel) => { await save(rules.filter((r) => !sel.some((s) => s.name === r.name))); notify.success(`Deleted ${sel.length} rule${sel.length === 1 ? "" : "s"}.`, "Delete succeeded"); }}
          csvName="lifecycle-rules.csv"
          columns={[
            { key: "name", label: "Name" },
            { key: "status", label: "Status", value: (r) => (r.enabled ? "Enabled" : "Disabled") },
            { key: "blobtype", label: "Blob type", value: () => "Block blobs" },
            { key: "basebolbs", label: "Base blobs", value: (r) => ruleSummary(r) },
            { key: "snapshots", label: "Snapshots", value: () => "--" },
            { key: "versions", label: "Versions", value: () => "--" },
          ]}
        />
      )}
      {tab === "code" && (
        <pre className="vy-mono" style={{ maxHeight: 420, overflow: "auto", background: "var(--colorNeutralBackground3)", padding: 12, borderRadius: 4 }}>
          {JSON.stringify({ rules }, null, 2)}
        </pre>
      )}
      <AddRuleDialog open={add} onClose={() => setAdd(false)} onCreate={(rule) => save([...rules, rule])} />
    </CapabilityContainer>
  );
}

function AddRuleDialog({ open, onClose, onCreate }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [prefix, setPrefix] = useState("");
  const [cool, setCool] = useState("");
  const [archive, setArchive] = useState("");
  const [del, setDel] = useState("");
  const [busy, setBusy] = useState(false);
  const valid = /^[a-zA-Z0-9-_]{1,256}$/.test(name) && (cool || archive || del);
  const go = async () => {
    setBusy(true);
    try {
      const actions = {};
      if (cool) actions.tierToCool = { daysAfterModificationGreaterThan: Number(cool) };
      if (archive) actions.tierToArchive = { daysAfterModificationGreaterThan: Number(archive) };
      if (del) actions.delete = { daysAfterModificationGreaterThan: Number(del) };
      await onCreate({
        name, enabled: true, type: "Lifecycle",
        definition: {
          filters: { blobTypes: ["blockBlob"], prefixMatch: prefix.split(",").map((s) => s.trim()).filter(Boolean) },
          actions: { baseBlob: actions },
        },
      });
      notify.success(`Rule '${name}' was added.`, "Rule added");
      setName(""); setPrefix(""); setCool(""); setArchive(""); setDel(""); onClose();
    } catch (e) { notify.error(e, "Failed to add the rule"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Add a rule">
        <DialogBody>
          <DialogTitle action={<Button appearance="subtle" icon={<Dismiss20Regular />} aria-label="Close" onClick={onClose} />}>Add a rule</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Rule name" /></Field>
              <Field label="Blob prefix match (comma-separated)" hint="Leave blank to match every blob in the account.">
                <Input value={prefix} onChange={(_, d) => setPrefix(d.value)} aria-label="Blob prefix match" />
              </Field>
              <Field label="Move to cool storage after (days since modification)"><Input type="number" value={cool} onChange={(_, d) => setCool(d.value)} /></Field>
              <Field label="Move to archive storage after (days since modification)"><Input type="number" value={archive} onChange={(_, d) => setArchive(d.value)} /></Field>
              <Field label="Delete the blob after (days since modification)"><Input type="number" value={del} onChange={(_, d) => setDel(d.value)} /></Field>
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!valid || busy} onClick={go}>Add</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

const STORAGE_ACTIONS = [
  "Microsoft.Storage/storageAccounts/read", "Microsoft.Storage/storageAccounts/write", "Microsoft.Storage/storageAccounts/delete",
  "Microsoft.Storage/storageAccounts/listKeys/action", "Microsoft.Storage/storageAccounts/blobServices/containers/read",
  "Microsoft.Storage/storageAccounts/blobServices/containers/write", "Microsoft.Storage/storageAccounts/blobServices/containers/delete",
];
function Iam({ a }) { return <ResourceIam a={a} capId="azure.storage.iam" actions={STORAGE_ACTIONS} />; }

// ── Resource sharing (CORS) — tabs are real; every panel is an honest gap ──────────────
// ── Shared access signature — a real form that generates a cosmetic SAS token; Vyomi
// never verifies a SAS (or SharedKey) signature, same disclosed limitation as Access keys.
const SAS_SERVICES = ["Blob", "File", "Queue", "Table"];
const SAS_RESOURCE_TYPES = ["Service", "Container", "Object"];
const SAS_PERMISSIONS = ["Read", "Write", "Delete", "List", "Add", "Create", "Update", "Process", "Immutable storage", "Permanent delete"];

function CheckboxRow({ label, options, checked, onChange }) {
  return (
    <div className="vy-form-row"><span className="vy-label">{label}</span>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
        {options.map((o) => (
          <Checkbox key={o} label={o} checked={checked.includes(o)}
            onChange={(_, d) => onChange(d.checked ? [...checked, o] : checked.filter((x) => x !== o))} />
        ))}
      </div>
    </div>
  );
}

function Sas({ a }) {
  const [services, setServices] = useState(SAS_SERVICES);
  const [resourceTypes, setResourceTypes] = useState(["Service"]);
  const [permissions, setPermissions] = useState(["Read", "List"]);
  const [versionDelete, setVersionDelete] = useState([]);
  const [indexPerms, setIndexPerms] = useState([]);
  const [start, setStart] = useState(() => new Date().toISOString().slice(0, 16));
  const [expiry, setExpiry] = useState(() => new Date(Date.now() + 86400000 * 8).toISOString().slice(0, 16));
  const [ips, setIps] = useState("");
  const [protocol, setProtocol] = useState("https");
  const [routing, setRouting] = useState("basic");
  const [signingKey, setSigningKey] = useState("key1");
  const [sas, setSas] = useState(null);
  const generate = async () => {
    const keys = await api.listKeys(a.resourceGroup, a.name).catch(() => []);
    const key = keys.find((k) => k.keyName === signingKey)?.value || "key";
    const perm = permissions.map((p) => p[0].toLowerCase()).join("");
    const ss = services.map((s) => s[0].toLowerCase()).join("");
    const srt = resourceTypes.map((s) => s[0].toLowerCase()).join("");
    const sp = protocol === "https" ? "https" : "https,http";
    const sig = btoa(`${key}|${ss}|${srt}|${perm}|${start}|${expiry}`).replace(/[^a-zA-Z0-9]/g, "").slice(0, 44);
    const token = `sv=2021-12-02&ss=${ss}&srt=${srt}&sp=${perm}&se=${expiry}&st=${start}&spr=${sp}&sig=${encodeURIComponent(sig + "=")}`;
    const ep = api.blobEndpoint(a.name);
    setSas({
      connectionString: `DefaultEndpointsProtocol=${location.protocol.replace(":", "")};AccountName=${a.name};SharedAccessSignature=${token};BlobEndpoint=${ep};`,
      token,
      url: `${ep}?${token}`,
    });
  };
  return (
    <CapabilityContainer id="azure.storage.sas" title={`${a.name} | Shared access signature`}>
      <section className="vy-section" style={{ display: "flex", flexDirection: "column", gap: 10, maxWidth: 760 }}>
        <CheckboxRow label="Allowed services" options={SAS_SERVICES} checked={services} onChange={setServices} />
        <CheckboxRow label="Allowed resource types" options={SAS_RESOURCE_TYPES} checked={resourceTypes} onChange={setResourceTypes} />
        <CheckboxRow label="Allowed permissions" options={SAS_PERMISSIONS} checked={permissions} onChange={setPermissions} />
        <CheckboxRow label="Blob versioning permissions" options={["Enables deletion of versions"]} checked={versionDelete} onChange={setVersionDelete} />
        <CheckboxRow label="Allowed blob index permissions" options={["Read/Write", "Filter"]} checked={indexPerms} onChange={setIndexPerms} />
        <div className="vy-form-row"><span className="vy-label">Start and expiry date/time</span>
          <div style={{ display: "flex", gap: 8 }}>
            <Input type="datetime-local" value={start} onChange={(_, d) => setStart(d.value)} aria-label="Start date and time" />
            <Input type="datetime-local" value={expiry} onChange={(_, d) => setExpiry(d.value)} aria-label="End date and time" />
          </div>
        </div>
        <Field label="Allowed IP addresses"><Input placeholder="for example, 168.1.5.65 or 168.1.5.65-168.1.5.70" value={ips} onChange={(_, d) => setIps(d.value)} /></Field>
        <div className="vy-form-row"><span className="vy-label">Allowed protocols</span>
          <RadioGroup layout="horizontal" value={protocol} onChange={(_, d) => setProtocol(d.value)} aria-label="Allowed protocols">
            <Radio value="https" label="HTTPS only" /><Radio value="both" label="HTTPS and HTTP" />
          </RadioGroup>
        </div>
        <div className="vy-form-row"><span className="vy-label">Preferred routing tier</span>
          <RadioGroup layout="horizontal" value={routing} onChange={(_, d) => setRouting(d.value)} aria-label="Preferred routing tier">
            <Radio value="basic" label="Basic (default)" /><Radio value="microsoft" label="Microsoft network routing" /><Radio value="internet" label="Internet routing" />
          </RadioGroup>
        </div>
        <Field label="Signing key">
          <Select value={signingKey} onChange={(_, d) => setSigningKey(d.value)} aria-label="Signing key">
            <option value="key1">key1</option><option value="key2">key2</option>
          </Select>
        </Field>
        <div><Button appearance="primary" onClick={generate}>Generate SAS and connection string</Button></div>
        {sas && <>
          <Field label="Connection string"><Input readOnly value={sas.connectionString} /></Field>
          <Field label="SAS token"><Input readOnly value={sas.token} /></Field>
          <Field label="Blob service SAS URL"><Input readOnly value={sas.url} /></Field>
        </>}
      </section>
    </CapabilityContainer>
  );
}

function Cors({ a }) {
  const [tab, setTab] = useState("blob");
  const notify = useNotify();
  const svc = useAsync(() => api.getBlobServiceProperties(a.resourceGroup, a.name), [a.id]);
  const rules = svc.data?.cors?.corsRules || [];
  const [add, setAdd] = useState(false);
  const save = async (next) => {
    try {
      await api.putBlobServiceProperties(a.resourceGroup, a.name, { cors: { corsRules: next } });
      svc.reload();
    } catch (e) { notify.error(e, "Saving CORS rules failed"); }
  };
  return (
    <>
      <div className="vy-panel-title">{a.name} | Resource sharing (CORS)</div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Resource sharing (CORS) tabs">
        <Tab value="blob">Blob service</Tab>
        <Tab value="file">File service</Tab>
        <Tab value="queue">Queue service</Tab>
        <Tab value="table">Table service</Tab>
      </TabList>
      {tab === "blob" && (
        <CapabilityContainer id="azure.storage.cors" title="Blob service"
          actions={<>
            <ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add CORS rule</ToolbarButton>
            <ToolbarButton icon={<Delete20Regular />} disabled={!rules.length} onClick={() => save([])}>Delete all</ToolbarButton>
          </>}>
          <ErrorBar error={svc.error} />
          <table className="vy-grid">
            <thead><tr><th>Allowed origins</th><th>Allowed methods</th><th>Allowed headers</th><th>Exposed headers</th><th>Max age</th><th /></tr></thead>
            <tbody>
              {rules.length ? rules.map((r, i) => (
                <tr key={i}>
                  <td>{(r.allowedOrigins || []).join(", ")}</td>
                  <td>{(r.allowedMethods || []).join(", ")}</td>
                  <td>{(r.allowedHeaders || []).join(", ") || "--"}</td>
                  <td>{(r.exposedHeaders || []).join(", ") || "--"}</td>
                  <td>{r.maxAgeInSeconds ?? 0}</td>
                  <td><Button appearance="subtle" icon={<Delete20Regular />} aria-label="Remove rule" onClick={() => save(rules.filter((_, j) => j !== i))} /></td>
                </tr>
              )) : <tr><td colSpan={6} className="vy-muted">No CORS rules have been added.</td></tr>}
            </tbody>
          </table>
        </CapabilityContainer>
      )}
      {tab === "file" && <CapabilityContainer id="azure.storage.fileservice" title="File service"><FileServiceSettings a={a} /><ServiceCors a={a} kind="fileServices" title="File service CORS" /></CapabilityContainer>}
      {tab === "queue" && <CapabilityContainer id="azure.storage.queueservice" title="Queue service"><ServiceCors a={a} kind="queueServices" title="Queue service CORS" /><ServiceMonitoring a={a} kind="queue" /></CapabilityContainer>}
      {tab === "table" && <CapabilityContainer id="azure.storage.tableservice" title="Table service"><ServiceCors a={a} kind="tableServices" title="Table service CORS" /><ServiceMonitoring a={a} kind="table" /></CapabilityContainer>}
      <AddCorsRuleDialog open={add} onClose={() => setAdd(false)} onCreate={(rule) => save([...rules, rule])} />
    </>
  );
}

function AddCorsRuleDialog({ open, onClose, onCreate }) {
  const notify = useNotify();
  const [origins, setOrigins] = useState("*");
  const [methods, setMethods] = useState(["GET"]);
  const [headers, setHeaders] = useState("*");
  const [exposed, setExposed] = useState("*");
  const [maxAge, setMaxAge] = useState("200");
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try {
      await onCreate({
        allowedOrigins: origins.split(",").map((s) => s.trim()).filter(Boolean),
        allowedMethods: methods,
        allowedHeaders: headers.split(",").map((s) => s.trim()).filter(Boolean),
        exposedHeaders: exposed.split(",").map((s) => s.trim()).filter(Boolean),
        maxAgeInSeconds: Number(maxAge) || 0,
      });
      notify.success("CORS rule added.", "Rule added");
      onClose();
    } catch (e) { notify.error(e, "Failed to add the CORS rule"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Add CORS rule">
        <DialogBody>
          <DialogTitle action={<Button appearance="subtle" icon={<Dismiss20Regular />} aria-label="Close" onClick={onClose} />}>Add CORS rule</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Allowed origins" hint="Comma-separated, or * for any origin."><Input value={origins} onChange={(_, d) => setOrigins(d.value)} /></Field>
              <CheckboxRow label="Allowed methods" options={["GET", "HEAD", "POST", "PUT", "DELETE", "OPTIONS", "MERGE"]} checked={methods} onChange={setMethods} />
              <Field label="Allowed headers" hint="Comma-separated, or * for any header."><Input value={headers} onChange={(_, d) => setHeaders(d.value)} /></Field>
              <Field label="Exposed headers"><Input value={exposed} onChange={(_, d) => setExposed(d.value)} /></Field>
              <Field label="Max age (seconds)"><Input type="number" value={maxAge} onChange={(_, d) => setMaxAge(d.value)} /></Field>
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={busy || !methods.length} onClick={go}>Save</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

function StaticWebsite({ a }) {
  const notify = useNotify();
  const svc = useAsync(() => api.getBlobServiceProperties(a.resourceGroup, a.name), [a.id]);
  const init = () => ({
    enabled: !!svc.data?.staticWebsite?.enabled,
    indexDocument: svc.data?.staticWebsite?.indexDocument || "index.html",
    errorDocument: svc.data?.staticWebsite?.errorDocument404Path || "",
  });
  const [f, setF] = useState(init);
  const [busy, setBusy] = useState(false);
  useEffect(() => setF(init()), [svc.data]);
  const dirty = JSON.stringify(f) !== JSON.stringify(init());
  const save = async () => {
    setBusy(true);
    try {
      await api.putBlobServiceProperties(a.resourceGroup, a.name, {
        staticWebsite: { enabled: f.enabled, indexDocument: f.indexDocument, errorDocument404Path: f.errorDocument },
      });
      notify.success(`Static website settings on '${a.name}' were saved.`, "Saved");
      svc.reload();
    } catch (e) { notify.error(e, "Saving static website settings failed"); }
    finally { setBusy(false); }
  };
  return (
    <CapabilityContainer id="azure.storage.staticwebsite" title={`${a.name} | Static website`}
      actions={<>
        <ToolbarButton icon={<Save20Regular />} disabled={!dirty || busy} onClick={save}>Save</ToolbarButton>
        <ToolbarButton icon={<Dismiss20Regular />} disabled={!dirty} onClick={() => setF(init())}>Discard</ToolbarButton>
      </>}>
      <ErrorBar error={svc.error} />
      <section className="vy-section" style={{ maxWidth: 600, display: "flex", flexDirection: "column", gap: 10 }}>
        <div className="vy-form-row"><span className="vy-label">Static website</span>
          <RadioGroup layout="horizontal" value={f.enabled ? "on" : "off"} onChange={(_, d) => setF((x) => ({ ...x, enabled: d.value === "on" }))} aria-label="Static website">
            <Radio value="off" label="Disabled" /><Radio value="on" label="Enabled" />
          </RadioGroup>
        </div>
        <Field label="Index document name"><Input value={f.indexDocument} onChange={(_, d) => setF((x) => ({ ...x, indexDocument: d.value }))} /></Field>
        <Field label="Error document path"><Input value={f.errorDocument} onChange={(_, d) => setF((x) => ({ ...x, errorDocument: d.value }))} /></Field>
        <Field label="Primary endpoint" hint={f.enabled ? "Served from the $web container (upload index.html/404.html there)." : "Enable and Save to serve $web content here."}>
          <div style={{ display: "flex", gap: 4 }}>
            <Input readOnly value={api.websiteEndpoint(a.name)} style={{ flex: 1 }} />
            <Button as="a" href={api.websiteEndpoint(a.name)} target="_blank" rel="noreferrer" disabled={!svc.data?.staticWebsite?.enabled}>Browse</Button>
          </div>
        </Field>
      </section>
    </CapabilityContainer>
  );
}

// ── Export template (client-side ARM/Bicep/Terraform generated from this resource) ────

// ── Data protection (Microsoft.Storage/storageAccounts/blobServices/default) ───────────
function DeletedContainers({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listDeletedContainers(a.name), [a.name]);
  return (
    <BrowseGrid
      resourceName="deleted container" rowKey={(r) => r.name} items={data || []} loading={loading} error={error} onRefresh={reload}
      csvName="deleted-containers.csv"
      columns={[{ key: "name", label: "Name" }, { key: "modified", label: "Last modified (before delete)", value: (r) => fmtDate(r.modified) },
        { key: "undelete", label: "", render: (r) => <Button size="small" onClick={async () => { await api.undeleteContainer(a.name, r.name); notify.success(`Container '${r.name}' was restored.`, "Undelete succeeded"); reload(); }}>Undelete</Button> }]}
    />
  );
}

function ChangeFeedView({ a }) {
  const { data, loading, error } = useAsync(() => api.getChangeFeed(a.name), [a.name]);
  const rows = data || [];
  return (
    <>
      <ErrorBar error={error} />
      {loading ? <Loading /> : rows.length ? (
        <table className="vy-grid">
          <thead><tr><th>Time</th><th>Event</th><th>Container</th><th>Blob</th></tr></thead>
          <tbody>{rows.slice().reverse().map((e, i) => <tr key={i}><td>{fmtDate(e.time)}</td><td>{e.event}</td><td>{e.container}</td><td>{e.blob || "--"}</td></tr>)}</tbody>
        </table>
      ) : <p className="vy-muted" style={{ fontSize: 13 }}>No change feed events yet — upload or delete a blob.</p>}
    </>
  );
}

function DataProtection({ a }) {
  const notify = useNotify();
  const svc = useAsync(() => api.getBlobServiceProperties(a.resourceGroup, a.name), [a.id]);
  const init = () => {
    const p = svc.data || {};
    return {
      backup: false,
      pitr: !!p.restorePolicy?.enabled,
      softDeleteBlobs: !!p.deleteRetentionPolicy?.enabled, softDeleteBlobDays: p.deleteRetentionPolicy?.days ?? 7,
      softDeleteContainers: !!p.containerDeleteRetentionPolicy?.enabled, softDeleteContainerDays: p.containerDeleteRetentionPolicy?.days ?? 7,
      permanentDelete: false, softDeleteShares: false, softDeleteShareDays: 7,
      versioning: !!p.isVersioningEnabled, changeFeed: !!p.changeFeed?.enabled, immutability: !!a.properties?.immutableStorageWithVersioning?.enabled,
    };
  };
  const [f, setF] = useState(init);
  const [busy, setBusy] = useState(false);
  useEffect(() => setF(init()), [svc.data]);
  const dirty = JSON.stringify(f) !== JSON.stringify(init());
  const cb = (k, label, hint) => (
    <Checkbox key={k} checked={f[k]} onChange={(_, d) => setF((x) => ({ ...x, [k]: !!d.checked }))} label={hint ? <span>{label} <span className="vy-muted">({hint})</span></span> : label} />
  );
  const save = async () => {
    setBusy(true);
    try {
      await api.putBlobServiceProperties(a.resourceGroup, a.name, {
        deleteRetentionPolicy: { enabled: f.softDeleteBlobs, days: Number(f.softDeleteBlobDays) || 7 },
        containerDeleteRetentionPolicy: { enabled: f.softDeleteContainers, days: Number(f.softDeleteContainerDays) || 7 },
        restorePolicy: { enabled: f.pitr },
        isVersioningEnabled: f.versioning,
        changeFeed: { enabled: f.changeFeed },
      });
      if (f.immutability !== !!a.properties?.immutableStorageWithVersioning?.enabled)
        await api.updateStorageAccount(a.resourceGroup, a.name, { properties: { immutableStorageWithVersioning: { enabled: f.immutability } } });
      notify.success(`Data protection settings on '${a.name}' were saved.`, "Saved");
      svc.reload();
    } catch (e) { notify.error(e, "Saving data protection settings failed"); }
    finally { setBusy(false); }
  };
  return (
    <CapabilityContainer id="azure.storage.dataprotection" title={`${a.name} | Data protection`}
      actions={<>
        <ToolbarButton icon={<Save20Regular />} disabled={!dirty || busy} onClick={save}>Save</ToolbarButton>
        <ToolbarButton icon={<Dismiss20Regular />} disabled={!dirty} onClick={() => setF(init())}>Discard</ToolbarButton>
      </>}>
      <ErrorBar error={svc.error} />
      <div style={{ display: "flex", flexDirection: "column", gap: 16, marginTop: 8 }}>
        <section className="vy-section"><h3>Recovery</h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {cb("backup", "Enable operational backup with Azure Backup", "not enforced — no backup engine")}
            {cb("pitr", "Enable point-in-time restore for containers", "not enforced")}
            {cb("softDeleteBlobs", "Enable soft delete for blobs", "ENFORCED — deleted blobs are recoverable, see Containers")}
            <Field label="Keep deleted blobs for (in days)" style={{ maxWidth: 220, marginLeft: 24 }}>
              <Input type="number" value={String(f.softDeleteBlobDays)} onChange={(_, d) => setF((x) => ({ ...x, softDeleteBlobDays: d.value }))} /></Field>
            {cb("softDeleteContainers", "Enable soft delete for containers", "ENFORCED — deleted containers are recoverable below")}
            <Field label="Keep deleted containers for (in days)" style={{ maxWidth: 220, marginLeft: 24 }}>
              <Input type="number" value={String(f.softDeleteContainerDays)} onChange={(_, d) => setF((x) => ({ ...x, softDeleteContainerDays: d.value }))} /></Field>
            {cb("permanentDelete", "Enable permanent delete for soft deleted items", "not enforced")}
            {cb("softDeleteShares", "Enable soft delete for file shares", "Azure Files has no core in this repo")}
            <Field label="Keep deleted file shares for (in days)" style={{ maxWidth: 220, marginLeft: 24 }}>
              <Input type="number" value={String(f.softDeleteShareDays)} onChange={(_, d) => setF((x) => ({ ...x, softDeleteShareDays: d.value }))} /></Field>
          </div>
        </section>
        <section className="vy-section"><h3>Tracking</h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {cb("versioning", "Enable versioning for blobs", "ENFORCED — overwriting a blob keeps the prior body as a real version")}
            {cb("changeFeed", "Enable blob change feed", "ENFORCED — real BlobCreated/BlobDeleted events, see below")}
          </div>
        </section>
        <section className="vy-section"><h3>Access control</h3>
          {cb("immutability", "Enable version-level immutability support", "stored on the account; blob immutability policies are not enforced")}
        </section>
      </div>
      {f.softDeleteContainers && <section className="vy-section" style={{ marginTop: 16 }}><h3>Deleted containers</h3>
        <DeletedContainers a={a} />
      </section>}
      {f.changeFeed && <section className="vy-section" style={{ marginTop: 16 }}><h3>Change feed events</h3>
        <ChangeFeedView a={a} />
      </section>}
    </CapabilityContainer>
  );
}

// ── Locks (Microsoft.Authorization/locks, scoped to this storage account) ─────────────
function Locks({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listLocks(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const [add, setAdd] = useState(false);
  const [gap, setGap] = useState(null); // "Subscription" | "Resource group" | "Feedback"
  const rows = data || [];
  return (
    <>
      <div className="vy-panel-title">{a.name} | Locks</div>
      <BrowseGrid
        resourceName="lock" rowKey={(r) => r.name} filterPlaceholder="Search to filter items..."
        items={rows} loading={loading} error={error} onRefresh={reload}
        extraCommands={<>
          <ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add</ToolbarButton>
          <ToolbarButton onClick={() => setGap("Subscription")}>Subscription</ToolbarButton>
          <ToolbarButton onClick={() => setGap("Resource group")}>Resource group</ToolbarButton>
          <ToolbarButton onClick={() => setGap("Feedback")}>Feedback</ToolbarButton>
        </>}
        onDelete={async (sel) => {
          for (const r of sel) await api.deleteLock(a.resourceGroup, a.name, r.name);
          notify.success(`Deleted ${sel.length} lock${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
          reload();
        }}
        csvName="locks.csv"
        columns={[
          { key: "name", label: "Lock name" },
          { key: "type", label: "Lock type", value: (r) => (r.properties?.level === "ReadOnly" ? "Read-only" : "Delete") },
          { key: "scope", label: "Scope", value: () => a.name },
          { key: "notes", label: "Notes", value: (r) => r.properties?.notes || "--" },
        ]}
      />
      <AddLockDialog open={add} onClose={() => setAdd(false)}
        onCreate={async (name, level, notes) => { await api.putLock(a.resourceGroup, a.name, name, { properties: { level, notes } }); reload(); }} />
      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label={gap || "Not simulated"}>
          <DialogBody>
            <DialogTitle>{gap}</DialogTitle>
            <DialogContent>
              <NotSimulated feature={gap === "Feedback" ? "Sending product feedback" : `Locks scoped to the ${(gap || "").toLowerCase()}`} />
            </DialogContent>
            <DialogActions><Button onClick={() => setGap(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

function AddLockDialog({ open, onClose, onCreate }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [type, setType] = useState("Delete");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const valid = /^[a-zA-Z0-9._-]{1,90}$/.test(name);
  const go = async () => {
    setBusy(true);
    try {
      await onCreate(name, type === "Read-only" ? "ReadOnly" : "CanNotDelete", notes);
      notify.success(`Lock '${name}' was added.`, "Lock added");
      setName(""); setNotes(""); setType("Delete"); onClose();
    } catch (e) { notify.error(e, "Failed to add lock"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Add lock">
        <DialogBody>
          <DialogTitle action={<Button appearance="subtle" icon={<Dismiss20Regular />} aria-label="Close" onClick={onClose} />}>Add lock</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Lock name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Lock name" /></Field>
              <Field label="Lock type" required>
                <Select value={type} onChange={(_, d) => setType(d.value)} aria-label="Lock type">
                  <option>Read-only</option><option>Delete</option>
                </Select>
              </Field>
              <Field label="Notes"><Textarea value={notes} onChange={(_, d) => setNotes(d.value)} aria-label="Notes" /></Field>
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

// ── Activity log (Microsoft.Insights/eventtypes/management/values, scoped to this account) ──

// ── Queues (Azure Storage Queue REST, a global data plane — see api.js) ────────────────
function Queues({ self }) {
  const notify = useNotify();
  const account = self.split("/").pop();
  const { data, loading, error, reload } = useAsync(() => api.listQueues(account), [self]);
  const [create, setCreate] = useState(false);
  const [gap, setGap] = useState(false);
  return (
    <CapabilityContainer id="azure.storage.queues" title={`${account} | Queues`}>
      <BrowseGrid
        resourceName="queue" rowKey={(r) => r.name} filterPlaceholder="Search queues by prefix"
        items={data || []} loading={loading} error={error} onRefresh={reload}
        extraCommands={<>
          <ToolbarButton icon={<Add20Regular />} onClick={() => setCreate(true)}>Queue</ToolbarButton>
          <ToolbarButton onClick={() => setGap(true)}>Give feedback</ToolbarButton>
        </>}
        onDelete={async (rows) => {
          for (const r of rows) await api.deleteQueue(r.name);
          notify.success(`Deleted ${rows.length} queue${rows.length === 1 ? "" : "s"}.`, "Delete succeeded");
          reload();
        }}
        csvName="queues.csv"
        columns={[
          { key: "name", label: "Queue", render: (r) => <Link href={`${self}/queues?queue=${encodeURIComponent(r.name)}`}>{r.name}</Link> },
          { key: "url", label: "Url", value: (r) => api.queueUrl(r.name) },
        ]}
      />
      <NewQueueDialog open={create} onClose={() => setCreate(false)} onCreated={reload} />
      <Dialog open={gap} onOpenChange={(_, d) => setGap(d.open)}>
        <DialogSurface aria-label="Give feedback">
          <DialogBody>
            <DialogTitle>Give feedback</DialogTitle>
            <DialogContent><NotSimulated feature="Sending product feedback" /></DialogContent>
            <DialogActions><Button onClick={() => setGap(false)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </CapabilityContainer>
  );
}

function NewQueueDialog({ open, onClose, onCreated }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const valid = /^(?!-)(?!.*--)[a-z0-9-]{3,63}(?<!-)$/.test(name);
  const go = async () => {
    setBusy(true);
    try {
      await api.createQueue(name);
      notify.success(`Successfully created queue '${name}'.`, "Queue created");
      setName(""); onClose(); onCreated();
    } catch (e) { notify.error(e, "Failed to create queue"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Add queue">
        <DialogBody>
          <DialogTitle action={<Button appearance="subtle" icon={<Dismiss20Regular />} aria-label="Close" onClick={onClose} />}>Add queue</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Queue name" required validationMessage={name && !valid ? "Queue names must be 3-63 characters: lowercase letters, numbers and single hyphens." : undefined}>
                <Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Queue name" />
              </Field>
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

function QueueDetail({ name, self }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.peekMessages(name), [name]);
  const meta = useAsync(() => api.getQueueMetadata(name), [name]);
  const [send, setSend] = useState(false);
  return (
    <>
      <div style={{ fontSize: 13, marginTop: 12 }}><Link href={`${self}/queues`}>Queues</Link> <span className="vy-muted">&gt;</span> {name}</div>
      <div className="vy-panel-title">{name} <span className="vy-muted" style={{ fontWeight: 400, fontSize: 13 }}>Queue</span></div>
      <KV label="Approximate message count" value={meta.data?.approximateMessageCount ?? "--"} />
      <BrowseGrid
        resourceName="message" rowKey={(r) => r.id}
        items={data || []} loading={loading} error={error}
        onRefresh={() => { reload(); meta.reload(); }}
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setSend(true)}>Add message</ToolbarButton>}
        onDelete={async (rows) => {
          const received = await api.receiveMessages(name, 32);
          for (const r of rows) {
            const m = received.find((x) => x.id === r.id);
            if (m) await api.deleteMessage(name, m.id, m.popReceipt);
          }
          notify.success(`Deleted ${rows.length} message${rows.length === 1 ? "" : "s"}.`, "Delete succeeded");
          reload(); meta.reload();
        }}
        csvName={`${name}-messages.csv`}
        columns={[
          { key: "id", label: "Id" },
          { key: "text", label: "Message text" },
          { key: "insertionTime", label: "Insertion time", value: (r) => fmtDate(r.insertionTime) },
          { key: "expirationTime", label: "Expiration time", value: (r) => fmtDate(r.expirationTime) },
          { key: "dequeueCount", label: "Dequeue count" },
        ]}
      />
      <SendMessageDialog open={send} onClose={() => setSend(false)}
        onSend={async (text) => { await api.sendMessage(name, text); reload(); meta.reload(); }} />
    </>
  );
}

function SendMessageDialog({ open, onClose, onSend }) {
  const notify = useNotify();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try {
      await onSend(text);
      notify.success("Message added to the queue.", "Message added");
      setText(""); onClose();
    } catch (e) { notify.error(e, "Failed to add message"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Add message">
        <DialogBody>
          <DialogTitle action={<Button appearance="subtle" icon={<Dismiss20Regular />} aria-label="Close" onClick={onClose} />}>Add message</DialogTitle>
          <DialogContent>
            <Field label="Message"><Textarea value={text} onChange={(_, d) => setText(d.value)} aria-label="Message" /></Field>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!text || busy} onClick={go}>OK</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

// ── Tables (Azure Table REST / OData, a global data plane — see api.js) ────────────────
function Tables({ self }) {
  const notify = useNotify();
  const account = self.split("/").pop();
  const { data, loading, error, reload } = useAsync(api.listTables, []);
  const [create, setCreate] = useState(false);
  const [gap, setGap] = useState(false);
  return (
    <CapabilityContainer id="azure.storage.tables" title={`${account} | Tables`}>
      <BrowseGrid
        resourceName="table" rowKey={(r) => r.TableName} filterPlaceholder="Search tables by prefix"
        items={data || []} loading={loading} error={error} onRefresh={reload}
        extraCommands={<>
          <ToolbarButton icon={<Add20Regular />} onClick={() => setCreate(true)}>Table</ToolbarButton>
          <ToolbarButton onClick={() => setGap(true)}>Give feedback</ToolbarButton>
        </>}
        onDelete={async (rows) => {
          for (const r of rows) await api.deleteTable(r.TableName);
          notify.success(`Deleted ${rows.length} table${rows.length === 1 ? "" : "s"}.`, "Delete succeeded");
          reload();
        }}
        csvName="tables.csv"
        columns={[
          { key: "name", label: "Table", render: (r) => <Link href={`${self}/tables?table=${encodeURIComponent(r.TableName)}`}>{r.TableName}</Link> },
          { key: "url", label: "Url", value: (r) => api.tableUrl(r.TableName) },
        ]}
      />
      <NewTableDialog open={create} onClose={() => setCreate(false)} onCreated={reload} />
      <Dialog open={gap} onOpenChange={(_, d) => setGap(d.open)}>
        <DialogSurface aria-label="Give feedback">
          <DialogBody>
            <DialogTitle>Give feedback</DialogTitle>
            <DialogContent><NotSimulated feature="Sending product feedback" /></DialogContent>
            <DialogActions><Button onClick={() => setGap(false)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </CapabilityContainer>
  );
}

function NewTableDialog({ open, onClose, onCreated }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const valid = /^[A-Za-z][A-Za-z0-9]{2,62}$/.test(name);
  const go = async () => {
    setBusy(true);
    try {
      await api.createTable(name);
      notify.success(`Successfully created table '${name}'.`, "Table created");
      setName(""); onClose(); onCreated();
    } catch (e) { notify.error(e, "Failed to create table"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Add table">
        <DialogBody>
          <DialogTitle action={<Button appearance="subtle" icon={<Dismiss20Regular />} aria-label="Close" onClick={onClose} />}>Add table</DialogTitle>
          <DialogContent>
            <Field label="Table name" required validationMessage={name && !valid ? "Table names must be 3-63 alphanumeric characters, starting with a letter." : undefined}>
              <Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Table name" />
            </Field>
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

function TableDetail({ name, self }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listEntities(name), [name]);
  const [add, setAdd] = useState(false);
  // Columns are fixed (not derived from the loaded rows): BrowseGrid picks its initial
  // shown-column set from whatever `columns` it saw on its FIRST render, so a column list
  // that grows once `data` arrives would silently stay hidden.
  const otherProps = (r) => JSON.stringify(Object.fromEntries(Object.entries(r)
    .filter(([k]) => !["PartitionKey", "RowKey", "Timestamp", "_key"].includes(k) && !k.startsWith("odata."))));
  const rows = (data || []).map((e) => ({ ...e, _key: `${e.PartitionKey}/${e.RowKey}` }));
  return (
    <>
      <div style={{ fontSize: 13, marginTop: 12 }}><Link href={`${self}/tables`}>Tables</Link> <span className="vy-muted">&gt;</span> {name}</div>
      <div className="vy-panel-title">{name} <span className="vy-muted" style={{ fontWeight: 400, fontSize: 13 }}>Table</span></div>
      <BrowseGrid
        resourceName="entity" rowKey={(r) => r._key}
        items={rows} loading={loading} error={error} onRefresh={reload}
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add entity</ToolbarButton>}
        onDelete={async (sel) => {
          for (const r of sel) await api.deleteEntity(name, r.PartitionKey, r.RowKey);
          notify.success(`Deleted ${sel.length} entit${sel.length === 1 ? "y" : "ies"}.`, "Delete succeeded");
          reload();
        }}
        csvName={`${name}-entities.csv`}
        columns={[
          { key: "pk", label: "PartitionKey", value: (r) => r.PartitionKey },
          { key: "rk", label: "RowKey", value: (r) => r.RowKey },
          { key: "props", label: "Properties", value: otherProps },
        ]}
      />
      <AddEntityDialog open={add} onClose={() => setAdd(false)}
        onCreate={async (entity) => { await api.insertEntity(name, entity); reload(); }} />
    </>
  );
}

function AddEntityDialog({ open, onClose, onCreate }) {
  const notify = useNotify();
  const [pk, setPk] = useState("");
  const [rk, setRk] = useState("");
  const [props, setProps] = useState("{}");
  const [busy, setBusy] = useState(false);
  const parsed = (() => { try { return JSON.parse(props || "{}"); } catch { return null; } })();
  const valid = pk && rk && parsed !== null;
  const go = async () => {
    setBusy(true);
    try {
      await onCreate({ PartitionKey: pk, RowKey: rk, ...parsed });
      notify.success("Entity added.", "Entity added");
      setPk(""); setRk(""); setProps("{}"); onClose();
    } catch (e) { notify.error(e, "Failed to add entity"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Add entity">
        <DialogBody>
          <DialogTitle action={<Button appearance="subtle" icon={<Dismiss20Regular />} aria-label="Close" onClick={onClose} />}>Add entity</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="PartitionKey" required><Input value={pk} onChange={(_, d) => setPk(d.value)} /></Field>
              <Field label="RowKey" required><Input value={rk} onChange={(_, d) => setRk(d.value)} /></Field>
              <Field label="Other properties (JSON)" validationMessage={props && parsed === null ? "Invalid JSON" : undefined}>
                <Textarea value={props} onChange={(_, d) => setProps(d.value)} />
              </Field>
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

// ── Storage browser (a unified view over Containers + Blobs this Vyomi already models) ──
function StorageBrowser({ account, self }) {
  const { data, loading, error, reload } = useAsync(() => api.listContainers(account), [account]);
  const [open, setOpen] = useState(null);
  const blobs = useAsync(() => (open ? api.listBlobs(account, open) : Promise.resolve([])), [account, open]);
  return (
    <CapabilityContainer id="azure.storage.storagebrowser" title={`${account} | Storage browser`}>
      <div style={{ display: "flex", gap: 16, marginTop: 8 }}>
        <section className="vy-section" style={{ minWidth: 220 }}>
          <h3>Containers</h3>
          <ErrorBar error={error} />
          {loading ? <Loading /> : (
            <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
              {(data || []).map((c) => (
                <li key={c.name}>
                  <Link as="button" onClick={() => setOpen(c.name)} style={{ fontWeight: open === c.name ? 600 : 400 }}>{c.name}</Link>
                </li>
              ))}
              {!(data || []).length && <li className="vy-muted">No containers yet.</li>}
            </ul>
          )}
          <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
        </section>
        <section className="vy-section" style={{ flex: 1 }}>
          <h3>{open ? `Blobs in ${open}` : "Select a container"}</h3>
          <ErrorBar error={blobs.error} />
          {open && (blobs.loading ? <Loading /> : (
            <table className="vy-grid">
              <thead><tr><th>Name</th><th>Access tier</th><th>Size</th><th>Modified</th></tr></thead>
              <tbody>
                {(blobs.data || []).length ? blobs.data.map((b) => (
                  <tr key={b.name}><td>{b.name}</td><td>{b.tier}</td><td>{fmtBytes(b.size)}</td><td>{fmtDate(b.modified)}</td></tr>
                )) : <tr><td colSpan={4} className="vy-muted">This container has no blobs.</td></tr>}
              </tbody>
            </table>
          ))}
        </section>
      </div>
      <p style={{ fontSize: 13, marginTop: 12 }}>For uploads, access tiers and SAS, use <Link href={`${self}/containers`}>Containers</Link>.</p>
    </CapabilityContainer>
  );
}

// ── Blob inventory — on-demand (not daily-scheduled) real CSV report blob ─────────────
function Inventory({ a }) {
  const notify = useNotify();
  const [dest, setDest] = useState("inventory-reports");
  const [busy, setBusy] = useState(false);
  const { data, loading, error, reload } = useAsync(() => api.listBlobs(a.name, dest).catch(() => []), [a.name, dest]);
  const run = async () => {
    setBusy(true);
    try {
      const r = await api.runInventoryNow(a.name, dest);
      notify.success(`Wrote '${r.blobName}' with ${r.rowCount} row(s) to '${dest}'.`, "Inventory run completed");
      reload();
    } catch (e) { notify.error(e, "Inventory run failed"); }
    finally { setBusy(false); }
  };
  return (
    <CapabilityContainer id="azure.storage.inventory" title={`${a.name} | Blob inventory`}
      actions={<ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>}>
      <p style={{ fontSize: 13 }}>Vyomi has no job scheduler, so "Run inventory now" below runs the real listing on demand instead of the real feature's daily background job — the report blob it writes is real.</p>
      <Field label="Destination container" style={{ maxWidth: 320 }}><Input value={dest} onChange={(_, d) => setDest(d.value)} /></Field>
      <div style={{ marginTop: 8 }}><Button appearance="primary" disabled={busy} onClick={run}>Run inventory now</Button></div>
      <section className="vy-section" style={{ marginTop: 16 }}><h3>Inventory reports</h3>
        <ErrorBar error={error} />
        {loading ? <Loading /> : (data || []).length ? (
          <table className="vy-grid">
            <thead><tr><th>Report</th><th>Size</th><th>Generated</th><th /></tr></thead>
            <tbody>{data.map((b) => <tr key={b.name}><td>{b.name}</td><td>{fmtBytes(b.size)}</td><td>{fmtDate(b.modified)}</td>
              <td><Button size="small" onClick={() => api.downloadBlob(a.name, dest, b.name)}>Download</Button></td></tr>)}</tbody>
          </table>
        ) : <p className="vy-muted">No inventory reports yet — click "Run inventory now".</p>}
      </section>
    </CapabilityContainer>
  );
}

// ── Data Lake Gen2 upgrade — a real, one-way ARM PATCH (core/azure_arm_core.py rejects an
// ineligible kind or a downgrade attempt — see _storage_hns_block) ────────────────────
function DataLakeGen2Upgrade({ a, reload }) {
  const notify = useNotify();
  const [busy, setBusy] = useState(false);
  const enabled = !!a.properties?.isHnsEnabled;
  const eligible = ["StorageV2", "BlockBlobStorage"].includes(a.kind);
  const go = async () => {
    setBusy(true);
    try {
      await api.upgradeToDataLakeGen2(a.resourceGroup, a.name);
      notify.success(`'${a.name}' was upgraded to support a hierarchical namespace.`, "Upgrade succeeded");
      reload();
    } catch (e) { notify.error(e, "Upgrade failed"); }
    finally { setBusy(false); }
  };
  return (
    <CapabilityContainer id="azure.storage.datalakegen2upgrade" title={`${a.name} | Data Lake Gen2 upgrade`}>
      <KV label="Hierarchical namespace" value={enabled ? "Enabled" : "Disabled"} />
      <KV label="Account kind" value={a.kind} />
      {enabled ? <InfoBar>This account already has a hierarchical namespace — the upgrade is one-way and already applied.</InfoBar>
        : eligible ? <>
          <p style={{ fontSize: 13 }}>Upgrading enables a real hierarchical namespace flag on this account. This is irreversible — core/azure_arm_core.py rejects turning it back off.</p>
          <Button appearance="primary" disabled={busy} onClick={go}>Upgrade</Button>
        </> : <InfoBar intent="warning">Hierarchical namespace requires a general-purpose v2 or premium block blob account — change the account kind first.</InfoBar>}
      <NotSimulatedContainer title="Metadata rewrite" feature="The full-container metadata rewrite a real upgrade job performs" note="Vyomi's blob core has no directory/path metadata to rewrite — containers stay flat either way." />
    </CapabilityContainer>
  );
}

// ── Metrics / Insights (Microsoft.Insights/metrics — real numbers, see api.getMetrics) ──
const METRIC_LABEL = { UsedCapacity: "Used capacity", BlobCount: "Blob count", ContainerCount: "Container count", Transactions: "Transactions", Ingress: "Ingress", Egress: "Egress" };
function fmtMetric(name, value) {
  return name === "UsedCapacity" || name === "Ingress" || name === "Egress" ? fmtBytes(value) : String(value);
}

function Metrics({ a }) {
  const { data, loading, error, reload } = useAsync(() => api.getMetrics(a.resourceGroup, a.name), [a.id]);
  return (
    <CapabilityContainer id="azure.storage.metrics" title={`${a.name} | Metrics`}
      actions={<ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>}>
      <p style={{ fontSize: 13 }}>Real numbers derived from this account's own activity (core/azure_blob_core.py) over the native `Microsoft.Insights/metrics` wire — a single current value, not a persisted historical time series.</p>
      <ErrorBar error={error} />
      {loading ? <Loading /> : (
        <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginTop: 8 }}>
          {api.STORAGE_METRICS.map((m) => (
            <section className="vy-section" key={m} style={{ minWidth: 160 }}>
              <h3>{METRIC_LABEL[m]}</h3>
              <div style={{ fontSize: 22 }}>{fmtMetric(m, data?.[m]?.value ?? 0)}</div>
            </section>
          ))}
        </div>
      )}
      <NotSimulatedContainer title="Availability / latency" feature="Availability and SuccessE2ELatency metrics" note="Vyomi always serves successfully with no transient failures to measure." />
    </CapabilityContainer>
  );
}

function Insights({ a }) {
  const { data, loading, error } = useAsync(() => api.getMetrics(a.resourceGroup, a.name), [a.id]);
  return (
    <CapabilityContainer id="azure.storage.insights" title={`${a.name} | Insights`}>
      <p style={{ fontSize: 13 }}>The same real metrics as <Link href="#">Metrics</Link>, laid out as an at-a-glance dashboard.</p>
      <ErrorBar error={error} />
      {loading ? <Loading /> : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 8, maxWidth: 480 }}>
          {api.STORAGE_METRICS.map((m) => (
            <div key={m} className="vy-kv"><span>{METRIC_LABEL[m]}</span><span>{fmtMetric(m, data?.[m]?.value ?? 0)}</span></div>
          ))}
        </div>
      )}
    </CapabilityContainer>
  );
}

// ── Alerts (Microsoft.Insights/metricAlerts, scoped via properties.scopes) ─────────────
function Alerts({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listMetricAlerts(a.resourceGroup, a.id), [a.id]);
  const metrics = useAsync(() => api.getMetrics(a.resourceGroup, a.name), [a.id]);
  const [add, setAdd] = useState(false);
  return (
    <CapabilityContainer id="azure.storage.alerts" title={`${a.name} | Alerts`}
      actions={<>
        <ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Create alert rule</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
      </>}>
      <BrowseGrid
        resourceName="alert rule" rowKey={(r) => r.name} items={data || []} loading={loading} error={error}
        onDelete={async (sel) => { for (const r of sel) await api.deleteMetricAlert(a.resourceGroup, r.name); notify.success(`Deleted ${sel.length} rule${sel.length === 1 ? "" : "s"}.`, "Delete succeeded"); reload(); }}
        csvName="alert-rules.csv"
        columns={[
          { key: "name", label: "Name" },
          { key: "condition", label: "Condition", value: (r) => { const c = r.properties?.criteria?.allOf?.[0]; return c ? `${c.metricName} ${c.operator} ${c.threshold}` : "--"; } },
          { key: "severity", label: "Severity", value: (r) => r.properties?.severity },
          { key: "status", label: "Status", render: (r) => (metrics.data ? (api.alertFired(r, metrics.data) ? <span style={{ color: "var(--colorPaletteRedForeground1)" }}>Fired</span> : "OK") : "--") },
        ]}
      />
      <Dialog open={add} onOpenChange={(_, d) => !d.open && setAdd(false)}>
        <DialogSurface aria-label="Create alert rule"><CreateAlertRuleBody a={a} onClose={() => setAdd(false)} onCreated={reload} /></DialogSurface>
      </Dialog>
    </CapabilityContainer>
  );
}

function CreateAlertRuleBody({ a, onClose, onCreated }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [metricName, setMetricName] = useState("UsedCapacity");
  const [operator, setOperator] = useState("GreaterThan");
  const [threshold, setThreshold] = useState("1000000");
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try {
      await api.putMetricAlert(a.resourceGroup, name, a.id, { metricName, operator, threshold: Number(threshold) });
      notify.success(`Alert rule '${name}' was created.`, "Create succeeded");
      onClose(); onCreated();
    } catch (e) { notify.error(e, "Failed to create alert rule"); }
    finally { setBusy(false); }
  };
  return (
    <DialogBody>
      <DialogTitle action={<Button appearance="subtle" icon={<Dismiss20Regular />} aria-label="Close" onClick={onClose} />}>Create alert rule</DialogTitle>
      <DialogContent>
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <Field label="Alert rule name" required><Input value={name} onChange={(_, d) => setName(d.value)} /></Field>
          <Field label="Signal (metric)"><Select value={metricName} onChange={(_, d) => setMetricName(d.value)}>
            {api.STORAGE_METRICS.map((m) => <option key={m} value={m}>{METRIC_LABEL[m]}</option>)}
          </Select></Field>
          <Field label="Operator"><Select value={operator} onChange={(_, d) => setOperator(d.value)}>
            <option value="GreaterThan">Greater than</option><option value="GreaterThanOrEqual">Greater than or equal to</option>
            <option value="LessThan">Less than</option><option value="LessThanOrEqual">Less than or equal to</option>
          </Select></Field>
          <Field label="Threshold value"><Input type="number" value={threshold} onChange={(_, d) => setThreshold(d.value)} /></Field>
        </div>
      </DialogContent>
      <DialogActions>
        <Button appearance="primary" disabled={!name || busy} onClick={go}>Create alert rule</Button>
        <Button onClick={onClose}>Cancel</Button>
      </DialogActions>
    </DialogBody>
  );
}

// ── Diagnostic settings (Microsoft.Insights/diagnosticSettings, a real ARM extension
// resource) + Logs (gated read-back of the real request log — see api.getDiagnosticLog) ──
const LOG_CATEGORIES = ["StorageRead", "StorageWrite", "StorageDelete"];

function Diagnostics({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listDiagnosticSettings(a.resourceGroup, a.name), [a.id]);
  const [add, setAdd] = useState(false);
  return (
    <CapabilityContainer id="azure.storage.diagnostics" title={`${a.name} | Diagnostic settings`}
      actions={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add diagnostic setting</ToolbarButton>}>
      <p style={{ fontSize: 13 }}>Enabling a log category here really gates what the <Link href="#">Logs</Link> page shows for this account — it is not delivered to the configured destination (no Log Analytics/Event Hub ingestion engine exists in Vyomi).</p>
      <BrowseGrid
        resourceName="diagnostic setting" rowKey={(r) => r.name} items={data || []} loading={loading} error={error} onRefresh={reload}
        onDelete={async (sel) => { for (const r of sel) await api.deleteDiagnosticSetting(a.resourceGroup, a.name, r.name); notify.success(`Deleted ${sel.length} setting${sel.length === 1 ? "" : "s"}.`, "Delete succeeded"); reload(); }}
        csvName="diagnostic-settings.csv"
        columns={[
          { key: "name", label: "Name" },
          { key: "destination", label: "Destination", value: (r) => r.properties?.storageAccountId || r.properties?.workspaceId || r.properties?.eventHubName || "--" },
          { key: "categories", label: "Log categories", value: (r) => (r.properties?.logs || []).filter((c) => c.enabled).map((c) => c.category).join(", ") || "--" },
        ]}
      />
      <Dialog open={add} onOpenChange={(_, d) => !d.open && setAdd(false)}>
        <DialogSurface aria-label="Add diagnostic setting"><AddDiagnosticSettingBody a={a} onClose={() => setAdd(false)} onAdded={reload} /></DialogSurface>
      </Dialog>
    </CapabilityContainer>
  );
}

function AddDiagnosticSettingBody({ a, onClose, onAdded }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [destAccount, setDestAccount] = useState(a.name);
  const [cats, setCats] = useState(["StorageWrite"]);
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try {
      const destId = `/subscriptions/${a.id.split("/")[2]}/resourceGroups/${a.resourceGroup}/providers/Microsoft.Storage/storageAccounts/${destAccount}`;
      await api.putDiagnosticSetting(a.resourceGroup, a.name, name, {
        storageAccountId: destId, logs: LOG_CATEGORIES.map((c) => ({ category: c, enabled: cats.includes(c) })),
      });
      notify.success(`Diagnostic setting '${name}' was created.`, "Create succeeded");
      onClose(); onAdded();
    } catch (e) { notify.error(e, "Failed to create diagnostic setting"); }
    finally { setBusy(false); }
  };
  return (
    <DialogBody>
      <DialogTitle action={<Button appearance="subtle" icon={<Dismiss20Regular />} aria-label="Close" onClick={onClose} />}>Add diagnostic setting</DialogTitle>
      <DialogContent>
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <Field label="Diagnostic setting name" required><Input value={name} onChange={(_, d) => setName(d.value)} /></Field>
          <Field label="Destination storage account" hint="Must be a real storage account in this subscription."><Input value={destAccount} onChange={(_, d) => setDestAccount(d.value)} /></Field>
          <CheckboxRow label="Log categories" options={LOG_CATEGORIES} checked={cats} onChange={setCats} />
        </div>
      </DialogContent>
      <DialogActions>
        <Button appearance="primary" disabled={!name || !cats.length || busy} onClick={go}>Save</Button>
        <Button onClick={onClose}>Cancel</Button>
      </DialogActions>
    </DialogBody>
  );
}

function LogsPage({ a }) {
  const { data, loading, error, reload } = useAsync(() => api.getDiagnosticLog(a.name), [a.name]);
  const [filter, setFilter] = useState("");
  const rows = (data?.value || []).filter((r) => !filter || JSON.stringify(r).toLowerCase().includes(filter.toLowerCase()));
  return (
    <CapabilityContainer id="azure.storage.logs" title={`${a.name} | Logs`}
      actions={<ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Run</ToolbarButton>}>
      <p style={{ fontSize: 13 }}>A simple field filter over this account's real, in-memory request log — not a KQL/Log Analytics workspace query engine.</p>
      <Field label="Filter" style={{ maxWidth: 360 }}><Input value={filter} onChange={(_, d) => setFilter(d.value)} placeholder="Filter rows..." /></Field>
      <ErrorBar error={error} />
      {!loading && data && data.enabledCategories?.length === 0 && (
        <InfoBar intent="warning">No <Link href="#">Diagnostic setting</Link> on this account has an enabled log category yet — nothing is being captured.</InfoBar>
      )}
      {loading ? <Loading /> : rows.length ? (
        <table className="vy-grid">
          <thead><tr><th>Time</th><th>Category</th><th>Operation</th><th>Status</th><th>URI</th></tr></thead>
          <tbody>{rows.slice().reverse().map((r, i) => <tr key={i}><td>{fmtDate(r.time)}</td><td>{r.category}</td><td>{r.operation}</td><td>{r.status}</td><td>{r.uri}</td></tr>)}</tbody>
        </table>
      ) : <p className="vy-muted">No log rows to show.</p>}
    </CapabilityContainer>
  );
}

// ── Workbooks (Microsoft.Insights/workbooks) — real ARM-backed saved views pinned to a
// metric this account actually reports ─────────────────────────────────────────────────
function WorkbookPreview({ a, metricName }) {
  const { data, loading } = useAsync(() => api.getMetrics(a.resourceGroup, a.name), [a.id, metricName]);
  return loading ? <Loading /> : <div style={{ fontSize: 20 }}>{METRIC_LABEL[metricName] || metricName}: {fmtMetric(metricName, data?.[metricName]?.value ?? 0)}</div>;
}

function Workbooks({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listWorkbooks(a.resourceGroup, a.id), [a.id]);
  const [add, setAdd] = useState(false);
  const [open, setOpen] = useState(null);
  return (
    <CapabilityContainer id="azure.storage.workbooks" title={`${a.name} | Workbooks`}
      actions={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>New</ToolbarButton>}>
      <BrowseGrid
        resourceName="workbook" rowKey={(r) => r.name} items={data || []} loading={loading} error={error} onRefresh={reload}
        onDelete={async (sel) => { for (const r of sel) await api.deleteWorkbook(a.resourceGroup, r.name); notify.success(`Deleted ${sel.length} workbook${sel.length === 1 ? "" : "s"}.`, "Delete succeeded"); reload(); }}
        csvName="workbooks.csv"
        columns={[
          { key: "name", label: "Name", render: (r) => <Link as="button" onClick={() => setOpen(r)}>{r.properties?.displayName || r.name}</Link> },
          { key: "category", label: "Category", value: (r) => r.properties?.category },
        ]}
      />
      <Dialog open={add} onOpenChange={(_, d) => !d.open && setAdd(false)}>
        <DialogSurface aria-label="New workbook"><CreateWorkbookBody a={a} onClose={() => setAdd(false)} onCreated={reload} /></DialogSurface>
      </Dialog>
      <Dialog open={!!open} onOpenChange={(_, d) => !d.open && setOpen(null)}>
        <DialogSurface aria-label={open?.properties?.displayName || "Workbook"}>
          <DialogBody>
            <DialogTitle>{open?.properties?.displayName}</DialogTitle>
            <DialogContent>{open && <WorkbookPreview a={a} metricName={JSON.parse(open.properties.serializedData || "{}").metric} />}</DialogContent>
            <DialogActions><Button onClick={() => setOpen(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </CapabilityContainer>
  );
}

function CreateWorkbookBody({ a, onClose, onCreated }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [metricName, setMetricName] = useState("UsedCapacity");
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try {
      await api.putWorkbook(a.resourceGroup, `${a.name}-${name}`.replace(/[^a-zA-Z0-9-]/g, ""), a.id, name, metricName);
      notify.success(`Workbook '${name}' was created.`, "Create succeeded");
      onClose(); onCreated();
    } catch (e) { notify.error(e, "Failed to create workbook"); }
    finally { setBusy(false); }
  };
  return (
    <DialogBody>
      <DialogTitle action={<Button appearance="subtle" icon={<Dismiss20Regular />} aria-label="Close" onClick={onClose} />}>New workbook</DialogTitle>
      <DialogContent>
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <Field label="Title" required><Input value={name} onChange={(_, d) => setName(d.value)} /></Field>
          <Field label="Pinned metric"><Select value={metricName} onChange={(_, d) => setMetricName(d.value)}>
            {api.STORAGE_METRICS.map((m) => <option key={m} value={m}>{METRIC_LABEL[m]}</option>)}
          </Select></Field>
        </div>
      </DialogContent>
      <DialogActions>
        <Button appearance="primary" disabled={!name || busy} onClick={go}>Create</Button>
        <Button onClick={onClose}>Cancel</Button>
      </DialogActions>
    </DialogBody>
  );
}


// ── Large file shares (Configuration): one-way, only on Standard LRS/ZRS/GRS/GZRS (core/azure_files_core.validate_account) ──
function LargeFileShares({ a, reload }) {
  const notify = useNotify();
  const on = a.properties?.largeFileSharesState === "Enabled";
  const premium = a.kind === "FileStorage" || /^premium/i.test(a.sku?.name || "");
  const enable = async () => {
    try { await api.updateStorageAccount(a.resourceGroup, a.name, { properties: { largeFileSharesState: "Enabled" } }); notify.success("Large file shares enabled (this cannot be undone).", "Saved"); reload?.(); }
    catch (e) { notify.error(e, "Enabling large file shares failed"); }
  };
  return (
    <CapabilityContainer id="azure.storage.largefileshares" title="Large file shares">
      <KV label="Large file shares" value={premium ? "Always on (premium FileStorage)" : on ? "Enabled" : "Disabled"} />
      {!premium && !on && <Button onClick={enable} aria-label="Enable large file shares">Enabled</Button>}
      <p className="vy-muted" style={{ fontSize: 12 }}>Raises the maximum share size from 5 TiB to 100 TiB. Cannot be disabled afterwards; requires Standard LRS, ZRS, GRS or GZRS.</p>
    </CapabilityContainer>
  );
}

function AzureAiSearch({ a }) {
  const containers = useAsync(() => api.listContainers(a.name), [a.name]);
  return (
    <AiSearchIntegration source={{ kind: "storage", capId: "azure.storage.azureaisearch", title: `${a.name} | Azure AI Search`, account: a.name,
      containers: (containers.data || []).map((c) => c.name), connectionString: `DefaultEndpointsProtocol=https;AccountName=${a.name};EndpointSuffix=core.windows.net` }} />
  );
}
