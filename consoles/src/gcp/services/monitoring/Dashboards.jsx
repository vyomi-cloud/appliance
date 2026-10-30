/* Dashboards list — custom dashboards over the native Dashboards API (v1). */
import { useState } from "react";
import {
  Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, Menu, MenuItem, Stack,
  TextField, ToggleButton, Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import LabelIcon from "@mui/icons-material/esm/LabelOutlined.js";
import SellIcon from "@mui/icons-material/esm/SellOutlined.js";
import MoreVertIcon from "@mui/icons-material/esm/MoreVert.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { PageHeader, Section } from "../../kit/common.jsx";
import { Link, hashHref } from "../../link.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

function RowMenu({ dash, onDeleted }) {
  const notify = useNotify();
  const [anchor, setAnchor] = useState(null);
  const [del, setDel] = useState(false);
  const id = dash.name.split("/").pop();
  return (
    <>
      <IconButton size="small" aria-label={`Actions for ${dash.displayName}`} onClick={(e) => setAnchor(e.currentTarget)}><MoreVertIcon fontSize="small" /></IconButton>
      <Menu anchorEl={anchor} open={!!anchor} onClose={() => setAnchor(null)}>
        <MenuItem component="a" href={hashHref("monitoring", "dashboards", id)} onClick={() => setAnchor(null)}>Open</MenuItem>
        <MenuItem onClick={() => { setAnchor(null); setDel(true); }}>Delete</MenuItem>
      </Menu>
      <DeleteDialog open={del} onClose={() => setDel(false)} title="Delete dashboard?" confirmText={dash.displayName}
        onConfirm={async () => { await api.deleteDashboard(id); notify.success(`Deleted dashboard "${dash.displayName}"`); onDeleted(); }}>
        <Typography variant="body2">Dashboard <b>{dash.displayName}</b> will be permanently deleted.</Typography>
      </DeleteDialog>
    </>
  );
}

function ManageLabelsDialog({ open, onClose, dashboards, onDone }) {
  const notify = useNotify();
  const [key, setKey] = useState("");
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>Manage labels</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <Typography variant="body2" color="text.secondary">Add a label to {dashboards.length} selected dashboard{dashboards.length === 1 ? "" : "s"}.</Typography>
          <TextField label="Key" size="small" value={key} onChange={(e) => setKey(e.target.value)} />
          <TextField label="Value" size="small" value={value} onChange={(e) => setValue(e.target.value)} />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" disabled={!key || busy} onClick={async () => {
          setBusy(true);
          for (const d of dashboards) await api.patchDashboard(d.name.split("/").pop(), { displayName: d.displayName, labels: { ...(d.labels || {}), [key]: value }, etag: d.etag });
          notify.success("Labels updated");
          setBusy(false); onDone();
        }}>Save</Button>
      </DialogActions>
    </Dialog>
  );
}

export default function Dashboards() {
  const notify = useNotify();
  const project = useProject();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [labelsDlg, setLabelsDlg] = useState(false);
  const [showLabels, setShowLabels] = useState(false);
  const [dense, setDense] = useState(false);
  const { data = [], loading, error, reload } = useAsync(() => api.listDashboards(), [project]);

  const selected = data.filter((d) => sel.includes(d.name));

  return (
    <>
      <PageHeader title="Dashboards" actions={<>
        <Button startIcon={<AddIcon />} href="#/monitoring/dashboards/create">Create Custom Dashboard</Button>
        <Button href="#/monitoring/integrations">View Dashboard Templates</Button>
        <Button href="#/monitoring/integrations">Import Grafana Dashboards</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
      </>} />

      <Section title="Add or create more dashboards">
        <Typography variant="body2" color="text.secondary">
          Build a custom dashboard from scratch, start from a template for your workloads, or import an existing Grafana dashboard.
        </Typography>
      </Section>

      <Box sx={{ mt: 2 }}>
        <Stack direction="row" spacing={1} sx={{ mb: 1 }}>
          <ToggleButton size="small" value="labels" selected={showLabels} onChange={() => setShowLabels((v) => !v)} aria-label="Labels">
            <LabelIcon fontSize="small" sx={{ mr: 0.75 }} />Labels
          </ToggleButton>
          <Button size="small" startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
          <ToggleButton size="small" value="tags" selected={dense} onChange={() => setDense((v) => !v)} aria-label="Tags">
            <SellIcon fontSize="small" sx={{ mr: 0.75 }} />Tags
          </ToggleButton>
          <Button size="small" disabled={!sel.length} onClick={() => setLabelsDlg(true)}>Manage Labels</Button>
        </Stack>
        <ResourceTable
          resourceName="dashboards"
          items={data}
          loading={loading}
          error={error}
          onRetry={reload}
          selectable
          selected={sel}
          onSelectedChange={setSel}
          dense={dense}
          rowKey={(d) => d.name}
          filterPlaceholder="Filter"
          columns={[
            { id: "name", header: "Name", sortField: "displayName", cell: (d) => (
              <Stack spacing={0.5}>
                <Link href={hashHref("monitoring", "dashboards", d.name.split("/").pop())}>{d.displayName}</Link>
                {showLabels && (Object.entries(d.labels || {}).length
                  ? <Stack direction="row" spacing={0.5}>{Object.entries(d.labels).map(([k, v]) => <Chip key={k} size="small" label={`${k}: ${v}`} />)}</Stack>
                  : <Typography variant="caption" color="text.secondary">No labels</Typography>)}
              </Stack>
            ) },
            { id: "type", header: "Type", cell: () => "Custom" },
            { id: "description", header: "Description", cell: (d) => Object.keys(d.labels || {}).length ? Object.entries(d.labels).map(([k, v]) => `${k}=${v}`).join(", ") : "—" },
            { id: "actions", header: "Actions", cell: (d) => <RowMenu dash={d} onDeleted={reload} /> },
          ]}
          empty={
            <Stack spacing={1.5} alignItems="center">
              <Typography variant="body2" color="text.secondary">There are no dashboards in this project yet.</Typography>
              <Button variant="contained" startIcon={<AddIcon />} href="#/monitoring/dashboards/create">Create Custom Dashboard</Button>
            </Stack>
          }
        />
      </Box>

      <DeleteDialog open={del} onClose={() => setDel(false)}
        title={sel.length === 1 ? "Delete dashboard?" : `Delete ${sel.length} dashboards?`}
        confirmText={sel.length === 1 ? selected[0]?.displayName : "DELETE"}
        onConfirm={async () => {
          for (const d of selected) await api.deleteDashboard(d.name.split("/").pop());
          notify.success(sel.length === 1 ? `Deleted dashboard "${selected[0]?.displayName}"` : `Deleted ${sel.length} dashboards`);
          setSel([]); reload();
        }}>
        <Typography variant="body2">{selected.map((d) => d.displayName).join(", ")} will be permanently deleted.</Typography>
      </DeleteDialog>
      <ManageLabelsDialog open={labelsDlg} onClose={() => setLabelsDlg(false)} dashboards={selected} onDone={() => { setLabelsDlg(false); reload(); }} />
    </>
  );
}
