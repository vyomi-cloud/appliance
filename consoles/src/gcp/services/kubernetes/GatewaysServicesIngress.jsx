/* Gateways, Services & Ingress — real Kubernetes networking objects across every cluster,
 * over the data plane bridge (core/gcp_gke_dataplane_core.py). */
import { useState } from "react";
import {
  Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, FormControl,
  InputLabel, MenuItem, Select, Stack, Tab, Tabs, TextField, Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, PageHeader } from "../../kit/common.jsx";
import * as api from "./api.js";

const TABS = [
  ["gateways", "Gateways", api.listGateways, api.deleteGateway, (g) => g.spec.gatewayClassName],
  ["services", "Services", api.listServices, api.deleteService, (s) => s.spec.type],
  ["ingress", "Ingress", api.listIngresses, api.deleteIngress, () => "Ingress"],
];
const rowKey = (o) => `${o._location}/${o._cluster}/${o.metadata.namespace}/${o.metadata.name}`;
const endpointsOf = (o) => o._endpoints ?? "—";

export default function GatewaysServicesIngress() {
  const [tab, setTab] = useState("gateways");
  const [create, setCreate] = useState(false);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const notify = useNotify();
  const [, label, listFn, deleteFn, typeOf] = TABS.find(([id]) => id === tab);
  const list = useAsync(() => api.overAllClusters(listFn), [tab]);
  const data = list.data || [];
  const byKey = (k) => data.find((o) => rowKey(o) === k);

  return (
    <>
      <PageHeader title="Gateways, Services & Ingress" actions={<>
        <Button startIcon={<AddIcon />} onClick={() => setCreate(true)}>Create</Button>
        <Button startIcon={<RefreshIcon />} onClick={list.reload}>Refresh</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
      </>} />
      <Tabs value={tab} onChange={(_, t) => { setTab(t); setSel([]); }} sx={{ borderBottom: 1, borderColor: "divider", mb: 2.5 }} aria-label="Discovery tabs">
        {TABS.map(([id, l]) => <Tab key={id} value={id} label={l} />)}
      </Tabs>
      <ErrorAlert error={list.error} title={`Failed to load ${label.toLowerCase()}`} />
      <ResourceTable
        resourceName={label.toLowerCase()}
        items={data}
        rowKey={rowKey}
        loading={list.loading}
        selectable
        selected={sel}
        onSelectedChange={setSel}
        filterPlaceholder="Filter"
        columns={[
          { id: "name", header: "Name", sortField: "metadata.name", cell: (o) => o.metadata.name },
          { id: "status", header: "Status", cell: () => "OK" },
          { id: "type", header: "Type", cell: (o) => typeOf(o) },
          { id: "endpoints", header: "Endpoints", cell: (o) => endpointsOf(o) },
          { id: "pods", header: "Pods", cell: (o) => endpointsOf(o) },
          { id: "ns", header: "Namespace", cell: (o) => o.metadata.namespace },
          { id: "cluster", header: "Cluster", cell: (o) => o._cluster },
        ]}
        empty={<Typography variant="body2" color="text.secondary">No {label.toLowerCase()} yet.</Typography>}
      />
      {create && <CreateDialog kind={tab} onClose={() => setCreate(false)} onSaved={() => { notify.success(`${label} created`); list.reload(); }} />}
      <DeleteDialog
        open={del}
        onClose={() => setDel(false)}
        title={sel.length === 1 ? "Delete object?" : `Delete ${sel.length} objects?`}
        confirmText={sel.length === 1 ? byKey(sel[0])?.metadata.name : "DELETE"}
        onConfirm={async () => {
          for (const k of sel) {
            const o = byKey(k);
            if (o) await deleteFn(o._location, o._cluster, o.metadata.namespace, o.metadata.name);
          }
          notify.success(sel.length === 1 ? "Deleted" : `Deleted ${sel.length} objects`);
          setSel([]); list.reload();
        }}
      >
        <Typography variant="body2">{sel.map((k) => byKey(k)?.metadata.name).join(", ")} will be permanently deleted.</Typography>
      </DeleteDialog>
    </>
  );
}

function CreateDialog({ kind, onClose, onSaved }) {
  const clusters = useAsync(() => api.listClusters(), []);
  const [cluster, setCluster] = useState("");
  const [ns, setNs] = useState("default");
  const [name, setName] = useState("");
  const [selectorKey, setSelectorKey] = useState("app");
  const [selectorValue, setSelectorValue] = useState("");
  const [port, setPort] = useState("80");
  const [svcType, setSvcType] = useState("ClusterIP");
  const [backendService, setBackendService] = useState("");
  const [host, setHost] = useState("");
  const [gatewayClass, setGatewayClass] = useState("gke-l7-global-external-managed");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const cl = (clusters.data || []).find((c) => c.name === cluster);
  const ok = cl && /^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$/.test(name) &&
    (kind === "services" ? selectorKey && selectorValue && port : kind === "ingress" ? backendService : gatewayClass);

  const save = async () => {
    setBusy(true); setError(null);
    try {
      if (kind === "services") {
        await api.createService(cl.location, cl.name, ns, {
          metadata: { name }, spec: { selector: { [selectorKey]: selectorValue }, ports: [{ port: Number(port), targetPort: Number(port) }], type: svcType },
        });
      } else if (kind === "ingress") {
        await api.createIngress(cl.location, cl.name, ns, {
          metadata: { name },
          spec: { rules: [{ ...(host ? { host } : {}), http: { paths: [{ path: "/", pathType: "Prefix", backend: { service: { name: backendService, port: { number: Number(port) } } } }] } }] },
        });
      } else {
        await api.createGateway(cl.location, cl.name, ns, {
          metadata: { name }, spec: { gatewayClassName: gatewayClass, listeners: [{ name: "http", protocol: "HTTP", port: Number(port) }] },
        });
      }
      onSaved(); onClose();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <Dialog open onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth aria-labelledby="discovery-create-title">
      <DialogTitle id="discovery-create-title">Create {kind === "services" ? "Service" : kind === "ingress" ? "Ingress" : "Gateway"}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <FormControl disabled={!(clusters.data || []).length}>
            <InputLabel id="disc-cluster-l">Cluster</InputLabel>
            <Select labelId="disc-cluster-l" label="Cluster" value={cluster} onChange={(e) => setCluster(e.target.value)} inputProps={{ "aria-label": "Cluster" }}>
              {(clusters.data || []).map((c) => <MenuItem key={`${c.location}/${c.name}`} value={c.name}>{c.name} ({c.location})</MenuItem>)}
            </Select>
          </FormControl>
          <TextField label="Namespace" value={ns} onChange={(e) => setNs(e.target.value.trim())} inputProps={{ "aria-label": "Namespace" }} />
          <TextField label="Name" value={name} onChange={(e) => setName(e.target.value.trim())} inputProps={{ "aria-label": "Name" }} />
          {kind === "services" && <>
            <Stack direction="row" spacing={1}>
              <TextField label="Selector key" value={selectorKey} onChange={(e) => setSelectorKey(e.target.value.trim())} />
              <TextField label="Selector value" value={selectorValue} onChange={(e) => setSelectorValue(e.target.value.trim())} />
            </Stack>
            <TextField label="Port" type="number" value={port} onChange={(e) => setPort(e.target.value)} />
            <FormControl>
              <InputLabel id="disc-svctype-l">Type</InputLabel>
              <Select labelId="disc-svctype-l" label="Type" value={svcType} onChange={(e) => setSvcType(e.target.value)} inputProps={{ "aria-label": "Type" }}>
                <MenuItem value="ClusterIP">Cluster IP</MenuItem>
                <MenuItem value="NodePort">Node port</MenuItem>
                <MenuItem value="LoadBalancer">Load balancer</MenuItem>
              </Select>
            </FormControl>
          </>}
          {kind === "ingress" && <>
            <TextField label="Host (optional)" value={host} onChange={(e) => setHost(e.target.value.trim())} />
            <TextField label="Backend service name" value={backendService} onChange={(e) => setBackendService(e.target.value.trim())} helperText="Must already exist in this namespace." />
            <TextField label="Backend service port" type="number" value={port} onChange={(e) => setPort(e.target.value)} />
          </>}
          {kind === "gateways" && <>
            <TextField label="Gateway class" value={gatewayClass} onChange={(e) => setGatewayClass(e.target.value.trim())} />
            <TextField label="Listener port" type="number" value={port} onChange={(e) => setPort(e.target.value)} />
          </>}
          {error && <Alert severity="error">{error.message}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy || !ok} onClick={save}>{busy ? "Creating…" : "Create"}</Button>
      </DialogActions>
    </Dialog>
  );
}
