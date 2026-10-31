/* Instance templates — global resource, list + a Create dialog (the spec has no dedicated
 * create page; the real console's wizard becomes a minimal real dialog here). */
import { useEffect, useState } from "react";
import {
  Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, FormControl, InputLabel, MenuItem, Select, Stack, TextField, Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { fmtDate, PageHeader } from "../../kit/common.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

function CreateDialog({ open, onClose, onCreated }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [touched, setTouched] = useState(false);
  const [machineTypes, setMachineTypes] = useState([]);
  const [machineType, setMachineType] = useState("e2-medium");
  const [osIdx, setOsIdx] = useState(0);
  const [diskType, setDiskType] = useState("pd-balanced");
  const [diskSize, setDiskSize] = useState(10);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!open) return;
    setName(""); setTouched(false); setError(null); setMachineType("e2-medium"); setOsIdx(0); setDiskType("pd-balanced"); setDiskSize(10);
    api.listMachineTypes(api.DEFAULT_ZONE).then(setMachineTypes).catch(() => setMachineTypes([]));
  }, [open]);

  const nameErr = touched ? api.validResourceName(name) : null;

  const submit = async () => {
    setTouched(true);
    if (api.validResourceName(name)) return;
    setBusy(true); setError(null);
    const [osProject, osFamily] = api.OS_IMAGES[osIdx];
    try {
      await api.insertInstanceTemplate({
        name,
        properties: {
          machineType,
          disks: [{ boot: true, autoDelete: true, initializeParams: { sourceImage: api.osImageSource(osProject, osFamily), diskType, diskSizeGb: Number(diskSize) } }],
          networkInterfaces: [{}],
        },
      });
      notify.success(`Created instance template "${name}"`);
      onCreated();
      onClose();
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Create instance template</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 0.5 }}>
          {error && <Alert severity="error"><b>{error.code || "Error"}</b>: {error.message}</Alert>}
          <TextField label="Name" required autoFocus value={name} onChange={(e) => setName(e.target.value.trim())}
            onBlur={() => setTouched(true)} error={!!nameErr} helperText={nameErr || " "} inputProps={{ "aria-label": "Name" }} />
          <FormControl fullWidth>
            <InputLabel id="it-mt-l">Machine type</InputLabel>
            <Select labelId="it-mt-l" label="Machine type" value={machineType} onChange={(e) => setMachineType(e.target.value)}>
              {machineTypes.map((m) => <MenuItem key={m.name} value={m.name}>{m.name} ({m.guestCpus} vCPU, {Math.round(m.memoryMb / 1024)} GB memory)</MenuItem>)}
            </Select>
          </FormControl>
          <FormControl fullWidth>
            <InputLabel id="it-os-l">Boot disk — Operating system</InputLabel>
            <Select labelId="it-os-l" label="Boot disk — Operating system" value={osIdx} onChange={(e) => setOsIdx(e.target.value)}>
              {api.OS_IMAGES.map(([, , , label], i) => <MenuItem key={i} value={i}>{label}</MenuItem>)}
            </Select>
          </FormControl>
          <Stack direction="row" spacing={2}>
            <FormControl fullWidth>
              <InputLabel id="it-dt-l">Boot disk type</InputLabel>
              <Select labelId="it-dt-l" label="Boot disk type" value={diskType} onChange={(e) => setDiskType(e.target.value)}>
                {api.DISK_TYPES.map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
              </Select>
            </FormControl>
            <TextField fullWidth label="Boot disk size (GB)" type="number" value={diskSize} onChange={(e) => setDiskSize(e.target.value)} inputProps={{ min: 10 }} />
          </Stack>
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy} onClick={submit}>{busy ? "Creating…" : "Create"}</Button>
      </DialogActions>
    </Dialog>
  );
}

export default function InstanceTemplates() {
  const notify = useNotify();
  const project = useProject();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [create, setCreate] = useState(false);
  const { data = [], loading, error, reload } = useAsync(() => api.listInstanceTemplates(), [project]);

  const byKey = (k) => data.find((t) => t.name === k);

  return (
    <>
      <PageHeader title="Instance templates" actions={<>
        <Button startIcon={<AddIcon />} onClick={() => setCreate(true)}>Create instance template</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
      </>} />
      <ResourceTable
        resourceName="instance templates"
        items={data}
        loading={loading}
        error={error}
        onRetry={reload}
        selectable
        selected={sel}
        onSelectedChange={setSel}
        rowKey={(t) => t.name}
        filterPlaceholder="Enter property name or value"
        columns={[
          { id: "name", header: "Name", sortField: "name", cell: (t) => t.name },
          { id: "location", header: "Location", cell: () => "global" },
          { id: "machineType", header: "Machine type", cell: (t) => t._display?.machineType || "—" },
          { id: "image", header: "Image", cell: (t) => t._display?.imageName || "—" },
          { id: "diskType", header: "Disk type", cell: (t) => t._display?.diskType || "—" },
          { id: "inuse", header: "In use by", cell: () => "—" },
          { id: "created", header: "Creation time", sortField: "creationTimestamp", cell: (t) => fmtDate(t.creationTimestamp) },
        ]}
        empty={
          <Stack spacing={1.5} alignItems="center">
            <Typography variant="body2" color="text.secondary">There are no instance templates in this project.</Typography>
            <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreate(true)}>Create instance template</Button>
          </Stack>
        }
      />
      <CreateDialog open={create} onClose={() => setCreate(false)} onCreated={reload} />
      <DeleteDialog
        open={del}
        onClose={() => setDel(false)}
        title={sel.length === 1 ? "Delete instance template?" : `Delete ${sel.length} instance templates?`}
        confirmText={sel.length === 1 ? byKey(sel[0])?.name : "DELETE"}
        warning="This can't be undone."
        onConfirm={async () => {
          for (const k of sel) {
            const t = byKey(k);
            if (t) await api.deleteInstanceTemplate(t.name);
          }
          notify.success(sel.length === 1 ? `Deleted instance template "${byKey(sel[0])?.name}"` : `Deleted ${sel.length} instance templates`);
          setSel([]);
          reload();
        }}
      >
        <Typography variant="body2">{sel.length === 1 ? <>Instance template <b>{byKey(sel[0])?.name}</b> will be permanently deleted.</> : <>{sel.length} instance templates will be permanently deleted.</>}</Typography>
      </DeleteDialog>
    </>
  );
}
