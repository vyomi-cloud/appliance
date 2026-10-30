/* Key detail: Versions (lifecycle: create/make-primary/enable/disable/destroy/restore),
 * Overview (read-only settings) and Permissions (IAM policy on the key — config_only:
 * Vyomi stores and returns it, but never enforces it on a KMS call). */
import { useState } from "react";
import {
  Box, Breadcrumbs, Button, Chip, FormControl, IconButton, InputLabel, Menu, MenuItem, Select, Stack, Tab, Tabs, TextField, Typography,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import AddIcon from "@mui/icons-material/esm/Add.js";
import EditIcon from "@mui/icons-material/esm/Edit.js";
import AutorenewIcon from "@mui/icons-material/esm/Autorenew.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import MoreVertIcon from "@mui/icons-material/esm/MoreVert.js";
import { useAsync } from "../../../../common/useAsync.js";
import { useNotify } from "../../../../common/notify.jsx";
import ResourceTable from "../../../kit/ResourceTable.jsx";
import { CapabilityContainer } from "../../../kit/Capability.jsx";
import { ErrorAlert, fmtDate, KeyValue, PageHeader, Section } from "../../../kit/common.jsx";
import { Link, hashHref } from "../../../link.jsx";
import * as api from "./api.js";

const TABS = [["versions", "Versions"], ["overview", "Overview"], ["permissions", "Permissions"]];

export default function KeyDetail({ params, query }) {
  const { location: loc, keyring: keyRing, name: k } = params;
  const tab = TABS.some(([t]) => t === query.tab) ? query.tab : "versions";
  const key = useAsync(() => api.getKey(loc, keyRing, k), [loc, keyRing, k]);
  const setTab = (t) => { location.hash = hashHref("security", "kms", "key", "manage", loc, keyRing, k) + (t === "versions" ? "" : `?tab=${t}`); };
  const notify = useNotify();
  const [rotateBusy, setRotateBusy] = useState(false);

  const rotate = async () => {
    setRotateBusy(true);
    try {
      const v = await api.createVersion(loc, keyRing, k);
      await api.setPrimaryVersion(loc, keyRing, k, api.parseVersionId(v.name));
      notify.success(`Rotated key — primary version is now ${api.parseVersionId(v.name)}`);
      key.reload();
    } catch (e) { notify.error(e); } finally { setRotateBusy(false); }
  };

  return (
    <>
      <PageHeader title={k} back={<IconButton aria-label="Back" href={`#/security/kms/keyring/manage/${loc}/${keyRing}`}><ArrowBackIcon /></IconButton>}
        actions={<>
          <Button startIcon={<AutorenewIcon />} disabled={rotateBusy} onClick={rotate}>Rotate key</Button>
          <Button startIcon={<RefreshIcon />} onClick={key.reload}>Refresh</Button>
        </>} />
      <Breadcrumbs sx={{ mb: 1.5 }}>
        <Link href="#/security/kms/keyrings">Key management</Link>
        <Link href={`#/security/kms/keyring/manage/${loc}/${keyRing}`}>{keyRing}</Link>
        <Typography variant="body2" sx={{ fontWeight: 500 }}>{k}</Typography>
      </Breadcrumbs>
      {key.error && <ErrorAlert error={key.error} title="Failed to load key" />}
      <Tabs value={tab} onChange={(_, t) => setTab(t)} sx={{ borderBottom: 1, borderColor: "divider", mb: 2.5 }} aria-label="Key tabs">
        {TABS.map(([id, label]) => <Tab key={id} value={id} label={label} />)}
      </Tabs>
      {tab === "versions" && key.data && <Versions loc={loc} keyRing={keyRing} k={k} keyData={key.data} reloadKey={key.reload} />}
      {tab === "overview" && key.data && <Overview loc={loc} keyRing={keyRing} k={k} keyData={key.data} reload={key.reload} />}
      {tab === "permissions" && <Permissions loc={loc} keyRing={keyRing} k={k} />}
    </>
  );
}

const STATE_ACTIONS = { ENABLED: ["Disable", "Destroy"], DISABLED: ["Enable", "Destroy"], DESTROY_SCHEDULED: ["Restore"], DESTROYED: [] };

function Versions({ loc, keyRing, k, keyData, reloadKey }) {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [menu, setMenu] = useState(null);
  const vers = useAsync(() => api.listVersions(loc, keyRing, k), [loc, keyRing, k, keyData]);
  const primary = api.parseVersionId(keyData.primary?.name);

  const run = async (fn, msg) => {
    try { await fn(); notify.success(msg); setSel([]); vers.reload(); reloadKey(); }
    catch (e) { notify.error(e); }
  };
  const ver = (v) => api.parseVersionId(v.name);
  const bulk = (action) => {
    const ids = sel.filter((id) => STATE_ACTIONS[(vers.data || []).find((v) => ver(v) === id)?.state]?.includes(action));
    return run(() => Promise.all(ids.map((id) => (
      action === "Disable" ? api.setVersionState(loc, keyRing, k, id, "DISABLED")
      : action === "Enable" ? api.setVersionState(loc, keyRing, k, id, "ENABLED")
      : action === "Destroy" ? api.destroyVersion(loc, keyRing, k, id)
      : api.restoreVersion(loc, keyRing, k, id)
    ))), `${action}d ${ids.length} version${ids.length === 1 ? "" : "s"}`);
  };

  return (
    <>
      <Stack direction="row" spacing={1} sx={{ mb: 1.5 }}>
        <Button startIcon={<AddIcon />} onClick={() => run(() => api.createVersion(loc, keyRing, k), "Created a new version")}>Create new version</Button>
        <Button disabled={!sel.length} onClick={() => bulk("Disable")}>Disable</Button>
        <Button disabled={!sel.length} onClick={() => bulk("Enable")}>Enable</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => bulk("Destroy")}>Destroy</Button>
        <Button disabled={!sel.length} onClick={() => bulk("Restore")}>Restore</Button>
      </Stack>
      <ResourceTable
        resourceName="versions"
        items={vers.data || []}
        rowKey={ver}
        loading={vers.loading}
        error={vers.error}
        onRetry={vers.reload}
        selectable
        selected={sel}
        onSelectedChange={setSel}
        filterPlaceholder="Filter versions"
        columns={[
          { id: "version", header: "Version", sortValue: (v) => Number(ver(v)), cell: (v) => <>{ver(v)}{ver(v) === primary && <Chip size="small" sx={{ ml: 1 }} label="Primary" />}</> },
          { id: "state", header: "State", cell: (v) => api.STATE_LABEL[v.state] || v.state },
          { id: "algorithm", header: "Algorithm", cell: () => "Google symmetric key" },
          { id: "created", header: "Created on", sortField: "createTime", cell: (v) => fmtDate(v.createTime) },
          { id: "destroy", header: "Scheduled for destruction on", cell: (v) => fmtDate(v.destroyTime) },
          { id: "actions", header: "Actions", cell: (v) => (
            <IconButton size="small" aria-label={`Actions for version ${ver(v)}`} onClick={(e) => setMenu({ anchor: e.currentTarget, v })}><MoreVertIcon fontSize="small" /></IconButton>
          ) },
        ]}
      />
      <Menu anchorEl={menu?.anchor} open={!!menu} onClose={() => setMenu(null)}>
        <MenuItem disabled={menu?.v.state !== "ENABLED" || ver(menu?.v) === primary}
          onClick={() => { const id = ver(menu.v); setMenu(null); run(() => api.setPrimaryVersion(loc, keyRing, k, id), `Version ${id} is now primary`); }}>Make primary</MenuItem>
        <MenuItem disabled={menu?.v.state !== "ENABLED"}
          onClick={() => { const id = ver(menu.v); setMenu(null); run(() => api.setVersionState(loc, keyRing, k, id, "DISABLED"), `Disabled version ${id}`); }}>Disable</MenuItem>
        <MenuItem disabled={!["ENABLED", "DISABLED"].includes(menu?.v.state)}
          onClick={() => { const id = ver(menu.v); setMenu(null); run(() => api.destroyVersion(loc, keyRing, k, id), `Scheduled version ${id} for destruction`); }}>Destroy</MenuItem>
      </Menu>
    </>
  );
}

function Overview({ loc, keyRing, k, keyData, reload }) {
  const notify = useNotify();
  const [editRot, setEditRot] = useState(false);
  const [editLabels, setEditLabels] = useState(false);
  const ls = Object.entries(keyData.labels || {});
  return (
    <Stack spacing={2}>
      <Section title="Key details">
        <KeyValue items={[
          ["Purpose", api.purposeLabel(keyData.purpose)],
          ["Protection level", "Software"],
          ["Primary version", api.parseVersionId(keyData.primary?.name)],
          ["Rotation period", api.rotationLabel(keyData.rotationPeriod),
            <IconButton key="e" size="small" aria-label="Edit rotation period" onClick={() => setEditRot(true)}><EditIcon fontSize="inherit" /></IconButton>],
          ["Next rotation", fmtDate(keyData.nextRotationTime)],
          ["Labels", ls.length ? <Stack direction="row" spacing={0.5} sx={{ flexWrap: "wrap", rowGap: 0.5 }}>{ls.map(([k2, v]) => <Chip key={k2} size="small" label={`${k2}: ${v}`} />)}</Stack> : "None",
            <IconButton key="e" size="small" aria-label="Edit labels" onClick={() => setEditLabels(true)}><EditIcon fontSize="inherit" /></IconButton>],
        ]} />
      </Section>
      {editRot && <RotationDialog current={keyData.rotationPeriod} onClose={() => setEditRot(false)} onSave={async (period) => {
        const next = period ? new Date(Date.now() + Number(period.replace("s", "")) * 1000).toISOString() : null;
        await api.patchKey(loc, keyRing, k, { rotationPeriod: period, nextRotationTime: next }, ["rotationPeriod", "nextRotationTime"]);
        notify.success("Updated rotation period"); reload();
      }} />}
      {editLabels && <LabelsDialog labels={keyData.labels || {}} onClose={() => setEditLabels(false)} onSave={async (next) => {
        await api.patchKey(loc, keyRing, k, { labels: next }, ["labels"]);
        notify.success("Updated labels"); reload();
      }} />}
    </Stack>
  );
}

function SaveDialog({ title, onClose, onSave, children }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  return (
    <Box role="dialog" aria-label={title} sx={{ position: "fixed", inset: 0, bgcolor: "rgba(0,0,0,.4)", display: "grid", placeItems: "center", zIndex: 1300 }} onClick={onClose}>
      <Box sx={{ bgcolor: "background.paper", borderRadius: 2, p: 3, minWidth: 360, maxWidth: 480 }} onClick={(e) => e.stopPropagation()}>
        <Typography variant="h3" component="h2" sx={{ mb: 2 }}>{title}</Typography>
        <Stack spacing={2}>{children}{error && <ErrorAlert error={error} />}</Stack>
        <Stack direction="row" spacing={1} sx={{ mt: 3, justifyContent: "flex-end" }}>
          <Button onClick={onClose} disabled={busy}>Cancel</Button>
          <Button variant="contained" disabled={busy} onClick={async () => { setBusy(true); setError(null); try { await onSave(); onClose(); } catch (e) { setError(e); } finally { setBusy(false); } }}>Save</Button>
        </Stack>
      </Box>
    </Box>
  );
}

function RotationDialog({ current, onClose, onSave }) {
  const [v, setV] = useState(current || "");
  return (
    <SaveDialog title="Edit rotation period" onClose={onClose} onSave={() => onSave(v)}>
      <FormControl>
        <InputLabel id="rot-edit-l">Key rotation period</InputLabel>
        <Select labelId="rot-edit-l" label="Key rotation period" value={v} onChange={(e) => setV(e.target.value)} inputProps={{ "aria-label": "Key rotation period" }}>
          {api.ROTATION_PERIODS.map(([pv, l]) => <MenuItem key={pv} value={pv}>{l}</MenuItem>)}
        </Select>
      </FormControl>
    </SaveDialog>
  );
}

function LabelsDialog({ labels, onClose, onSave }) {
  const [rows, setRows] = useState(Object.entries(labels).map(([key, value]) => ({ key, value })));
  return (
    <SaveDialog title="Edit labels" onClose={onClose} onSave={() => onSave(Object.fromEntries(rows.map((r) => [r.key, r.value])))}>
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

const ROLES = [
  ["roles/cloudkms.cryptoKeyEncrypterDecrypter", "Cloud KMS CryptoKey Encrypter/Decrypter"],
  ["roles/cloudkms.cryptoKeyEncrypter", "Cloud KMS CryptoKey Encrypter"],
  ["roles/cloudkms.cryptoKeyDecrypter", "Cloud KMS CryptoKey Decrypter"],
  ["roles/cloudkms.cryptoKeyViewer", "Cloud KMS CryptoKey Viewer"],
  ["roles/cloudkms.admin", "Cloud KMS Admin"],
];
const roleName = (r) => ROLES.find(([v]) => v === r)?.[1] || r;

function Permissions({ loc, keyRing, k }) {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [grant, setGrant] = useState(false);
  const pol = useAsync(() => api.getIamPolicy(loc, keyRing, k), [loc, keyRing, k]);
  const rows = (pol.data?.bindings || []).flatMap((b) => b.members.map((m) => ({ key: `${m}|${b.role}`, member: m, role: b.role })));
  const writePolicy = async (bindings) => { await api.setIamPolicy(loc, keyRing, k, { ...pol.data, bindings }); pol.reload(); };

  return (
    <CapabilityContainer id="gcp.kms.key.permissions" title="Permissions"
      description="Principals with access to this key."
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
        empty={<Typography variant="body2" color="text.secondary">No principals have been granted access to this key.</Typography>} />
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
  const ok = /^(user|serviceAccount|group|domain):.+/.test(member);
  return (
    <SaveDialog title="Grant access" onClose={onClose} onSave={() => (ok ? onSave(member, role) : Promise.reject(new Error("Enter a valid principal.")))}>
      <TextField label="New principals" value={member} onChange={(e) => setMember(e.target.value.trim())} inputProps={{ "aria-label": "New principals" }}
        helperText="e.g. user:dev@example.com, serviceAccount:app@vyomi-project.iam.gserviceaccount.com" />
      <FormControl><InputLabel id="role-l">Role</InputLabel>
        <Select labelId="role-l" label="Role" value={role} onChange={(e) => setRole(e.target.value)}>
          {ROLES.map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
        </Select>
      </FormControl>
    </SaveDialog>
  );
}
