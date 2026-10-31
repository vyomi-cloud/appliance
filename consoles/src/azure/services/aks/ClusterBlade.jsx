/* Kubernetes service (AKS cluster) resource blade: left resource menu + panels. Overview,
 * Activity log, Access control (IAM), Tags, Namespaces, Run command, Node pools, Cluster
 * configuration, Locks, Properties and Export template are backed by native ARM calls;
 * Workloads, Services and ingresses and Configuration list the Kubernetes objects the cluster
 * really holds (kubectl through runCommand — stored, never scheduled); Microsoft Defender for
 * Cloud shows this cluster's live recommendations (Kubescape). Everything else in the menu
 * (Storage, Custom resources, Events, Azure Monitor/Advisor/GitOps integrations) is an honest
 * NotSimulated panel. */
import { useEffect, useState } from "react";
import {
  Button, Checkbox, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Link,
  Select, Spinner, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow, Tab, TabList, Textarea, ToolbarButton,
} from "@fluentui/react-components";
import { Add20Regular, ArrowClockwise20Regular, ArrowDownload20Regular, Delete20Regular, Dismiss20Regular, Play20Regular, Save20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { locationLabel } from "../../kit/arm.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import ResourceBlade from "../../kit/ResourceBlade.jsx";
import { Essentials, ErrorBar, Glyph, KV, Loading, NotSimulated, NotSimulatedContainer, fmtDate } from "../../kit/common.jsx";
import { remember, forget } from "../../kit/recent.js";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ResourceRecommendations } from "../defender/Pages.jsx";

export const MENU = [
  { id: "overview", label: "Overview" },
  { id: "activitylog", label: "Activity log" },
  { id: "iam", label: "Access control (IAM)" },
  { id: "tags", label: "Tags" },
  { id: "diagnose", label: "Diagnose and solve problems" },
  { id: "defender", label: "Microsoft Defender for Cloud" },
  { group: "Kubernetes resources", items: [
    { id: "namespaces", label: "Namespaces" }, { id: "workloads", label: "Workloads" },
    { id: "servicesingresses", label: "Services and ingresses" }, { id: "storage", label: "Storage" },
    { id: "configuration", label: "Configuration" }, { id: "customresources", label: "Custom resources" },
    { id: "events", label: "Events" }, { id: "runcommand", label: "Run command" },
  ] },
  { group: "Settings", items: [
    { id: "nodepools", label: "Node pools" }, { id: "clusterconfiguration", label: "Cluster configuration" },
    { id: "applicationscaling", label: "Application scaling" }, { id: "networking", label: "Networking" },
    { id: "extensionsapplications", label: "Extensions + applications" }, { id: "backup", label: "Backup" },
    { id: "gitops", label: "GitOps" }, { id: "automateddeployments", label: "Automated deployments" },
    { id: "policies", label: "Policies" }, { id: "properties", label: "Properties" }, { id: "locks", label: "Locks" },
  ] },
  { group: "Monitoring", items: [
    { id: "insights", label: "Insights" }, { id: "alerts", label: "Alerts" }, { id: "metrics", label: "Metrics" },
    { id: "diagnosticsettings", label: "Diagnostic settings" }, { id: "advisorrecommendations", label: "Advisor recommendations" },
    { id: "logs", label: "Logs" }, { id: "workbooks", label: "Workbooks" },
  ] },
  { group: "Automation", items: [{ id: "tasks", label: "Tasks" }, { id: "exporttemplate", label: "Export template" }] },
  { group: "Help", items: [{ id: "supporttroubleshooting", label: "Support + Troubleshooting" }] },
];
const LABEL = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
const NS_NOTES = {
  diagnose: "Diagnose and solve problems",
  storage: "Kubernetes persistent volumes / storage classes",
  customresources: "Kubernetes custom resource definitions",
  applicationscaling: "KEDA-based application scaling",
  networking: "Cluster networking settings (configured at create time; see the create wizard's Networking tab)",
  extensionsapplications: "Cluster extensions and applications",
  backup: "Azure Backup for AKS",
  gitops: "Flux GitOps configurations",
  automateddeployments: "Automated deployments (GitHub Actions)",
  policies: "Azure Policy assignments",
  insights: "Container insights",
  alerts: "Alert rules",
  metrics: "Cluster metrics",
  diagnosticsettings: "Diagnostic settings",
  advisorrecommendations: "Advisor recommendations",
  logs: "Log Analytics queries",
  workbooks: "Workbooks",
  tasks: "Tasks",
  supporttroubleshooting: "Support + Troubleshooting",
};

export default function ClusterBlade({ params, query }) {
  const { rg, name } = params;
  const panel = params.panel || "overview";
  const cluster = useAsync(() => api.getCluster(rg, name), [rg, name]);
  const self = `#/aks/${encodeURIComponent(rg)}/${encodeURIComponent(name)}`;
  useEffect(() => { if (cluster.data) remember({ name, type: "Kubernetes service", href: self }); }, [!!cluster.data, self]);

  let body;
  if (cluster.loading && !cluster.data) body = <Loading />;
  else if (cluster.error) body = <><ErrorBar error={cluster.error} title="Failed to load the kubernetes service" /><Link href="#/aks">Back to Kubernetes services</Link></>;
  else {
    const a = cluster.data, reload = cluster.reload;
    const P = {
      overview: () => <Overview a={a} reload={reload} self={self} />,
      iam: () => <AccessControlIam a={a} />,
      tags: () => <Tags a={a} reload={reload} />,
      namespaces: () => <Namespaces a={a} />,
      workloads: () => <Workloads a={a} />,
      servicesingresses: () => <ServicesIngresses a={a} />,
      configuration: () => <Configuration a={a} />,
      defender: () => <ResourceRecommendations resourceId={a.id} />,
      runcommand: () => <RunCommand a={a} />,
      nodepools: () => <NodePools a={a} />,
      clusterconfiguration: () => <ClusterConfiguration a={a} reload={reload} />,
      properties: () => <Properties a={a} />,
      locks: () => <Locks a={a} />,
      activitylog: () => <ActivityLog a={a} />,
      exporttemplate: () => <ExportTemplate a={a} />,
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
      title={panel === "overview" ? name : `${name} | ${LABEL[panel] || panel}`} subtitle="Kubernetes service" glyph={<Glyph id="aks" />} closeHref="#/aks"
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
  const [tab, setTab] = useState("getstarted");
  const [del, setDel] = useState(false);
  const [connect, setConnect] = useState(false);
  const [busy, setBusy] = useState(false);
  const p = a.properties || {};
  const pools = p.agentPoolProfiles || [];
  const nodeCount = pools.reduce((n, x) => n + (x.count || 0), 0);
  const power = async (action) => {
    setBusy(true);
    try { await (action === "start" ? api.startCluster(a.resourceGroup, a.name) : api.stopCluster(a.resourceGroup, a.name)); notify.success(`${action === "start" ? "Starting" : "Stopping"} '${a.name}'.`, "Request submitted"); reload(); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-cmdbar" role="toolbar" aria-label="Overview commands">
        <ToolbarButton onClick={() => setConnect(true)}>Connect</ToolbarButton>
        <ToolbarButton disabled={busy} onClick={() => power("start")}>Start</ToolbarButton>
        <ToolbarButton disabled={busy} onClick={() => power("stop")}>Stop</ToolbarButton>
        <ToolbarButton icon={<Delete20Regular />} onClick={() => setDel(true)}>Delete</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
      </div>
      <Essentials
        left={[
          ["Resource group", <Link href="#/resourcegroups">{a.resourceGroup}</Link>],
          ["Status", p.powerState?.code === "Stopped" ? "Stopped" : p.provisioningState || "Succeeded"],
          ["Location", locationLabel(a.location)],
          ["Subscription", sub.displayName || sub.id],
          ["Subscription ID", sub.id],
        ]}
        right={[
          ["Kubernetes version", p.kubernetesVersion],
          ["API server address", p.fqdn],
          ["Network configuration", p.networkProfile?.networkPlugin ? `${p.networkProfile.networkPlugin} (${p.networkProfile.networkPluginMode || "node subnet"})` : "--"],
          ["Node pools", `${pools.length} pool${pools.length === 1 ? "" : "s"} (${nodeCount} node${nodeCount === 1 ? "" : "s"})`],
          ["Tags", <span>{Object.keys(a.tags || {}).length ? Object.entries(a.tags).map(([k, v]) => `${k} : ${v}`).join(", ") : ""} <Link href={`${self}/tags`}>{Object.keys(a.tags || {}).length ? "Edit" : "Add tags"}</Link></span>],
        ]}
      />
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Overview tabs">
        <Tab value="getstarted">Get started</Tab>
        <Tab value="monitoring">Monitoring</Tab>
        <Tab value="properties">Properties</Tab>
        <Tab value="capabilities">Capabilities</Tab>
        <Tab value="recommendations">Recommendations</Tab>
        <Tab value="tutorials">Tutorials</Tab>
      </TabList>
      {tab === "getstarted" && (
        <div style={{ marginTop: 12 }}>
          <p style={{ fontSize: 13 }}>Manage node pools and namespaces, or run a command against the cluster.</p>
          <Link href={`${self}/nodepools`}>Node pools</Link>{" · "}<Link href={`${self}/namespaces`}>Namespaces</Link>{" · "}<Link href={`${self}/runcommand`}>Run command</Link>
        </div>
      )}
      {tab === "monitoring" && <NotSimulatedContainer feature="Cluster monitoring (CPU/memory charts, node and pod health)" />}
      {tab === "properties" && <PropertyList a={a} />}
      {tab === "capabilities" && <NotSimulatedContainer feature="The capabilities overview" />}
      {tab === "recommendations" && <NotSimulatedContainer feature="Advisor recommendations" />}
      {tab === "tutorials" && <NotSimulatedContainer feature="Tutorials" />}

      <Dialog open={connect} onOpenChange={(_, d) => !d.open && setConnect(false)}>
        <ConnectDialogBody a={a} onClose={() => setConnect(false)} />
      </Dialog>
      <DeleteDialog open={del} onClose={() => setDel(false)} resourceType="kubernetes service" names={[a.name]}
        onConfirm={async () => {
          await api.deleteCluster(a.resourceGroup, a.name);
          forget(self);
          notify.success(`Kubernetes service '${a.name}' was deleted.`, "Delete succeeded");
          navigate("aks");
        }} />
    </>
  );
}

function ConnectDialogBody({ a, onClose }) {
  const { data, loading, error } = useAsync(() => api.listClusterUserCredential(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const kubeconfig = data?.kubeconfigs?.[0] ? api.decodeKubeconfig(data.kubeconfigs[0].value) : "";
  return (
    <DialogSurface aria-label="Connect">
      <DialogBody>
        <DialogTitle>Connect to the cluster</DialogTitle>
        <DialogContent>
          {loading ? <Loading /> : <ErrorBar error={error} />}
          {kubeconfig && (
            <>
              <p style={{ fontSize: 13 }}>Download the cluster's kubeconfig, or run <code>az aks get-credentials</code>, then connect with kubectl.</p>
              <Textarea readOnly value={kubeconfig} style={{ width: "100%", minHeight: 200, fontFamily: "monospace" }} aria-label="kubeconfig" />
            </>
          )}
        </DialogContent>
        <DialogActions><Button onClick={onClose}>Close</Button></DialogActions>
      </DialogBody>
    </DialogSurface>
  );
}

function PropertyList({ a }) {
  const p = a.properties || {};
  return (
    <div className="vy-props" style={{ marginTop: 12 }}>
      <KV label="Cluster name" value={a.name} />
      <KV label="Resource ID" value={a.id} />
      <KV label="Kubernetes version" value={p.kubernetesVersion} />
      <KV label="DNS prefix" value={p.dnsPrefix} />
      <KV label="FQDN" value={p.fqdn} />
      <KV label="Node resource group" value={p.nodeResourceGroup} />
    </div>
  );
}

// ── Access control (IAM) ──────────────────────────────────────────────────────────────
function AccessControlIam({ a }) {
  const [tab, setTab] = useState("check");
  const [dlg, setDlg] = useState(null);
  return (
    <>
      <div className="vy-panel-title">Access control (IAM)</div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Access control (IAM) tabs">
        <Tab value="check">Check access</Tab>
        <Tab value="assignments">Role assignments</Tab>
        <Tab value="roles">Roles</Tab>
        <Tab value="deny">Deny assignments</Tab>
        <Tab value="classic">Classic administrators</Tab>
      </TabList>
      {tab === "check" && (
        <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 16 }}>
          <section className="vy-section"><h3>My access</h3>
            <Button onClick={() => setDlg("mine")}>View my access</Button>
          </section>
          <section className="vy-section"><h3>Check access</h3>
            <Button onClick={() => setDlg("check")}>Check access</Button>
          </section>
        </div>
      )}
      {tab === "assignments" && (
        <div style={{ marginTop: 12 }}>
          <div className="vy-panel-title">Role assignments</div>
          <NotSimulatedContainer feature="Role assignments scoped to this AKS cluster (Microsoft.Authorization/roleAssignments is simulated at subscription scope only)" />
        </div>
      )}
      {tab === "roles" && (
        <div style={{ marginTop: 12 }}>
          <div className="vy-panel-title">Roles</div>
          <NotSimulatedContainer feature="The built-in and custom role catalog" />
        </div>
      )}
      {tab === "deny" && (
        <div style={{ marginTop: 12 }}>
          <div className="vy-panel-title">Deny assignments</div>
          <NotSimulatedContainer feature="Deny assignments" />
        </div>
      )}
      {tab === "classic" && <div style={{ marginTop: 12 }}><NotSimulatedContainer title="Classic administrators" feature="Classic administrators (co-administrators)" /></div>}
      <Dialog open={!!dlg} onOpenChange={(_, d) => !d.open && setDlg(null)}>
        <DialogSurface aria-label="Access check">
          <DialogBody>
            <DialogTitle>{dlg === "mine" ? "My access" : "Check access"}</DialogTitle>
            <DialogContent><NotSimulated feature="Per-identity role-assignment resolution for this resource" note={`The cluster's resource id is ${a.id}.`} /></DialogContent>
            <DialogActions><Button onClick={() => setDlg(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

// ── Tags ───────────────────────────────────────────────────────────────────────────────
export function TagRows({ tags, onChange, resource }) {
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
            <TableCell>{resource}</TableCell>
            <TableCell>{i < tags.length - 1 && <Button appearance="subtle" size="small" icon={<Delete20Regular />} aria-label="Delete tag" onClick={() => onChange(tags.filter((_, j) => j !== i))} />}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function Tags({ a, reload }) {
  const notify = useNotify();
  const init = () => [...Object.entries(a.tags || {}).map(([name, value]) => ({ name, value })), { name: "", value: "" }];
  const [rows, setRows] = useState(init);
  const [busy, setBusy] = useState(false);
  const apply = async () => {
    setBusy(true);
    try {
      // ARM PUT replaces the resource's tag set exactly (a PATCH would merge and keep removed keys).
      const { id, name, type, resourceGroup, ...rest } = a;
      await api.createCluster(a.resourceGroup, a.name, { ...rest, tags: Object.fromEntries(rows.filter((t) => t.name).map((t) => [t.name, t.value])) });
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
        <Button appearance="secondary" disabled={busy || !rows.some((t) => t.name)} onClick={async () => { setRows([{ name: "", value: "" }]); await apply(); }}>Delete all</Button>
      </div>
    </>
  );
}

// ── Namespaces (stateful list on properties.namespaces) ────────────────────────────────
function Namespaces({ a }) {
  // Own fresh fetch (not the outer ClusterBlade's cached cluster `a`, keyed only on [rg,name] —
  // it wouldn't refetch across a same-document hash navigation into this panel, e.g. a tab
  // switch on an already-mounted blade, and would show a stale namespace list).
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.getCluster(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const [create, setCreate] = useState(false);
  const rows = data ? api.listNamespaces(data) : [];
  return (
    <>
      <div className="vy-panel-title">Namespaces</div>
      <BrowseGrid
        resourceName="namespace" rowKey={(r) => r.name} filterPlaceholder="Filter by namespace name"
        items={rows} loading={loading} error={error} onRefresh={reload} onCreate={() => setCreate(true)}
        onDelete={async (sel) => {
          for (const r of sel) await api.deleteNamespace(a.resourceGroup, a.name, r.name);
          notify.success(`Deleted ${sel.length} namespace${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
          reload();
        }}
        csvName="namespaces.csv"
        columns={[
          { key: "name", label: "Name" },
          { key: "status", label: "Status" },
          { key: "age", label: "Age", value: (r) => fmtDate(r.createdAt) },
        ]}
      />
      <CreateNamespaceDialog open={create} onClose={() => setCreate(false)}
        onCreate={async (nsName) => { await api.addNamespace(a.resourceGroup, a.name, nsName); reload(); }} />
    </>
  );
}

function CreateNamespaceDialog({ open, onClose, onCreate }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const valid = /^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$/.test(name);
  const go = async () => {
    setBusy(true);
    try { await onCreate(name); notify.success(`Namespace '${name}' was created.`, "Namespace created"); setName(""); onClose(); }
    catch (e) { notify.error(e, "Failed to create namespace"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Create a namespace">
        <DialogBody>
          <DialogTitle action={<Button appearance="subtle" icon={<Dismiss20Regular />} aria-label="Close" onClick={onClose} />}>Create a namespace</DialogTitle>
          <DialogContent><Field label="Name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Name" /></Field></DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!valid || busy} onClick={go}>Create</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

// ── Workloads / Services and ingresses / Configuration — the cluster's stored Kubernetes objects ──
// Read with `kubectl get … -A -o json` and written with `kubectl apply` / `kubectl delete`, all
// through the native runCommand action. Vyomi stores objects but runs no containers: the status
// columns say so instead of inventing readiness.
const ageOf = (o) => fmtDate(o.metadata?.creationTimestamp);
const ready = (o) => `${o.status?.readyReplicas ?? 0}/${o.spec?.replicas ?? 1}`;
const K8S_TABS = {
  deployments: { kind: "deployments", label: "Deployments", columns: [
    { key: "ready", label: "Ready", value: ready }, { key: "uptodate", label: "Up-to-date", value: (o) => o.status?.updatedReplicas ?? 0 },
    { key: "available", label: "Available", value: (o) => o.status?.availableReplicas ?? 0 }] },
  pods: { kind: "pods", label: "Pods", columns: [
    { key: "ready", label: "Ready", value: (o) => `0/${(o.spec?.containers || []).length}` },
    { key: "phase", label: "Phase", value: (o) => o.status?.phase || "Pending" }, { key: "restarts", label: "Restart count", value: () => 0 },
    { key: "image", label: "Images", value: (o) => (o.spec?.containers || []).map((c) => c.image).join(", ") }] },
  replicasets: { kind: "replicasets", label: "Replica sets", columns: [{ key: "ready", label: "Ready", value: ready }] },
  statefulsets: { kind: "statefulsets", label: "Stateful sets", columns: [{ key: "ready", label: "Ready", value: ready }] },
  daemonsets: { kind: "daemonsets", label: "Daemon sets", columns: [
    { key: "desired", label: "Desired", value: (o) => o.status?.desiredNumberScheduled ?? 0 }, { key: "current", label: "Current", value: (o) => o.status?.currentNumberScheduled ?? 0 },
    { key: "ready", label: "Ready", value: (o) => o.status?.numberReady ?? 0 }] },
  jobs: { kind: "jobs", label: "Jobs", columns: [{ key: "completions", label: "Completions", value: (o) => `${o.status?.succeeded ?? 0}/${o.spec?.completions ?? 1}` }] },
  cronjobs: { kind: "cronjobs", label: "Cron jobs", columns: [{ key: "schedule", label: "Schedule", value: (o) => o.spec?.schedule }, { key: "suspend", label: "Suspend", value: (o) => String(!!o.spec?.suspend) }] },
  services: { kind: "services", label: "Services", columns: [
    { key: "type", label: "Type", value: (o) => o.spec?.type || "ClusterIP" }, { key: "clusterip", label: "Cluster IP", value: (o) => o.spec?.clusterIP },
    { key: "external", label: "External IP", value: (o) => (o.spec?.type === "LoadBalancer" ? "Pending — Vyomi doesn't provision a load balancer" : (o.spec?.externalIPs || []).join(", ") || "-") },
    { key: "ports", label: "Ports", value: (o) => (o.spec?.ports || []).map((p) => `${p.port}/${p.protocol || "TCP"}`).join(", ") }] },
  ingresses: { kind: "ingresses", label: "Ingresses", columns: [
    { key: "class", label: "Class", value: (o) => o.spec?.ingressClassName || "-" },
    { key: "hosts", label: "Hosts", value: (o) => (o.spec?.rules || []).map((r) => r.host).filter(Boolean).join(", ") || "*" },
    { key: "address", label: "Address", value: () => "Pending — no ingress controller runs in Vyomi" }] },
  configmaps: { kind: "configmaps", label: "Config maps", columns: [{ key: "data", label: "Data", value: (o) => Object.keys(o.data || {}).length }] },
  secrets: { kind: "secrets", label: "Secrets", columns: [{ key: "type", label: "Type", value: (o) => o.type }, { key: "data", label: "Data", value: (o) => Object.keys(o.data || {}).length }] },
};
const SCHEDULED = new Set(["deployments", "pods", "replicasets", "statefulsets", "daemonsets", "jobs", "cronjobs"]);

function K8sTabs({ a, title, tabs, capId }) {
  const [tab, setTab] = useState(tabs[0]);
  const [apply, setApply] = useState(false);
  const notify = useNotify();
  const t = K8S_TABS[tab];
  const { data, loading, error, reload } = useAsync(() => api.listK8s(a.resourceGroup, a.name, t.kind), [a.resourceGroup, a.name, tab]);
  return (
    <>
      <div className="vy-panel-title">{title}</div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label={`${title} tabs`}>
        {tabs.map((k) => <Tab key={k} value={k}>{K8S_TABS[k].label}</Tab>)}
      </TabList>
      <div style={{ marginTop: 12 }}>
        <CapabilityContainer id={capId} title={t.label}>
          <BrowseGrid
            resourceName={t.label.toLowerCase().replace(/s$/, "")} rowKey={(o) => `${o.metadata.namespace}/${o.metadata.name}`}
            items={(data || []).map((o) => ({ ...o, name: o.metadata.name }))} loading={loading} error={error} onRefresh={reload} onCreate={() => setApply(true)}
            onDelete={async (sel) => {
              for (const o of sel) await api.deleteK8s(a.resourceGroup, a.name, t.kind, o.metadata.namespace, o.metadata.name);
              notify.success(`Deleted ${sel.length} object${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
              reload();
            }}
            csvName={`${t.kind}.csv`} filterPlaceholder="Filter by name or namespace"
            pills={[{ key: "ns", label: "Namespace", value: (o) => o.metadata.namespace }]}
            columns={[
              { key: "name", label: "Name", value: (o) => o.metadata.name },
              { key: "namespace", label: "Namespace", value: (o) => o.metadata.namespace },
              ...(SCHEDULED.has(tab) ? [{ key: "status", label: "Status", value: () => "Not scheduled — Vyomi doesn't run containers" }] : []),
              ...t.columns,
              { key: "age", label: "Age", value: ageOf },
            ]}
          />
        </CapabilityContainer>
      </div>
      <ApplyYamlDialog a={a} open={apply} onClose={() => setApply(false)} onApplied={reload} />
    </>
  );
}

function ApplyYamlDialog({ a, open, onClose, onApplied }) {
  const notify = useNotify();
  const [yaml, setYaml] = useState("");
  const [busy, setBusy] = useState(false);
  const [out, setOut] = useState("");
  const go = async () => {
    setBusy(true); setOut("");
    try {
      const logs = await api.applyYaml(a.resourceGroup, a.name, yaml);
      setOut(logs); notify.success(logs.trim().split("\n").slice(0, 3).join("; "), "Applied");
      onApplied && onApplied();
    } catch (e) { setOut(e.message); notify.error(e, "Apply failed"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Apply a YAML" style={{ maxWidth: 820 }}>
        <DialogBody>
          <DialogTitle action={<Button appearance="subtle" icon={<Dismiss20Regular />} aria-label="Close" onClick={onClose} />}>Apply a YAML</DialogTitle>
          <DialogContent>
            <p style={{ fontSize: 12, marginTop: 0 }}>Runs <code>kubectl apply -f -</code> against the cluster through Run command. Objects are stored and listed; nothing is scheduled, because Vyomi doesn't run containers.</p>
            <Textarea value={yaml} onChange={(_, d) => setYaml(d.value)} aria-label="YAML" placeholder={"apiVersion: apps/v1\nkind: Deployment\n..."} style={{ width: "100%", minHeight: 280, fontFamily: "monospace" }} />
            {out && <Textarea readOnly value={out} aria-label="kubectl output" style={{ width: "100%", minHeight: 90, fontFamily: "monospace", marginTop: 8 }} />}
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!yaml.trim() || busy} onClick={go}>Apply</Button>
            <Button onClick={onClose}>Close</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

function Workloads({ a }) {
  return <K8sTabs a={a} title="Workloads" capId="azure.aks.workloads" tabs={["deployments", "pods", "replicasets", "statefulsets", "daemonsets", "jobs", "cronjobs"]} />;
}

function ServicesIngresses({ a }) {
  return <K8sTabs a={a} title="Services and ingresses" capId="azure.aks.workloads" tabs={["services", "ingresses"]} />;
}

function Configuration({ a }) {
  return <K8sTabs a={a} title="Configuration" capId="azure.aks.workloads" tabs={["configmaps", "secrets"]} />;
}

// ── Run command ────────────────────────────────────────────────────────────────────────
function RunCommand({ a }) {
  const notify = useNotify();
  const [command, setCommand] = useState("");
  const [out, setOut] = useState(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try { setOut(await api.runCommand(a.resourceGroup, a.name, command)); }
    catch (e) { notify.error(e, "Run command failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">Run command</div>
      <section className="vy-section" style={{ maxWidth: 760 }}>
        <Field label="Command"><Textarea value={command} onChange={(_, d) => setCommand(d.value)} placeholder="kubectl get pods -A" aria-label="Command" style={{ minHeight: 80, fontFamily: "monospace" }} /></Field>
        <Button appearance="primary" icon={<Play20Regular />} disabled={!command || busy} onClick={run} style={{ marginTop: 8 }} aria-label="Run">Run</Button>
        {busy && <Loading />}
        {out && <Textarea readOnly value={out.logs} style={{ width: "100%", minHeight: 160, fontFamily: "monospace", marginTop: 8 }} aria-label="Output" />}
      </section>
    </>
  );
}

// ── Node pools ─────────────────────────────────────────────────────────────────────────
function NodePools({ a }) {
  const notify = useNotify();
  const [tab, setTab] = useState("pools");
  const { data, loading, error, reload } = useAsync(() => api.listNodePools(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const [add, setAdd] = useState(false);
  const [scaleRow, setScaleRow] = useState(null);
  const pools = data || [];
  const busyOn = async (r, fn) => {
    try { await fn(); notify.success(`Node pool '${r.name}' updated.`, "Request submitted"); reload(); }
    catch (e) { notify.error(e, `Failed to update node pool '${r.name}'`); }
  };
  const NEXT_VERSION = { "1.27.9": "1.28.5", "1.28.5": "1.29.2", "1.29.2": "1.30.0" };
  const upgrade = async () => {
    const next = NEXT_VERSION[a.properties?.kubernetesVersion] || "1.30.0";
    try {
      await api.updateCluster(a.resourceGroup, a.name, { properties: { kubernetesVersion: next } });
      notify.success(`Upgrading '${a.name}' to Kubernetes ${next}.`, "Upgrade started");
      reload();
    } catch (e) { notify.error(e, "Upgrade failed"); }
  };
  return (
    <>
      <div className="vy-panel-title">Node pools</div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Node pools tabs">
        <Tab value="pools">Node pools</Tab><Tab value="nodes">Nodes</Tab>
      </TabList>
      {tab === "pools" ? (
        <div style={{ marginTop: 12 }}>
          <BrowseGrid
            resourceName="node pool" rowKey={(r) => r.name} filterPlaceholder="Filter by name"
            items={pools} loading={loading} error={error} onRefresh={reload}
            extraCommands={<>
              <ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add node pool</ToolbarButton>
              <ToolbarButton onClick={upgrade}>Upgrade Kubernetes</ToolbarButton>
              <ToolbarButton disabled={!pools.length} onClick={() => setScaleRow("__first__")}>Scale node pool</ToolbarButton>
            </>}
            onDelete={async (sel) => {
              for (const r of sel) await api.deleteNodePool(a.resourceGroup, a.name, r.name);
              notify.success(`Deleted ${sel.length} node pool${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
              reload();
            }}
            csvName="node-pools.csv"
            columns={[
              { key: "name", label: "Name" },
              { key: "provisioningState", label: "Provisioning state", value: (r) => r.properties?.provisioningState || "Succeeded" },
              { key: "powerState", label: "Power state", value: (r) => r.properties?.powerState?.code || "Running" },
              { key: "scaleMethod", label: "Scale method", value: (r) => (r.properties?.enableAutoScaling ? "Autoscale" : "Manual") },
              { key: "targetNodes", label: "Target nodes", value: (r) => r.properties?.count },
              { key: "readyNodes", label: "Ready nodes", value: (r) => (r.properties?.powerState?.code === "Stopped" ? 0 : r.properties?.count) },
              { key: "autoscaling", label: "Autoscaling", value: (r) => (r.properties?.enableAutoScaling ? "Enabled" : "Disabled") },
              { key: "kubernetesVersion", label: "Kubernetes version", value: (r) => r.properties?.orchestratorVersion || a.properties?.kubernetesVersion },
              { key: "mode", label: "Mode", value: (r) => r.properties?.mode || "System" },
              { key: "nodeImageVersion", label: "Node image version", value: (r) => r.properties?.nodeImageVersion || "AKSUbuntu-2204" },
              { key: "osSKU", label: "OS SKU", value: (r) => r.properties?.osSKU || "Ubuntu" },
              { key: "nodeSize", label: "Node size", value: (r) => r.properties?.vmSize },
            ]}
          />
          <div className="vy-cmdbar" role="toolbar" aria-label="Node pool power commands" style={{ marginTop: 8 }}>
            {pools.map((p) => (
              <span key={p.name} style={{ marginRight: 12 }}>
                <ToolbarButton size="small" onClick={() => busyOn(p, () => api.patchNodePool(a.resourceGroup, a.name, p.name, { properties: { powerState: { code: "Running" } } }))}>Start {p.name}</ToolbarButton>
                <ToolbarButton size="small" onClick={() => busyOn(p, () => api.patchNodePool(a.resourceGroup, a.name, p.name, { properties: { powerState: { code: "Stopped" } } }))}>Stop {p.name}</ToolbarButton>
                <ToolbarButton size="small" onClick={() => busyOn(p, () => api.patchNodePool(a.resourceGroup, a.name, p.name, { properties: { nodeImageVersion: `AKSUbuntu-2204-${Date.now() % 100000}` } }))}>Update image</ToolbarButton>
              </span>
            ))}
          </div>
        </div>
      ) : (
        <div style={{ marginTop: 12 }}>
          <table className="vy-grid">
            <thead><tr><th>Name</th><th>Node pool</th><th>Status</th><th>Role</th><th>Kubernetes version</th><th>OS</th><th>VM size</th></tr></thead>
            <tbody>
              {api.flattenNodes(pools).map((n) => (
                <tr key={n.name}><td>{n.name}</td><td>{n.pool}</td><td>{n.status}</td><td>{n.role}</td><td>{n.kubernetesVersion || "--"}</td><td>{n.os || "--"}</td><td>{n.vmSize}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <AddNodePoolDialog open={add} onClose={() => setAdd(false)} onCreate={async (p) => { await api.putNodePool(a.resourceGroup, a.name, p.name, { properties: { mode: p.mode, vmSize: p.vmSize, count: p.count, osSKU: "Ubuntu", type: "VirtualMachineScaleSets" } }); reload(); }} />
      <ScaleNodePoolDialog open={!!scaleRow} pools={pools} onClose={() => setScaleRow(null)}
        onScale={async (poolName, count) => { await api.patchNodePool(a.resourceGroup, a.name, poolName, { properties: { count } }); reload(); }} />
    </>
  );
}

function AddNodePoolDialog({ open, onClose, onCreate }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [mode, setMode] = useState("User");
  const [vmSize, setVmSize] = useState("Standard_DS2_v2");
  const [count, setCount] = useState(3);
  const [busy, setBusy] = useState(false);
  const valid = /^[a-z][a-z0-9]{0,11}$/.test(name);
  const go = async () => {
    setBusy(true);
    try { await onCreate({ name, mode, vmSize, count }); notify.success(`Node pool '${name}' was added.`, "Node pool added"); setName(""); onClose(); }
    catch (e) { notify.error(e, "Failed to add node pool"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Add node pool">
        <DialogBody>
          <DialogTitle action={<Button appearance="subtle" icon={<Dismiss20Regular />} aria-label="Close" onClick={onClose} />}>Add node pool</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Node pool name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Node pool name" /></Field>
              <Field label="Mode"><Select value={mode} onChange={(_, d) => setMode(d.value)} aria-label="Mode"><option>User</option><option>System</option></Select></Field>
              <Field label="Node size"><Input value={vmSize} onChange={(_, d) => setVmSize(d.value)} aria-label="Node size" /></Field>
              <Field label="Node count"><Input type="number" value={String(count)} onChange={(_, d) => setCount(Number(d.value) || 1)} aria-label="Node count" /></Field>
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

function ScaleNodePoolDialog({ open, pools, onClose, onScale }) {
  const notify = useNotify();
  const [poolName, setPoolName] = useState("");
  const [count, setCount] = useState(3);
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try { await onScale(poolName || pools[0]?.name, count); onClose(); }
    catch (e) { notify.error(e, "Failed to scale node pool"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Scale node pool">
        <DialogBody>
          <DialogTitle>Scale node pool</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Node pool"><Select value={poolName || pools[0]?.name || ""} onChange={(_, d) => setPoolName(d.value)} aria-label="Node pool">{pools.map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}</Select></Field>
              <Field label="Node count"><Input type="number" value={String(count)} onChange={(_, d) => setCount(Number(d.value) || 1)} aria-label="Node count" /></Field>
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={busy || !pools.length} onClick={go}>Save</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

// ── Cluster configuration ───────────────────────────────────────────────────────────────
function ClusterConfiguration({ a, reload }) {
  const notify = useNotify();
  const p = a.properties || {};
  const init = () => ({ version: p.kubernetesVersion || "", autoUpgrade: p.autoUpgradeProfile?.upgradeChannel || "patch", auth: a.properties?.disableLocalAccounts ? "aad-rbac" : "local" });
  const [f, setF] = useState(init);
  const [busy, setBusy] = useState(false);
  const dirty = JSON.stringify(f) !== JSON.stringify(init());
  const save = async () => {
    setBusy(true);
    try {
      await api.updateCluster(a.resourceGroup, a.name, { properties: {
        kubernetesVersion: f.version, autoUpgradeProfile: { upgradeChannel: f.autoUpgrade },
        disableLocalAccounts: f.auth !== "local",
      } });
      notify.success(`Cluster configuration for '${a.name}' was saved.`, "Saved");
      reload();
    } catch (e) { notify.error(e, "Saving cluster configuration failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">Cluster configuration</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Cluster configuration commands">
        <ToolbarButton icon={<Save20Regular />} disabled={!dirty || busy} onClick={save}>Save</ToolbarButton>
        <ToolbarButton disabled={!dirty} onClick={() => setF(init())}>Discard</ToolbarButton>
      </div>
      <section className="vy-section"><h3>Upgrade</h3>
        <Field label="Kubernetes version"><Select value={f.version} onChange={(_, d) => setF((x) => ({ ...x, version: d.value }))} aria-label="Kubernetes version">
          <option value="1.27.9">1.27.9</option><option value="1.28.5">1.28.5</option><option value="1.29.2">1.29.2</option><option value="1.30.0">1.30.0</option>
        </Select></Field>
        <Field label="Automatic upgrade"><Select value={f.autoUpgrade} onChange={(_, d) => setF((x) => ({ ...x, autoUpgrade: d.value }))} aria-label="Automatic upgrade">
          <option value="patch">Enabled with patch (recommended)</option><option value="stable">Enabled with stable</option><option value="rapid">Enabled with rapid</option><option value="node-image">Enabled with node image</option><option value="none">Disabled</option>
        </Select></Field>
      </section>
      <section className="vy-section"><h3>Authentication and Authorization</h3>
        <Field label="Authentication and Authorization"><Select value={f.auth} onChange={(_, d) => setF((x) => ({ ...x, auth: d.value }))} aria-label="Authentication and Authorization">
          <option value="local">Local accounts with Kubernetes RBAC</option>
          <option value="aad-k8s-rbac">Microsoft Entra ID authentication with Kubernetes RBAC</option>
          <option value="aad-rbac">Microsoft Entra ID authentication with Azure RBAC</option>
        </Select></Field>
      </section>
    </>
  );
}

// ── Properties ─────────────────────────────────────────────────────────────────────────
function Properties({ a }) {
  const p = a.properties || {};
  return (
    <>
      <div className="vy-panel-title">Properties</div>
      <div className="vy-props">
        <KV label="Name" value={a.name} />
        <KV label="Resource ID" value={a.id} />
        <KV label="Location" value={locationLabel(a.location)} />
        <KV label="Kubernetes version" value={p.kubernetesVersion} />
        <KV label="DNS prefix" value={p.dnsPrefix} />
        <KV label="FQDN" value={p.fqdn} />
        <KV label="Node resource group" value={p.nodeResourceGroup} />
        <KV label="Provisioning state" value={p.provisioningState} />
      </div>
    </>
  );
}

// ── Locks (Microsoft.Authorization/locks, scoped to this cluster) ─────────────────────
function Locks({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listLocks(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const [add, setAdd] = useState(false);
  const [gap, setGap] = useState(null);
  const rows = data || [];
  return (
    <>
      <div className="vy-panel-title">Locks</div>
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

// ── Activity log (Microsoft.Insights/eventtypes/management/values, scoped to this cluster) ──
function ActivityLog({ a }) {
  const { data, loading, error, reload } = useAsync(() => api.listActivityLog(a.resourceGroup, a.name), [a.id]);
  const [filter, setFilter] = useState("");
  const [pinned, setPinned] = useState(false);
  const [gap, setGap] = useState(null);
  const rows = (data || []).filter((r) => !filter || (r.operationName?.localizedValue || "").toLowerCase().includes(filter.toLowerCase()));
  return (
    <>
      <div className="vy-panel-title">{a.name} | Activity log</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Activity log commands">
        <ToolbarButton onClick={() => setGap("Activity")}>Activity</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Edit columns")}>Edit columns</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Export Activity Logs")}>Export Activity Logs</ToolbarButton>
        <ToolbarButton icon={<ArrowDownload20Regular />} onClick={() => downloadActivity(rows, a.name)}>Download as CSV</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Insights")}>Insights</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Feedback")}>Feedback</ToolbarButton>
        <ToolbarButton onClick={() => setPinned((v) => !v)}>{pinned ? "Unpin current filters" : "Pin current filters"}</ToolbarButton>
        <ToolbarButton onClick={() => setFilter("")}>Reset filters</ToolbarButton>
      </div>
      <Input size="small" style={{ margin: "8px 0", width: 240 }} placeholder="Filter by operation" value={filter} onChange={(_, d) => setFilter(d.value)} aria-label="Filter by operation" />
      <ErrorBar error={error} />
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
            <DialogContent><NotSimulated feature={gap === "Feedback" ? "Sending product feedback" : gap || ""} /></DialogContent>
            <DialogActions><Button onClick={() => setGap(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

function downloadActivity(rows, name) {
  const cols = [{ label: "Operation name" }, { label: "Status" }, { label: "Time stamp" }];
  const esc = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const text = [cols.map((c) => esc(c.label)).join(","), ...rows.map((r) => [r.operationName?.localizedValue, r.status?.localizedValue, r.eventTimestamp].map(esc).join(","))].join("\r\n");
  const el = document.createElement("a");
  el.href = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
  el.download = `${name}-activity-log.csv`;
  document.body.appendChild(el); el.click(); el.remove();
}

// ── Export template ────────────────────────────────────────────────────────────────────
function ExportTemplate({ a }) {
  const [tab, setTab] = useState("arm");
  const [params, setParams] = useState(true);
  const template = {
    "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
    contentVersion: "1.0.0.0",
    ...(params ? { parameters: { clusterName: { type: "string", defaultValue: a.name } } } : {}),
    resources: [{ type: "Microsoft.ContainerService/managedClusters", apiVersion: api.ARM.apiVersion, name: params ? "[parameters('clusterName')]" : a.name, location: a.location, properties: a.properties }],
  };
  const text = JSON.stringify(template, null, 2);
  const download = () => {
    const el = document.createElement("a");
    el.href = URL.createObjectURL(new Blob([text], { type: "application/json" }));
    el.download = `${a.name}.json`;
    document.body.appendChild(el); el.click(); el.remove();
  };
  return (
    <>
      <div className="vy-panel-title">Export template</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Export template commands">
        <ToolbarButton icon={<ArrowDownload20Regular />} onClick={download}>Download</ToolbarButton>
        <ToolbarButton disabled>Add to library (preview)</ToolbarButton>
        <ToolbarButton disabled>Deploy</ToolbarButton>
        <ToolbarButton disabled>Visualize template</ToolbarButton>
      </div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Export template tabs">
        <Tab value="arm">ARM Template</Tab>
        <Tab value="bicep">Bicep</Tab>
        <Tab value="terraform">Terraform</Tab>
      </TabList>
      <section className="vy-section" style={{ marginTop: 12 }}><h3>Template</h3>
        <Checkbox label="Include parameters" checked={params} onChange={(_, d) => setParams(!!d.checked)} />
        {tab === "arm" && <Textarea readOnly value={text} style={{ width: "100%", minHeight: 320, fontFamily: "monospace" }} />}
        {tab !== "arm" && <NotSimulatedContainer feature={`${tab === "bicep" ? "Bicep" : "Terraform"} template export`} />}
      </section>
    </>
  );
}
