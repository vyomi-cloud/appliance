/* Storage account resource blade: left resource menu + panels. Overview, Tags, Containers,
 * Access keys, Configuration, Endpoints, Redundancy, Networking and Encryption are backed by
 * native ARM / Blob calls; everything else in the menu is an honest NotSimulated panel. */
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
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import ResourceBlade from "../../kit/ResourceBlade.jsx";
import { ErrorBar, Essentials, fmtBytes, fmtDate, Glyph, InfoBar, KV, Loading, NotSimulated, NotSimulatedContainer } from "../../kit/common.jsx";
import { remember, forget } from "../../kit/recent.js";
import { useSubscription } from "../../kit/subscription.js";
import { TagRows } from "./CreateStorageAccount.jsx";
import * as api from "./api.js";

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
  iam: "Role assignments scoped to a storage account (Access control (IAM))",
  datamigration: "Data migration tools",
  events: "Event Grid subscriptions on storage events",
  storagebrowser: "Storage browser",
  storagemover: "Storage Mover",
  partnersolutions: "Partner solutions",
  fileshares: "Azure Files (file shares)",
  tables: "Table storage",
  frontdoorcdn: "Front Door and CDN",
  sas: "Shared access signature (SAS) generation",
  defender: "Microsoft Defender for Cloud",
  objectreplication: "Object replication",
  inventory: "Blob inventory",
  staticwebsite: "Static website hosting",
  lifecycle: "Lifecycle management policies",
  azureaisearch: "Azure AI Search",
  datalakegen2upgrade: "Data Lake Gen2 upgrade",
  cors: "Resource sharing (CORS) rules",
  advisor: "Advisor recommendations",
  insights: "Storage insights",
  alerts: "Alert rules",
  metrics: "Storage metrics",
  workbooks: "Workbooks",
  diagnostics: "Diagnostic settings",
  logs: "Log Analytics queries",
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
      overview: () => <Overview a={a} reload={reload} self={self} />,
      tags: () => <Tags a={a} reload={reload} />,
      containers: () => (query.container ? <Container account={name} container={query.container} self={self} /> : <Containers account={name} self={self} />),
      accesskeys: () => <AccessKeys a={a} />,
      configuration: () => <Configuration a={a} reload={reload} />,
      endpoints: () => <Endpoints a={a} />,
      redundancy: () => <Redundancy a={a} self={self} />,
      networking: () => <Networking a={a} />,
      encryption: () => <Encryption a={a} />,
      dataprotection: () => <DataProtection a={a} />,
      staticwebsite: () => <StaticWebsite a={a} />,
      exporttemplate: () => <ExportTemplate a={a} />,
      iam: () => <Iam a={a} />,
      cors: () => <Cors a={a} />,
      lifecycle: () => <Lifecycle a={a} />,
      sas: () => <Sas a={a} />,
      activitylog: () => <ActivityLog a={a} />,
      locks: () => <Locks a={a} />,
      queues: () => (query.queue ? <QueueDetail name={query.queue} self={self} /> : <Queues self={self} />),
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
      {tab === "properties" && <Properties a={a} />}
      {tab === "monitoring" && <NotSimulatedContainer feature="Storage account monitoring (requests, egress, latency charts)" />}
      {tab === "capabilities" && <NotSimulatedContainer feature="The capabilities overview" />}
      {tab === "recommendations" && <NotSimulatedContainer feature="Advisor recommendations" />}
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

function Properties({ a }) {
  const p = a.properties || {};
  const net = p.publicNetworkAccess === "Disabled" ? "Disabled" : p.networkAcls?.defaultAction === "Deny" ? "Selected networks" : "All networks";
  return (
    <div className="vy-props" style={{ marginTop: 12 }}>
      <section className="vy-section"><h3>Blob service</h3>
        <KV label="Hierarchical namespace" value={onoff(p.isHnsEnabled, false)} />
        <KV label="Default access tier" value={p.accessTier || "--"} />
        <KV label="Blob anonymous access" value={onoff(p.allowBlobPublicAccess, false)} />
        <KV label="Blob soft delete" value={ns("Blob soft delete")} />
        <KV label="Container soft delete" value={ns("Container soft delete")} />
        <KV label="Versioning" value={ns("Blob versioning")} />
        <KV label="Change feed" value={ns("Blob change feed")} />
        <KV label="NFS v3" value={ns("NFS v3")} />
        <KV label="Allow cross-tenant replication" value={onoff(p.allowCrossTenantReplication, false)} />
      </section>
      <section className="vy-section"><h3>Security</h3>
        <KV label="Require secure transfer for REST API operations" value={onoff(p.supportsHttpsTrafficOnly, true)} />
        <KV label="Storage account key access" value={onoff(p.allowSharedKeyAccess, true)} />
        <KV label="Minimum TLS version" value={(p.minimumTlsVersion || "TLS1_0").replace("TLS", "Version ").replace("_", ".")} />
        <KV label="Infrastructure encryption" value={ns("Infrastructure encryption")} />
      </section>
      <section className="vy-section"><h3>Networking</h3>
        <KV label="Allow access from" value={net} />
        <KV label="Number of private endpoint connections" value={ns("Private endpoints")} />
        <KV label="Network routing" value={p.routingPreference?.routingChoice === "InternetRouting" ? "Internet routing" : "Microsoft network routing"} />
        <KV label="Endpoint type" value="Standard" />
      </section>
      <section className="vy-section"><h3>File service</h3>
        <KV label="Large file share" value={ns("Azure Files")} />
        <KV label="Identity-based access" value={ns("Azure Files identity-based access")} />
      </section>
      <section className="vy-section"><h3>Queue service</h3>
        <KV label="Approximate messaging" value="Shared across every storage account on this Vyomi — see Queues." />
      </section>
      <section className="vy-section"><h3>Table service</h3>
        <KV label="Table storage" value={ns("Table storage")} />
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
  const [busy, setBusy] = useState(false);
  const valid = /^(?!-)(?!.*--)[a-z0-9-]{3,63}(?<!-)$/.test(name);
  const go = async () => {
    setBusy(true);
    try {
      await api.createContainer(account, name);
      notify.success(`Successfully created storage container '${name}'.`, "Container created");
      setName(""); onClose(); onCreated();
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
                <Select value="private" aria-label="Anonymous access level"><option value="private">Private (no anonymous access)</option></Select>
              </Field>
              <NotSimulated feature="Encryption scope and Enable version-level immutability support for new containers" />
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

function Container({ account, container, self }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listBlobs(account, container), [account, container]);
  const [upload, setUpload] = useState(false);
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
        extraCommands={<ToolbarButton icon={<ArrowUpload20Regular />} onClick={() => setUpload(true)}>Upload</ToolbarButton>}
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
          { key: "contentType", label: "Content type", hidden: true },
          { key: "md5", label: "Content-MD5", hidden: true },
        ]}
      />
      <UploadBlob open={upload} onClose={() => setUpload(false)} account={account} container={container} existing={(data || []).map((b) => b.name)} onDone={reload} />
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

function AccessKeys({ a }) {
  const keys = useAsync(() => api.listKeys(a.resourceGroup, a.name), [a.id]);
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
          <Secret label="Key" value={k.value} />
          <Secret label="Connection string" value={`DefaultEndpointsProtocol=${location.protocol.replace(":", "")};AccountName=${a.name};AccountKey=${k.value};BlobEndpoint=${ep};`} />
        </section>
      ))}
      <NotSimulatedContainer title="Rotate key" feature="Key rotation and key expiry reminders" />
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
      <NotSimulatedContainer title="Large file shares" feature="Azure Files large file shares" />
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
      <NotSimulatedContainer title="File service" feature="Azure Files (file shares) endpoints" />
      <NotSimulatedContainer title="Other services" feature="Data Lake Storage, Static website and Table service endpoints in the v4 portal lens" />
    </>
  );
}

function Redundancy({ a, self }) {
  return (
    <>
      <div className="vy-panel-title">{a.name} | Redundancy</div>
      <KV label="Redundancy" value={api.skuLabel(a.sku?.name)} />
      <KV label="Primary location" value={locationLabel(a.location)} />
      <p style={{ fontSize: 13 }}>Change redundancy in <Link href={`${self}/configuration`}>Configuration</Link>.</p>
      <section className="vy-section"><h3>Storage endpoints</h3>
        <p style={{ fontSize: 13 }}>See <Link href={`${self}/endpoints`}>Endpoints</Link> for this account's service URLs.</p>
      </section>
      <NotSimulatedContainer title="Geo-replication" feature="Geo-replication, the secondary region and customer-managed failover" note="Vyomi stores data once, locally." />
    </>
  );
}

function Networking({ a }) {
  const p = a.properties || {};
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
        <NotSimulatedContainer title="Virtual networks" feature="Virtual network rules for storage accounts" />
        <NotSimulatedContainer title="Firewall" feature="Address range IP firewall rules for storage accounts" />
        <NotSimulatedContainer title="Resource instances" feature="Resource instances (trusted Azure resource access by resource ID)" />
        <NotSimulatedContainer title="Exceptions" feature="Allow Azure services on the trusted services list to access this storage account" />
      </div>}
      {tab === "private" && <NotSimulatedContainer title="Private endpoint connections" feature="Private endpoints for storage accounts" />}
      {tab === "advanced" && <div style={{ display: "flex", flexDirection: "column", gap: 16, marginTop: 12 }}>
        <section className="vy-section"><h3>Network routing</h3>
          <KV label="Routing preference" value={p.routingPreference?.routingChoice === "InternetRouting" ? "Internet routing" : "Microsoft network routing"} />
          <NotSimulated feature="Publish route-specific endpoints for Microsoft network routing and Internet routing" />
        </section>
        <NotSimulatedContainer title="Custom domain" feature="Custom domain mapping — Domain name and Use indirect CNAME validation for storage accounts" />
      </div>}
    </>
  );
}

function Encryption({ a }) {
  return (
    <>
      <div className="vy-panel-title">{a.name} | Encryption</div>
      <section className="vy-section"><h3>Encryption selection</h3>
        <KV label="Encryption type" value={a.properties?.encryption?.keySource === "Microsoft.Keyvault" ? "Customer-managed keys" : "Microsoft-managed keys (MMK)"} />
      </section>
      <NotSimulatedContainer title="Customer-managed keys" feature="Customer-managed keys and encryption scopes" />
      <NotSimulatedContainer title="Infrastructure encryption" feature="Infrastructure (double) encryption" />
    </>
  );
}

// ── Static website (Microsoft.Storage/storageAccounts/blobServices/default, properties.staticWebsite) ──
// ── Access control (IAM) — tabs are real; every panel is an honest gap ────────────────
// ── Lifecycle management — tabs are real; both views are an honest gap ─────────────────
function Lifecycle({ a }) {
  const [tab, setTab] = useState("list");
  const [gap, setGap] = useState(null);
  return (
    <>
      <div className="vy-panel-title">{a.name} | Lifecycle management</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Lifecycle management commands">
        <ToolbarButton icon={<Add20Regular />} onClick={() => setGap("Add a rule")}>Add a rule</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Enable")}>Enable</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Disable")}>Disable</ToolbarButton>
        <ToolbarButton icon={<Delete20Regular />} onClick={() => setGap("Delete")}>Delete</ToolbarButton>
      </div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Lifecycle management tabs">
        <Tab value="list">List View</Tab>
        <Tab value="code">Code View</Tab>
      </TabList>
      {tab === "list" && <NotSimulatedContainer title="Rules" feature="Lifecycle management rules (columns: Name, Status, Blob type, Base blobs, Snapshots, Versions) that tier or expire blobs on a schedule" />}
      {tab === "code" && <NotSimulatedContainer title="Policy JSON" feature="The lifecycle management policy JSON editor" />}
      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label={gap || "Not simulated"}>
          <DialogBody>
            <DialogTitle>{gap}</DialogTitle>
            <DialogContent><NotSimulated feature="Lifecycle management rules" /></DialogContent>
            <DialogActions><Button onClick={() => setGap(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

function Iam({ a }) {
  const [tab, setTab] = useState("check");
  return (
    <>
      <div className="vy-panel-title">{a.name} | Access control (IAM)</div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Access control (IAM) tabs">
        <Tab value="check">Check access</Tab>
        <Tab value="assignments">Role assignments</Tab>
        <Tab value="roles">Roles</Tab>
        <Tab value="deny">Deny assignments</Tab>
        <Tab value="classic">Classic administrators</Tab>
      </TabList>
      {tab === "check" && <div style={{ display: "flex", flexDirection: "column", gap: 16, marginTop: 12 }}>
        <NotSimulatedContainer title="My access" feature="View my access" />
        <NotSimulatedContainer title="Check access" feature="Check access" />
      </div>}
      {tab === "assignments" && <NotSimulatedContainer title="Role assignments" feature="Role assignments scoped to a storage account" />}
      {tab === "roles" && <NotSimulatedContainer title="Roles" feature="The built-in and custom role catalog" />}
      {tab === "deny" && <NotSimulatedContainer title="Deny assignments" feature="Deny assignments" />}
      {tab === "classic" && <NotSimulatedContainer title="Classic administrators" feature="Classic administrators" />}
    </>
  );
}

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
  return (
    <>
      <div className="vy-panel-title">{a.name} | Resource sharing (CORS)</div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Resource sharing (CORS) tabs">
        <Tab value="blob">Blob service</Tab>
        <Tab value="file">File service</Tab>
        <Tab value="queue">Queue service</Tab>
        <Tab value="table">Table service</Tab>
      </TabList>
      {tab === "blob" && <NotSimulatedContainer title="Blob service" feature="CORS rules for the Blob service" />}
      {tab === "file" && <NotSimulatedContainer title="File service" feature="CORS rules for the File service" />}
      {tab === "queue" && <NotSimulatedContainer title="Queue service" feature="CORS rules for the Queue service" />}
      {tab === "table" && <NotSimulatedContainer title="Table service" feature="CORS rules for the Table service" />}
    </>
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
        <Field label="Primary endpoint"><Input readOnly value={`${api.blobEndpoint(a.name)}/$web`} /></Field>
      </section>
    </CapabilityContainer>
  );
}

// ── Export template (client-side ARM/Bicep/Terraform generated from this resource) ────
function ExportTemplate({ a }) {
  const [tab, setTab] = useState("arm");
  const [params, setParams] = useState(true);
  const resource = { type: "Microsoft.Storage/storageAccounts", apiVersion: "2023-01-01", name: a.name, location: a.location, tags: a.tags || {}, sku: a.sku, kind: a.kind, properties: a.properties };
  const arm = {
    "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
    contentVersion: "1.0.0.0",
    parameters: params ? { storageAccountName: { type: "string", defaultValue: a.name } } : {},
    resources: [{ ...resource, name: params ? "[parameters('storageAccountName')]" : a.name }],
  };
  const bicep = `resource ${a.name.replace(/[^a-zA-Z0-9]/g, "")} 'Microsoft.Storage/storageAccounts@2023-01-01' = {\n  name: '${a.name}'\n  location: '${a.location}'\n  sku: {\n    name: '${a.sku?.name}'\n  }\n  kind: '${a.kind}'\n}\n`;
  const terraform = `resource "azurerm_storage_account" "${a.name.replace(/[^a-zA-Z0-9]/g, "_")}" {\n  name                     = "${a.name}"\n  location                 = "${a.location}"\n  account_tier             = "${a.sku?.tier || "Standard"}"\n  account_replication_type = "${(a.sku?.name || "").split("_")[1] || "LRS"}"\n}\n`;
  const text = tab === "arm" ? JSON.stringify(arm, null, 2) : tab === "bicep" ? bicep : terraform;
  const [gap, setGap] = useState(null);
  return (
    <>
      <div className="vy-panel-title">{a.name} | Export template</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Export template commands">
        <ToolbarButton icon={<ArrowDownload20Regular />} as="a" href={`data:text/plain,${encodeURIComponent(text)}`} download={`${a.name}-template.${tab === "arm" ? "json" : tab === "bicep" ? "bicep" : "tf"}`}>Download</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Add to library (preview)")}>Add to library (preview)</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Deploy")}>Deploy</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Visualize template")}>Visualize template</ToolbarButton>
      </div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Export template tabs">
        <Tab value="arm">ARM Template</Tab>
        <Tab value="bicep">Bicep</Tab>
        <Tab value="terraform">Terraform</Tab>
      </TabList>
      <section className="vy-section" style={{ marginTop: 12 }}><h3>Template</h3>
        {tab === "arm" && <Checkbox checked={params} onChange={(_, d) => setParams(!!d.checked)} label="Include parameters" />}
        <pre className="vy-mono" style={{ maxHeight: 420, overflow: "auto", background: "var(--colorNeutralBackground3)", padding: 12, borderRadius: 4 }}>{text}</pre>
      </section>
      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label={gap || "Not simulated"}>
          <DialogBody>
            <DialogTitle>{gap}</DialogTitle>
            <DialogContent><NotSimulated feature={gap} /></DialogContent>
            <DialogActions><Button onClick={() => setGap(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

// ── Data protection (Microsoft.Storage/storageAccounts/blobServices/default) ───────────
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
      versioning: !!p.isVersioningEnabled, changeFeed: !!p.changeFeed?.enabled, immutability: false,
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
            {cb("backup", "Enable operational backup with Azure Backup")}
            {cb("pitr", "Enable point-in-time restore for containers")}
            {cb("softDeleteBlobs", "Enable soft delete for blobs")}
            <Field label="Keep deleted blobs for (in days)" style={{ maxWidth: 220, marginLeft: 24 }}>
              <Input type="number" value={String(f.softDeleteBlobDays)} onChange={(_, d) => setF((x) => ({ ...x, softDeleteBlobDays: d.value }))} /></Field>
            {cb("softDeleteContainers", "Enable soft delete for containers")}
            <Field label="Keep deleted containers for (in days)" style={{ maxWidth: 220, marginLeft: 24 }}>
              <Input type="number" value={String(f.softDeleteContainerDays)} onChange={(_, d) => setF((x) => ({ ...x, softDeleteContainerDays: d.value }))} /></Field>
            {cb("permanentDelete", "Enable permanent delete for soft deleted items")}
            {cb("softDeleteShares", "Enable soft delete for file shares")}
            <Field label="Keep deleted file shares for (in days)" style={{ maxWidth: 220, marginLeft: 24 }}>
              <Input type="number" value={String(f.softDeleteShareDays)} onChange={(_, d) => setF((x) => ({ ...x, softDeleteShareDays: d.value }))} /></Field>
          </div>
        </section>
        <section className="vy-section"><h3>Tracking</h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {cb("versioning", "Enable versioning for blobs")}
            {cb("changeFeed", "Enable blob change feed")}
          </div>
        </section>
        <section className="vy-section"><h3>Access control</h3>
          {cb("immutability", "Enable version-level immutability support")}
        </section>
      </div>
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
function ActivityLog({ a }) {
  const { data, loading, error, reload } = useAsync(() => api.listActivityLog(a.resourceGroup, a.name), [a.id]);
  const [gap, setGap] = useState(null);
  const rows = data || [];
  return (
    <CapabilityContainer id="azure.storage.activitylog" title={`${a.name} | Activity log`}
      actions={<>
        <ToolbarButton onClick={() => setGap("Edit columns")}>Edit columns</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Export Activity Logs")}>Export Activity Logs</ToolbarButton>
        <ToolbarButton icon={<ArrowDownload20Regular />} onClick={() => setGap("Download as CSV")}>Download as CSV</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Feedback")}>Feedback</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Pin current filters")}>Pin current filters</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Reset filters")}>Reset filters</ToolbarButton>
      </>}>
      <ErrorBar error={error} />
      <NotSimulated feature="Severity/category filtering and the Timespan picker" note="This list always shows everything recorded since the simulation booted." />
      <table className="vy-grid">
        <thead><tr><th>Operation name</th><th>Status</th><th>Time</th><th>Time stamp</th><th>Subscription</th><th>Event initiated by</th></tr></thead>
        <tbody>
          {loading ? <tr><td colSpan={6}><Spinner size="tiny" /></td></tr> : rows.length ? rows.map((r) => (
            <tr key={r.id}>
              <td>{r.operationName?.localizedValue || r.operationName?.value}</td>
              <td>{r.status?.localizedValue || r.status?.value}</td>
              <td>{fmtDate(r.eventTimestamp)}</td>
              <td>{r.eventTimestamp}</td>
              <td>{r.subscriptionId}</td>
              <td>{r.caller}</td>
            </tr>
          )) : <tr><td colSpan={6} className="vy-muted">No events to display</td></tr>}
        </tbody>
      </table>
      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label={gap || "Not simulated"}>
          <DialogBody>
            <DialogTitle>{gap}</DialogTitle>
            <DialogContent><NotSimulated feature={gap === "Feedback" ? "Sending product feedback" : gap} /></DialogContent>
            <DialogActions><Button onClick={() => setGap(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </CapabilityContainer>
  );
}

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
