/* Backup for GKE — backup plans + on-demand backups over the native gkebackup.googleapis.com
 * REST shape (core/gcp_container_core.py: projects.locations.backupPlans[.backups]). A backup
 * plan names a cluster to protect; "Create backup now" snapshots that cluster's control-plane
 * config (node pool shapes, version) into a Backup resource. See
 * core/capabilities/gcp/kubernetes.json's gcp.kubernetes.backup entry for what's limited. */
import { useState } from "react";
import {
  Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, FormControl,
  InputLabel, MenuItem, Select, Stack, TextField, Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import PlayArrowIcon from "@mui/icons-material/esm/PlayArrow.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, PageHeader, Section, fmtBytes, fmtDate } from "../../kit/common.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

const shortId = (full) => (full || "").split("/").pop();
const stateColor = (s) => ({ READY: "success", SUCCEEDED: "success", FAILED: "error" }[s] || "default");

export default function BackupForGke() {
  const notify = useNotify();
  const project = useProject();
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(false);
  const [del, setDel] = useState(false);
  const clusters = useAsync(() => api.listClusters(), [project]);
  const plans = useAsync(() => api.listBackupPlans(), [project]);
  const data = plans.data || [];

  const byKey = (k) => data.find((p) => p.name === k);
  const one = sel.length === 1 ? byKey(sel[0]) : null;
  const clusterName = (full) => clusters.data?.find((c) => `projects/${project}/locations/${c.location}/clusters/${c.name}` === full)?.name || shortId(full);

  const backups = useAsync(() => (one ? api.listBackups(one.name.split("/")[3], shortId(one.name)) : Promise.resolve([])), [one?.name]);

  return (
    <>
      <PageHeader title="Backup for GKE" actions={<>
        <Button startIcon={<AddIcon />} onClick={() => setCreate(true)}>Create backup plan</Button>
        <Button startIcon={<RefreshIcon />} onClick={plans.reload}>Refresh</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
      </>} />
      <ErrorAlert error={plans.error} title="Failed to load backup plans" />
      <ResourceTable
        resourceName="backup plans"
        items={data}
        rowKey={(p) => p.name}
        loading={plans.loading}
        selectable
        selected={sel}
        onSelectedChange={setSel}
        filterPlaceholder="Filter backup plans"
        columns={[
          { id: "name", header: "Name", sortField: "name", cell: (p) => shortId(p.name) },
          { id: "cluster", header: "Cluster", cell: (p) => clusterName(p.cluster) },
          { id: "state", header: "State", cell: (p) => <Chip size="small" label={p.state} color={stateColor(p.state)} /> },
          { id: "pods", header: "Protected pods", cell: (p) => p.protectedPodCount },
          { id: "created", header: "Created", cell: (p) => fmtDate(p.createTime) },
        ]}
        empty={
          <Stack spacing={1.5} alignItems="center">
            <Typography variant="body2" color="text.secondary">There are no backup plans in this project.</Typography>
            <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreate(true)}>Create backup plan</Button>
          </Stack>
        }
      />
      <Box sx={{ mt: 2.5 }}>
        <Section
          title={<Stack direction="row" spacing={1} alignItems="center"><span>Backups</span><CapabilityBadge id="gcp.kubernetes.backup" /></Stack>}
          description={one ? `On-demand backups for plan "${shortId(one.name)}".` : "Select a backup plan above to see its backups."}
          actions={one && <Button size="small" startIcon={<PlayArrowIcon />} onClick={async () => {
            try { await api.createBackup(one.name.split("/")[3], shortId(one.name), `backup-${Date.now().toString(36)}`); notify.success("Backup created"); backups.reload(); plans.reload(); }
            catch (e) { notify.error(e); }
          }}>Create backup now</Button>}
        >
          {one ? (
            <ResourceTable
              resourceName="backups"
              items={backups.data || []}
              rowKey={(b) => b.name}
              loading={backups.loading}
              dense
              columns={[
                { id: "name", header: "Name", cell: (b) => shortId(b.name) },
                { id: "state", header: "State", cell: (b) => <Chip size="small" label={b.state} color={stateColor(b.state)} /> },
                { id: "size", header: "Size", cell: (b) => fmtBytes(b.sizeBytes) },
                { id: "version", header: "Cluster version", cell: (b) => b.clusterMetadata?.k8sVersion },
                { id: "created", header: "Created", cell: (b) => fmtDate(b.createTime) },
                { id: "del", header: "", cell: (b) => (
                  <Button size="small" color="error" aria-label={`Delete backup ${shortId(b.name)}`} onClick={async () => {
                    try { await api.deleteBackup(one.name.split("/")[3], shortId(one.name), shortId(b.name)); notify.success("Backup deleted"); backups.reload(); }
                    catch (e) { notify.error(e); }
                  }}>Delete</Button>
                ) },
              ]}
              empty={<Typography variant="body2" color="text.secondary">No backups yet for this plan.</Typography>}
            />
          ) : <Typography variant="body2" color="text.secondary">No backup plan selected.</Typography>}
        </Section>
      </Box>
      {create && <CreateDialog clusters={clusters.data || []} project={project} onClose={() => setCreate(false)} onSave={async ({ id, cluster, description, retentionDays }) => {
        await api.createBackupPlan(cluster.split("/")[3], id, { cluster, description, retentionPolicy: { backupRetainDays: Number(retentionDays) || 0 } });
        notify.success(`Created backup plan "${id}"`); plans.reload();
      }} />}
      <DeleteDialog
        open={del}
        onClose={() => setDel(false)}
        title={sel.length === 1 ? "Delete backup plan?" : `Delete ${sel.length} backup plans?`}
        confirmText={sel.length === 1 ? shortId(sel[0]) : "DELETE"}
        warning="Deleting a backup plan also deletes every backup it owns. This can't be undone."
        onConfirm={async () => {
          for (const k of sel) { const p = byKey(k); await api.deleteBackupPlan(p.name.split("/")[3], shortId(p.name), true); }
          notify.success(sel.length === 1 ? `Deleted backup plan "${shortId(sel[0])}"` : `Deleted ${sel.length} backup plans`);
          setSel([]); plans.reload();
        }}
      >
        <Typography variant="body2">{sel.map((k) => shortId(k)).join(", ")} will be permanently deleted.</Typography>
      </DeleteDialog>
    </>
  );
}

function CreateDialog({ clusters, project, onClose, onSave }) {
  const [id, setId] = useState("backup-plan-1");
  const [cluster, setCluster] = useState(clusters[0] ? `${clusters[0].name}` : "");
  const [description, setDescription] = useState("");
  const [retentionDays, setRetentionDays] = useState("0");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const ok = /^[a-z]([-a-z0-9]{0,38}[a-z0-9])?$/.test(id) && cluster;

  const save = async () => {
    setBusy(true); setError(null);
    try {
      const c = clusters.find((x) => x.name === cluster);
      await onSave({ id, cluster: `projects/${project}/locations/${c.location}/clusters/${c.name}`, description, retentionDays });
      onClose();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <Dialog open onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth aria-labelledby="backup-plan-title">
      <DialogTitle id="backup-plan-title">Create backup plan</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField label="Name" value={id} onChange={(e) => setId(e.target.value.trim())} inputProps={{ "aria-label": "Name" }} helperText="Lowercase letters, numbers and hyphens." />
          <FormControl disabled={!clusters.length}>
            <InputLabel id="bp-cluster-l">Cluster</InputLabel>
            <Select labelId="bp-cluster-l" label="Cluster" value={cluster} onChange={(e) => setCluster(e.target.value)} inputProps={{ "aria-label": "Cluster" }}>
              {clusters.map((c) => <MenuItem key={`${c.location}/${c.name}`} value={c.name}>{c.name} ({c.location})</MenuItem>)}
            </Select>
          </FormControl>
          {!clusters.length && <Typography variant="body2" color="text.secondary">Create a cluster first — a backup plan needs one to protect.</Typography>}
          <TextField label="Description" value={description} onChange={(e) => setDescription(e.target.value)} multiline minRows={2} inputProps={{ "aria-label": "Description" }} />
          <TextField label="Backup retention (days)" type="number" value={retentionDays} onChange={(e) => setRetentionDays(e.target.value)} helperText="0 keeps backups indefinitely." />
          {error && <Typography variant="body2" color="error">{error.message}</Typography>}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy || !ok} onClick={save}>{busy ? "Creating…" : "Create"}</Button>
      </DialogActions>
    </Dialog>
  );
}
