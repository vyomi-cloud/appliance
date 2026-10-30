/* Cluster details: summary + tabs (Details, Nodes, Storage, Observability, Logs), all on
 * the native Kubernetes Engine REST API. Storage/Observability/Logs need a live Kubernetes
 * API server or Cloud Monitoring data this simulator doesn't generate for GKE — honest gaps. */
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
      {tab === "details" && c.data && <Details cluster={c.data} />}
      {tab === "nodes" && c.data && <Nodes cluster={c.data} location={location} reload={c.reload} />}
      {tab === "storage" && <CapabilityContainer id="gcp.kubernetes.storage" title="Storage" />}
      {tab === "observability" && <CapabilityContainer id="gcp.kubernetes.observability" title="Observability" />}
      {tab === "logs" && <CapabilityContainer id="gcp.kubernetes.logs" title="Logs" />}
      {c.data && <EditDialog open={edit} onClose={() => setEdit(false)} cluster={c.data} location={location} reload={c.reload} />}
      <DeployDialog open={deploy} onClose={() => setDeploy(false)} />
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
function Details({ cluster: cl }) {
  const auto = (cl.autopilot || {}).enabled;
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

// ── Nodes ────────────────────────────────────────────────────────────────────────────────
function Nodes({ cluster: cl, location, reload }) {
  const notify = useNotify();
  const [add, setAdd] = useState(false);
  const pools = cl.nodePools || [];
  const autopilot = !!(cl.autopilot || {}).enabled;
  if (autopilot) {
    return (
      <Stack spacing={2}>
        <Typography variant="h3" component="h2">Node pools</Typography>
        <Typography variant="body2" color="text.secondary">Autopilot manages node pools automatically — there's nothing to add, resize or delete.</Typography>
        <CapabilityContainer id="gcp.kubernetes.cluster.nodes" title="Nodes" />
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
      <CapabilityContainer id="gcp.kubernetes.cluster.nodes" title="Nodes" />
      {add && <AddPoolDialog onClose={() => setAdd(false)} onSave={async (pool) => {
        await api.createNodePool(location, cl.name, pool); notify.success(`Added node pool "${pool.name}"`); reload();
      }} />}
    </Stack>
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
