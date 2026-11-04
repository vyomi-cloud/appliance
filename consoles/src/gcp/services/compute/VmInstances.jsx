/* VM instances — list across all zones, bulk lifecycle actions, delete. */
import { useState } from "react";
import {
  Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, Menu, MenuItem, Stack, Tab, Tabs, TextField, Tooltip, Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import UploadIcon from "@mui/icons-material/esm/Upload.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import PlayArrowIcon from "@mui/icons-material/esm/PlayArrow.js";
import StopIcon from "@mui/icons-material/esm/Stop.js";
import PauseIcon from "@mui/icons-material/esm/Pause.js";
import RestartAltIcon from "@mui/icons-material/esm/RestartAlt.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import MoreVertIcon from "@mui/icons-material/esm/MoreVert.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { PageHeader, NotSimulated, ErrorAlert, fmtDate } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { Link } from "../../link.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";
import { InstanceSchedules, RecommendationsTable } from "./Ext.jsx";

function TabPanel({ value, name, children }) {
  return value === name ? <Box sx={{ pt: 2 }}>{children}</Box> : null;
}

export default function VmInstances() {
  const notify = useNotify();
  const project = useProject();
  const [tab, setTab] = useState("instances");
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [menu, setMenu] = useState(null);
  const [importOpen, setImportOpen] = useState(false);
  const { data = [], loading, error, reload } = useAsync(() => api.listInstancesAllZones(), [project]);
  const { data: ops = [], loading: opsLoading } = useAsync(() => api.listOperations(), [project]);
  const instanceOps = ops.filter((o) => (o.targetLink || "").includes("/instances/"));

  const byKey = (k) => data.find((i) => `${i._zoneScope}/${i.name}` === k);
  const bulk = async (action) => {
    for (const k of sel) {
      const inst = byKey(k);
      if (!inst) continue;
      try { await api.instanceAction(inst._zoneScope, inst.name, action); }
      catch (e) { notify.error(`${action} failed for ${inst.name}: ${e.message}`); }
    }
    notify.success(`Requested "${action}" for ${sel.length} instance${sel.length === 1 ? "" : "s"}`);
    setSel([]);
    reload();
  };

  return (
    <>
      <PageHeader title="VM instances" actions={<>
        <Button startIcon={<AddIcon />} href="#/compute/instances/create">Create instance</Button>
        <Button startIcon={<UploadIcon />} onClick={() => setImportOpen(true)}>Import VM</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
      </>} />
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        <Tab label="Instances" value="instances" />
        <Tab label="Observability" value="observability" />
        <Tab label="Instance schedules" value="schedules" />
      </Tabs>
      <TabPanel value={tab} name="instances">
        <Stack direction="row" spacing={1} sx={{ mb: 1 }}>
          <Button size="small" startIcon={<PlayArrowIcon />} disabled={!sel.length} onClick={() => bulk("start")}>Start / Resume</Button>
          <Button size="small" startIcon={<StopIcon />} disabled={!sel.length} onClick={() => bulk("stop")}>Stop</Button>
          <Button size="small" startIcon={<PauseIcon />} disabled={!sel.length} onClick={() => bulk("suspend")}>Suspend</Button>
          <Button size="small" startIcon={<RestartAltIcon />} disabled={!sel.length} onClick={() => bulk("reset")}>Reset</Button>
          <Button size="small" startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
        </Stack>
        <ResourceTable
          resourceName="VM instances"
          items={data}
          loading={loading}
          error={error}
          onRetry={reload}
          selectable
          selected={sel}
          onSelectedChange={setSel}
          rowKey={(i) => `${i._zoneScope}/${i.name}`}
          filterPlaceholder="Enter property name or value"
          columns={[
            { id: "status", header: "Status", sortField: "status", cell: (i) => <Chip size="small" color={api.statusChipColor(i.status)} label={i.status} /> },
            { id: "name", header: "Name", sortField: "name", cell: (i) => <Link href={`#/compute/instances/${i._zoneScope}/${i.name}`}>{i.name}</Link> },
            { id: "zone", header: "Zone", sortField: "_zoneScope", cell: (i) => i._zoneScope },
            { id: "rec", header: "Recommendations", cell: () => "—" },
            { id: "inuse", header: "In use by", cell: () => "—" },
            { id: "internal", header: "Internal IP", cell: (i) => api.internalIpOf(i) },
            { id: "external", header: "External IP", cell: (i) => api.externalIpOf(i) },
            {
              id: "connect", header: "Connect",
              cell: (i) => i.status === "RUNNING"
                ? <NotSimulated compact feature="SSH" note="No guest OS runs behind this instance." />
                : <Typography variant="body2" color="text.secondary">—</Typography>,
            },
            {
              id: "actions", header: "", width: 48,
              cell: (i) => (
                <IconButton size="small" aria-label={`Actions for ${i.name}`} onClick={(e) => setMenu({ el: e.currentTarget, inst: i })}><MoreVertIcon fontSize="small" /></IconButton>
              ),
            },
          ]}
          empty={
            <Stack spacing={1.5} alignItems="center">
              <Typography variant="body2" color="text.secondary">There are no VM instances in this project.</Typography>
              <Button variant="contained" startIcon={<AddIcon />} href="#/compute/instances/create">Create instance</Button>
            </Stack>
          }
        />
      </TabPanel>
      <TabPanel value={tab} name="observability">
        <CapabilityContainer id="gcp.compute.observability" title="Observability">
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
            Recent lifecycle activity Vyomi actually recorded for VM instances in this project.
          </Typography>
          <ResourceTable
            resourceName="operations"
            items={instanceOps.slice(0, 20)}
            loading={opsLoading}
            columns={[
              { id: "target", header: "Instance", cell: (o) => api.last(o.targetLink) },
              { id: "type", header: "Operation", cell: (o) => o.operationType },
              { id: "status", header: "Status", cell: (o) => o.status },
              { id: "time", header: "Time", cell: (o) => fmtDate(o.endTime) },
            ]}
          />
        </CapabilityContainer>
        <Box sx={{ mt: 2 }}>
          <CapabilityContainer id="gcp.compute.recommender" title="Recommendations">
            <RecommendationsTable />
          </CapabilityContainer>
        </Box>
        <NotSimulated compact feature="VM Manager"
          note="VM Manager (Patch, OS policies, VM Extension Manager) needs a guest OS and patch agent, which Vyomi doesn't run." />
      </TabPanel>
      <TabPanel value={tab} name="schedules">
        <InstanceSchedules instances={data} />
      </TabPanel>

      <Menu anchorEl={menu?.el} open={!!menu} onClose={() => setMenu(null)}>
        {["start", "stop", "suspend", "reset"].map((a) => (
          <MenuItem key={a} onClick={async () => { const inst = menu.inst; setMenu(null); try { await api.instanceAction(inst._zoneScope, inst.name, a); notify.success(`${a} requested for "${inst.name}"`); reload(); } catch (e) { notify.error(e.message); } }}>
            {{ start: "Start / Resume", stop: "Stop", suspend: "Suspend", reset: "Reset" }[a]}
          </MenuItem>
        ))}
        <MenuItem onClick={() => { setSel([`${menu.inst._zoneScope}/${menu.inst.name}`]); setMenu(null); setDel(true); }}>Delete</MenuItem>
        {menu && <MenuItem component="a" href={`#/compute/instances/${menu.inst._zoneScope}/${menu.inst.name}`} onClick={() => setMenu(null)}>View logs</MenuItem>}
        {menu && <MenuItem component="a" href={`#/compute/instances/${menu.inst._zoneScope}/${menu.inst.name}`} onClick={() => setMenu(null)}>View monitoring</MenuItem>}
      </Menu>

      <DeleteDialog
        open={del}
        onClose={() => setDel(false)}
        title={sel.length === 1 ? "Delete instance?" : `Delete ${sel.length} instances?`}
        confirmText={sel.length === 1 ? byKey(sel[0])?.name : "DELETE"}
        warning="Attached disks set to auto-delete are removed as well. This can't be undone."
        onConfirm={async () => {
          for (const k of sel) {
            const inst = byKey(k);
            if (inst) await api.deleteInstance(inst._zoneScope, inst.name);
          }
          notify.success(sel.length === 1 ? `Deleted instance "${byKey(sel[0])?.name}"` : `Deleted ${sel.length} instances`);
          setSel([]);
          reload();
        }}
      >
        <Typography variant="body2">{sel.length === 1 ? <>Instance <b>{byKey(sel[0])?.name}</b> will be permanently deleted.</> : <>{sel.length} instances will be permanently deleted.</>}</Typography>
      </DeleteDialog>

      {importOpen && <ImportVmDialog onClose={() => setImportOpen(false)} onDone={(m) => { notify.success(m); reload(); }} />}
    </>
  );
}

/* Import VM: a .tar.gz disk archive in Cloud Storage -> an image (rawDisk images.insert) -> an instance booting from it. */
function ImportVmDialog({ onClose, onDone }) {
  const [src, setSrc] = useState("gs://");
  const [name, setName] = useState("");
  const [zone, setZone] = useState("us-central1-a");
  const [machine, setMachine] = useState("e2-medium");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const nameErr = name ? api.validResourceName(name) : null;
  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const image = `${name}-imported`;
      await api.importImage(image, src);
      await api.insertInstance(zone, { name, machineType: machine, disks: [{ boot: true, autoDelete: true, initializeParams: { sourceImage: `global/images/${image}` } }] });
      onDone(`Imported VM "${name}" from ${src}`);
      onClose();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Dialog open onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth aria-labelledby="impvm-title">
      <DialogTitle id="impvm-title">Import VM</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <ErrorAlert error={error} title="Failed to import VM" />
          <TextField label="Source disk archive (gs://bucket/disk.tar.gz)" value={src} onChange={(e) => setSrc(e.target.value.trim())} inputProps={{ "aria-label": "VM import source" }} />
          <TextField label="Instance name" value={name} onChange={(e) => setName(e.target.value.trim())} error={!!nameErr} helperText={nameErr || " "} inputProps={{ "aria-label": "Imported instance name" }} />
          <TextField label="Zone" value={zone} onChange={(e) => setZone(e.target.value.trim())} />
          <TextField label="Machine type" value={machine} onChange={(e) => setMachine(e.target.value.trim())} />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy || !name || !!nameErr || src.length < 8} onClick={submit}>{busy ? "Importing…" : "Import"}</Button>
      </DialogActions>
    </Dialog>
  );
}
