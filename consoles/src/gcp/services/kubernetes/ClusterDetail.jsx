/* Cluster details: summary + tabs (Details, Nodes, Storage, Observability, Logs). Details/
 * Nodes/Logs are the native Kubernetes Engine REST API (control plane); Storage/Observability
 * read the real Kubernetes data plane (core/gcp_gke_dataplane_core.py) scoped to this cluster. */
import { useState } from "react";
import {
  Alert, Box, Button, Checkbox, Chip, Dialog, DialogActions, DialogContent, DialogTitle, FormControl,
  FormControlLabel, IconButton, InputLabel, MenuItem, Radio, RadioGroup, Select, Stack, Tab, Tabs, TextField, Typography,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import EditIcon from "@mui/icons-material/esm/Edit.js";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import LinkIcon from "@mui/icons-material/esm/Link.js";
import CloudUploadIcon from "@mui/icons-material/esm/CloudUpload.js";
import ContentCopyIcon from "@mui/icons-material/esm/FileCopy.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, KeyValue, PageHeader, Section } from "../../kit/common.jsx";
import { CapabilityBadge, CapabilityContainer } from "../../kit/Capability.jsx";
import { hashHref } from "../../link.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";
import DeployDialog from "./DeployDialog.jsx";
import ConnectDialog from "./ConnectDialog.jsx";

const TABS = [["details", "Details"], ["nodes", "Nodes"], ["storage", "Storage"], ["observability", "Observability"], ["logs", "Logs"]];
const location_ = window.location;   // `location` is the route param (region) below

export default function ClusterDetail({ params, query }) {
  const { location, name } = params;
  const notify = useNotify();
  const tab = TABS.some(([t]) => t === query.tab) ? query.tab : "details";
  const c = useAsync(() => api.getCluster(location, name), [location, name]);
  const [deploy, setDeploy] = useState(false);
  const [connect, setConnect] = useState(false);
  const [edit, setEdit] = useState(false);
  const [del, setDel] = useState(false);

  return (
    <>
      <PageHeader title="Cluster details" back={<IconButton aria-label="Back to clusters" href={hashHref("kubernetes", "clusters")}><ArrowBackIcon /></IconButton>}
        actions={<>
          <Button startIcon={<EditIcon />} disabled={!c.data} onClick={() => setEdit(true)}>Edit</Button>
          <Button startIcon={<CloudUploadIcon />} onClick={() => setDeploy(true)}>Deploy</Button>
          <Button startIcon={<LinkIcon />} disabled={!c.data} onClick={() => setConnect(true)}>Connect</Button>
          <Button startIcon={<ContentCopyIcon />} disabled={!c.data} href={c.data ? `${hashHref("kubernetes", "clusters", "create")}?name=${encodeURIComponent(name)}&region=${encodeURIComponent(location)}&network=${encodeURIComponent(c.data.network || "default")}&channel=${encodeURIComponent((c.data.releaseChannel || {}).channel || "REGULAR")}` : undefined}>Duplicate</Button>
          <Button startIcon={<DeleteIcon />} disabled={!c.data} onClick={() => setDel(true)}>Delete</Button>
          <Button startIcon={<RefreshIcon />} onClick={c.reload}>Refresh</Button>
        </>} />
      {c.error ? <ErrorAlert error={c.error} title="Failed to load cluster" /> : (
        <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1.5 }}>
          <Typography variant="h2" component="h2" sx={{ fontSize: 22 }}>{name}</Typography>
          {c.data && <Chip size="small" label={api.statusLabel(c.data.status)} color={c.data.status === "RUNNING" ? "success" : c.data.status === "ERROR" ? "error" : "default"} />}
        </Stack>
      )}
      <Tabs value={tab} onChange={(_, t) => { location_.hash = (hashHref("kubernetes", "clusters", location, name) + (t === "details" ? "" : `?tab=${t}`)).slice(1); }}
        sx={{ borderBottom: 1, borderColor: "divider", mb: 2.5 }} aria-label="Cluster tabs">
        {TABS.map(([id, label]) => <Tab key={id} value={id} label={label} />)}
      </Tabs>
      {tab !== "details" && !c.data && !c.error && <Typography variant="body2" color="text.secondary">Loading…</Typography>}
      {tab === "details" && c.data && <Details cluster={c.data} location={location} />}
      {tab === "nodes" && c.data && <Nodes cluster={c.data} location={location} reload={c.reload} />}
      {tab === "storage" && c.data && <ClusterStorage location={location} cluster={c.data.name} />}
      {tab === "observability" && c.data && <ClusterObservability location={location} cluster={c.data.name} />}
      {tab === "logs" && c.data && <Logs location={location} name={name} />}
      {c.data && <EditDialog open={edit} onClose={() => setEdit(false)} cluster={c.data} location={location} reload={c.reload} />}
      <DeployDialog open={deploy} onClose={() => setDeploy(false)} cluster={c.data?.name} location={location} onDeployed={() => notify.success("Workload deployed")} />
      <ConnectDialog open={connect} onClose={() => setConnect(false)} cluster={c.data && { ...c.data, location_name: location }} />
      <DeleteDialog open={del} onClose={() => setDel(false)} title="Delete cluster?" confirmText={name}
        warning="Deleting a cluster deletes all its node pools. This can't be undone."
        onConfirm={async () => { await api.deleteCluster(location, name); notify.success(`Deleted cluster "${name}"`); location_.hash = hashHref("kubernetes", "clusters").slice(1); }}>
        <Typography variant="body2">Cluster <b>{name}</b> will be permanently deleted.</Typography>
      </DeleteDialog>
    </>
  );
}

// ── Details ─────────────────────────────────────────────────────────────────────────────
function Details({ cluster: cl, location }) {
  const auto = (cl.autopilot || {}).enabled;
  const notify = useNotify();
  const project = useProject();
  const memberships = useAsync(() => api.listMemberships(), [cl.name]);
  const membership = api.findMembership(memberships.data || [], project, location, cl.name);
  const [busy, setBusy] = useState(false);
  const toggleFleet = async () => {
    setBusy(true);
    try {
      if (membership) { await api.deleteMembership(api.membershipId(membership)); notify.success("Removed from fleet"); }
      else { await api.createMembership(`${cl.name}-member`, location, cl.name); notify.success("Registered to fleet"); }
      memberships.reload();
    } catch (e) { notify.error(e); } finally { setBusy(false); }
  };
  return (
    <Stack spacing={2}>
      <Section title="Cluster basics">
        <KeyValue items={[
          ["Name", cl.name],
          ["Location type", auto || (cl.locations || []).length > 1 ? "Regional" : "Zonal"],
          ["Region", cl.zone],
          ["Release channel", api.channelLabel((cl.releaseChannel || {}).channel)],
          ["Version", cl.currentMasterVersion],
          ["Total size", `${cl.currentNodeCount} node${cl.currentNodeCount === 1 ? "" : "s"}`],
          ["Endpoint", cl.endpoint],
          ["Mode", auto ? "Autopilot" : "Standard"],
          ["Fleet membership", membership ? "Registered" : "Not registered",
            <Button size="small" disabled={busy || memberships.loading} onClick={toggleFleet}>{membership ? "Unregister" : "Register to fleet"}</Button>],
        ]} />
      </Section>
      <Section title="Networking">
        <KeyValue items={[
          ["Network", cl.network],
          ["Subnet", cl.subnetwork],
          ["Cluster pod IPv4 range", cl.clusterIpv4Cidr],
          ["Service IPv4 range", cl.servicesIpv4Cidr],
          ["Control plane access", api.controlPlaneAccessLabel(cl), <CapabilityBadge id="gcp.kubernetes.cluster.private-networking" />],
          ["DNS endpoint", (cl.controlPlaneEndpointsConfig?.dnsEndpointConfig || {}).endpoint],
        ]} />
      </Section>
    </Stack>
  );
}

// ── Logs (real GKE control-plane operations for this cluster — see the capability's
// limitations for what this doesn't cover) ────────────────────────────────────────────────
function Logs({ location, name }) {
  const ops = useAsync(() => api.listOperations(location), [location, name]);
  const rows = (ops.data || []).filter((o) => (o.targetLink || "").includes(`/clusters/${name}`))
    .sort((a, b) => (b.startTime || "").localeCompare(a.startTime || ""));
  return (
    <CapabilityContainer id="gcp.kubernetes.logs" title="Logs">
      <ErrorAlert error={ops.error} title="Failed to load operations" />
      <ResourceTable
        resourceName="operations"
        items={rows}
        rowKey={(o) => o.name}
        loading={ops.loading}
        dense
        columns={[
          { id: "type", header: "Operation", cell: (o) => o.operationType },
          { id: "target", header: "Target", cell: (o) => o.targetLink?.split("/v1/")[1] },
          { id: "status", header: "Status", cell: (o) => <Chip size="small" label={o.status} color={o.status === "DONE" ? "success" : "default"} /> },
          { id: "time", header: "Time", cell: (o) => o.startTime },
        ]}
        empty={<Typography variant="body2" color="text.secondary">No control-plane operations recorded for this cluster yet.</Typography>}
      />
    </CapabilityContainer>
  );
}

// ── Nodes ────────────────────────────────────────────────────────────────────────────────
function Nodes({ cluster: cl, location, reload }) {
  const notify = useNotify();
  const [add, setAdd] = useState(false);
  const pools = cl.nodePools || [];
  const autopilot = !!(cl.autopilot || {}).enabled;
  const nodes = useAsync(() => api.listK8sNodes(location, cl.name), [location, cl.name, cl.currentNodeCount]);
  if (autopilot) {
    return (
      <Stack spacing={2}>
        <Typography variant="h3" component="h2">Node pools</Typography>
        <Typography variant="body2" color="text.secondary">Autopilot manages node pools automatically — there's nothing to add, resize or delete.</Typography>
      </Stack>
    );
  }
  return (
    <Stack spacing={2}>
      <Stack direction="row" alignItems="center" spacing={1}>
        <Typography variant="h3" component="h2" sx={{ flex: 1 }}>Node pools</Typography>
        <Button startIcon={<AddIcon />} onClick={() => setAdd(true)}>Add node pool</Button>
      </Stack>
      <Box>
        <ResourceTable
          resourceName="node pools"
          items={pools}
          rowKey={(p) => p.name}
          dense
          columns={[
            { id: "name", header: "Name", sortField: "name", cell: (p) => p.name },
            { id: "status", header: "Status", cell: (p) => <Chip size="small" label={api.statusLabel(p.status)} color="success" /> },
            { id: "version", header: "Version", cell: (p) => p.version },
            { id: "nodes", header: "Number of nodes", sortValue: (p) => p.initialNodeCount, cell: (p) => p.initialNodeCount },
            { id: "machine", header: "Machine type", cell: (p) => p.config?.machineType },
            { id: "image", header: "Image type", cell: (p) => p.config?.imageType },
            { id: "autoscaling", header: "Autoscaling", cell: (p) => p.autoscaling?.enabled ? `${p.autoscaling.minNodeCount}–${p.autoscaling.maxNodeCount} nodes` : "Disabled" },
            { id: "del", header: "", cell: (p) => (
              <IconButton size="small" aria-label={`Delete node pool ${p.name}`} disabled={pools.length === 1}
                onClick={async () => { try { await api.deleteNodePool(location, cl.name, p.name); notify.success(`Deleted node pool "${p.name}"`); reload(); } catch (e) { notify.error(e); } }}>
                <DeleteIcon fontSize="small" />
              </IconButton>
            ) },
          ]}
        />
      </Box>
      <Typography variant="h3" component="h2">Nodes</Typography>
      <ErrorAlert error={nodes.error} title="Failed to load nodes" />
      <ResourceTable
        resourceName="nodes"
        items={nodes.data || []}
        rowKey={(n) => n.metadata.name}
        loading={nodes.loading}
        dense
        columns={[
          { id: "name", header: "Name", cell: (n) => n.metadata.name },
          { id: "status", header: "Status", cell: (n) => <Chip size="small" label={n.status.conditions[0].status === "True" ? "Ready" : "NotReady"} color="success" /> },
          { id: "pool", header: "Node pool", cell: (n) => n.metadata.labels["cloud.google.com/gke-nodepool"] },
          { id: "cpu", header: "CPU requested", cell: (n) => `${n.status.allocatable.cpu} allocatable` },
          { id: "memory", header: "Memory requested", cell: (n) => `${n.status.allocatable.memory} allocatable` },
          { id: "storage", header: "Storage requested", cell: () => "—" },
        ]}
        empty={<Typography variant="body2" color="text.secondary">No nodes yet.</Typography>}
      />
      {add && <AddPoolDialog onClose={() => setAdd(false)} onSave={async (pool) => {
        await api.createNodePool(location, cl.name, pool); notify.success(`Added node pool "${pool.name}"`); reload();
      }} />}
    </Stack>
  );
}

// ── Storage (this cluster's real StorageClasses + PersistentVolumeClaims) ─────────────────
function ClusterStorage({ location, cluster }) {
  const scs = useAsync(() => api.listStorageClasses(location, cluster), [location, cluster]);
  const pvcs = useAsync(() => api.listPvcs(location, cluster), [location, cluster]);
  return (
    <Stack spacing={2}>
      <Section title={<Stack direction="row" spacing={1} alignItems="center"><span>Storage classes</span><CapabilityBadge id="gcp.kubernetes.storage" /></Stack>}>
        <ResourceTable resourceName="storage classes" items={scs.data || []} rowKey={(o) => o.metadata.name} loading={scs.loading} dense
          columns={[
            { id: "name", header: "Name", cell: (o) => o.metadata.name },
            { id: "provisioner", header: "Provisioner", cell: (o) => o.provisioner },
            { id: "default", header: "Default", cell: (o) => (o.metadata.annotations?.["storageclass.kubernetes.io/is-default-class"] === "true" ? "Yes" : "") },
          ]} />
      </Section>
      <Section title="Persistent volume claims">
        <ResourceTable resourceName="persistent volume claims" items={pvcs.data || []} rowKey={(o) => `${o.metadata.namespace}/${o.metadata.name}`} loading={pvcs.loading} dense
          columns={[
            { id: "name", header: "Name", cell: (o) => o.metadata.name },
            { id: "status", header: "Status", cell: (o) => o.status.phase },
            { id: "capacity", header: "Capacity", cell: (o) => o.status.capacity?.storage },
            { id: "class", header: "Storage class", cell: (o) => o.spec.storageClassName },
            { id: "ns", header: "Namespace", cell: (o) => o.metadata.namespace },
          ]}
          empty={<Typography variant="body2" color="text.secondary">No persistent volume claims in this cluster yet.</Typography>} />
      </Section>
    </Stack>
  );
}

// ── Observability (real, derived-only resource/cost rollup — see capability notes) ────────
function ClusterObservability({ location, cluster }) {
  const obs = useAsync(() => api.getObservability(location, cluster), [location, cluster]);
  if (obs.loading) return <Typography variant="body2" color="text.secondary">Loading…</Typography>;
  if (!obs.data) return <ErrorAlert error={obs.error} title="Failed to load observability data" />;
  const o = obs.data;
  return (
    <CapabilityContainer id="gcp.kubernetes.observability" title="Observability">
      <Stack spacing={2}>
        <KeyValue items={[
          ["Namespaces", o.namespaces], ["Workloads", o.workloads], ["Pods", o.pods],
          ["Services", o.services], ["Secrets", o.secrets], ["ConfigMaps", o.configmaps],
        ]} />
        <Typography variant="h3" component="h2" sx={{ fontSize: 16 }}>Cost optimization: requested vs. allocatable</Typography>
        <KeyValue items={[
          ["CPU requested / allocatable", `${o.requestedCpu} / ${o.allocatableCpu} vCPU (${o.cpuUtilizationPct}%)`],
          ["Memory requested / allocatable", `${o.requestedMemoryMi} / ${o.allocatableMemoryMi} Mi (${o.memoryUtilizationPct}%)`],
        ]} />
      </Stack>
    </CapabilityContainer>
  );
}

const IMAGE_TYPES = ["COS_CONTAINERD", "UBUNTU_CONTAINERD", "COS", "UBUNTU"];

function AddPoolDialog({ onClose, onSave }) {
  const [name, setName] = useState("");
  const [count, setCount] = useState("3");
  const [machine, setMachine] = useState("e2-medium");
  const [image, setImage] = useState("COS_CONTAINERD");
  const [autoscale, setAutoscale] = useState(false);
  const [min, setMin] = useState("1");
  const [max, setMax] = useState("5");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const ok = /^[a-z]([-a-z0-9]{0,38}[a-z0-9])?$/.test(name) && Number.isInteger(Number(count)) && Number(count) >= 0;
  const save = async () => {
    setBusy(true); setError(null);
    try {
      await onSave({
        name, initialNodeCount: Number(count), config: { machineType: machine, imageType: image },
        ...(autoscale ? { autoscaling: { enabled: true, minNodeCount: Number(min), maxNodeCount: Number(max) } } : {}),
      });
      onClose();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Dialog open onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth aria-labelledby="pool-title">
      <DialogTitle id="pool-title">Add node pool</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField label="Name" value={name} onChange={(e) => setName(e.target.value.trim())} inputProps={{ "aria-label": "Node pool name" }} helperText="Lowercase letters, numbers and hyphens." />
          <TextField label="Number of nodes" type="number" value={count} onChange={(e) => setCount(e.target.value)} />
          <TextField label="Machine type" value={machine} onChange={(e) => setMachine(e.target.value)} />
          <FormControl>
            <InputLabel id="img-l">Image type</InputLabel>
            <Select labelId="img-l" label="Image type" value={image} onChange={(e) => setImage(e.target.value)}>
              {IMAGE_TYPES.map((v) => <MenuItem key={v} value={v}>{v}</MenuItem>)}
            </Select>
          </FormControl>
          <FormControlLabel control={<Checkbox checked={autoscale} onChange={(e) => setAutoscale(e.target.checked)} />} label="Enable autoscaling" />
          {autoscale && <Stack direction="row" spacing={1}>
            <TextField label="Minimum nodes" type="number" value={min} onChange={(e) => setMin(e.target.value)} />
            <TextField label="Maximum nodes" type="number" value={max} onChange={(e) => setMax(e.target.value)} />
          </Stack>}
          {error && <Alert severity="error">{error.message}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy || !ok} onClick={save}>Add</Button>
      </DialogActions>
    </Dialog>
  );
}

// ── Edit ─────────────────────────────────────────────────────────────────────────────────
function EditDialog({ open, onClose, cluster: cl, location, reload }) {
  const notify = useNotify();
  const [rows, setRows] = useState(() => Object.entries(cl.resourceLabels || {}).map(([key, value]) => ({ key, value })));
  const [channel, setChannel] = useState((cl.releaseChannel || {}).channel || "REGULAR");
  const cpe = cl.controlPlaneEndpointsConfig || {};
  const [dnsAccess, setDnsAccess] = useState((cpe.dnsEndpointConfig || {}).allowExternalTraffic !== false);
  const [ipv4Access, setIpv4Access] = useState((cpe.ipEndpointsConfig || {}).enabled !== false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const bad = rows.some((r) => !/^[a-z][a-z0-9_-]{0,62}$/.test(r.key));
  const noAccess = !dnsAccess && !ipv4Access;
  const save = async () => {
    setBusy(true); setError(null);
    try {
      await api.setResourceLabels(location, cl.name, Object.fromEntries(rows.map((r) => [r.key, r.value])), cl.labelFingerprint);
      if (channel !== (cl.releaseChannel || {}).channel) await api.updateCluster(location, cl.name, { desiredReleaseChannel: { channel } });
      if (dnsAccess !== (cpe.dnsEndpointConfig || {}).allowExternalTraffic || ipv4Access !== (cpe.ipEndpointsConfig || {}).enabled) {
        await api.updateCluster(location, cl.name, {
          desiredControlPlaneEndpointsConfig: { dnsEndpointConfig: { allowExternalTraffic: dnsAccess }, ipEndpointsConfig: { enabled: ipv4Access } },
        });
      }
      notify.success("Cluster settings saved");
      reload(); onClose();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth aria-labelledby="edit-title">
      <DialogTitle id="edit-title">Edit cluster</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <Typography variant="body2" sx={{ fontWeight: 500 }}>Release channel</Typography>
          <RadioGroup value={channel} onChange={(e) => setChannel(e.target.value)}>
            {api.CHANNELS.map(([v, l]) => <FormControlLabel key={v} value={v} control={<Radio size="small" />} label={l} />)}
          </RadioGroup>
          <Typography variant="body2" sx={{ fontWeight: 500 }}>Control plane access</Typography>
          <Stack spacing={0.5}>
            <FormControlLabel control={<Checkbox checked={dnsAccess} onChange={(e) => setDnsAccess(e.target.checked)} inputProps={{ "aria-label": "Access using DNS" }} />} label="Access using DNS" />
            <FormControlLabel control={<Checkbox checked={ipv4Access} onChange={(e) => setIpv4Access(e.target.checked)} inputProps={{ "aria-label": "Access using IPv4 addresses" }} />} label="Access using IPv4 addresses" />
            {noAccess && <Typography variant="body2" color="error">At least one access method must be enabled.</Typography>}
          </Stack>
          <Typography variant="body2" sx={{ fontWeight: 500 }}>Labels</Typography>
          {rows.map((r, i) => (
            <Stack key={i} direction="row" spacing={1} alignItems="center">
              <TextField label={`Key ${i + 1}`} value={r.key} onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, key: e.target.value } : x))} />
              <TextField label={`Value ${i + 1}`} value={r.value} onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, value: e.target.value } : x))} />
              <IconButton aria-label={`Delete label ${i + 1}`} onClick={() => setRows(rows.filter((_, j) => j !== i))}><DeleteIcon fontSize="small" /></IconButton>
            </Stack>
          ))}
          <Box><Button startIcon={<AddIcon />} onClick={() => setRows([...rows, { key: "", value: "" }])}>Add label</Button></Box>
          {error && <Alert severity="error">{error.message}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy || bad || noAccess} onClick={save}>Save</Button>
      </DialogActions>
    </Dialog>
  );
}
