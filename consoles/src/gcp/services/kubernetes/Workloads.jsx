/* Workloads — Deployments/StatefulSets/Jobs (+ their Pods) across every cluster, over the
 * real Kubernetes data plane (core/gcp_gke_dataplane_core.py's clusters/{c}/k8s/... bridge). */
import { useState } from "react";
import { Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, Stack, TextField, Typography } from "@mui/material";
import CloudUploadIcon from "@mui/icons-material/esm/CloudUpload.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import TuneIcon from "@mui/icons-material/esm/Tune.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, PageHeader } from "../../kit/common.jsx";
import DeployDialog from "./DeployDialog.jsx";
import * as api from "./api.js";

const rowKey = (w) => `${w._location}/${w._cluster}/${w.metadata.namespace}/${w.kind}/${w.metadata.name}`;
const statusOf = (w) => {
  if (w.kind === "Job") return w.status?.conditions?.[0]?.type === "Complete" ? "Complete" : "Running";
  return w.status?.conditions?.[0]?.status === "True" ? "OK" : "Updating";
};

export default function Workloads() {
  const [deploy, setDeploy] = useState(false);
  const [scale, setScale] = useState(null);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const notify = useNotify();
  const list = useAsync(() => api.overAllClusters(api.listWorkloads), []);
  const data = list.data || [];
  const byKey = (k) => data.find((w) => rowKey(w) === k);

  return (
    <>
      <PageHeader title="Workloads" actions={<>
        <Button startIcon={<CloudUploadIcon />} onClick={() => setDeploy(true)}>Deploy</Button>
        <Button startIcon={<RefreshIcon />} onClick={list.reload}>Refresh</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
      </>} />
      <ErrorAlert error={list.error} title="Failed to load workloads" />
      <ResourceTable
        resourceName="workloads"
        items={data}
        rowKey={rowKey}
        loading={list.loading}
        selectable
        selected={sel}
        onSelectedChange={setSel}
        filterPlaceholder="Filter"
        columns={[
          { id: "name", header: "Name", sortField: "metadata.name", cell: (w) => w.metadata.name },
          { id: "status", header: "Status", cell: (w) => <Chip size="small" label={statusOf(w)} color={statusOf(w) === "Updating" ? "default" : "success"} /> },
          { id: "type", header: "Type", cell: (w) => w.kind },
          { id: "pods", header: "Pods", cell: (w) => `${w._podsReady ?? 0}/${w.spec?.replicas ?? w.spec?.completions ?? w._podsReady ?? 0}` },
          { id: "ns", header: "Namespace", cell: (w) => w.metadata.namespace },
          { id: "cluster", header: "Cluster", cell: (w) => w._cluster },
          { id: "scale", header: "", cell: (w) => (w.kind !== "Job" &&
            <Button size="small" startIcon={<TuneIcon fontSize="small" />} onClick={() => setScale(w)}>Scale</Button>) },
        ]}
        empty={<Typography variant="body2" color="text.secondary">No workloads deployed yet.</Typography>}
      />
      <DeployDialog open={deploy} onClose={() => setDeploy(false)} onDeployed={() => { notify.success("Workload deployed"); list.reload(); }} />
      {scale && <ScaleDialog workload={scale} onClose={() => setScale(null)} onSaved={() => { notify.success("Workload scaled"); list.reload(); }} />}
      <DeleteDialog
        open={del}
        onClose={() => setDel(false)}
        title={sel.length === 1 ? "Delete workload?" : `Delete ${sel.length} workloads?`}
        confirmText={sel.length === 1 ? byKey(sel[0])?.metadata.name : "DELETE"}
        onConfirm={async () => {
          for (const k of sel) {
            const w = byKey(k);
            if (w) await api.deleteWorkload(w._location, w._cluster, w.kind, w.metadata.namespace, w.metadata.name);
          }
          notify.success(sel.length === 1 ? "Deleted workload" : `Deleted ${sel.length} workloads`);
          setSel([]); list.reload();
        }}
      >
        <Typography variant="body2">{sel.map((k) => byKey(k)?.metadata.name).join(", ")} and its pods will be permanently deleted.</Typography>
      </DeleteDialog>
    </>
  );
}

function ScaleDialog({ workload, onClose, onSaved }) {
  const [replicas, setReplicas] = useState(String(workload.spec?.replicas ?? 1));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const plural = workload.kind === "Deployment" ? "deployments" : "statefulsets";
  const save = async () => {
    setBusy(true); setError(null);
    try {
      await api.scaleWorkload(workload._location, workload._cluster, plural, workload.metadata.namespace, workload.metadata.name, Number(replicas));
      onSaved(); onClose();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Dialog open onClose={busy ? undefined : onClose} maxWidth="xs" fullWidth aria-labelledby="scale-title">
      <DialogTitle id="scale-title">Scale {workload.metadata.name}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField label="Replicas" type="number" value={replicas} onChange={(e) => setReplicas(e.target.value)} inputProps={{ "aria-label": "Replicas" }} autoFocus />
          {error && <Typography variant="body2" color="error">{error.message}</Typography>}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy} onClick={save}>{busy ? "Saving…" : "Save"}</Button>
      </DialogActions>
    </Dialog>
  );
}
