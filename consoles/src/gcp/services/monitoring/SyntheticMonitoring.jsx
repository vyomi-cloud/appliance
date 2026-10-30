/* Synthetic monitoring — a real UptimeCheckConfig whose check type is synthetic_monitor
 * (a Cloud Functions v2 target) instead of http_check/tcp_check. Vyomi has no Cloud
 * Functions execution runtime, so run status/success rate/latency are an honest gap; see
 * gcp.monitoring.synthetic-monitors. */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, Menu, MenuItem, Stack, TextField, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import MoreVertIcon from "@mui/icons-material/esm/MoreVert.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { PageHeader } from "../../kit/common.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

function CreateDialog({ open, onClose, onCreated }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [fn, setFn] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>Create Synthetic Monitor</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <TextField autoFocus label="Display name" value={name} onChange={(e) => setName(e.target.value)} />
          <TextField label="Cloud Function (v2) name" placeholder="projects/p/locations/us-central1/functions/check" value={fn} onChange={(e) => setFn(e.target.value)} />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" disabled={!name.trim() || !fn.trim() || busy} onClick={async () => {
          setBusy(true);
          await api.createUptimeCheck({
            displayName: name, monitoredResource: { type: "uptime_url", labels: { host: "synthetic" } },
            syntheticMonitor: { cloudFunctionV2: { name: fn } }, period: "300s", timeout: "10s",
          });
          notify.success(`Created synthetic monitor "${name}"`);
          setBusy(false); onCreated();
        }}>Create</Button>
      </DialogActions>
    </Dialog>
  );
}

function RowMenu({ mon, onDeleted }) {
  const notify = useNotify();
  const [anchor, setAnchor] = useState(null);
  const [del, setDel] = useState(false);
  const id = mon.name.split("/").pop();
  return (
    <>
      <IconButton size="small" aria-label={`Actions for ${mon.displayName}`} onClick={(e) => setAnchor(e.currentTarget)}><MoreVertIcon fontSize="small" /></IconButton>
      <Menu anchorEl={anchor} open={!!anchor} onClose={() => setAnchor(null)}>
        <MenuItem onClick={() => { setAnchor(null); setDel(true); }}>Delete</MenuItem>
      </Menu>
      <DeleteDialog open={del} onClose={() => setDel(false)} title="Delete synthetic monitor?" confirmText={mon.displayName}
        onConfirm={async () => { await api.deleteUptimeCheck(id); notify.success(`Deleted synthetic monitor "${mon.displayName}"`); onDeleted(); }}>
        <Typography variant="body2">Synthetic monitor <b>{mon.displayName}</b> will be permanently deleted.</Typography>
      </DeleteDialog>
    </>
  );
}

export default function SyntheticMonitoring() {
  const project = useProject();
  const [createOpen, setCreateOpen] = useState(false);
  const { data, loading, error, reload } = useAsync(async () => ({ checks: await api.listUptimeChecks(), policies: await api.listPolicies() }), [project]);
  const monitors = (data?.checks || []).filter((c) => c.syntheticMonitor);
  const policies = data?.policies || [];
  const policyCount = (mon) => policies.filter((p) => (p.conditions || []).some((c) => (c.conditionThreshold?.filter || "").includes(mon.name))).length;

  return (
    <>
      <PageHeader title="Synthetic monitoring" actions={<Button startIcon={<AddIcon />} onClick={() => setCreateOpen(true)}>Create Synthetic Monitor</Button>} />
      <ResourceTable
        resourceName="synthetic monitors"
        items={monitors}
        loading={loading}
        error={error}
        onRetry={reload}
        rowKey={(m) => m.name}
        filterPlaceholder="Filter"
        columns={[
          { id: "status", header: <>Status<CapabilityBadge id="gcp.monitoring.synthetic-monitors" /></>, cell: () => "—" },
          { id: "name", header: "Name", sortField: "displayName", cell: (m) => m.displayName },
          { id: "rate", header: "Success rate", cell: () => "—" },
          { id: "latency", header: "Average Latency", cell: () => "—" },
          { id: "policies", header: "Alert policies", cell: (m) => policyCount(m) || "—" },
          { id: "actions", header: "", cell: (m) => <RowMenu mon={m} onDeleted={reload} /> },
        ]}
        empty={
          <Stack spacing={1.5} alignItems="center">
            <Typography variant="body2" color="text.secondary">No monitors configured</Typography>
            <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreateOpen(true)}>Create monitor</Button>
          </Stack>
        }
      />
      <CreateDialog open={createOpen} onClose={() => setCreateOpen(false)} onCreated={() => { setCreateOpen(false); reload(); }} />
    </>
  );
}
