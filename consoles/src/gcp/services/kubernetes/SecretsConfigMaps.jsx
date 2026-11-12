/* Secrets & ConfigMaps — real Kubernetes-native Secret/ConfigMap objects across every
 * cluster, over the data plane bridge (core/gcp_gke_dataplane_core.py). */
import { useState } from "react";
import {
  Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, FormControl,
  IconButton, InputLabel, MenuItem, Select, Stack, TextField, Typography,
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

const rowKey = (o) => `${o._location}/${o._cluster}/${o.metadata.namespace}/${o.kind}/${o.metadata.name}`;

async function listBoth() {
  const [secrets, configmaps] = await Promise.all([
    api.overAllClusters(api.listSecrets),
    api.overAllClusters(api.listConfigMaps),
  ]);
  return [...secrets, ...configmaps];
}

export default function SecretsConfigMaps() {
  const notify = useNotify();
  const [create, setCreate] = useState(false);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const list = useAsync(listBoth, []);
  const data = list.data || [];
  const byKey = (k) => data.find((o) => rowKey(o) === k);

  return (
    <>
      <PageHeader title="Secrets & ConfigMaps" actions={<>
        <Button startIcon={<AddIcon />} onClick={() => setCreate(true)}>Create</Button>
        <Button startIcon={<RefreshIcon />} onClick={list.reload}>Refresh</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
      </>} />
      <ErrorAlert error={list.error} title="Failed to load secrets and config maps" />
      <ResourceTable
        resourceName="secrets and config maps"
        items={data}
        rowKey={rowKey}
        loading={list.loading}
        selectable
        selected={sel}
        onSelectedChange={setSel}
        filterPlaceholder="Filter"
        columns={[
          { id: "name", header: "Name", sortField: "metadata.name", cell: (o) => o.metadata.name },
          { id: "type", header: "Type", cell: (o) => o.kind === "Secret" ? (o.type || "Opaque") : "ConfigMap" },
          { id: "ns", header: "Namespace", cell: (o) => o.metadata.namespace },
          { id: "cluster", header: "Cluster", cell: (o) => o._cluster },
        ]}
        empty={<Typography variant="body2" color="text.secondary">No secrets or config maps yet.</Typography>}
      />
      {create && <CreateDialog onClose={() => setCreate(false)} onSaved={() => { notify.success("Created"); list.reload(); }} />}
      <DeleteDialog
        open={del}
        onClose={() => setDel(false)}
        title={sel.length === 1 ? "Delete object?" : `Delete ${sel.length} objects?`}
        confirmText={sel.length === 1 ? byKey(sel[0])?.metadata.name : "DELETE"}
        onConfirm={async () => {
          for (const k of sel) {
            const o = byKey(k);
            if (!o) continue;
            const del_ = o.kind === "Secret" ? api.deleteSecret : api.deleteConfigMap;
            await del_(o._location, o._cluster, o.metadata.namespace, o.metadata.name);
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

function CreateDialog({ onClose, onSaved }) {
  const clusters = useAsync(() => api.listClusters(), []);
  const [kind, setKind] = useState("Secret");
  const [cluster, setCluster] = useState("");
  const [ns, setNs] = useState("default");
  const [name, setName] = useState("");
  const [rows, setRows] = useState([{ key: "", value: "" }]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const cl = (clusters.data || []).find((c) => c.name === cluster);
  const ok = cl && /^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$/.test(name) && api.validNsName(ns) === null && rows.some((r) => r.key);

  const save = async () => {
    setBusy(true); setError(null);
    try {
      const data = Object.fromEntries(rows.filter((r) => r.key).map((r) => [r.key, r.value]));
      if (kind === "Secret") await api.createSecret(cl.location, cl.name, ns, { metadata: { name }, stringData: data });
      else await api.createConfigMap(cl.location, cl.name, ns, { metadata: { name }, data });
      onSaved(); onClose();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <Dialog open onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth aria-labelledby="sec-cm-title">
      <DialogTitle id="sec-cm-title">Create Secret / ConfigMap</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <FormControl>
            <InputLabel id="sec-kind-l">Kind</InputLabel>
            <Select labelId="sec-kind-l" label="Kind" value={kind} onChange={(e) => setKind(e.target.value)} inputProps={{ "aria-label": "Kind" }}>
              <MenuItem value="Secret">Secret</MenuItem>
              <MenuItem value="ConfigMap">ConfigMap</MenuItem>
            </Select>
          </FormControl>
          <FormControl disabled={!(clusters.data || []).length}>
            <InputLabel id="sec-cluster-l">Cluster</InputLabel>
            <Select labelId="sec-cluster-l" label="Cluster" value={cluster} onChange={(e) => setCluster(e.target.value)} inputProps={{ "aria-label": "Cluster" }}>
              {(clusters.data || []).map((c) => <MenuItem key={`${c.location}/${c.name}`} value={c.name}>{c.name} ({c.location})</MenuItem>)}
            </Select>
          </FormControl>
          <TextField label="Namespace" value={ns} onChange={(e) => setNs(e.target.value.trim())} inputProps={{ "aria-label": "Namespace" }} />
          <TextField label="Name" value={name} onChange={(e) => setName(e.target.value.trim())} inputProps={{ "aria-label": "Name" }} />
          <Typography variant="body2" sx={{ fontWeight: 500 }}>Data</Typography>
          {rows.map((r, i) => (
            <Stack key={i} direction="row" spacing={1} alignItems="center">
              <TextField label={`Key ${i + 1}`} value={r.key} onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, key: e.target.value } : x))} />
              <TextField label={`Value ${i + 1}`} value={r.value} onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, value: e.target.value } : x))} type={kind === "Secret" ? "password" : "text"} />
              <IconButton aria-label={`Delete row ${i + 1}`} onClick={() => setRows(rows.filter((_, j) => j !== i))}><DeleteIcon fontSize="small" /></IconButton>
            </Stack>
          ))}
          <Button size="small" startIcon={<AddIcon />} onClick={() => setRows([...rows, { key: "", value: "" }])} sx={{ alignSelf: "flex-start" }}>Add entry</Button>
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
