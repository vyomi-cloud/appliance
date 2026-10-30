/* Settings — Notification channels (real CRUD), Log/Metric/Trace scopes (cross-project
 * observability scoping; Vyomi is single-project, so these are an honest gap). */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogContent, DialogTitle, FormControl, IconButton, InputLabel, MenuItem, Menu, Select, Stack, Tab, Tabs, TextField, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import MoreVertIcon from "@mui/icons-material/esm/MoreVert.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { PageHeader, Section } from "../../kit/common.jsx";
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
      {tab === "logscopes" && (
        <Section title="Log scopes" actions={<Button size="small" disabled>Create log scope</Button>}>
          <CapabilityContainer id="gcp.monitoring.settings.log-scopes" title="Cross-project log scopes" />
        </Section>
      )}
      {tab === "metricscope" && (
        <Section title="Metric scope">
          <Typography variant="body2">This project's metric scope includes only <b>{useProject()}</b> — Vyomi is single-project, so there are no monitored projects to add.</Typography>
        </Section>
      )}
      {tab === "tracescopes" && <CapabilityContainer id="gcp.monitoring.settings.log-scopes" title="Trace scopes" />}
    </>
  );
}
