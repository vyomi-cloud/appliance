/* Service account detail: Details / Principals with access / Keys / Metrics / Logs tabs. */
import { useState } from "react";
import { Box, Button, FormControl, IconButton, InputLabel, MenuItem, Select, Stack, Tab, Tabs, TextField, Typography } from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, fmtDate, KeyValue, PageHeader, Section } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

const TABS = [["details", "Details"], ["principals", "Principals with access"], ["keys", "Keys"], ["metrics", "Metrics"], ["logs", "Logs"]];

export default function ServiceAccountDetail({ params, query }) {
  const email = params["resource-name"];
  const tab = TABS.some(([t]) => t === query.tab) ? query.tab : "details";
  const sa = useAsync(() => api.getServiceAccount(email), [email]);

  return (
    <>
      <PageHeader title={email} back={<IconButton aria-label="Back to service accounts" href="#/iam-admin/serviceaccounts"><ArrowBackIcon /></IconButton>} />
      <Tabs value={tab} onChange={(_, t) => { location.hash = `#/iam-admin/serviceaccounts/details/${encodeURIComponent(email)}` + (t === "details" ? "" : `?tab=${t}`); }}
        sx={{ borderBottom: 1, borderColor: "divider", mb: 2.5 }} aria-label="Service account tabs">
        {TABS.map(([id, label]) => <Tab key={id} value={id} label={label} />)}
      </Tabs>
      <ErrorAlert error={sa.error} title="Failed to load service account" />
      {tab === "details" && sa.data && <Details email={email} sa={sa.data} reload={sa.reload} />}
      {tab === "principals" && <Principals email={email} />}
      {tab === "keys" && <Keys email={email} />}
      {tab === "metrics" && <Metrics email={email} />}
      {tab === "logs" && <Logs email={email} />}
    </>
  );
}

function Details({ email, sa, reload }) {
  const notify = useNotify();
  const [name, setName] = useState(sa.displayName || "");
  const [desc, setDesc] = useState(sa.description || "");
  const [busy, setBusy] = useState(false);
  return (
    <Stack spacing={2}>
      <Section title="Service account details" actions={
        <Button variant="contained" size="small" disabled={busy} onClick={async () => {
          setBusy(true);
          try { await api.patchServiceAccount(email, { displayName: name, description: desc }); notify.success("Saved"); reload(); }
          catch (e) { notify.error(e); } finally { setBusy(false); }
        }}>Save</Button>}>
        <Stack spacing={2} sx={{ maxWidth: 480 }}>
          <TextField label="Name" value={name} onChange={(e) => setName(e.target.value)} />
          <TextField label="Description" multiline minRows={2} value={desc} onChange={(e) => setDesc(e.target.value)} />
          <KeyValue items={[["Email", sa.email], ["Unique ID", sa.uniqueId]]} />
        </Stack>
      </Section>
      <Section title="Service account status" actions={
        <Button color={sa.disabled ? "primary" : "error"} disabled={busy} onClick={async () => {
          setBusy(true);
          try {
            if (sa.disabled) await api.enableServiceAccount(email); else await api.disableServiceAccount(email);
            notify.success(sa.disabled ? "Enabled service account" : "Disabled service account"); reload();
          } catch (e) { notify.error(e); } finally { setBusy(false); }
        }}>
          {sa.disabled ? "Enable service account" : "Disable service account"}
        </Button>}>
        <Typography variant="body2">{sa.disabled ? "Disabled" : "Enabled"}</Typography>
      </Section>
    </Stack>
  );
}

function Principals({ email }) {
  const notify = useNotify();
  const sares = api.serviceAccountResource(email);
  const pol = useAsync(() => api.getIamPolicy(sares), [email]);
  const [sel, setSel] = useState([]);
  const [grant, setGrant] = useState(false);
  const rows = (pol.data?.bindings || []).flatMap((b) => b.members.map((m) => ({ key: `${b.role}|${m}`, role: b.role, member: m })));
  const write = async (next, msg) => { await api.setIamPolicy({ ...pol.data, bindings: next }, sares); notify.success(msg); setSel([]); pol.reload(); };
  return (
    <Section title="Principals with access to this service account" actions={
      <Stack direction="row" spacing={1}>
        <Button startIcon={<AddIcon />} onClick={() => setGrant(true)}>Grant access</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={async () => {
          const drop = new Set(sel);
          const next = (pol.data?.bindings || []).map((b) => ({ ...b, members: b.members.filter((m) => !drop.has(`${b.role}|${m}`)) })).filter((b) => b.members.length);
          await write(next, `Removed ${sel.length} role binding${sel.length === 1 ? "" : "s"}`);
        }}>Remove access</Button>
      </Stack>}>
      <ErrorAlert error={pol.error} />
      <ResourceTable resourceName="principals" items={rows} rowKey={(r) => r.key} loading={pol.loading} selectable selected={sel} onSelectedChange={setSel}
        columns={[
          { id: "principal", header: "Principal", sortField: "member", cell: (r) => r.member },
          { id: "name", header: "Name", cell: (r) => api.parseMember(r.member).display.split("@")[0] },
          { id: "role", header: "Role", sortValue: (r) => api.roleTitle(r.role), cell: (r) => api.roleTitle(r.role) },
          { id: "inheritance", header: "Inheritance", cell: () => "Direct" },
        ]} />
      {grant && <GrantPanel onClose={() => setGrant(false)} onSave={async (member, role) => {
        const bs = (pol.data?.bindings || []).map((b) => ({ ...b, members: [...b.members] }));
        const hit = bs.find((b) => b.role === role);
        if (hit) { if (!hit.members.includes(member)) hit.members.push(member); } else bs.push({ role, members: [member] });
        await write(bs, `Granted ${api.roleTitle(role)} to ${member}`);
      }} />}
    </Section>
  );
}

function GrantPanel({ onClose, onSave }) {
  const [member, setMember] = useState("");
  const [role, setRole] = useState("roles/iam.serviceAccountUser");
  const ok = /^(user|serviceAccount|group|domain):.+/.test(member);
  return (
    <Box sx={{ position: "fixed", top: 0, right: 0, bottom: 0, width: { xs: "100%", sm: 420 }, bgcolor: "background.paper", boxShadow: 6, zIndex: 1300, p: 3, overflowY: "auto" }} role="dialog" aria-label="Grant access">
      <Typography variant="h2" component="h2" sx={{ mb: 2 }}>Grant access</Typography>
      <Stack spacing={2}>
        <TextField label="New principals" value={member} onChange={(e) => setMember(e.target.value.trim())} helperText="e.g. user:dev@example.com" />
        <FormControl><InputLabel id="sa-role-l">Role</InputLabel>
          <Select labelId="sa-role-l" label="Role" value={role} onChange={(e) => setRole(e.target.value)}>
            <MenuItem value="roles/iam.serviceAccountUser">Service Account User</MenuItem>
            <MenuItem value="roles/iam.serviceAccountAdmin">Service Account Admin</MenuItem>
          </Select>
        </FormControl>
      </Stack>
      <Stack direction="row" spacing={1} sx={{ mt: 3 }}>
        <Button variant="contained" disabled={!ok} onClick={async () => { await onSave(member, role); onClose(); }}>Save</Button>
        <Button onClick={onClose}>Cancel</Button>
      </Stack>
    </Box>
  );
}

const SA_LOG_ACTION_LABEL = {
  GRANT: "Granted role", REVOKE: "Revoked role", CREATE_KEY: "Created key", DELETE_KEY: "Deleted key",
  DISABLE: "Disabled service account", ENABLE: "Enabled service account", UPDATE: "Updated service account",
};

function Logs({ email }) {
  const list = useAsync(() => api.listServiceAccountActivity(email), [email]);
  return (
    <Box sx={{ pt: 1 }}>
      <CapabilityContainer id="gcp.iam-admin.service-account-logs" title="Logs">
        <ErrorAlert error={list.error} title="Failed to load logs" />
        <ResourceTable resourceName="log entries" items={list.data || []} rowKey={(ev) => ev.id} loading={list.loading} onRetry={list.reload}
          filterPlaceholder="Filter" empty="No admin activity recorded for this service account yet"
          columns={[
            { id: "time", header: "Time", sortField: "time", cell: (ev) => fmtDate(ev.time) },
            { id: "event", header: "Event", cell: (ev) => SA_LOG_ACTION_LABEL[ev.action] || ev.action },
            { id: "detail", header: "Detail", cell: (ev) => ev.role ? `${api.roleTitle(ev.role)} → ${ev.member}` : ev.member || "—" },
          ]} />
      </CapabilityContainer>
    </Box>
  );
}

function Metrics({ email }) {
  const m = useAsync(() => api.getServiceAccountMetrics(email), [email]);
  return (
    <Box sx={{ pt: 1 }}>
      <CapabilityContainer id="gcp.iam-admin.service-account-metrics-logs" title="Metrics">
        <ErrorAlert error={m.error} title="Failed to load metrics" />
        <KeyValue items={[
          ["Total requests", String(m.data?.totalRequests ?? "—")],
          ["Last request", m.data?.lastCallTime ? fmtDate(m.data.lastCallTime) : "No requests yet"],
        ]} />
        <Typography variant="subtitle2" sx={{ mt: 2, mb: 1 }}>Requests by method</Typography>
        <ResourceTable resourceName="methods" items={m.data?.byMethod || []} rowKey={(r) => r.method} loading={m.loading}
          empty="No requests made with this service account's credentials yet"
          columns={[
            { id: "method", header: "Method", cell: (r) => r.method },
            { id: "count", header: "Request count", cell: (r) => r.count },
          ]} />
        <Typography variant="subtitle2" sx={{ mt: 2, mb: 1 }}>Requests by day</Typography>
        <ResourceTable resourceName="days" items={m.data?.series || []} rowKey={(r) => r.date} loading={m.loading}
          empty="No daily activity recorded yet"
          columns={[
            { id: "date", header: "Date", cell: (r) => r.date },
            { id: "count", header: "Request count", cell: (r) => r.count },
          ]} />
      </CapabilityContainer>
    </Box>
  );
}

function Keys({ email }) {
  const notify = useNotify();
  const list = useAsync(() => api.listKeys(email), [email]);
  const [del, setDel] = useState(null);
  const [busy, setBusy] = useState(false);
  return (
    <Section title="Keys" actions={
      <Button startIcon={<AddIcon />} disabled={busy} onClick={async () => {
        setBusy(true);
        try { await api.createKey(email); notify.success("Created new key"); list.reload(); } catch (e) { notify.error(e); } finally { setBusy(false); }
      }}>Add key</Button>}>
      <ErrorAlert error={list.error} />
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
        Create new key, or upload a public key certificate from an existing key pair.
      </Typography>
      <Stack direction="row" spacing={1} sx={{ mb: 1.5 }}>
        <Button disabled={busy} onClick={async () => { setBusy(true); try { await api.createKey(email); notify.success("Created new key"); list.reload(); } finally { setBusy(false); } }}>Create new key</Button>
        <Button disabled>Upload existing key</Button>
      </Stack>
      <ResourceTable resourceName="keys" items={list.data || []} rowKey={(k) => k.name} loading={list.loading} onRetry={list.reload}
        columns={[
          { id: "type", header: "Type", cell: (k) => k.keyType },
          { id: "status", header: "Status", cell: (k) => k.disabled ? "Disabled" : "Active" },
          { id: "key", header: "Key", cell: (k) => k.name.split("/").pop().slice(0, 16) + "…" },
          { id: "created", header: "Key creation date", sortField: "validAfterTime", cell: (k) => fmtDate(k.validAfterTime) },
          { id: "expires", header: "Key expiration date", sortField: "validBeforeTime", cell: (k) => fmtDate(k.validBeforeTime) },
          { id: "actions", header: "Actions", cell: (k) => <Button size="small" color="error" onClick={() => setDel(k.name.split("/").pop())}>Delete</Button> },
        ]} />
      <DeleteDialog open={!!del} onClose={() => setDel(null)} title="Delete this key?" actionLabel="Delete"
        warning="Make sure the key isn't used by any application before deleting it."
        onConfirm={async () => { await api.deleteKey(email, del); notify.success("Deleted key"); list.reload(); }} />
    </Section>
  );
}
