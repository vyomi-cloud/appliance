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
import { ErrorAlert, fmtBytes, fmtDate, fmtDuration, KeyValue, NotSimulated, NotSimulatedContainer, PageHeader, Section } from "../../kit/common.jsx";
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
      {tab === "observability" && <NotSimulatedContainer title="Observability" feature="Cloud Monitoring metrics for Cloud Storage (requests, bandwidth, total bytes)" />}
      {tab === "inventory" && <NotSimulatedContainer title="Inventory reports" feature="Storage Insights inventory reports" />}
      {tab === "operations" && <NotSimulatedContainer title="Operations" feature="Long-running bucket operations" />}
    </>
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
      <Box sx={{ mt: 1.5 }}><NotSimulated compact feature="Object version history, holds and per-object encryption" /></Box>
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
  const ls = Object.entries(bucket.labels || {});
  const patch = async (body, msg) => { await api.patchBucket(bucket.name, body); notify.success(msg); reload(); };
  return (
    <Stack spacing={2}>
      <Section title="Overview">
        <KeyValue items={[
          ["Location type", api.LOCATION_TYPE_LABEL[bucket.locationType]],
          ["Location", bucket.location.toLowerCase()],
          ["Default storage class", api.classLabel(bucket.storageClass), <IconButton key="e" size="small" aria-label="Edit default storage class" onClick={() => setEditClass(true)}><EditIcon fontSize="inherit" /></IconButton>],
          ["Created", fmtDate(bucket.timeCreated)],
          ["Last modified", fmtDate(bucket.updated)],
          ["Labels", ls.length ? <Stack direction="row" spacing={0.5} sx={{ flexWrap: "wrap", rowGap: 0.5 }}>{ls.map(([k, v]) => <Chip key={k} size="small" label={`${k}: ${v}`} />)}</Stack> : "None",
            <IconButton key="e" size="small" aria-label="Edit labels" onClick={() => setEditLabels(true)}><EditIcon fontSize="inherit" /></IconButton>],
          ["gsutil URI", `gs://${bucket.name}`],
          ["Metageneration", bucket.metageneration],
          ...(bucket.rpo ? [["Replication", bucket.rpo === "ASYNC_TURBO" ? "Turbo" : "Default"]] : []),
        ]} />
      </Section>
      <NotSimulatedContainer title="Requester pays" />
      <NotSimulatedContainer title="Static website configuration" feature="Static website hosting (main page / 404 page)" />
      <NotSimulatedContainer title="Cross-origin resource sharing (CORS)" />
      {editLabels && <LabelsDialog labels={bucket.labels || {}} onClose={() => setEditLabels(false)} onSave={async (next) => {
        const body = { ...Object.fromEntries(Object.keys(bucket.labels || {}).map((k) => [k, null])), ...next };
        await patch({ labels: body }, "Updated labels");
      }} />}
      {editClass && <ClassDialog value={bucket.storageClass} onClose={() => setEditClass(false)} onSave={(v) => patch({ storageClass: v }, "Updated default storage class")} />}
    </Stack>
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
      <Section title="Public access" actions={
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
          <Typography variant="h3" component="h2" sx={{ flex: 1 }}>Permissions — View by principals</Typography>
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
        <Box sx={{ mt: 1.5 }}><NotSimulated compact feature="IAM and ACL enforcement on data access" note="Policies are stored and returned to SDKs (getIamPolicy / setIamPolicy), but Vyomi doesn't check them on requests." /></Box>
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

// ── Protection ──────────────────────────────────────────────────────────────────────────
function Protection({ bucket, reload }) {
  const notify = useNotify();
  const [edit, setEdit] = useState(false);
  const [remove, setRemove] = useState(false);
  const rp = bucket.retentionPolicy;
  return (
    <Stack spacing={2}>
      <NotSimulatedContainer title="Soft delete policy (for data recovery)" feature="Soft delete" />
      <NotSimulatedContainer title="Object versioning (for version control)" feature="Object versioning" />
      <Section title="Bucket retention policy" description="Objects can't be deleted or replaced until they reach the age you set. Enforced by Vyomi."
        actions={<>
          <Button variant="outlined" startIcon={rp ? <EditIcon /> : <AddIcon />} onClick={() => setEdit(true)}>{rp ? "Edit retention policy" : "Set retention policy"}</Button>
          {rp && <Button startIcon={<DeleteIcon />} onClick={() => setRemove(true)}>Remove</Button>}
        </>}>
        {rp ? <KeyValue items={[["Retention period", fmtDuration(rp.retentionPeriod)], ["Effective since", fmtDate(rp.effectiveTime)], ["Status", rp.isLocked ? "Locked" : "Unlocked"]]} />
          : <Typography variant="body2" color="text.secondary">No retention policy is set on this bucket.</Typography>}
      </Section>
      <NotSimulatedContainer title="Object retention" feature="Object retention and object holds" />
      <NotSimulatedContainer title="Data encryption" feature="Customer-managed encryption keys (CMEK)" />
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
        <Typography variant="h3" component="h2" sx={{ flex: 1 }}>Lifecycle rules</Typography>
        <Button startIcon={<AddIcon />} onClick={() => setAdd(true)}>Add a rule</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={async () => {
          try { await save(rules.filter((r) => !sel.includes(r.key))); notify.success(`Deleted ${sel.length} rule${sel.length === 1 ? "" : "s"}`); setSel([]); reload(); } catch (e) { notify.error(e); }
        }}>Delete</Button>
        <Button disabled={!rules.length} onClick={() => setDelAll(true)}>Delete all</Button>
      </Stack>
      <Typography variant="body2" color="text.secondary">Lifecycle rules let you apply actions to a bucket's objects when certain conditions are met.</Typography>
      <ResourceTable resourceName="lifecycle rules" items={rules} rowKey={(r) => r.key} selectable selected={sel} onSelectedChange={setSel} dense
        filterPlaceholder="Filter rules"
        columns={[
          { id: "action", header: "Action", cell: (r) => actionText(r.action || {}) },
          { id: "condition", header: "Object condition", wrap: true, cell: (r) => condText(r.condition || {}) },
        ]}
        empty={<Typography variant="body2" color="text.secondary">No lifecycle rules have been added to this bucket.</Typography>} />
      <NotSimulated compact feature="Lifecycle rule execution" note="Rules are stored on the bucket and returned to SDKs, but Vyomi does not run them against objects." />
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
  const [prefix, setPrefix] = useState("");
  const [suffix, setSuffix] = useState("");
  const condition = {
    ...(age !== "" ? { age: Number(age) } : {}),
    ...(before ? { createdBefore: before } : {}),
    ...(prefix ? { matchesPrefix: prefix.split(",").map((s) => s.trim()).filter(Boolean) } : {}),
    ...(suffix ? { matchesSuffix: suffix.split(",").map((s) => s.trim()).filter(Boolean) } : {}),
  };
  const ok = Object.keys(condition).length > 0 && (age === "" || (Number.isInteger(Number(age)) && Number(age) >= 0));
  const act = action === "Delete" ? { type: "Delete" } : { type: "SetStorageClass", storageClass: action };
  return (
    <SaveDialog title="Add a rule" onClose={onClose} disabled={!ok} onSave={() => onSave({ action: act, condition })}>
      <Typography variant="body2" sx={{ fontWeight: 500 }}>Select an action</Typography>
      <RadioGroup value={action} onChange={(e) => setAction(e.target.value)} aria-label="Lifecycle action">
        <FormControlLabel value="NEARLINE" control={<Radio size="small" />} label="Set storage class to Nearline" />
        <FormControlLabel value="COLDLINE" control={<Radio size="small" />} label="Set storage class to Coldline" />
        <FormControlLabel value="ARCHIVE" control={<Radio size="small" />} label="Set storage class to Archive" />
        <FormControlLabel value="Delete" control={<Radio size="small" />} label="Delete object" />
      </RadioGroup>
      <Typography variant="body2" sx={{ fontWeight: 500 }}>Select object conditions</Typography>
      <TextField label="Age (days)" type="number" value={age} onChange={(e) => setAge(e.target.value)} />
      <TextField label="Created before" type="date" value={before} onChange={(e) => setBefore(e.target.value)} InputLabelProps={{ shrink: true }} />
      <TextField label="Object name matches prefix" value={prefix} onChange={(e) => setPrefix(e.target.value)} helperText="Comma-separated" />
      <TextField label="Object name matches suffix" value={suffix} onChange={(e) => setSuffix(e.target.value)} helperText="Comma-separated" />
    </SaveDialog>
  );
}
