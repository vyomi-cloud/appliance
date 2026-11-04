/* Settings — Notification channels (real CRUD). Metric Scope is real cross-project
 * aggregation (Metrics Scopes API v1; see gcp.monitoring.settings.metric-scope). Log/Trace
 * Scopes stay an honest gap: they'd extend Log Explorer / Trace Explorer, both separate,
 * unbuilt products in this console. */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogContent, DialogTitle, FormControl, IconButton, InputLabel, MenuItem, Menu, Select, Stack, Tab, Tabs, TextField, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import MoreVertIcon from "@mui/icons-material/esm/MoreVert.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { PageHeader } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

const TABS = ["channels", "logscopes", "metricscope", "tracescopes"];

function CreateChannelDialog({ open, onClose, descriptors, onCreated }) {
  const notify = useNotify();
  const [type, setType] = useState("email");
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const desc = descriptors.find((d) => d.type === type);
  const labelKey = desc?.labels?.[0]?.key || "value";
  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>Add notification channel</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <FormControl><InputLabel id="chan-type">Type</InputLabel>
            <Select labelId="chan-type" label="Type" value={type} onChange={(e) => setType(e.target.value)}>
              {descriptors.map((d) => <MenuItem key={d.type} value={d.type}>{d.displayName}</MenuItem>)}
            </Select>
          </FormControl>
          <TextField label="Display name" value={name} onChange={(e) => setName(e.target.value)} />
          <TextField label={labelKey} value={value} onChange={(e) => setValue(e.target.value)} />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" disabled={!value.trim() || busy} onClick={async () => {
          setBusy(true);
          await api.createChannel({ type, displayName: name || value, labels: { [labelKey]: value } });
          notify.success("Notification channel created");
          setBusy(false); onCreated();
        }}>Create</Button>
      </DialogActions>
    </Dialog>
  );
}

function ChannelRowMenu({ chan, onDeleted }) {
  const notify = useNotify();
  const [anchor, setAnchor] = useState(null);
  const [del, setDel] = useState(false);
  const id = chan.name.split("/").pop();
  return (
    <>
      <IconButton size="small" aria-label="Actions" onClick={(e) => setAnchor(e.currentTarget)}><MoreVertIcon fontSize="small" /></IconButton>
      <Menu anchorEl={anchor} open={!!anchor} onClose={() => setAnchor(null)}>
        <MenuItem onClick={() => { setAnchor(null); setDel(true); }}>Delete</MenuItem>
      </Menu>
      <DeleteDialog open={del} onClose={() => setDel(false)} title="Delete notification channel?" confirmText={api.channelLabel(chan)}
        onConfirm={async () => { await api.deleteChannel(id, true); notify.success("Deleted notification channel"); onDeleted(); }}>
        <Typography variant="body2">This notification channel will be permanently deleted.</Typography>
      </DeleteDialog>
    </>
  );
}

function MetricScopeTab() {
  const project = useProject();
  const notify = useNotify();
  const [addOpen, setAddOpen] = useState(false);
  const [pid, setPid] = useState("");
  const { data, loading, error, reload } = useAsync(() => api.getMetricsScope(), [project]);
  const monitored = (data?.monitoredProjects || []).filter((p) => p.name.split("/").pop() !== project);
  return (
    <>
      <Typography variant="body2" sx={{ mb: 2 }}>
        This project's metric scope includes <b>{project}</b> and every project added below — Metrics Explorer,
        dashboards, Cost Explorer and the Overview panels read all of their time series.
      </Typography>
      <Stack direction="row" justifyContent="flex-end" sx={{ mb: 1 }}>
        <Button startIcon={<AddIcon />} onClick={() => setAddOpen(true)}>Add a project</Button>
      </Stack>
      <ResourceTable
        resourceName="monitored projects"
        items={monitored}
        loading={loading}
        error={error}
        onRetry={reload}
        rowKey={(p) => p.name}
        columns={[
          { id: "name", header: "Project ID", cell: (p) => p.name.split("/").pop() },
          { id: "actions", header: "", cell: (p) => (
            <Button size="small" onClick={async () => {
              await api.removeMonitoredProject(p.name.split("/").pop());
              notify.success("Removed monitored project");
              reload();
            }}>Remove</Button>
          ) },
        ]}
        empty={<Typography variant="body2" color="text.secondary">No other projects are monitored from this workspace.</Typography>}
      />
      <Dialog open={addOpen} onClose={() => setAddOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Add a monitored project</DialogTitle>
        <DialogContent>
          <TextField autoFocus fullWidth label="Project ID" value={pid} onChange={(e) => setPid(e.target.value)} sx={{ mt: 1 }} inputProps={{ "aria-label": "Project ID" }} />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAddOpen(false)}>Cancel</Button>
          <Button variant="contained" disabled={!pid.trim()} onClick={async () => {
            await api.addMonitoredProject(pid.trim());
            notify.success(`Added "${pid.trim()}" to this project's metric scope`);
            setPid(""); setAddOpen(false); reload();
          }}>Add</Button>
        </DialogActions>
      </Dialog>
    </>
  );
}

function ChannelsTab() {
  const project = useProject();
  const [createOpen, setCreateOpen] = useState(false);
  const { data, loading, error, reload } = useAsync(async () => ({ channels: await api.listChannels(), descriptors: await api.channelDescriptors() }), [project]);
  return (
    <>
      <Stack direction="row" justifyContent="flex-end" sx={{ mb: 1 }}><Button startIcon={<AddIcon />} onClick={() => setCreateOpen(true)}>Add notification channel</Button></Stack>
      <ResourceTable
        resourceName="notification channels"
        items={data?.channels || []}
        loading={loading}
        error={error}
        onRetry={reload}
        rowKey={(c) => c.name}
        filterPlaceholder="Filter"
        columns={[
          { id: "name", header: "Display name", sortField: "displayName", cell: (c) => api.channelLabel(c) },
          { id: "type", header: "Type", sortField: "type", cell: (c) => c.type },
          { id: "status", header: "Status", cell: (c) => c.enabled ? "Enabled" : "Disabled" },
          { id: "actions", header: "", cell: (c) => <ChannelRowMenu chan={c} onDeleted={reload} /> },
        ]}
        empty={<Typography variant="body2" color="text.secondary">No notification channels yet.</Typography>}
      />
      <CreateChannelDialog open={createOpen} onClose={() => setCreateOpen(false)} descriptors={data?.descriptors || []} onCreated={() => { setCreateOpen(false); reload(); }} />
    </>
  );
}

export default function Settings({ query }) {
  const tab = TABS.includes(query?.tab) ? query.tab : "channels";
  return (
    <>
      <PageHeader title="Settings" />
      <Tabs value={tab} onChange={(_, t) => { location.hash = `/monitoring/settings${t === "channels" ? "" : `?tab=${t}`}`; }} sx={{ mb: 2 }}>
        <Tab value="channels" label="Notification channels" />
        <Tab value="logscopes" label="Log Scopes" />
        <Tab value="metricscope" label="Metric Scope" />
        <Tab value="tracescopes" label="Trace Scopes" />
      </Tabs>
      {tab === "channels" && <ChannelsTab />}
      {tab === "logscopes" && <CapabilityContainer id="gcp.monitoring.settings.log-scopes" title="Log scopes" />}
      {tab === "metricscope" && (
        <CapabilityContainer id="gcp.monitoring.settings.metric-scope" title="Metric scope">
          <MetricScopeTab />
        </CapabilityContainer>
      )}
      {tab === "tracescopes" && <CapabilityContainer id="gcp.monitoring.settings.trace-scopes" title="Trace scopes" />}
    </>
  );
}
