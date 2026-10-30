/* Instance groups — unmanaged groups only (per core/capabilities/gcp/compute.json), list
 * across all zones + a Create dialog (no dedicated create page in the spec). */
import { useEffect, useState } from "react";
import {
  Alert, Button, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle, FormControl, FormControlLabel,
  FormGroup, InputLabel, MenuItem, Select, Stack, TextField, Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { fmtDate, PageHeader } from "../../kit/common.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

const ALL_ZONES = Object.values(api.ZONES_BY_REGION).flat();

function CreateDialog({ open, onClose, onCreated }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [touched, setTouched] = useState(false);
  const [zone, setZone] = useState(api.DEFAULT_ZONE);
  const [instances, setInstances] = useState([]);
  const [picked, setPicked] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!open) return;
    setName(""); setTouched(false); setError(null); setZone(api.DEFAULT_ZONE); setPicked([]);
    api.listInstancesAllZones().then(setInstances).catch(() => setInstances([]));
  }, [open]);

  const nameErr = touched ? api.validResourceName(name) : null;
  const candidates = instances.filter((i) => i._zoneScope === zone);

  const submit = async () => {
    setTouched(true);
    if (api.validResourceName(name)) return;
    setBusy(true); setError(null);
    try {
      await api.insertInstanceGroup(zone, { name });
      if (picked.length) await api.addGroupInstances(zone, name, picked);
      notify.success(`Created instance group "${name}"`);
      onCreated();
      onClose();
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Create instance group</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 0.5 }}>
          {error && <Alert severity="error"><b>{error.code || "Error"}</b>: {error.message}</Alert>}
          <TextField label="Name" required autoFocus value={name} onChange={(e) => setName(e.target.value.trim())}
            onBlur={() => setTouched(true)} error={!!nameErr} helperText={nameErr || " "} inputProps={{ "aria-label": "Name" }} />
          <FormControl fullWidth>
            <InputLabel id="ig-zone-l">Zone</InputLabel>
            <Select labelId="ig-zone-l" label="Zone" value={zone} onChange={(e) => { setZone(e.target.value); setPicked([]); }}>
              {ALL_ZONES.map((z) => <MenuItem key={z} value={z}>{z}</MenuItem>)}
            </Select>
          </FormControl>
          <Stack>
            <Typography variant="body2" sx={{ fontWeight: 500, mb: 0.5 }}>Add instances in {zone} (optional)</Typography>
            {candidates.length ? (
              <FormGroup sx={{ maxHeight: 180, overflow: "auto" }}>
                {candidates.map((i) => (
                  <FormControlLabel key={i.name} control={<Checkbox size="small" checked={picked.includes(i.name)}
                    onChange={() => setPicked((p) => p.includes(i.name) ? p.filter((n) => n !== i.name) : [...p, i.name])} />} label={i.name} />
                ))}
              </FormGroup>
            ) : <Typography variant="body2" color="text.secondary">No instances in this zone.</Typography>}
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

export default function InstanceGroups() {
  const notify = useNotify();
  const project = useProject();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [create, setCreate] = useState(false);
  const { data = [], loading, error, reload } = useAsync(() => api.listInstanceGroupsAllZones(), [project]);

  const byKey = (k) => data.find((g) => `${g._zoneScope}/${g.name}` === k);

  return (
    <>
      <PageHeader title={<>Instance groups <CapabilityBadge id="gcp.compute.instance_groups.crud" /></>} actions={<>
        <Button startIcon={<AddIcon />} onClick={() => setCreate(true)}>Create instance group</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
      </>} />
      <ResourceTable
        resourceName="instance groups"
        items={data}
        loading={loading}
        error={error}
        onRetry={reload}
        selectable
        selected={sel}
        onSelectedChange={setSel}
        rowKey={(g) => `${g._zoneScope}/${g.name}`}
        filterPlaceholder="Enter property name or value"
        columns={[
          { id: "status", header: "Status", cell: () => "Up to date" },
          { id: "name", header: "Name", sortField: "name", cell: (g) => g.name },
          { id: "instances", header: "Instances", sortField: "size", cell: (g) => g.size },
          { id: "template", header: "Template", cell: () => "—" },
          { id: "type", header: "Group type", cell: () => "Unmanaged" },
          { id: "created", header: "Creation time", sortField: "creationTimestamp", cell: (g) => fmtDate(g.creationTimestamp) },
          { id: "location", header: "Location", sortField: "_zoneScope", cell: (g) => g._zoneScope },
          { id: "autoscaling", header: "Autoscaling", cell: () => "Off" },
          { id: "inuse", header: "In use by", cell: () => "—" },
        ]}
        empty={
          <Stack spacing={1.5} alignItems="center">
            <Typography variant="body2" color="text.secondary">There are no instance groups in this project.</Typography>
            <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreate(true)}>Create instance group</Button>
          </Stack>
        }
      />
      <CreateDialog open={create} onClose={() => setCreate(false)} onCreated={reload} />
      <DeleteDialog
        open={del}
        onClose={() => setDel(false)}
        title={sel.length === 1 ? "Delete instance group?" : `Delete ${sel.length} instance groups?`}
        confirmText={sel.length === 1 ? byKey(sel[0])?.name : "DELETE"}
        warning="This can't be undone."
        onConfirm={async () => {
          for (const k of sel) {
            const g = byKey(k);
            if (g) await api.deleteInstanceGroup(g._zoneScope, g.name);
          }
          notify.success(sel.length === 1 ? `Deleted instance group "${byKey(sel[0])?.name}"` : `Deleted ${sel.length} instance groups`);
          setSel([]);
          reload();
        }}
      >
        <Typography variant="body2">{sel.length === 1 ? <>Instance group <b>{byKey(sel[0])?.name}</b> will be permanently deleted.</> : <>{sel.length} instance groups will be permanently deleted.</>}</Typography>
      </DeleteDialog>
    </>
  );
}
