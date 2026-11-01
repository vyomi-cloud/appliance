/* Bucket details: summary strip + tabs (Objects, Configuration, Permissions, Protection,
 * Lifecycle, Observability, Inventory reports, Operations), all on the native GCS API. */
import { useRef, useState } from "react";
import {
  Alert, Box, Breadcrumbs, Button, Chip, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, FormControl,
  FormControlLabel, IconButton, InputLabel, MenuItem, Radio, RadioGroup, Select, Stack, Tab, Tabs, TextField, Tooltip, Typography,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import UploadIcon from "@mui/icons-material/esm/Upload.js";
import CreateNewFolderIcon from "@mui/icons-material/esm/CreateNewFolder.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import DownloadIcon from "@mui/icons-material/esm/Download.js";
import FolderIcon from "@mui/icons-material/esm/Folder.js";
import InsertDriveFileIcon from "@mui/icons-material/esm/InsertDriveFile.js";
import EditIcon from "@mui/icons-material/esm/Edit.js";
import AddIcon from "@mui/icons-material/esm/Add.js";
import ContentCopyIcon from "@mui/icons-material/esm/ContentCopy.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, fmtBytes, fmtDate, fmtDuration, KeyValue, NotSimulated, PageHeader, Section } from "../../kit/common.jsx";
import { CapabilityBadge, CapabilityContainer } from "../../kit/Capability.jsx";
import { Link, hashHref } from "../../link.jsx";
import * as api from "./api.js";

const TABS = [
  ["objects", "Objects"], ["configuration", "Configuration"], ["permissions", "Permissions"], ["protection", "Protection"],
  ["lifecycle", "Lifecycle"], ["observability", "Observability"], ["inventory", "Inventory reports"], ["operations", "Operations"],
];
const bucketHref = (b, q = {}) => {
  const qs = new URLSearchParams(Object.entries(q).filter(([, v]) => v)).toString();
  return hashHref("storage", "browser", b) + (qs ? "?" + qs : "");
};

export default function BucketDetail({ params, query }) {
  const bucket = params.name;
  const tab = TABS.some(([t]) => t === query.tab) ? query.tab : "objects";
  const b = useAsync(() => api.getBucket(bucket), [bucket]);
  const pol = useAsync(() => api.getIamPolicy(bucket).catch(() => null), [bucket]);
  const reloadAll = () => { b.reload(); pol.reload(); };

  return (
    <>
      <PageHeader title="Bucket details" back={<IconButton aria-label="Back to buckets" href="#/storage/browser"><ArrowBackIcon /></IconButton>}
        actions={<Button startIcon={<RefreshIcon />} onClick={reloadAll}>Refresh</Button>} />
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1.5 }}>
        <Typography variant="h2" component="h2" sx={{ fontSize: 22 }}>{bucket}</Typography>
        <Tooltip title="Copy bucket name"><IconButton size="small" aria-label="Copy bucket name" onClick={() => navigator.clipboard?.writeText(bucket).catch(() => {})}><ContentCopyIcon fontSize="inherit" /></IconButton></Tooltip>
      </Stack>
      {b.error ? <ErrorAlert error={b.error} title="Failed to load bucket" /> : (
        <Stack direction="row" spacing={4} sx={{ mb: 1, flexWrap: "wrap", rowGap: 1 }} aria-label="Bucket summary">
          {[["Location", b.data && `${b.data.location.toLowerCase()} (${api.LOCATION_TYPE_LABEL[b.data.locationType]})`],
            ["Storage class", b.data && api.classLabel(b.data.storageClass)],
            ["Public access", b.data && api.publicAccess(b.data, pol.data)],
            ["Protection", b.data && api.protection(b.data)]].map(([k, v]) => (
            <Box key={k}><Typography variant="caption" color="text.secondary">{k}</Typography><Typography variant="body2">{v || "…"}</Typography></Box>
          ))}
        </Stack>
      )}
      <Tabs value={tab} onChange={(_, t) => { location.hash = bucketHref(bucket, { tab: t === "objects" ? "" : t }).slice(1); }}
        variant="scrollable" scrollButtons="auto" sx={{ borderBottom: 1, borderColor: "divider", mb: 2.5 }} aria-label="Bucket tabs">
        {TABS.map(([id, label]) => <Tab key={id} value={id} label={label} />)}
      </Tabs>
      {tab === "objects" && <Objects bucket={bucket} prefix={query.prefix || ""} meta={b.data} policy={pol.data} />}
      {tab !== "objects" && !b.data && !b.error && <CircularProgress size={24} />}
      {tab === "configuration" && b.data && <Configuration bucket={b.data} reload={b.reload} />}
      {tab === "permissions" && b.data && <Permissions bucket={b.data} policy={pol} reload={reloadAll} />}
      {tab === "protection" && b.data && <Protection bucket={b.data} reload={b.reload} />}
      {tab === "lifecycle" && b.data && <Lifecycle bucket={b.data} reload={b.reload} />}
      {tab === "observability" && <Observability bucket={bucket} />}
      {tab === "inventory" && <CapabilityContainer id="gcp.storage.inventory-reports" title="Inventory reports" />}
      {tab === "operations" && <Operations bucket={bucket} />}
    </>
  );
}

// ── Observability (gcp.storage.observability — real request-count metering) ───────────
function Observability({ bucket }) {
  const [hours, setHours] = useState("1");
  const series = useAsync(() => api.getRequestCountSeries(bucket, Number(hours)), [bucket, hours]);
  const total = (series.data || []).reduce((n, p) => n + p.v, 0);
  const vals = (series.data || []).map((p) => p.v);
  const max = Math.max(...vals, 1);
  const d = vals.map((v, i) => `${i === 0 ? "M" : "L"} ${(i / Math.max(vals.length - 1, 1)) * 320} ${40 - (v / max) * 36}`).join(" ");
  return (
    <CapabilityContainer id="gcp.storage.observability" title="Monitoring"
      description="Real request-count metering, fed by actual API activity against this bucket."
      actions={<FormControl size="small" sx={{ minWidth: 160 }}>
        <InputLabel id="obs-range">Time range</InputLabel>
        <Select labelId="obs-range" label="Time range" value={hours} onChange={(e) => setHours(e.target.value)}>
          <MenuItem value="1">Last hour</MenuItem>
          <MenuItem value="6">Last 6 hours</MenuItem>
          <MenuItem value="24">Last 24 hours</MenuItem>
        </Select>
      </FormControl>}>
      <Typography variant="body2" sx={{ mb: 1 }}><b>{total}</b> API requests in the selected range</Typography>
      {vals.length
        ? <svg width={320} height={44} role="img" aria-label="Request count over time"><path d={d} fill="none" stroke="currentColor" strokeWidth={1.5} /></svg>
        : <Typography variant="body2" color="text.secondary">No requests recorded yet for this bucket in the selected range.</Typography>}
    </CapabilityContainer>
  );
}

// ── Operations ──────────────────────────────────────────────────────────────────────────
function Operations({ bucket }) {
  const { data, loading, error, reload } = useAsync(() => api.listBucketOperations(bucket), [bucket]);
  const ops = (data || []).map((o) => ({ ...o, key: o.name, id: o.name.split("/").pop() }));
  return (
    <Stack spacing={2}>
      <Stack direction="row" alignItems="center" spacing={1}>
        <Typography variant="h3" component="h2">Long-running bucket operations</Typography>
        <CapabilityBadge id="gcp.storage.operations" />
        <Box sx={{ flex: 1 }} />
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
      </Stack>
      {error && <ErrorAlert error={error} />}
      <ResourceTable resourceName="operations" items={ops} rowKey={(o) => o.key} loading={loading} dense
        filterPlaceholder="Filter operations"
        columns={[
          { id: "id", header: "Operation ID", cell: (o) => o.id },
          { id: "type", header: "Type", cell: (o) => o.metadata?.type },
          { id: "status", header: "Status", cell: (o) => o.done ? "Done" : "Running" },
          { id: "created", header: "Created", sortValue: (o) => o.metadata?.createTime || "", cell: (o) => fmtDate(o.metadata?.createTime) },
          { id: "updated", header: "Updated", sortValue: (o) => o.metadata?.endTime || "", cell: (o) => fmtDate(o.metadata?.endTime) },
        ]}
        empty={<Typography variant="body2" color="text.secondary">No operations have run on this bucket yet — try switching Turbo replication on a dual-region bucket.</Typography>} />
    </Stack>
  );
}

// ── Objects ─────────────────────────────────────────────────────────────────────────────
function Objects({ bucket, prefix, meta, policy }) {
  const notify = useNotify();
  const file = useRef(null);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [folder, setFolder] = useState(null);
  const [busy, setBusy] = useState(false);
  const { data, loading, error, reload } = useAsync(() => api.listLevel(bucket, prefix), [bucket, prefix]);
  const items = data ? [...data.folders, ...data.objects] : [];
  const crumbs = prefix.split("/").filter(Boolean);
  const retention = Number(meta?.retentionPolicy?.retentionPeriod || 0);

  const upload = async (files) => {
    setBusy(true);
    try {
      for (const f of files) await api.uploadObject(bucket, prefix + f.name, f, f.type);
      notify.success(`Uploaded ${files.length} file${files.length === 1 ? "" : "s"}`);
      reload();
    } catch (e) { notify.error(e, "Upload failed"); }
    finally { setBusy(false); if (file.current) file.current.value = ""; }
  };

  return (
    <>
      <input ref={file} type="file" multiple hidden onChange={(e) => e.target.files.length && upload([...e.target.files])} aria-label="Upload files" />
      <Breadcrumbs sx={{ mb: 1.5 }} aria-label="Object path">
        <Link href="#/storage/browser">Buckets</Link>
        {crumbs.length ? <Link href={bucketHref(bucket)}>{bucket}</Link> : <Typography variant="body2" sx={{ fontWeight: 500 }}>{bucket}</Typography>}
        {crumbs.map((c, i) => i === crumbs.length - 1
          ? <Typography key={i} variant="body2" sx={{ fontWeight: 500 }}>{c}</Typography>
          : <Link key={i} href={bucketHref(bucket, { prefix: crumbs.slice(0, i + 1).join("/") + "/" })}>{c}</Link>)}
      </Breadcrumbs>
      <Stack direction="row" spacing={0.5} sx={{ mb: 1.5, flexWrap: "wrap" }}>
        <Button variant="contained" startIcon={busy ? <CircularProgress size={16} color="inherit" /> : <UploadIcon />} disabled={busy} onClick={() => file.current?.click()}>Upload</Button>
        <Button startIcon={<CreateNewFolderIcon />} onClick={() => setFolder("")}>Create folder</Button>
        <Button startIcon={<DownloadIcon />} disabled={sel.length !== 1 || sel[0].endsWith("/")}
          href={sel.length === 1 && !sel[0].endsWith("/") ? api.downloadUrl(bucket, sel[0]) : undefined} download={sel[0]?.split("/").pop()}>Download</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
      </Stack>
      <ResourceTable
        resourceName="objects and folders"
        items={items}
        rowKey={(o) => o.key}
        loading={loading}
        error={error}
        onRetry={reload}
        selectable
        selected={sel}
        onSelectedChange={setSel}
        filterPlaceholder="Filter objects and folders"
        dense
        columns={[
          { id: "name", header: "Name", sortValue: (o) => (o.folder ? "0" : "1") + (o.name || o.display), cell: (o) => o.folder
            ? <Stack direction="row" spacing={1} alignItems="center"><FolderIcon fontSize="small" sx={{ color: "text.secondary" }} /><Link href={bucketHref(bucket, { prefix: o.key })}>{o.name}</Link></Stack>
            : <Stack direction="row" spacing={1} alignItems="center"><InsertDriveFileIcon fontSize="small" sx={{ color: "text.secondary" }} /><Link href={hashHref("storage", "browser", bucket, "object") + "?name=" + encodeURIComponent(o.key)}>{o.display}</Link></Stack> },
          { id: "size", header: "Size", sortValue: (o) => Number(o.size || 0), cell: (o) => o.folder ? "—" : fmtBytes(o.size) },
          { id: "type", header: "Type", cell: (o) => o.folder ? "Folder" : o.contentType },
          { id: "created", header: "Created", sortValue: (o) => o.timeCreated || "", cell: (o) => o.folder ? "—" : fmtDate(o.timeCreated) },
          { id: "class", header: "Storage class", cell: (o) => o.folder ? "—" : api.classLabel(o.storageClass) },
          { id: "updated", header: "Last modified", sortValue: (o) => o.updated || "", cell: (o) => o.folder ? "—" : fmtDate(o.updated) },
          { id: "public", header: "Public access", cell: (o) => o.folder ? "—" : (meta ? api.publicAccess(meta, policy) : "…") },
          { id: "retention", header: "Retention expiration date", cell: (o) => o.folder || !retention ? "—" : fmtDate(new Date(new Date(o.updated).getTime() + retention * 1000)) },
        ]}
        empty={<Typography variant="body2" color="text.secondary">No rows to display. Upload files or create a folder.</Typography>}
      />
      <Box sx={{ mt: 1.5 }}><NotSimulated compact feature="Per-object customer-managed encryption keys" note="Object holds, object retention and — on a bucket with versioning/soft delete on — noncurrent version history are real; see the bucket's Protection tab." /></Box>
      <DeleteDialog
        open={del}
        onClose={() => setDel(false)}
        title={`Delete ${sel.length} item${sel.length === 1 ? "" : "s"}?`}
        confirmText="DELETE"
        warning={sel.some((k) => k.endsWith("/")) ? "Deleting a folder deletes every object in it." : undefined}
        onConfirm={async () => {
          for (const k of sel) {
            if (k.endsWith("/")) await api.deletePrefix(bucket, k);
            else await api.deleteObject(bucket, k);
          }
          notify.success(`Deleted ${sel.length} item${sel.length === 1 ? "" : "s"}`);
          setSel([]); reload();
        }}
      >
        <Typography variant="body2">{sel.join(", ")}</Typography>
      </DeleteDialog>
      <Dialog open={folder !== null} onClose={() => setFolder(null)} maxWidth="xs" fullWidth aria-labelledby="cf-title">
        <DialogTitle id="cf-title">Create folder</DialogTitle>
        <DialogContent>
          <TextField autoFocus fullWidth label="Name" sx={{ mt: 1 }} value={folder || ""} onChange={(e) => setFolder(e.target.value)} inputProps={{ "aria-label": "Folder name" }}
            error={!!folder && folder.includes("/")} helperText={folder && folder.includes("/") ? "Folder names can't contain \"/\"." : `Created in gs://${bucket}/${prefix}`} />
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={() => setFolder(null)}>Cancel</Button>
          <Button variant="contained" disabled={!folder || folder.includes("/")} onClick={async () => {
            try { await api.createFolder(bucket, prefix + folder); notify.success(`Created folder "${folder}"`); setFolder(null); reload(); }
            catch (e) { notify.error(e); }
          }}>Create</Button>
        </DialogActions>
      </Dialog>
    </>
  );
}

// ── Configuration ───────────────────────────────────────────────────────────────────────
function Configuration({ bucket, reload }) {
  const notify = useNotify();
  const [editLabels, setEditLabels] = useState(false);
  const [editClass, setEditClass] = useState(false);
  const [editWebsite, setEditWebsite] = useState(false);
  const [editKms, setEditKms] = useState(false);
  const ls = Object.entries(bucket.labels || {});
  const patch = async (body, msg) => { await api.patchBucket(bucket.name, body); notify.success(msg); reload(); };
  return (
    <Stack spacing={2}>
      <Section title="Overview">
        <KeyValue items={[
          ["Created", fmtDate(bucket.timeCreated)],
          ["Updated", fmtDate(bucket.updated)],
          ["Location type", api.LOCATION_TYPE_LABEL[bucket.locationType]],
          ["Location", bucket.location.toLowerCase()],
          ["Default storage class", api.classLabel(bucket.storageClass), <IconButton key="e" size="small" aria-label="Edit default storage class" onClick={() => setEditClass(true)}><EditIcon fontSize="inherit" /></IconButton>],
          ["Hierarchical namespace", bucket.hierarchicalNamespace?.enabled ? "Enabled" : "Disabled"],
          ["Requester pays", bucket.billing?.requesterPays ? "Enabled" : "Not enabled"],
          ["Labels", ls.length ? <Stack direction="row" spacing={0.5} sx={{ flexWrap: "wrap", rowGap: 0.5 }}>{ls.map(([k, v]) => <Chip key={k} size="small" label={`${k}: ${v}`} />)}</Stack> : "None",
            <IconButton key="e" size="small" aria-label="Edit labels" onClick={() => setEditLabels(true)}><EditIcon fontSize="inherit" /></IconButton>],
          ["gsutil URI", `gs://${bucket.name}`],
          ["Cloud Console URL", `console.vyomi.cloud/storage/browser/${bucket.name}`],
          ["Metageneration", bucket.metageneration],
          ...(bucket.rpo ? [["Replication", bucket.rpo === "ASYNC_TURBO" ? "Turbo" : "Default"]] : []),
        ]} />
      </Section>
      <CapabilityContainer id="gcp.storage.encryption" title="Data encryption"
        actions={<Button variant="outlined" startIcon={bucket.encryption?.defaultKmsKeyName ? <EditIcon /> : <AddIcon />} onClick={() => setEditKms(true)}>
          {bucket.encryption?.defaultKmsKeyName ? "Edit Cloud KMS key" : "Use a Cloud KMS key"}
        </Button>}>
        {bucket.encryption?.defaultKmsKeyName
          ? <KeyValue items={[["Cloud KMS key", bucket.encryption.defaultKmsKeyName]]} />
          : <Typography variant="body2">Google-managed encryption key</Typography>}
      </CapabilityContainer>
      <CapabilityContainer id="gcp.storage.cors" title="Cross-origin resource sharing (CORS)">
        {bucket.cors?.length
          ? <KeyValue items={bucket.cors.map((r, i) => [`Rule ${i + 1}`, `${(r.method || []).join(", ") || "*"} from ${(r.origin || []).join(", ") || "*"}`])} />
          : <Typography variant="body2" color="text.secondary">CORS is not configured for this bucket.</Typography>}
      </CapabilityContainer>
      <CapabilityContainer id="gcp.storage.static-website" title="Static website configuration"
        actions={<Button variant="outlined" startIcon={bucket.website ? <EditIcon /> : <AddIcon />} onClick={() => setEditWebsite(true)}>Edit website configuration</Button>}>
        {bucket.website
          ? <KeyValue items={[
              ["Index (main) page suffix", bucket.website.mainPageSuffix || "—"],
              ["Error (404 not found) page", bucket.website.notFoundPage || "—"],
              ["Website endpoint", <Link key="url" href={api.websiteUrl(bucket.name)} target="_blank" rel="noopener">{api.websiteUrl(bucket.name)}</Link>],
            ]} />
          : <Typography variant="body2" color="text.secondary">Static website hosting is not configured for this bucket.</Typography>}
      </CapabilityContainer>
      <Tags bucket={bucket.name} />
      {bucket.hierarchicalNamespace?.enabled && <Folders bucket={bucket.name} />}
      {editLabels && <LabelsDialog labels={bucket.labels || {}} onClose={() => setEditLabels(false)} onSave={async (next) => {
        const body = { ...Object.fromEntries(Object.keys(bucket.labels || {}).map((k) => [k, null])), ...next };
        await patch({ labels: body }, "Updated labels");
      }} />}
      {editClass && <ClassDialog value={bucket.storageClass} onClose={() => setEditClass(false)} onSave={(v) => patch({ storageClass: v }, "Updated default storage class")} />}
      {editWebsite && <WebsiteDialog website={bucket.website} onClose={() => setEditWebsite(false)}
        onSave={(w) => patch({ website: w }, "Updated website configuration")} />}
      {editKms && <KmsDialog current={bucket.encryption?.defaultKmsKeyName} onClose={() => setEditKms(false)}
        onSave={(name) => patch({ encryption: name ? { defaultKmsKeyName: name } : null }, name ? "Cloud KMS key set" : "Reverted to Google-managed encryption")} />}
    </Stack>
  );
}

// ── Tags (GCP-wide resource tags, distinct from labels — gcp.storage.tags) ──────────────
function Tags({ bucket }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listTags(bucket), [bucket]);
  const [add, setAdd] = useState(false);
  const rows = (data || []).map((b) => {
    const parts = (b.tagValueNamespacedName || "").split("/");
    return { ...b, key: b.name, keyName: parts[parts.length - 2] || "", value: parts[parts.length - 1] || "" };
  });
  return (
    <CapabilityContainer id="gcp.storage.tags" title="Tags"
      description="GCP-wide resource tags (Resource Manager tagKeys/tagValues bindings) — distinct from labels."
      actions={<Button variant="outlined" startIcon={<AddIcon />} onClick={() => setAdd(true)}>Add tag</Button>}>
      {error && <ErrorAlert error={error} />}
      <ResourceTable resourceName="tags" items={rows} rowKey={(r) => r.key} loading={loading} dense
        columns={[
          { id: "key", header: "Key", cell: (r) => r.keyName },
          { id: "value", header: "Value", cell: (r) => r.value },
          { id: "remove", header: "", cell: (r) => <IconButton size="small" aria-label={`Remove tag ${r.keyName}`} onClick={async () => {
              try { await api.removeTagBinding(r.name); notify.success(`Removed tag ${r.keyName}`); reload(); } catch (e) { notify.error(e); }
            }}><DeleteIcon fontSize="small" /></IconButton> },
        ]}
        empty={<Typography variant="body2" color="text.secondary">No tags are attached to this bucket.</Typography>} />
      {add && <TagDialog onClose={() => setAdd(false)} onSave={async (k, v) => {
        await api.addTag(bucket, k, v); notify.success(`Added tag ${k}: ${v}`); reload();
      }} />}
    </CapabilityContainer>
  );
}

function TagDialog({ onClose, onSave }) {
  const [key, setKey] = useState("");
  const [value, setValue] = useState("");
  const ok = /^[a-z][a-z0-9_-]{0,62}$/.test(key) && /^[a-z0-9][a-z0-9_-]{0,62}$/.test(value);
  return (
    <SaveDialog title="Add tag" onClose={onClose} disabled={!ok} onSave={() => onSave(key, value)}>
      <TextField label="Key" value={key} onChange={(e) => setKey(e.target.value.trim())} helperText="e.g. env" />
      <TextField label="Value" value={value} onChange={(e) => setValue(e.target.value.trim())} helperText="e.g. prod" />
    </SaveDialog>
  );
}

// ── Folders (hierarchical namespace — gcp.storage.hierarchical-namespace) ──────────────
function Folders({ bucket }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listFolders(bucket), [bucket]);
  const [add, setAdd] = useState(false);
  const [rename, setRename] = useState(null);
  const rows = (data || []).map((f) => ({ ...f, key: f.name }));
  return (
    <CapabilityContainer id="gcp.storage.hierarchical-namespace" title="Folders"
      description="Real folders on this hierarchical-namespace bucket — renaming one moves every object and subfolder beneath it in a single atomic operation."
      actions={<Button variant="outlined" startIcon={<AddIcon />} onClick={() => setAdd(true)}>Create folder</Button>}>
      {error && <ErrorAlert error={error} />}
      <ResourceTable resourceName="folders" items={rows} rowKey={(f) => f.key} loading={loading} dense
        filterPlaceholder="Filter folders"
        columns={[
          { id: "name", header: "Name", cell: (f) => f.name },
          { id: "updated", header: "Updated", sortValue: (f) => f.updateTime || "", cell: (f) => fmtDate(f.updateTime) },
          { id: "actions", header: "", cell: (f) => <Stack direction="row">
              <Button size="small" onClick={() => setRename(f)}>Rename</Button>
              <IconButton size="small" aria-label={`Delete folder ${f.name}`} onClick={async () => {
                try { await api.deleteHnsFolder(bucket, f.name); notify.success(`Deleted folder "${f.name}"`); reload(); }
                catch (e) { notify.error(e); }
              }}><DeleteIcon fontSize="small" /></IconButton>
            </Stack> },
        ]}
        empty={<Typography variant="body2" color="text.secondary">No folders yet.</Typography>} />
      {add && <FolderDialog title="Create folder" onClose={() => setAdd(false)} onSave={async (name) => {
        await api.createHnsFolder(bucket, name, true); notify.success(`Created folder "${name}"`); reload();
      }} />}
      {rename && <FolderDialog title={`Rename "${rename.name}"`} initial={rename.name} onClose={() => setRename(null)} onSave={async (name) => {
        await api.renameHnsFolder(bucket, rename.name, name); notify.success(`Renamed to "${name}"`); reload();
      }} />}
    </CapabilityContainer>
  );
}

function FolderDialog({ title, initial, onClose, onSave }) {
  const [name, setName] = useState(initial || "");
  const ok = /^[^/]+(\/[^/]+)*\/?$/.test(name) && name.length > 0;
  return (
    <SaveDialog title={title} onClose={onClose} disabled={!ok} onSave={() => onSave(name.endsWith("/") ? name : name + "/")}>
      <TextField label="Folder path" value={name} onChange={(e) => setName(e.target.value)} helperText="e.g. logs/2026/" autoFocus />
    </SaveDialog>
  );
}

function KmsDialog({ current, onClose, onSave }) {
  const [name, setName] = useState(current || "");
  const valid = !name || /^projects\/[^/]+\/locations\/[^/]+\/keyRings\/[^/]+\/cryptoKeys\/[^/]+$/.test(name);
  return (
    <SaveDialog title="Use a Cloud KMS key" onClose={onClose} disabled={!valid} onSave={() => onSave(name || null)}>
      <Typography variant="body2" color="text.secondary">Vyomi validates the key's resource name and stamps it on every object written to this bucket from now on, but does not perform real envelope encryption with it.</Typography>
      <TextField label="Cloud KMS key" value={name} onChange={(e) => setName(e.target.value)} error={!valid}
        helperText={valid ? "Leave blank to revert to a Google-managed key." : "projects/P/locations/L/keyRings/R/cryptoKeys/K"} />
    </SaveDialog>
  );
}

function WebsiteDialog({ website, onClose, onSave }) {
  const [main, setMain] = useState(website?.mainPageSuffix || "index.html");
  const [notFound, setNotFound] = useState(website?.notFoundPage || "404.html");
  return (
    <SaveDialog title="Edit website configuration" onClose={onClose} onSave={() => onSave({ mainPageSuffix: main, notFoundPage: notFound })}>
      <TextField label="Index (main) page suffix" value={main} onChange={(e) => setMain(e.target.value)} />
      <TextField label="Error (404 not found) page" value={notFound} onChange={(e) => setNotFound(e.target.value)} />
    </SaveDialog>
  );
}

function SaveDialog({ title, onClose, onSave, children, disabled }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  return (
    <Dialog open onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth aria-label={title}>
      <DialogTitle>{title}</DialogTitle>
      <DialogContent><Stack spacing={2} sx={{ pt: 1 }}>{children}{error && <Alert severity="error">{error.message}</Alert>}</Stack></DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy || disabled} onClick={async () => { setBusy(true); setError(null); try { await onSave(); onClose(); } catch (e) { setError(e); } finally { setBusy(false); } }}>Save</Button>
      </DialogActions>
    </Dialog>
  );
}

function LabelsDialog({ labels, onClose, onSave }) {
  const [rows, setRows] = useState(Object.entries(labels).map(([key, value]) => ({ key, value })));
  const bad = rows.some((r) => !/^[a-z][a-z0-9_-]{0,62}$/.test(r.key));
  return (
    <SaveDialog title="Edit labels" onClose={onClose} disabled={bad} onSave={() => onSave(Object.fromEntries(rows.map((r) => [r.key, r.value])))}>
      {rows.map((r, i) => (
        <Stack key={i} direction="row" spacing={1} alignItems="center">
          <TextField label={`Key ${i + 1}`} value={r.key} onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, key: e.target.value } : x))} />
          <TextField label={`Value ${i + 1}`} value={r.value} onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, value: e.target.value } : x))} />
          <IconButton aria-label={`Delete label ${i + 1}`} onClick={() => setRows(rows.filter((_, j) => j !== i))}><DeleteIcon fontSize="small" /></IconButton>
        </Stack>
      ))}
      <Box><Button startIcon={<AddIcon />} onClick={() => setRows([...rows, { key: "", value: "" }])}>Add label</Button></Box>
    </SaveDialog>
  );
}

function ClassDialog({ value, onClose, onSave }) {
  const [v, setV] = useState(value);
  return (
    <SaveDialog title="Edit default storage class" onClose={onClose} onSave={() => onSave(v)}>
      <Typography variant="body2" color="text.secondary">Changing the default class only affects objects added from now on.</Typography>
      <RadioGroup value={v} onChange={(e) => setV(e.target.value)}>
        {api.STORAGE_CLASSES.map(([c, l, d]) => <FormControlLabel key={c} value={c} control={<Radio size="small" />} label={<><b>{l}</b> — {d}</>} />)}
      </RadioGroup>
    </SaveDialog>
  );
}

// ── Permissions ─────────────────────────────────────────────────────────────────────────
const ROLES = [
  ["roles/storage.objectViewer", "Storage Object Viewer"], ["roles/storage.objectCreator", "Storage Object Creator"],
  ["roles/storage.objectUser", "Storage Object User"], ["roles/storage.objectAdmin", "Storage Object Admin"],
  ["roles/storage.admin", "Storage Admin"], ["roles/storage.legacyBucketOwner", "Storage Legacy Bucket Owner"],
  ["roles/storage.legacyBucketReader", "Storage Legacy Bucket Reader"], ["roles/storage.legacyObjectOwner", "Storage Legacy Object Owner"],
  ["roles/storage.legacyObjectReader", "Storage Legacy Object Reader"],
];
const roleName = (r) => ROLES.find(([v]) => v === r)?.[1] || r;

function Permissions({ bucket, policy, reload }) {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [grant, setGrant] = useState(false);
  const [busy, setBusy] = useState(false);
  const pap = bucket.iamConfiguration?.publicAccessPrevention === "enforced";
  const uniform = bucket.iamConfiguration?.uniformBucketLevelAccess?.enabled;
  const rows = (policy.data?.bindings || []).flatMap((b) => b.members.map((m) => ({ key: `${m}|${b.role}`, member: m, role: b.role })));
  const patchIam = async (iam, msg) => {
    setBusy(true);
    try { await api.patchBucket(bucket.name, { iamConfiguration: { ...bucket.iamConfiguration, ...iam } }); notify.success(msg); reload(); }
    catch (e) { notify.error(e); } finally { setBusy(false); }
  };
  const writePolicy = async (bindings) => {
    await api.setIamPolicy(bucket.name, { ...policy.data, bindings });
    reload();
  };
  return (
    <Stack spacing={2}>
      <Section title={<Stack direction="row" spacing={1} alignItems="center"><span>Public access</span><CapabilityBadge id="gcp.storage.permissions" /></Stack>} actions={
        <Button variant="outlined" disabled={busy} onClick={() => patchIam({ publicAccessPrevention: pap ? "inherited" : "enforced" }, pap ? "Removed public access prevention" : "Public access prevention enforced")}>
          {pap ? "Remove public access prevention" : "Prevent public access"}
        </Button>}>
        <Typography variant="body2">{api.publicAccess(bucket, policy.data)}</Typography>
        <Typography variant="body2" color="text.secondary">{pap ? "Public access prevention is enforced on this bucket." : "Public access prevention is not enforced on this bucket."}</Typography>
      </Section>
      <Section title="Access control" actions={
        <Button variant="outlined" disabled={busy} onClick={() => patchIam({ uniformBucketLevelAccess: { enabled: !uniform } }, `Switched to ${uniform ? "fine-grained" : "uniform"} access control`)}>
          {uniform ? "Switch to fine-grained" : "Switch to uniform"}
        </Button>}>
        <Typography variant="body2"><b>{uniform ? "Uniform" : "Fine-grained"}</b> — {uniform ? "Access is granted only through bucket-level permissions (IAM)." : "Object-level permissions (ACLs) apply in addition to bucket-level permissions (IAM)."}</Typography>
      </Section>
      <Box>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
          <Typography variant="h3" component="h2">Permissions — View by principals</Typography>
          <CapabilityBadge id="gcp.storage.permissions" />
          <Box sx={{ flex: 1 }} />
          <Button startIcon={<AddIcon />} onClick={() => setGrant(true)}>Grant access</Button>
          <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={async () => {
            try {
              const drop = new Set(sel);
              const next = (policy.data?.bindings || []).map((b) => ({ ...b, members: b.members.filter((m) => !drop.has(`${m}|${b.role}`)) })).filter((b) => b.members.length);
              await writePolicy(next); notify.success(`Removed ${sel.length} role binding${sel.length === 1 ? "" : "s"}`); setSel([]);
            } catch (e) { notify.error(e); }
          }}>Remove access</Button>
        </Stack>
        {policy.error && <ErrorAlert error={policy.error} />}
        <ResourceTable resourceName="principals" items={rows} rowKey={(r) => r.key} loading={policy.loading} selectable selected={sel} onSelectedChange={setSel} dense
          filterPlaceholder="Filter principals"
          columns={[
            { id: "member", header: "Principal", sortField: "member", cell: (r) => r.member },
            { id: "role", header: "Role", sortValue: (r) => roleName(r.role), cell: (r) => roleName(r.role) },
            { id: "roleId", header: "Role ID", cell: (r) => r.role, hidden: true },
          ]} />
      </Box>
      {grant && <GrantDialog onClose={() => setGrant(false)} onSave={async (member, role) => {
        const bs = (policy.data?.bindings || []).map((b) => ({ ...b, members: [...b.members] }));
        const hit = bs.find((b) => b.role === role);
        if (hit) { if (!hit.members.includes(member)) hit.members.push(member); } else bs.push({ role, members: [member] });
        await writePolicy(bs); notify.success(`Granted ${roleName(role)} to ${member}`);
      }} />}
    </Stack>
  );
}

function GrantDialog({ onClose, onSave }) {
  const [member, setMember] = useState("");
  const [role, setRole] = useState(ROLES[0][0]);
  const ok = /^(user|serviceAccount|group|domain):.+/.test(member) || member === "allUsers" || member === "allAuthenticatedUsers";
  return (
    <SaveDialog title={`Grant access`} onClose={onClose} disabled={!ok} onSave={() => onSave(member, role)}>
      <TextField label="New principals" value={member} onChange={(e) => setMember(e.target.value.trim())} inputProps={{ "aria-label": "New principals" }}
        helperText="e.g. user:dev@example.com, serviceAccount:app@vyomi-project.iam.gserviceaccount.com, allUsers" />
      <FormControl><InputLabel id="role-l">Role</InputLabel>
        <Select labelId="role-l" label="Role" value={role} onChange={(e) => setRole(e.target.value)}>
          {ROLES.map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
        </Select>
      </FormControl>
    </SaveDialog>
  );
}

// ── Object versions (gcp.storage.versioning) / soft-deleted objects (gcp.storage.soft-delete)
function ObjectVersions({ bucket }) {
  const { data, loading, error, reload } = useAsync(() => api.listVersions(bucket, false), [bucket]);
  const rows = (data || []).map((o) => ({ ...o, key: `${o.name}#${o.generation}` }));
  return (
    <Box sx={{ mt: 1 }}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
        <Typography variant="body2" sx={{ fontWeight: 500 }}>Object versions</Typography>
        <Box sx={{ flex: 1 }} />
        <Button size="small" startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
      </Stack>
      {error && <ErrorAlert error={error} />}
      <ResourceTable resourceName="versions" items={rows} rowKey={(o) => o.key} loading={loading} dense
        filterPlaceholder="Filter versions"
        columns={[
          { id: "name", header: "Name", cell: (o) => o.name },
          { id: "generation", header: "Generation", sortValue: (o) => Number(o.generation), cell: (o) => o.generation },
          { id: "size", header: "Size", cell: (o) => fmtBytes(o.size) },
          { id: "updated", header: "Last modified", sortValue: (o) => o.updated || "", cell: (o) => fmtDate(o.updated) },
          { id: "status", header: "Status", cell: (o) => o.timeDeleted ? "Noncurrent (deleted)" : "Noncurrent (overwritten)" },
        ]}
        empty={<Typography variant="body2" color="text.secondary">No noncurrent versions yet — overwrite or delete an object to create one.</Typography>} />
    </Box>
  );
}

function SoftDeletedObjects({ bucket }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listVersions(bucket, true), [bucket]);
  const rows = (data || []).map((o) => ({ ...o, key: `${o.name}#${o.generation}` }));
  return (
    <Box sx={{ mt: 1 }}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
        <Typography variant="body2" sx={{ fontWeight: 500 }}>Soft-deleted objects</Typography>
        <Box sx={{ flex: 1 }} />
        <Button size="small" startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
      </Stack>
      {error && <ErrorAlert error={error} />}
      <ResourceTable resourceName="soft-deleted objects" items={rows} rowKey={(o) => o.key} loading={loading} dense
        filterPlaceholder="Filter soft-deleted objects"
        columns={[
          { id: "name", header: "Name", cell: (o) => o.name },
          { id: "generation", header: "Generation", cell: (o) => o.generation },
          { id: "deleted", header: "Deleted", sortValue: (o) => o.timeDeleted || "", cell: (o) => fmtDate(o.timeDeleted) },
          { id: "restore", header: "", cell: (o) => <Button size="small" onClick={async () => {
              try { await api.restoreObject(bucket, o.name, o.generation); notify.success(`Restored "${o.name}"`); reload(); }
              catch (e) { notify.error(e); }
            }}>Restore</Button> },
        ]}
        empty={<Typography variant="body2" color="text.secondary">No soft-deleted objects within the retention window.</Typography>} />
    </Box>
  );
}

function SoftDeleteDialog({ onClose, onSave }) {
  const [n, setN] = useState("7");
  const ok = Number(n) > 0 && Number.isInteger(Number(n));
  return (
    <SaveDialog title="Enable soft delete" onClose={onClose} disabled={!ok} onSave={() => onSave(Number(n) * 86400)}>
      <Typography variant="body2" color="text.secondary">Objects deleted or overwritten while soft delete is on can be restored within the retention window.</Typography>
      <TextField label="Retention duration (days)" type="number" value={n} onChange={(e) => setN(e.target.value)} error={!ok} />
    </SaveDialog>
  );
}

// ── Protection ──────────────────────────────────────────────────────────────────────────
function Protection({ bucket, reload }) {
  const notify = useNotify();
  const [edit, setEdit] = useState(false);
  const [remove, setRemove] = useState(false);
  const [sdEdit, setSdEdit] = useState(false);
  const rp = bucket.retentionPolicy;
  const objRetEnabled = bucket.objectRetention?.mode === "Enabled";
  const versioningOn = !!bucket.versioning?.enabled;
  const softDelete = bucket.softDeletePolicy;
  return (
    <Stack spacing={2}>
      <CapabilityContainer id="gcp.storage.soft-delete" title="Soft delete policy (for data recovery)"
        actions={<Button variant="outlined" onClick={async () => {
          if (softDelete) { try { await api.patchBucket(bucket.name, { softDeletePolicy: null }); notify.success("Soft delete disabled"); reload(); } catch (e) { notify.error(e); } }
          else setSdEdit(true);
        }}>{softDelete ? "Disable" : "Enable"}</Button>}>
        {softDelete
          ? <>
              <KeyValue items={[["Retention duration", fmtDuration(softDelete.retentionDurationSeconds)]]} />
              <SoftDeletedObjects bucket={bucket.name} />
            </>
          : <Typography variant="body2" color="text.secondary">Soft delete is not enabled for this bucket. Deleted or overwritten objects can't be recovered.</Typography>}
      </CapabilityContainer>
      <CapabilityContainer id="gcp.storage.versioning" title="Object versioning (for version control)"
        actions={<Button variant="outlined" onClick={async () => {
          try { await api.patchBucket(bucket.name, { versioning: { enabled: !versioningOn } }); notify.success(versioningOn ? "Versioning disabled" : "Versioning enabled"); reload(); }
          catch (e) { notify.error(e); }
        }}>{versioningOn ? "Disable" : "Enable"}</Button>}>
        {versioningOn
          ? <ObjectVersions bucket={bucket.name} />
          : <Typography variant="body2" color="text.secondary">Object versioning is not enabled for this bucket.</Typography>}
      </CapabilityContainer>
      {sdEdit && <SoftDeleteDialog onClose={() => setSdEdit(false)} onSave={async (secs) => {
        try { await api.patchBucket(bucket.name, { softDeletePolicy: { retentionDurationSeconds: String(secs) } }); notify.success("Soft delete enabled"); setSdEdit(false); reload(); }
        catch (e) { notify.error(e); }
      }} />}
      <Section title="Bucket retention policy" description="Objects can't be deleted or replaced until they reach the age you set. Enforced by Vyomi."
        actions={<>
          <Button variant="outlined" startIcon={rp ? <EditIcon /> : <AddIcon />} onClick={() => setEdit(true)}>{rp ? "Edit retention policy" : "Set retention policy"}</Button>
          {rp && <Button startIcon={<DeleteIcon />} onClick={() => setRemove(true)}>Remove</Button>}
        </>}>
        {rp ? <KeyValue items={[["Retention period", fmtDuration(rp.retentionPeriod)], ["Effective since", fmtDate(rp.effectiveTime)], ["Status", rp.isLocked ? "Locked" : "Unlocked"]]} />
          : <Typography variant="body2" color="text.secondary">No retention policy is set on this bucket.</Typography>}
      </Section>
      <CapabilityContainer id="gcp.storage.object-holds" title="Object retention"
        actions={<Button variant="outlined" onClick={async () => {
          try { await api.patchBucket(bucket.name, { objectRetention: { mode: objRetEnabled ? "Disabled" : "Enabled" } }); notify.success(objRetEnabled ? "Object retention disabled" : "Object retention enabled"); reload(); }
          catch (e) { notify.error(e); }
        }}>{objRetEnabled ? "Disable" : "Enable object retention"}</Button>}>
        <Typography variant="body2">{objRetEnabled ? "Object retention is enabled on this bucket. Objects can carry a retainUntilTime or a hold that blocks delete/overwrite." : "Object retention is not enabled on this bucket."}</Typography>
      </CapabilityContainer>
      {edit && <RetentionDialog current={rp} onClose={() => setEdit(false)} onSave={async (secs) => {
        await api.patchBucket(bucket.name, { retentionPolicy: { retentionPeriod: String(secs) } }); notify.success("Retention policy saved"); reload();
      }} />}
      <DeleteDialog open={remove} onClose={() => setRemove(false)} title="Remove retention policy?" actionLabel="Remove"
        onConfirm={async () => { await api.patchBucket(bucket.name, { retentionPolicy: null }); notify.success("Retention policy removed"); reload(); }}>
        <Typography variant="body2">Objects in <b>{bucket.name}</b> will no longer be protected from deletion or replacement.</Typography>
      </DeleteDialog>
    </Stack>
  );
}

const UNITS = [["seconds", 1], ["days", 86400], ["months", 31 * 86400], ["years", Math.round(365.25 * 86400)]];
function RetentionDialog({ current, onClose, onSave }) {
  const secs = Number(current?.retentionPeriod || 7 * 86400);
  const best = [...UNITS].reverse().find(([, n]) => secs % n === 0) || UNITS[0];
  const [n, setN] = useState(String(secs / best[1]));
  const [unit, setUnit] = useState(best[0]);
  const ok = Number(n) > 0 && Number.isInteger(Number(n));
  return (
    <SaveDialog title="Set retention policy" onClose={onClose} disabled={!ok} onSave={() => onSave(Number(n) * UNITS.find(([u]) => u === unit)[1])}>
      <Stack direction="row" spacing={1}>
        <TextField label="Retention period" type="number" value={n} onChange={(e) => setN(e.target.value)} error={!ok} />
        <FormControl sx={{ width: 160 }}><InputLabel id="u-l">Unit</InputLabel>
          <Select labelId="u-l" label="Unit" value={unit} onChange={(e) => setUnit(e.target.value)}>{UNITS.map(([u]) => <MenuItem key={u} value={u}>{u[0].toUpperCase() + u.slice(1)}</MenuItem>)}</Select>
        </FormControl>
      </Stack>
    </SaveDialog>
  );
}

// ── Lifecycle ───────────────────────────────────────────────────────────────────────────
const actionText = (a) => a.type === "Delete" ? "Delete object" : a.type === "SetStorageClass" ? `Set to ${api.classLabel(a.storageClass)}` : a.type === "AbortIncompleteMultipartUpload" ? "Abort incomplete multipart upload" : a.type;
const condText = (c) => [
  c.age !== undefined && `${c.age}+ days since object was created`,
  c.createdBefore && `Created before ${c.createdBefore}`,
  c.matchesPrefix?.length && `Name matches prefix ${c.matchesPrefix.map((x) => `"${x}"`).join(", ")}`,
  c.matchesSuffix?.length && `Name matches suffix ${c.matchesSuffix.map((x) => `"${x}"`).join(", ")}`,
  c.matchesStorageClass?.length && `Storage class matches ${c.matchesStorageClass.map(api.classLabel).join(", ")}`,
].filter(Boolean).join(" · ") || "—";

function Lifecycle({ bucket, reload }) {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [add, setAdd] = useState(false);
  const [delAll, setDelAll] = useState(false);
  const rules = (bucket.lifecycle?.rule || []).map((r, i) => ({ ...r, key: String(i) }));
  const save = (next) => api.patchBucket(bucket.name, { lifecycle: next.length ? { rule: next.map(({ key, ...r }) => r) } : null });
  return (
    <Stack spacing={2}>
      <Stack direction="row" alignItems="center" spacing={1}>
        <Typography variant="h3" component="h2">Lifecycle rules</Typography>
        <CapabilityBadge id="gcp.storage.lifecycle" />
        <Box sx={{ flex: 1 }} />
        <Button startIcon={<AddIcon />} onClick={() => setAdd(true)}>Add a rule</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={async () => {
          try { await save(rules.filter((r) => !sel.includes(r.key))); notify.success(`Deleted ${sel.length} rule${sel.length === 1 ? "" : "s"}`); setSel([]); reload(); } catch (e) { notify.error(e); }
        }}>Delete</Button>
        <Button disabled={!rules.length} onClick={() => setDelAll(true)}>Delete all</Button>
      </Stack>
      <Typography variant="body2" color="text.secondary">Lifecycle rules let you apply actions to a bucket's objects when certain conditions are met. Vyomi evaluates rules for real each time the bucket's objects are read.</Typography>
      <ResourceTable resourceName="lifecycle rules" items={rules} rowKey={(r) => r.key} selectable selected={sel} onSelectedChange={setSel} dense
        filterPlaceholder="Filter rules"
        columns={[
          { id: "action", header: "Action", cell: (r) => actionText(r.action || {}) },
          { id: "condition", header: "Object condition", wrap: true, cell: (r) => condText(r.condition || {}) },
        ]}
        empty={<Typography variant="body2" color="text.secondary">No lifecycle rules have been added to this bucket.</Typography>} />
      {add && <RuleDialog onClose={() => setAdd(false)} onSave={async (rule) => { await save([...rules, rule]); notify.success("Lifecycle rule added"); reload(); }} />}
      <DeleteDialog open={delAll} onClose={() => setDelAll(false)} title="Delete all lifecycle rules?" confirmText="DELETE"
        onConfirm={async () => { await save([]); notify.success("Deleted all lifecycle rules"); setSel([]); reload(); }}>
        <Typography variant="body2">All {rules.length} rule(s) on <b>{bucket.name}</b> will be deleted.</Typography>
      </DeleteDialog>
    </Stack>
  );
}

function RuleDialog({ onClose, onSave }) {
  const [action, setAction] = useState("Delete");
  const [age, setAge] = useState("30");
  const [before, setBefore] = useState("");
  const [storageClassMatches, setStorageClassMatches] = useState("");
  const [newerVersions, setNewerVersions] = useState("");
  const [daysNoncurrent, setDaysNoncurrent] = useState("");
  const [noncurrentBefore, setNoncurrentBefore] = useState("");
  const [daysCustomTime, setDaysCustomTime] = useState("");
  const [customTimeBefore, setCustomTimeBefore] = useState("");
  const [prefix, setPrefix] = useState("");
  const [suffix, setSuffix] = useState("");
  const condition = {
    ...(age !== "" ? { age: Number(age) } : {}),
    ...(before ? { createdBefore: before } : {}),
    ...(storageClassMatches ? { matchesStorageClass: [storageClassMatches] } : {}),
    ...(newerVersions !== "" ? { numNewerVersions: Number(newerVersions) } : {}),
    ...(daysNoncurrent !== "" ? { daysSinceNoncurrentTime: Number(daysNoncurrent) } : {}),
    ...(noncurrentBefore ? { noncurrentTimeBefore: noncurrentBefore } : {}),
    ...(daysCustomTime !== "" ? { daysSinceCustomTime: Number(daysCustomTime) } : {}),
    ...(customTimeBefore ? { customTimeBefore } : {}),
    ...(prefix ? { matchesPrefix: prefix.split(",").map((s) => s.trim()).filter(Boolean) } : {}),
    ...(suffix ? { matchesSuffix: suffix.split(",").map((s) => s.trim()).filter(Boolean) } : {}),
  };
  const ok = Object.keys(condition).length > 0 && (age === "" || (Number.isInteger(Number(age)) && Number(age) >= 0));
  const act = action === "Delete" ? { type: "Delete" } : { type: "SetStorageClass", storageClass: action };
  return (
    <SaveDialog title="Add an object lifecycle rule" onClose={onClose} disabled={!ok} onSave={() => onSave({ action: act, condition })}>
      <Typography variant="body2" sx={{ fontWeight: 500 }}>Select an action</Typography>
      <RadioGroup value={action} onChange={(e) => setAction(e.target.value)} aria-label="Lifecycle action">
        <FormControlLabel value="NEARLINE" control={<Radio size="small" />} label="Set storage class to Nearline" />
        <FormControlLabel value="COLDLINE" control={<Radio size="small" />} label="Set storage class to Coldline" />
        <FormControlLabel value="ARCHIVE" control={<Radio size="small" />} label="Set storage class to Archive" />
        <FormControlLabel value="Delete" control={<Radio size="small" />} label="Delete object" />
      </RadioGroup>
      <Typography variant="body2" sx={{ fontWeight: 500 }}>Select object conditions</Typography>
      <TextField label="Age" type="number" helperText="Days since object was created" value={age} onChange={(e) => setAge(e.target.value)} />
      <TextField label="Created before" type="date" value={before} onChange={(e) => setBefore(e.target.value)} InputLabelProps={{ shrink: true }} />
      <FormControl><InputLabel id="rd-class">Storage class matches</InputLabel>
        <Select labelId="rd-class" label="Storage class matches" value={storageClassMatches} onChange={(e) => setStorageClassMatches(e.target.value)}>
          <MenuItem value="">Any</MenuItem>
          {api.STORAGE_CLASSES.map(([c, l]) => <MenuItem key={c} value={c}>{l}</MenuItem>)}
        </Select>
      </FormControl>
      <TextField label="Number of newer versions" type="number" value={newerVersions} onChange={(e) => setNewerVersions(e.target.value)}
        helperText="Vyomi keeps no noncurrent object versions, so this condition never matches." />
      <TextField label="Days since becoming noncurrent" type="number" value={daysNoncurrent} onChange={(e) => setDaysNoncurrent(e.target.value)}
        helperText="Vyomi keeps no noncurrent object versions, so this condition never matches." />
      <TextField label="Became noncurrent before" type="date" value={noncurrentBefore} onChange={(e) => setNoncurrentBefore(e.target.value)} InputLabelProps={{ shrink: true }}
        helperText="Vyomi keeps no noncurrent object versions, so this condition never matches." />
      <TextField label="Days since custom time" type="number" value={daysCustomTime} onChange={(e) => setDaysCustomTime(e.target.value)} />
      <TextField label="Custom time before" type="date" value={customTimeBefore} onChange={(e) => setCustomTimeBefore(e.target.value)} InputLabelProps={{ shrink: true }} />
      <TextField label="Object name matches prefix" value={prefix} onChange={(e) => setPrefix(e.target.value)} helperText="Comma-separated" />
      <TextField label="Object name matches suffix" value={suffix} onChange={(e) => setSuffix(e.target.value)} helperText="Comma-separated" />
    </SaveDialog>
  );
}
