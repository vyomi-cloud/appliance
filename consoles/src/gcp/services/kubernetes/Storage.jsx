/* Kubernetes Storage — StorageClasses (the real defaults every GKE cluster ships) and
 * PersistentVolumeClaims (bind instantly to an auto-provisioned PersistentVolume) across
 * every cluster, over the data plane bridge (core/gcp_gke_dataplane_core.py). */
import { useState } from "react";
import {
  Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, FormControl,
  InputLabel, MenuItem, Select, Stack, TextField, Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, PageHeader, Section } from "../../kit/common.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import * as api from "./api.js";

const pvcKey = (o) => `${o._location}/${o._cluster}/${o.metadata.namespace}/${o.metadata.name}`;
const scKey = (o) => `${o._location}/${o._cluster}/${o.metadata.name}`;

async function listStorageClasses() {
  return api.overAllClusters(api.listStorageClasses);
}

export default function Storage() {
  const notify = useNotify();
  const [create, setCreate] = useState(false);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const scs = useAsync(listStorageClasses, []);
  const pvcs = useAsync(() => api.overAllClusters(api.listPvcs), []);
  const data = pvcs.data || [];
  const byKey = (k) => data.find((o) => pvcKey(o) === k);

  return (
    <>
      <PageHeader title="Storage" />
      <Stack spacing={2.5}>
        <Section title={<Stack direction="row" spacing={1} alignItems="center"><span>Storage classes</span><CapabilityBadge id="gcp.kubernetes.storage" /></Stack>}
          description="Every cluster ships these StorageClasses the moment it comes up.">
          <ErrorAlert error={scs.error} title="Failed to load storage classes" />
          <ResourceTable
            resourceName="storage classes"
            items={scs.data || []}
            rowKey={scKey}
            loading={scs.loading}
            dense
            filterPlaceholder="Filter"
            columns={[
              { id: "name", header: "Name", sortField: "metadata.name", cell: (o) => o.metadata.name },
              { id: "provisioner", header: "Provisioner", cell: (o) => o.provisioner },
              { id: "default", header: "Default", cell: (o) => (o.metadata.annotations?.["storageclass.kubernetes.io/is-default-class"] === "true" ? "Yes" : "") },
              { id: "cluster", header: "Cluster", cell: (o) => o._cluster },
            ]}
          />
        </Section>
        <Section title="Persistent volume claims" actions={<>
          <Button size="small" startIcon={<AddIcon />} onClick={() => setCreate(true)}>Create</Button>
          <Button size="small" startIcon={<RefreshIcon />} onClick={pvcs.reload}>Refresh</Button>
          <Button size="small" startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
        </>}>
          <ErrorAlert error={pvcs.error} title="Failed to load PersistentVolumeClaims" />
          <ResourceTable
            resourceName="persistent volume claims"
            items={data}
            rowKey={pvcKey}
            loading={pvcs.loading}
            selectable
            selected={sel}
            onSelectedChange={setSel}
            filterPlaceholder="Filter"
            columns={[
              { id: "name", header: "Name", sortField: "metadata.name", cell: (o) => o.metadata.name },
              { id: "status", header: "Status", cell: (o) => o.status.phase },
              { id: "capacity", header: "Capacity", cell: (o) => o.status.capacity?.storage },
              { id: "class", header: "Storage class", cell: (o) => o.spec.storageClassName },
              { id: "ns", header: "Namespace", cell: (o) => o.metadata.namespace },
              { id: "cluster", header: "Cluster", cell: (o) => o._cluster },
            ]}
            empty={<Typography variant="body2" color="text.secondary">No persistent volume claims yet.</Typography>}
          />
        </Section>
      </Stack>
      {create && <CreateDialog onClose={() => setCreate(false)} onSaved={() => { notify.success("Persistent volume claim created"); pvcs.reload(); }} />}
      <DeleteDialog
        open={del}
        onClose={() => setDel(false)}
        title={sel.length === 1 ? "Delete claim?" : `Delete ${sel.length} claims?`}
        confirmText={sel.length === 1 ? byKey(sel[0])?.metadata.name : "DELETE"}
        warning="Deleting a claim reclaims its PersistentVolume. This can't be undone."
        onConfirm={async () => {
          for (const k of sel) {
            const o = byKey(k);
            if (o) await api.deletePvc(o._location, o._cluster, o.metadata.namespace, o.metadata.name);
          }
          notify.success(sel.length === 1 ? "Deleted" : `Deleted ${sel.length} claims`);
          setSel([]); pvcs.reload();
        }}
      >
        <Typography variant="body2">{sel.map((k) => byKey(k)?.metadata.name).join(", ")} will be permanently deleted.</Typography>
      </DeleteDialog>
    </>
  );
}

function CreateDialog({ onClose, onSaved }) {
  const clusters = useAsync(() => api.listClusters(), []);
  const [cluster, setCluster] = useState("");
  const [ns, setNs] = useState("default");
  const [name, setName] = useState("");
  const [size, setSize] = useState("10Gi");
  const [storageClass, setStorageClass] = useState("standard-rwo");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const cl = (clusters.data || []).find((c) => c.name === cluster);
  const ok = cl && /^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$/.test(name) && api.validNsName(ns) === null && /^\d+[GMT]i$/.test(size);

  const save = async () => {
    setBusy(true); setError(null);
    try {
      await api.createPvc(cl.location, cl.name, ns, {
        metadata: { name },
        spec: { storageClassName: storageClass, accessModes: ["ReadWriteOnce"], resources: { requests: { storage: size } } },
      });
      onSaved(); onClose();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <Dialog open onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth aria-labelledby="pvc-title">
      <DialogTitle id="pvc-title">Create persistent volume claim</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <FormControl disabled={!(clusters.data || []).length}>
            <InputLabel id="pvc-cluster-l">Cluster</InputLabel>
            <Select labelId="pvc-cluster-l" label="Cluster" value={cluster} onChange={(e) => setCluster(e.target.value)} inputProps={{ "aria-label": "Cluster" }}>
              {(clusters.data || []).map((c) => <MenuItem key={`${c.location}/${c.name}`} value={c.name}>{c.name} ({c.location})</MenuItem>)}
            </Select>
          </FormControl>
          <TextField label="Namespace" value={ns} onChange={(e) => setNs(e.target.value.trim())} inputProps={{ "aria-label": "Namespace" }} />
          <TextField label="Name" value={name} onChange={(e) => setName(e.target.value.trim())} inputProps={{ "aria-label": "Name" }} />
          <TextField label="Size" value={size} onChange={(e) => setSize(e.target.value.trim())} helperText="e.g. 10Gi" inputProps={{ "aria-label": "Size" }} />
          <FormControl>
            <InputLabel id="pvc-class-l">Storage class</InputLabel>
            <Select labelId="pvc-class-l" label="Storage class" value={storageClass} onChange={(e) => setStorageClass(e.target.value)} inputProps={{ "aria-label": "Storage class" }}>
              <MenuItem value="standard-rwo">standard-rwo</MenuItem>
              <MenuItem value="premium-rwo">premium-rwo</MenuItem>
              <MenuItem value="standard">standard</MenuItem>
            </Select>
          </FormControl>
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
