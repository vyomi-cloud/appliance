/* Snapshots — list, create-via-dialog (source disk + name), bulk delete. */
import { useEffect, useState } from "react";
import {
  Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, FormControl, InputLabel,
  MenuItem, Select, Stack, Tab, Tabs, TextField, Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import ScheduleIcon from "@mui/icons-material/esm/Schedule.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, fmtBytes, fmtDate, NotSimulated, PageHeader } from "../../kit/common.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

function TabPanel({ value, name, children }) {
  return value === name ? <Box sx={{ pt: 2 }}>{children}</Box> : null;
}

function CreateSnapshotDialog({ open, onClose, onCreated }) {
  const [disks, setDisks] = useState([]);
  const [diskKey, setDiskKey] = useState("");
  const [name, setName] = useState("");
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => { api.listDisksAllZones().then(setDisks).catch(() => setDisks([])); }, []);

  const nameErr = touched ? api.validResourceName(name) : null;
  const disk = disks.find((d) => `${d._zoneScope}/${d.name}` === diskKey);

  const submit = async () => {
    setTouched(true);
    if (!disk || api.validResourceName(name)) return;
    setBusy(true); setError(null);
    try {
      await api.createSnapshot(disk._zoneScope, disk.name, { name });
      onCreated(name);
      onClose();
      setName(""); setTouched(false); setDiskKey("");
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Create snapshot</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <ErrorAlert error={error} title="Failed to create snapshot" />
          <FormControl fullWidth>
            <InputLabel id="src-disk-l">Source disk</InputLabel>
            <Select labelId="src-disk-l" label="Source disk" value={diskKey} onChange={(e) => setDiskKey(e.target.value)}>
              {disks.map((d) => <MenuItem key={`${d._zoneScope}/${d.name}`} value={`${d._zoneScope}/${d.name}`}>{d._zoneScope}/{d.name}</MenuItem>)}
            </Select>
          </FormControl>
          <TextField label="Name" required value={name} onChange={(e) => setName(e.target.value.trim())} onBlur={() => setTouched(true)}
            error={!!nameErr} helperText={nameErr || " "} inputProps={{ "aria-label": "Snapshot name" }} />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy || !disk} onClick={submit}>{busy ? "Creating…" : "Create"}</Button>
      </DialogActions>
    </Dialog>
  );
}

export default function Snapshots() {
  const notify = useNotify();
  const project = useProject();
  const [tab, setTab] = useState("snapshots");
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [scheduleOpen, setScheduleOpen] = useState(false);
  const { data = [], loading, error, reload } = useAsync(() => api.listSnapshots(), [project]);

  return (
    <>
      <PageHeader title="Snapshots" actions={<>
        <Button startIcon={<AddIcon />} onClick={() => setCreateOpen(true)}>Create snapshot</Button>
        <Button startIcon={<ScheduleIcon />} onClick={() => setScheduleOpen(true)}>Create snapshot schedule</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
      </>} />
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        <Tab label="Snapshots" value="snapshots" />
        <Tab label="Snapshot schedules" value="schedules" />
        <Tab label="Instant snapshots" value="instant" />
      </Tabs>
      <TabPanel value={tab} name="snapshots">
        <ResourceTable
          resourceName="snapshots"
          items={data}
          loading={loading}
          error={error}
          onRetry={reload}
          selectable
          selected={sel}
          onSelectedChange={setSel}
          filterPlaceholder="Enter property name or value"
          columns={[
            { id: "status", header: "Status", sortField: "status", cell: (s) => s.status },
            { id: "name", header: "Name", sortField: "name", cell: (s) => s.name },
            { id: "location", header: "Location", cell: (s) => s._display?.location || "—" },
            { id: "size", header: "Snapshot size", sortField: "storageBytes", cell: (s) => fmtBytes(s.storageBytes) },
            { id: "created", header: "Creation time", sortField: "creationTimestamp", cell: (s) => fmtDate(s.creationTimestamp) },
            { id: "source", header: "Source disk", cell: (s) => s._display?.sourceDiskName || "—" },
            { id: "type", header: "Snapshot type", sortField: "snapshotType", cell: (s) => s.snapshotType },
          ]}
          empty={
            <Stack spacing={1.5} alignItems="center">
              <Typography variant="body2" color="text.secondary">There are no snapshots in this project.</Typography>
              <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreateOpen(true)}>Create snapshot</Button>
            </Stack>
          }
        />
      </TabPanel>
      <TabPanel value={tab} name="schedules">
        <NotSimulated feature="Snapshot schedules" note="Recurring automated snapshot policies aren't modeled." />
      </TabPanel>
      <TabPanel value={tab} name="instant">
        <NotSimulated feature="Instant snapshots" note="Instant snapshots aren't modeled." />
      </TabPanel>

      <CreateSnapshotDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={(name) => { notify.success(`Created snapshot "${name}"`); reload(); }}
      />

      <Dialog open={scheduleOpen} onClose={() => setScheduleOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Create snapshot schedule</DialogTitle>
        <DialogContent><NotSimulated feature="Snapshot schedules" note="Recurring automated snapshot policies aren't modeled." /></DialogContent>
        <DialogActions><Button onClick={() => setScheduleOpen(false)}>Close</Button></DialogActions>
      </Dialog>

      <DeleteDialog
        open={del}
        onClose={() => setDel(false)}
        title={sel.length === 1 ? "Delete snapshot?" : `Delete ${sel.length} snapshots?`}
        confirmText={sel.length === 1 ? sel[0] : "DELETE"}
        warning="Deleted snapshots can't be recovered. This can't be undone."
        onConfirm={async () => {
          for (const n of sel) await api.deleteSnapshot(n);
          notify.success(sel.length === 1 ? `Deleted snapshot "${sel[0]}"` : `Deleted ${sel.length} snapshots`);
          setSel([]);
          reload();
        }}
      >
        <Typography variant="body2">{sel.length === 1 ? <>Snapshot <b>{sel[0]}</b> will be permanently deleted.</> : <>{sel.length} snapshots will be permanently deleted.</>}</Typography>
      </DeleteDialog>
    </>
  );
}
