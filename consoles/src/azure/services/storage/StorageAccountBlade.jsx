/* Storage account resource blade: left resource menu + panels. Overview, Tags, Containers,
 * Access keys, Configuration, Endpoints, Redundancy, Networking and Encryption are backed by
 * native ARM / Blob calls; everything else in the menu is an honest NotSimulated panel. */
import { useEffect, useState } from "react";
import {
  Button, Checkbox, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Link,
  Radio, RadioGroup, Select, Tab, TabList, ToolbarButton,
} from "@fluentui/react-components";
import { ArrowClockwise20Regular, ArrowUpload20Regular, Copy16Regular, Delete20Regular, Eye16Regular, EyeOff16Regular, Save20Regular, Dismiss20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { href, navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { locationLabel } from "../../kit/arm.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
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
  { group: "Data storage", items: [{ id: "containers", label: "Containers" }, { id: "fileshares", label: "File shares" }, { id: "queues", label: "Queues" }, { id: "tables", label: "Tables" }] },
  { group: "Security + networking", items: [{ id: "networking", label: "Networking" }, { id: "accesskeys", label: "Access keys" }, { id: "sas", label: "Shared access signature" }, { id: "encryption", label: "Encryption" }, { id: "defender", label: "Microsoft Defender for Cloud" }] },
  { group: "Data management", items: [{ id: "redundancy", label: "Redundancy" }, { id: "dataprotection", label: "Data protection" }, { id: "objectreplication", label: "Object replication" }, { id: "inventory", label: "Blob inventory" }, { id: "staticwebsite", label: "Static website" }, { id: "lifecycle", label: "Lifecycle management" }] },
  { group: "Settings", items: [{ id: "configuration", label: "Configuration" }, { id: "cors", label: "Resource sharing (CORS)" }, { id: "advisor", label: "Advisor recommendations" }, { id: "endpoints", label: "Endpoints" }, { id: "locks", label: "Locks" }] },
  { group: "Monitoring", items: [{ id: "insights", label: "Insights" }, { id: "alerts", label: "Alerts" }, { id: "metrics", label: "Metrics" }, { id: "workbooks", label: "Workbooks" }, { id: "diagnostics", label: "Diagnostic settings" }, { id: "logs", label: "Logs" }] },
];
const LABEL = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
const NS_NOTES = {
  activitylog: "The ARM activity log",
  diagnose: "Diagnose and solve problems",
  iam: "Role assignments scoped to a storage account (Access control (IAM))",
  datamigration: "Data migration tools",
  events: "Event Grid subscriptions on storage events",
  storagebrowser: "Storage browser",
  fileshares: "Azure Files (file shares)",
  queues: "Queue storage in the v4 portal lens",
  tables: "Table storage",
  sas: "Shared access signature (SAS) generation",
  defender: "Microsoft Defender for Cloud",
  dataprotection: "Data protection (soft delete, versioning, change feed, point-in-time restore)",
  objectreplication: "Object replication",
  inventory: "Blob inventory",
  staticwebsite: "Static website hosting",
  lifecycle: "Lifecycle management policies",
  cors: "Resource sharing (CORS) rules",
  advisor: "Advisor recommendations",
  locks: "Management locks",
  insights: "Storage insights",
  alerts: "Alert rules",
  metrics: "Storage metrics",
  workbooks: "Workbooks",
  diagnostics: "Diagnostic settings",
  logs: "Log Analytics queries",
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
    }[panel];
    body = P ? P() : (
      <>
        <div className="vy-panel-title">{LABEL[panel] || panel}</div>
        <NotSimulated feature={NS_NOTES[panel] || `The ${LABEL[panel] || panel} panel`} />
      </>
    );
  }

  return (
    <ResourceBlade
      title={name} subtitle="Storage account" glyph={<Glyph text="SA" color="#0b7a75" />} closeHref="#/storage"
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
      </TabList>
      {tab === "properties" && <Properties a={a} />}
      {tab === "monitoring" && <NotSimulatedContainer feature="Storage account monitoring (requests, egress, latency charts)" />}
      {tab === "capabilities" && <NotSimulatedContainer feature="The capabilities overview" />}
      {tab === "recommendations" && <NotSimulatedContainer feature="Advisor recommendations" />}
      {tab === "tutorials" && <NotSimulatedContainer feature="Tutorials" />}

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
      <div className="vy-panel-title">Tags</div>
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
  return (
    <>
      <div className="vy-panel-title">Containers</div>
      <BrowseGrid
        resourceName="container" rowKey={(r) => r.name}
        items={data || []} loading={loading} error={error} onRefresh={reload}
        onCreate={() => setCreate(true)}
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
              <NotSimulated feature="Blob and container anonymous access levels, encryption scopes and version-level immutability" />
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
      <BrowseGrid
        resourceName="blob" rowKey={(r) => r.name}
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
          { key: "type", label: "Blob type" },
          { key: "size", label: "Size", value: (r) => fmtBytes(r.size) },
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
              <NotSimulated feature="Upload options for blob type, block size, access tier and encryption scope" note="Files upload as block blobs." />
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
      <div className="vy-panel-title">Access keys</div>
      <p style={{ fontSize: 13 }}>Access keys authenticate your applications' requests to this storage account. Use the connection string with the azure-storage-blob SDK or <span className="vy-mono">az storage</span>.</p>
      <InfoBar>Keys come from the native <span className="vy-mono">listKeys</span> ARM action. Vyomi issues fixed simulator keys and does not verify SharedKey signatures.</InfoBar>
      <ErrorBar error={keys.error} />
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
      const { sku, ...props } = f;
      await api.updateStorageAccount(a.resourceGroup, a.name, { sku: { name: sku }, properties: props });
      notify.success(`Configuration of '${a.name}' was saved.`, "Saved");
      reload();
    } catch (e) { notify.error(e, "Saving configuration failed"); }
    finally { setBusy(false); }
  };
  const perf = (f.sku.split("_")[0]) || "Standard";
  const skus = perf === "Premium" ? ["Premium_LRS", "Premium_ZRS"] : ["Standard_LRS", "Standard_ZRS", "Standard_GRS", "Standard_RAGRS", "Standard_GZRS", "Standard_RAGZRS"];
  return (
    <>
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
      <NotSimulatedContainer title="Large file shares" feature="Azure Files large file shares" />
    </>
  );
}

function Endpoints({ a }) {
  const ep = api.blobEndpoint(a.name);
  const p = a.properties?.primaryEndpoints || {};
  return (
    <>
      <div className="vy-panel-title">Endpoints</div>
      <section className="vy-section" style={{ maxWidth: 760, display: "flex", flexDirection: "column", gap: 10 }}>
        <h3>Blob service</h3>
        <Field label="Blob service (path-style, this Vyomi)" hint="Point azure-storage-blob / az storage at this URL; it is the endpoint this portal uses."><Input readOnly value={ep} /></Field>
        {p.blob && <Field label="Primary endpoint (from ARM)"><Input readOnly value={p.blob} /></Field>}
        <Field label="Storage account resource ID"><Input readOnly value={a.id} /></Field>
      </section>
      <NotSimulatedContainer title="Other services" feature="Data Lake Storage, Static website, File, Queue and Table service endpoints in the v4 portal lens" />
    </>
  );
}

function Redundancy({ a, self }) {
  return (
    <>
      <div className="vy-panel-title">Redundancy</div>
      <KV label="Redundancy" value={api.skuLabel(a.sku?.name)} />
      <KV label="Primary location" value={locationLabel(a.location)} />
      <p style={{ fontSize: 13 }}>Change redundancy in <Link href={`${self}/configuration`}>Configuration</Link>.</p>
      <NotSimulatedContainer title="Geo-replication" feature="Geo-replication, the secondary region and customer-managed failover" note="Vyomi stores data once, locally." />
    </>
  );
}

function Networking({ a }) {
  const p = a.properties || {};
  return (
    <>
      <div className="vy-panel-title">Networking</div>
      <InfoBar>{ENFORCEMENT}</InfoBar>
      <KV label="Public network access" value={p.publicNetworkAccess === "Disabled" ? "Disabled" : p.networkAcls?.defaultAction === "Deny" ? "Enabled from selected virtual networks and IP addresses" : "Enabled from all networks"} />
      <KV label="Routing preference" value={p.routingPreference?.routingChoice === "InternetRouting" ? "Internet routing" : "Microsoft network routing"} />
      <NotSimulatedContainer title="Firewalls and virtual networks" feature="Virtual network and IP firewall rules for storage accounts" />
      <NotSimulatedContainer title="Private endpoint connections" feature="Private endpoints for storage accounts" />
    </>
  );
}

function Encryption({ a }) {
  return (
    <>
      <div className="vy-panel-title">Encryption</div>
      <KV label="Encryption type" value={a.properties?.encryption?.keySource === "Microsoft.Keyvault" ? "Customer-managed keys" : "Microsoft-managed keys (MMK)"} />
      <NotSimulatedContainer title="Customer-managed keys" feature="Customer-managed keys and encryption scopes" />
      <NotSimulatedContainer title="Infrastructure encryption" feature="Infrastructure (double) encryption" />
    </>
  );
}
