/* Secret details: summary + tabs (Overview, Versions, Permissions, Logs). Versions is the
 * console's real working surface — add / enable / disable / destroy / view value, all on
 * the native Secret Manager REST API. Permissions (a real, enforced per-secret IAM policy)
 * and Logs (real Cloud Logging entries for the lifecycle events below) are real too. */
import { useRef, useState } from "react";
import {
  Alert, Box, Button, Chip, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, FormControl,
  FormControlLabel, Checkbox, IconButton, InputAdornment, InputLabel, Menu, MenuItem, Select, Stack, Tab, Tabs,
  TextField, Tooltip, Typography,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import AddIcon from "@mui/icons-material/esm/Add.js";
import UploadFileIcon from "@mui/icons-material/esm/UploadFile.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import EditIcon from "@mui/icons-material/esm/Edit.js";
import PlayArrowIcon from "@mui/icons-material/esm/PlayArrow.js";
import PauseIcon from "@mui/icons-material/esm/Pause.js";
import VisibilityIcon from "@mui/icons-material/esm/Visibility.js";
import VisibilityOffIcon from "@mui/icons-material/esm/VisibilityOff.js";
import MoreVertIcon from "@mui/icons-material/esm/MoreVert.js";
import ContentCopyIcon from "@mui/icons-material/esm/ContentCopy.js";
import { useAsync } from "../../../../common/useAsync.js";
import { useNotify } from "../../../../common/notify.jsx";
import ResourceTable from "../../../kit/ResourceTable.jsx";
import DeleteDialog from "../../../kit/DeleteDialog.jsx";
import { ErrorAlert, fmtDate, KeyValue, PageHeader, Section } from "../../../kit/common.jsx";
import { CapabilityContainer } from "../../../kit/Capability.jsx";
import { hashHref } from "../../../link.jsx";
import { EditSecretDialog, VERSION_STATE_LABEL } from "./Shared.jsx";
import * as api from "./api.js";

const TABS = [["overview", "Overview"], ["versions", "Versions"], ["permissions", "Permissions"], ["logs", "Logs"]];
// A REGIONAL secret's detail page lives at .../regional/{location}/{name} (params.location
// set) instead of .../secret/{name} — a distinct resource, see api.js / gcp_secretmanager_core.py.
const detailHref = (name, loc, q = {}) => {
  const qs = new URLSearchParams(Object.entries(q).filter(([, v]) => v)).toString();
  const base = loc ? hashHref("security", "secret-manager", "regional", loc, name) : hashHref("security", "secret-manager", "secret", name);
  return base + (qs ? "?" + qs : "");
};
const backHref = (loc) => hashHref("security", "secret-manager") + (loc ? `?tab=regional&location=${encodeURIComponent(loc)}` : "");

export default function SecretDetail({ params, query }) {
  const name = params.name;
  const loc = params.location || null;
  const tab = TABS.some(([t]) => t === query.tab) ? query.tab : "versions";
  const notify = useNotify();
  const s = useAsync(() => api.getSecret(name, loc), [name, loc]);
  const [edit, setEdit] = useState(false);
  const [del, setDel] = useState(false);

  return (
    <>
      <PageHeader title={name} back={<IconButton aria-label="Back to secrets" href={backHref(loc)}><ArrowBackIcon /></IconButton>}
        actions={<>
          <Button startIcon={<EditIcon />} disabled={!s.data} onClick={() => setEdit(true)}>Edit secret</Button>
          <Button startIcon={<DeleteIcon />} disabled={!s.data} onClick={() => setDel(true)}>Delete</Button>
          <Button startIcon={<RefreshIcon />} onClick={s.reload}>Refresh</Button>
        </>}>
        <Tabs value={tab} onChange={(_, t) => { location.hash = detailHref(name, loc, { tab: t === "versions" ? "" : t }).slice(1); }}
          sx={{ borderBottom: 1, borderColor: "divider" }} aria-label="Secret tabs">
          {TABS.map(([id, label]) => <Tab key={id} value={id} label={label} />)}
        </Tabs>
      </PageHeader>
      {s.error ? <ErrorAlert error={s.error} title="Failed to load secret" /> : !s.data ? <CircularProgress size={24} /> : <>
        {tab === "overview" && <Overview secret={s.data} />}
        {tab === "versions" && <Versions secret={s.data} location={loc} />}
        {tab === "permissions" && <Permissions name={name} location={loc} />}
        {tab === "logs" && <Logs name={name} />}
      </>}
      {edit && s.data && <EditSecretDialog secret={s.data} location={loc} onClose={() => setEdit(false)} onSaved={s.reload} notify={notify} />}
      <DeleteDialog open={del} onClose={() => setDel(false)} title="Delete secret?" confirmText={name}
        warning="All versions of the secret are deleted as well. This can't be undone."
        onConfirm={async () => { await api.deleteSecret(name, loc); notify.success(`Deleted secret "${name}"`); location.hash = backHref(loc).slice(1); }}>
        <Typography variant="body2">Secret <b>{name}</b> will be permanently deleted.</Typography>
      </DeleteDialog>
    </>
  );
}

// ── Overview ────────────────────────────────────────────────────────────────────────────
function Overview({ secret }) {
  const ls = Object.entries(secret.labels || {});
  const regional = api.isRegional(secret);
  return (
    <Section title="Secret details">
      <KeyValue items={[
        ["Resource ID", secret.name],
        [regional ? "Location" : "Replication policy", api.locationLabel(secret)],
        ["Encryption", api.encryptionLabel(secret)],
        ["Rotation", secret.rotation?.rotationPeriod ? `Every ${Math.round(Number(secret.rotation.rotationPeriod.replace("s", "")) / 86400)} days` : "Not configured"],
        ["Expiration", secret.expireTime ? fmtDate(secret.expireTime) : "Never"],
        ["Labels", ls.length ? <Stack useFlexGap direction="row" spacing={0.5} sx={{ flexWrap: "wrap", rowGap: 0.5 }}>{ls.map(([k, v]) => <Chip key={k} size="small" label={`${k}: ${v}`} />)}</Stack> : "None"],
        ["Created", fmtDate(secret.createTime)],
      ]} />
    </Section>
  );
}

// ── Versions ────────────────────────────────────────────────────────────────────────────
function Versions({ secret, location }) {
  const notify = useNotify();
  const name = api.shortName(secret.name);
  const [sel, setSel] = useState([]);
  const [add, setAdd] = useState(false);
  const [view, setView] = useState(null);
  const [menu, setMenu] = useState(null);
  const { data = [], loading, error, reload } = useAsync(() => api.listVersions(name, location), [name, location]);

  const setState = async (vers, fn, label) => {
    for (const v of vers) await fn(name, v, location);
    notify.success(`${label} ${vers.length} version${vers.length === 1 ? "" : "s"}`);
    setSel([]); reload();
  };

  return (
    <Stack spacing={1.5}>
      <Typography variant="h3" component="h2">Versions</Typography>
      <Stack direction="row" spacing={0.5}>
        <Button startIcon={<AddIcon />} onClick={() => setAdd(true)}>New version</Button>
        <Button startIcon={<PlayArrowIcon />} disabled={!sel.length} onClick={() => setState(sel, api.enableVersion, "Enabled")}>Enable</Button>
        <Button startIcon={<PauseIcon />} disabled={!sel.length} onClick={() => setState(sel, api.disableVersion, "Disabled")}>Disable</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setState(sel, api.destroyVersion, "Destroyed")}>Destroy</Button>
      </Stack>
      <ResourceTable
        resourceName="versions"
        items={data}
        rowKey={(v) => api.versionNumber(v.name)}
        loading={loading}
        error={error}
        onRetry={reload}
        selectable
        selected={sel}
        onSelectedChange={setSel}
        filterPlaceholder="Filter versions"
        columns={[
          { id: "version", header: "Version", sortValue: (v) => Number(api.versionNumber(v.name)), cell: (v) => api.versionNumber(v.name) },
          { id: "status", header: "Status", sortField: "state", cell: (v) => <Chip size="small" label={VERSION_STATE_LABEL[v.state] || v.state} color={v.state === "ENABLED" ? "success" : v.state === "DISABLED" ? "default" : "error"} /> },
          { id: "created", header: "Created", sortField: "createTime", cell: (v) => fmtDate(v.createTime) },
          { id: "location", header: "Location", cell: () => api.locationLabel(secret) },
          { id: "encryption", header: "Encryption", cell: () => api.encryptionLabel(secret) },
          { id: "actions", header: "Actions", cell: (v) => (
            <IconButton size="small" aria-label={`Actions for version ${api.versionNumber(v.name)}`} onClick={(e) => setMenu({ anchor: e.currentTarget, v })}>
              <MoreVertIcon fontSize="small" />
            </IconButton>
          ) },
        ]}
        empty={<Typography variant="body2" color="text.secondary">This secret has no versions yet.</Typography>}
      />
      <Menu anchorEl={menu?.anchor} open={!!menu} onClose={() => setMenu(null)}>
        <MenuItem disabled={menu?.v.state === "DESTROYED"} onClick={() => { setView(menu.v); setMenu(null); }}>View secret value</MenuItem>
        <MenuItem disabled={menu?.v.state !== "DISABLED"} onClick={() => { setState([api.versionNumber(menu.v.name)], api.enableVersion, "Enabled"); setMenu(null); }}>Enable</MenuItem>
        <MenuItem disabled={menu?.v.state !== "ENABLED"} onClick={() => { setState([api.versionNumber(menu.v.name)], api.disableVersion, "Disabled"); setMenu(null); }}>Disable</MenuItem>
        <MenuItem disabled={menu?.v.state === "DESTROYED"} onClick={() => { setState([api.versionNumber(menu.v.name)], api.destroyVersion, "Destroyed"); setMenu(null); }}>Destroy</MenuItem>
      </Menu>
      {add && <AddVersionDialog name={name} versions={data} location={location} onClose={() => setAdd(false)} onSaved={reload} notify={notify} />}
      {view && <ViewValueDialog name={name} version={view} location={location} onClose={() => setView(null)} />}
    </Stack>
  );
}

function AddVersionDialog({ name, versions, location, onClose, onSaved, notify }) {
  const file = useRef(null);
  const [value, setValue] = useState("");
  const [fileName, setFileName] = useState("");
  const [disablePast, setDisablePast] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const save = async () => {
    if (!value) return;
    setBusy(true); setError(null);
    try {
      const past = versions.map((v) => api.versionNumber(v.name));
      await api.addVersion(name, value, location);
      if (disablePast) for (const v of past) await api.disableVersion(name, v, location).catch(() => {});
      notify.success("Added new version");
      onSaved(); onClose();
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Dialog open onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth aria-labelledby="add-version-title">
      <DialogTitle id="add-version-title">Add new version</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {error && <Alert severity="error"><b>{error.code || "Error"}</b>: {error.message}</Alert>}
          <Typography variant="subtitle2">Version</Typography>
          <TextField label="Secret value" required multiline minRows={3} value={value} onChange={(e) => { setValue(e.target.value); setFileName(""); }} autoFocus />
          <Box>
            <Button startIcon={<UploadFileIcon />} onClick={() => file.current?.click()}>Browse</Button>
            <Typography component="span" variant="body2" sx={{ ml: 1 }}>{fileName || "Upload file"}</Typography>
            <input ref={file} type="file" hidden aria-label="Upload file" onChange={async (e) => { const f = e.target.files[0]; if (f) { setFileName(f.name); setValue(await f.text()); } }} />
          </Box>
          <FormControlLabel control={<Checkbox checked={disablePast} onChange={(e) => setDisablePast(e.target.checked)} />} label="Disable all past versions" />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy || !value} onClick={save}>{busy ? "Adding…" : "Add new version"}</Button>
      </DialogActions>
    </Dialog>
  );
}

function ViewValueDialog({ name, version, location, onClose }) {
  const ver = api.versionNumber(version.name);
  const { data, loading, error } = useAsync(() => api.accessVersion(name, ver, location), [name, ver, location]);
  const [show, setShow] = useState(false);
  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth aria-labelledby="view-value-title">
      <DialogTitle id="view-value-title">Secret value — version {ver}</DialogTitle>
      <DialogContent>
        {loading ? <CircularProgress size={20} /> : error ? <Alert severity="error">{error.message}</Alert> : (
          <TextField fullWidth value={data || ""} type={show ? "text" : "password"} InputProps={{
            readOnly: true,
            endAdornment: <InputAdornment position="end">
              <Tooltip title={show ? "Hide value" : "Show value"}><IconButton size="small" onClick={() => setShow((v) => !v)}>{show ? <VisibilityOffIcon fontSize="small" /> : <VisibilityIcon fontSize="small" />}</IconButton></Tooltip>
              <Tooltip title="Copy value"><IconButton size="small" onClick={() => navigator.clipboard?.writeText(data || "").catch(() => {})}><ContentCopyIcon fontSize="small" /></IconButton></Tooltip>
            </InputAdornment>,
          }} />
        )}
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}><Button onClick={onClose}>Close</Button></DialogActions>
    </Dialog>
  );
}

// ── Permissions ─────────────────────────────────────────────────────────────────────────
const ROLES = [
  ["roles/secretmanager.admin", "Secret Manager Admin"],
  ["roles/secretmanager.secretAccessor", "Secret Manager Secret Accessor"],
  ["roles/secretmanager.secretVersionAdder", "Secret Manager Secret Version Adder"],
  ["roles/secretmanager.secretVersionManager", "Secret Manager Secret Version Manager"],
  ["roles/secretmanager.viewer", "Secret Manager Viewer"],
];
const roleName = (r) => ROLES.find(([v]) => v === r)?.[1] || r;

function Permissions({ name, location }) {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [grant, setGrant] = useState(false);
  const pol = useAsync(() => api.getIamPolicy(name, location), [name, location]);
  const rows = (pol.data?.bindings || []).flatMap((b) => b.members.map((m) => ({ key: `${m}|${b.role}`, member: m, role: b.role })));
  const writePolicy = async (bindings) => { await api.setIamPolicy(name, { ...pol.data, bindings }, location); pol.reload(); };

  return (
    <CapabilityContainer id="gcp.secret-manager.permissions" title="Permissions"
      description="Principals with access to this secret."
      actions={<>
        <Button startIcon={<AddIcon />} onClick={() => setGrant(true)}>Grant access</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={async () => {
          const drop = new Set(sel);
          const next = (pol.data?.bindings || []).map((b) => ({ ...b, members: b.members.filter((m) => !drop.has(`${m}|${b.role}`)) })).filter((b) => b.members.length);
          await writePolicy(next); notify.success(`Removed ${sel.length} role binding${sel.length === 1 ? "" : "s"}`); setSel([]);
        }}>Remove access</Button>
      </>}>
      {pol.error && <ErrorAlert error={pol.error} />}
      <ResourceTable resourceName="principals" items={rows} rowKey={(r) => r.key} loading={pol.loading} selectable selected={sel} onSelectedChange={setSel} dense
        filterPlaceholder="Filter principals"
        columns={[
          { id: "member", header: "Principal", sortField: "member", cell: (r) => r.member },
          { id: "role", header: "Role", sortValue: (r) => roleName(r.role), cell: (r) => roleName(r.role) },
        ]}
        empty={<Typography variant="body2" color="text.secondary">No principals have been granted access to this secret.</Typography>} />
      {grant && <GrantDialog onClose={() => setGrant(false)} onSave={async (member, role) => {
        const bs = (pol.data?.bindings || []).map((b) => ({ ...b, members: [...b.members] }));
        const hit = bs.find((b) => b.role === role);
        if (hit) { if (!hit.members.includes(member)) hit.members.push(member); } else bs.push({ role, members: [member] });
        await writePolicy(bs); notify.success(`Granted ${roleName(role)} to ${member}`);
      }} />}
    </CapabilityContainer>
  );
}

function GrantDialog({ onClose, onSave }) {
  const [member, setMember] = useState("");
  const [role, setRole] = useState(ROLES[0][0]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const ok = /^(user|serviceAccount|group|domain):.+/.test(member);

  const save = async () => {
    setBusy(true); setError(null);
    try {
      if (!ok) throw new Error("Enter a valid principal.");
      await onSave(member, role);
      onClose();
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Dialog open onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth aria-labelledby="grant-access-title">
      <DialogTitle id="grant-access-title">Grant access</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {error && <Alert severity="error">{error.message}</Alert>}
          <TextField label="New principals" value={member} onChange={(e) => setMember(e.target.value.trim())} inputProps={{ "aria-label": "New principals" }}
            helperText="e.g. user:dev@example.com, serviceAccount:app@vyomi-project.iam.gserviceaccount.com" />
          <FormControl><InputLabel id="role-l">Role</InputLabel>
            <Select labelId="role-l" label="Role" value={role} onChange={(e) => setRole(e.target.value)}>
              {ROLES.map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
            </Select>
          </FormControl>
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy || !member} onClick={save}>{busy ? "Saving…" : "Save"}</Button>
      </DialogActions>
    </Dialog>
  );
}

// ── Logs ─────────────────────────────────────────────────────────────────────────────────
const LOG_EVENT_LABEL = {
  SECRET_CREATE: "Secret created", SECRET_UPDATE: "Secret updated", SECRET_DELETE: "Secret deleted",
  SECRET_EXPIRE: "Secret auto-expired", SECRET_SET_IAM_POLICY: "IAM policy updated",
  SECRET_VERSION_ADD: "Version added", SECRET_VERSION_ENABLE: "Version enabled",
  SECRET_VERSION_DISABLE: "Version disabled", SECRET_VERSION_DESTROY: "Version destroyed",
};

function Logs({ name }) {
  const { data = [], loading, error, reload } = useAsync(() => api.listLogs(name), [name]);
  return (
    <CapabilityContainer id="gcp.secret-manager.logs" title="Logs"
      description="Cloud Logging entries written for this secret's lifecycle events."
      actions={<Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>}>
      {error && <ErrorAlert error={error} />}
      <ResourceTable resourceName="log entries" items={data} rowKey={(e) => e.insertId} loading={loading} dense
        filterPlaceholder="Filter log entries"
        columns={[
          { id: "timestamp", header: "Timestamp", sortField: "timestamp", cell: (e) => fmtDate(e.timestamp) },
          { id: "severity", header: "Severity", sortField: "severity", cell: (e) => <Chip size="small" label={e.severity} /> },
          { id: "event", header: "Event", cell: (e) => LOG_EVENT_LABEL[e.labels?.eventType] || e.labels?.eventType || "—" },
          { id: "message", header: "Message", cell: (e) => e.textPayload || "—" },
        ]}
        empty={<Typography variant="body2" color="text.secondary">No log entries for this secret yet.</Typography>} />
    </CapabilityContainer>
  );
}
