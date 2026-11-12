/* Machine images — list, create-via-dialog (source instance + name), bulk delete. */
import { useEffect, useState } from "react";
import {
  Button, Dialog, DialogActions, DialogContent, DialogTitle, FormControl, InputLabel,
  MenuItem, Select, Stack, TextField, Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, fmtBytes, fmtDate, PageHeader } from "../../kit/common.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

function CreateMachineImageDialog({ open, onClose, onCreated }) {
  const [instances, setInstances] = useState([]);
  const [instKey, setInstKey] = useState("");
  const [name, setName] = useState("");
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => { api.listInstancesAllZones().then(setInstances).catch(() => setInstances([])); }, []);

  const nameErr = touched ? api.validResourceName(name) : null;
  const inst = instances.find((i) => `${i._zoneScope}/${i.name}` === instKey);

  const submit = async () => {
    setTouched(true);
    if (!inst || api.validResourceName(name)) return;
    setBusy(true); setError(null);
    try {
      await api.insertMachineImage({ name, sourceInstance: inst.name });
      onCreated(name);
      onClose();
      setName(""); setTouched(false); setInstKey("");
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Create machine image</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <ErrorAlert error={error} title="Failed to create machine image" />
          <FormControl fullWidth>
            <InputLabel id="src-inst-l">Source instance</InputLabel>
            <Select labelId="src-inst-l" label="Source instance" value={instKey} onChange={(e) => setInstKey(e.target.value)}>
              {instances.map((i) => <MenuItem key={`${i._zoneScope}/${i.name}`} value={`${i._zoneScope}/${i.name}`}>{i._zoneScope}/{i.name}</MenuItem>)}
            </Select>
          </FormControl>
          <TextField label="Name" required value={name} onChange={(e) => setName(e.target.value.trim())} onBlur={() => setTouched(true)}
            error={!!nameErr} helperText={nameErr || " "} inputProps={{ "aria-label": "Machine image name" }} />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy || !inst} onClick={submit}>{busy ? "Creating…" : "Create"}</Button>
      </DialogActions>
    </Dialog>
  );
}

export default function MachineImages() {
  const notify = useNotify();
  const project = useProject();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const { data = [], loading, error, reload } = useAsync(() => api.listMachineImages(), [project]);

  return (
    <>
      <PageHeader title="Machine images" actions={<>
        <Button startIcon={<AddIcon />} onClick={() => setCreateOpen(true)}>Create machine image</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
      </>} />
      <ResourceTable
        resourceName="machine images"
        items={data}
        loading={loading}
        error={error}
        onRetry={reload}
        selectable
        selected={sel}
        onSelectedChange={setSel}
        filterPlaceholder="Enter property name or value"
        columns={[
          { id: "name", header: "Name", sortField: "name", cell: (m) => m.name },
          { id: "location", header: "Location", cell: (m) => m._display?.location || "—" },
          { id: "source", header: "Source instance", cell: (m) => m._display?.sourceInstanceName || "—" },
          { id: "created", header: "Creation time", sortField: "creationTimestamp", cell: (m) => fmtDate(m.creationTimestamp) },
          { id: "size", header: "Total storage size", sortField: "totalStorageBytes", cell: (m) => fmtBytes(m.totalStorageBytes) },
        ]}
        empty={
          <Stack spacing={1.5} alignItems="center">
            <Typography variant="body2" color="text.secondary">There are no machine images in this project.</Typography>
            <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreateOpen(true)}>Create machine image</Button>
          </Stack>
        }
      />

      <CreateMachineImageDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={(name) => { notify.success(`Created machine image "${name}"`); reload(); }}
      />

      <DeleteDialog
        open={del}
        onClose={() => setDel(false)}
        title={sel.length === 1 ? "Delete machine image?" : `Delete ${sel.length} machine images?`}
        confirmText={sel.length === 1 ? sel[0] : "DELETE"}
        warning="Deleted machine images can't be recovered. This can't be undone."
        onConfirm={async () => {
          for (const n of sel) await api.deleteMachineImage(n);
          notify.success(sel.length === 1 ? `Deleted machine image "${sel[0]}"` : `Deleted ${sel.length} machine images`);
          setSel([]);
          reload();
        }}
      >
        <Typography variant="body2">{sel.length === 1 ? <>Machine image <b>{sel[0]}</b> will be permanently deleted.</> : <>{sel.length} machine images will be permanently deleted.</>}</Typography>
      </DeleteDialog>
    </>
  );
}
