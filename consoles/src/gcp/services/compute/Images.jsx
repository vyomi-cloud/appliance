/* Images — list, create-via-dialog (source disk + name + optional family), bulk delete. */
import { useEffect, useState } from "react";
import {
  Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, FormControl, InputLabel,
  MenuItem, Select, Stack, Tab, Tabs, TextField, Typography,
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

function TabPanel({ value, name, children }) {
  return value === name ? <Box sx={{ pt: 2 }}>{children}</Box> : null;
}

function CreateImageDialog({ open, onClose, onCreated }) {
  const [disks, setDisks] = useState([]);
  const [diskKey, setDiskKey] = useState("");
  const [name, setName] = useState("");
  const [family, setFamily] = useState("");
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
      await api.insertImage({ name, sourceDisk: disk.name, family: family || undefined });
      onCreated(name);
      onClose();
      setName(""); setFamily(""); setTouched(false); setDiskKey("");
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Create image</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <ErrorAlert error={error} title="Failed to create image" />
          <FormControl fullWidth>
            <InputLabel id="src-disk-l">Source disk</InputLabel>
            <Select labelId="src-disk-l" label="Source disk" value={diskKey} onChange={(e) => setDiskKey(e.target.value)}>
              {disks.map((d) => <MenuItem key={`${d._zoneScope}/${d.name}`} value={`${d._zoneScope}/${d.name}`}>{d._zoneScope}/{d.name}</MenuItem>)}
            </Select>
          </FormControl>
          <TextField label="Name" required value={name} onChange={(e) => setName(e.target.value.trim())} onBlur={() => setTouched(true)}
            error={!!nameErr} helperText={nameErr || " "} inputProps={{ "aria-label": "Image name" }} />
          <TextField label="Family (optional)" value={family} onChange={(e) => setFamily(e.target.value.trim())} />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy || !disk} onClick={submit}>{busy ? "Creating…" : "Create"}</Button>
      </DialogActions>
    </Dialog>
  );
}

function ImportImageDialog({ open, onClose, onDone }) {
  const [name, setName] = useState("");
  const [src, setSrc] = useState("gs://");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async () => {
    setBusy(true); setError(null);
    try { await api.importImage(name, src); onDone(`Imported image "${name}"`); setName(""); setSrc("gs://"); onClose(); }
    catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth aria-labelledby="imp-title">
      <DialogTitle id="imp-title">Import image</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <ErrorAlert error={error} title="Failed to import image" />
          <TextField label="Source (Cloud Storage .tar.gz containing disk.raw)" value={src} onChange={(e) => setSrc(e.target.value.trim())} inputProps={{ "aria-label": "Import source" }} />
          <TextField label="Image name" value={name} onChange={(e) => setName(e.target.value.trim())} error={!!name && !!api.validResourceName(name)} helperText={name ? api.validResourceName(name) || " " : " "} inputProps={{ "aria-label": "Imported image name" }} />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy || !name || !!api.validResourceName(name) || src.length < 8} onClick={submit}>{busy ? "Importing…" : "Import"}</Button>
      </DialogActions>
    </Dialog>
  );
}

function ExportImageDialog({ image, onClose, onDone }) {
  const [dest, setDest] = useState("gs://");
  const [fmt, setFmt] = useState("raw");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async () => {
    setBusy(true); setError(null);
    try { await api.exportImage(image, dest, fmt); onDone(`Exported image "${image}"`); onClose(); }
    catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Dialog open onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth aria-labelledby="exp-title">
      <DialogTitle id="exp-title">Export image {image}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <ErrorAlert error={error} title="Failed to export image" />
          <TextField label="Destination (gs://bucket/file.tar.gz)" value={dest} onChange={(e) => setDest(e.target.value.trim())} inputProps={{ "aria-label": "Export destination" }} />
          <FormControl fullWidth>
            <InputLabel id="exp-fmt">Format</InputLabel>
            <Select labelId="exp-fmt" label="Format" value={fmt} onChange={(e) => setFmt(e.target.value)}>
              {["raw", "vmdk", "vpc", "vhdx", "vdi", "qcow2"].map((f) => <MenuItem key={f} value={f}>{f}</MenuItem>)}
            </Select>
          </FormControl>
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy || dest.length < 8} onClick={submit}>{busy ? "Exporting…" : "Export"}</Button>
      </DialogActions>
    </Dialog>
  );
}

function JobHistory({ kind }) {
  const { data = [], loading, error, reload } = useAsync(() => api.listImageJobs(kind), [kind]);
  return (
    <ResourceTable resourceName={`image ${kind}s`} items={data} rowKey={(j) => j.id} loading={loading} error={error} onRetry={reload}
      filterPlaceholder="Filter history"
      columns={[
        { id: "status", header: "Status", sortField: "status", cell: (j) => j.status },
        { id: "image", header: "Image", sortField: "image", cell: (j) => j.image },
        { id: "uri", header: kind === "import" ? "Source" : "Destination", cell: (j) => j.uri },
        { id: "started", header: "Started", sortField: "startTime", cell: (j) => fmtDate(j.startTime) },
        { id: "error", header: "Error", cell: (j) => j.error || "—" },
      ]}
      empty={<Typography variant="body2" color="text.secondary">No image {kind}s have been run in this project.</Typography>} />
  );
}

export default function Images() {
  const notify = useNotify();
  const project = useProject();
  const [tab, setTab] = useState("images");
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [exportName, setExportName] = useState(null);
  const { data = [], loading, error, reload } = useAsync(() => api.listImages(), [project]);

  return (
    <>
      <PageHeader title="Images" actions={<>
        <Button startIcon={<AddIcon />} onClick={() => setCreateOpen(true)}>Create image</Button>
        <Button onClick={() => setImportOpen(true)}>Import image</Button>
        <Button disabled={sel.length !== 1} onClick={() => setExportName(sel[0])}>Export image</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
      </>} />
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        <Tab label="Images" value="images" />
        <Tab label="Image import history" value="import" />
        <Tab label="Image export history" value="export" />
      </Tabs>
      <TabPanel value={tab} name="images">
        <ResourceTable
          resourceName="images"
          items={data}
          loading={loading}
          error={error}
          onRetry={reload}
          selectable
          selected={sel}
          onSelectedChange={setSel}
          filterPlaceholder="Enter property name or value"
          columns={[
            { id: "status", header: "Status", sortField: "status", cell: (i) => i.status },
            { id: "name", header: "Name", sortField: "name", cell: (i) => i.name },
            { id: "location", header: "Location", cell: (i) => i._display?.location || "—" },
            { id: "archiveSize", header: "Archive size", sortField: "archiveSizeBytes", cell: (i) => fmtBytes(i.archiveSizeBytes) },
            { id: "diskSize", header: "Disk size", sortField: "diskSizeGb", cell: (i) => `${i.diskSizeGb} GB` },
            { id: "createdBy", header: "Created by", cell: (i) => i._display?.createdBy || "—" },
            { id: "family", header: "Family", sortField: "family", cell: (i) => i.family || "—" },
            { id: "created", header: "Creation time", sortField: "creationTimestamp", cell: (i) => fmtDate(i.creationTimestamp) },
          ]}
          empty={
            <Stack spacing={1.5} alignItems="center">
              <Typography variant="body2" color="text.secondary">There are no images in this project.</Typography>
              <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreateOpen(true)}>Create image</Button>
            </Stack>
          }
        />
      </TabPanel>
      <TabPanel value={tab} name="import">
        <JobHistory kind="import" key={`i${tab}${importOpen}${data.length}`} />
      </TabPanel>
      <TabPanel value={tab} name="export">
        <JobHistory kind="export" key={`e${tab}${exportName}`} />
      </TabPanel>

      <ImportImageDialog open={importOpen} onClose={() => setImportOpen(false)} onDone={(m) => { notify.success(m); reload(); }} />
      {exportName && <ExportImageDialog image={exportName} onClose={() => setExportName(null)} onDone={(m) => notify.success(m)} />}
      <CreateImageDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={(name) => { notify.success(`Created image "${name}"`); reload(); }}
      />

      <DeleteDialog
        open={del}
        onClose={() => setDel(false)}
        title={sel.length === 1 ? "Delete image?" : `Delete ${sel.length} images?`}
        confirmText={sel.length === 1 ? sel[0] : "DELETE"}
        warning="Deleted images can't be recovered. This can't be undone."
        onConfirm={async () => {
          for (const n of sel) await api.deleteImage(n);
          notify.success(sel.length === 1 ? `Deleted image "${sel[0]}"` : `Deleted ${sel.length} images`);
          setSel([]);
          reload();
        }}
      >
        <Typography variant="body2">{sel.length === 1 ? <>Image <b>{sel[0]}</b> will be permanently deleted.</> : <>{sel.length} images will be permanently deleted.</>}</Typography>
      </DeleteDialog>
    </>
  );
}
