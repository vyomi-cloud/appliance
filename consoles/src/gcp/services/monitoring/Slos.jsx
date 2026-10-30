/* Services & SLOs — real Service Monitoring API (v3) resources. Error-budget columns are
 * an honest gap (no live request/latency pipeline to burn a budget against); see
 * gcp.monitoring.slos in the capability registry. */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, Menu, MenuItem, TextField, Typography } from "@mui/material";
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

function DefineServiceDialog({ open, onClose, onCreated }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>Define service</DialogTitle>
      <DialogContent><TextField autoFocus fullWidth label="Service name" value={name} onChange={(e) => setName(e.target.value)} sx={{ mt: 1 }} /></DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" disabled={!name.trim() || busy} onClick={async () => {
          setBusy(true);
          await api.createService({ displayName: name });
          notify.success(`Defined service "${name}"`);
          setBusy(false); onCreated();
        }}>Define</Button>
      </DialogActions>
    </Dialog>
  );
}

function RowMenu({ svc, onDeleted }) {
  const notify = useNotify();
  const [anchor, setAnchor] = useState(null);
  const [del, setDel] = useState(false);
  const id = svc.name.split("/").pop();
  return (
    <>
      <IconButton size="small" aria-label={`Actions for ${svc.displayName}`} onClick={(e) => setAnchor(e.currentTarget)}><MoreVertIcon fontSize="small" /></IconButton>
      <Menu anchorEl={anchor} open={!!anchor} onClose={() => setAnchor(null)}>
        <MenuItem onClick={() => { setAnchor(null); setDel(true); }}>Delete</MenuItem>
      </Menu>
      <DeleteDialog open={del} onClose={() => setDel(false)} title="Delete service?" confirmText={svc.displayName}
        onConfirm={async () => { await api.deleteService(id); notify.success(`Deleted service "${svc.displayName}"`); onDeleted(); }}>
        <Typography variant="body2">Service <b>{svc.displayName}</b> and its SLOs will be permanently deleted.</Typography>
      </DeleteDialog>
    </>
  );
}

export default function Slos() {
  const project = useProject();
  const [defineOpen, setDefineOpen] = useState(false);
  const { data = [], loading, error, reload } = useAsync(() => api.listServices(), [project]);

  return (
    <>
      <PageHeader title="SLOs Overview" actions={<>
        <Button startIcon={<AddIcon />} onClick={() => setDefineOpen(true)}>Define service</Button>
        <Button disabled>Send feedback</Button>
        <Button disabled>Auto refresh</Button>
      </>} />
      <ResourceTable
        resourceName="services"
        items={data}
        loading={loading}
        error={error}
        onRetry={reload}
        rowKey={(s) => s.name}
        filterPlaceholder="Filter"
        columns={[
          { id: "name", header: "Name", sortField: "displayName", cell: (s) => s.displayName },
          { id: "type", header: "Type", cell: () => "Custom service" },
          { id: "budget", header: <>SLOs out of error budget<CapabilityBadge id="gcp.monitoring.slos" /></>, cell: () => "—" },
          { id: "firing", header: "SLOs with firing alert", cell: () => "—" },
          { id: "labels", header: "Labels", cell: (s) => Object.keys(s.userLabels || {}).length ? Object.entries(s.userLabels).map(([k, v]) => `${k}=${v}`).join(", ") : "—" },
          { id: "actions", header: "", cell: (s) => <RowMenu svc={s} onDeleted={reload} /> },
        ]}
        empty={<Typography variant="body2" color="text.secondary">No services</Typography>}
      />
      <DefineServiceDialog open={defineOpen} onClose={() => setDefineOpen(false)} onCreated={() => { setDefineOpen(false); reload(); }} />
    </>
  );
}
