/* IAM page: project-level policy bindings (Allow), deny policies (Deny) and the
 * applied-policy-change log (Recommendations history) — three tabs, three routes,
 * all on the native Cloud IAM / Resource Manager v1 :getIamPolicy / :setIamPolicy wire. */
import { useState } from "react";
import {
  Box, Button, Checkbox, FormControl, FormControlLabel, InputLabel, MenuItem, Radio, RadioGroup,
  Select, Stack, Tab, Tabs, TextField, ToggleButton, ToggleButtonGroup, Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import HistoryIcon from "@mui/icons-material/esm/History.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, fmtDate, NotSimulatedContainer, PageHeader, Section } from "../../kit/common.jsx";
import { getProject } from "../../project.js";
import * as api from "./api.js";

const TABS = [["allow", "Allow"], ["deny", "Deny"], ["recommendations", "Recommendations history"]];
const TAB_ROUTE = { allow: "#/iam-admin/iam", deny: "#/iam-admin/iam/deny", recommendations: "#/iam-admin/iam/log" };

export default function Iam({ tab, openGrant }) {
  return (
    <>
      <PageHeader title="IAM" actions={<Button href="https://cloud.google.com/iam/docs" target="_blank" rel="noreferrer">Learn</Button>} />
      <Tabs value={tab} onChange={(_, t) => { location.hash = TAB_ROUTE[t].slice(1); }} sx={{ borderBottom: 1, borderColor: "divider", mb: 2.5 }} aria-label="IAM tabs">
        {TABS.map(([id, label]) => <Tab key={id} value={id} label={label} />)}
      </Tabs>
      {tab === "allow" && <Allow openGrant={openGrant} />}
      {tab === "deny" && <Deny />}
      {tab === "recommendations" && <RecommendationsHistory />}
    </>
  );
}

// ── Allow ───────────────────────────────────────────────────────────────────────────────
function Allow({ openGrant }) {
  const notify = useNotify();
  const project = getProject();
  const pol = useAsync(() => api.getIamPolicy(), [project]);
  const [includeGoogle, setIncludeGoogle] = useState(false);
  const [viewBy, setViewBy] = useState("principals");
  const [sel, setSel] = useState([]);
  const [grant, setGrant] = useState(!!openGrant);

  const bindings = pol.data?.bindings || [];
  // "Google-provided role grants": bindings on roles GCP auto-creates for default
  // service agents — none exist in a fresh Vyomi project, so this is a real, working
  // filter that simply has nothing to hide by default (same as most real projects).
  const isGoogleProvided = (b) => b.members.every((m) => m.includes("gcp-sa-") || m.includes(".gserviceaccount.com") && b.role === "roles/editor");
  const visible = includeGoogle ? bindings : bindings.filter((b) => !isGoogleProvided(b));

  const principalRows = visible.flatMap((b) => b.members.map((m) => {
    const info = api.parseMember(m);
    return { key: `${b.role}|${m}`, role: b.role, member: m, type: info.type, name: info.display.split("@")[0] || info.display };
  }));
  const roleRows = visible.map((b) => ({ key: b.role, role: b.role, members: b.members }));

  const writeBindings = async (next, msg) => {
    await api.setIamPolicy({ ...pol.data, bindings: next });
    notify.success(msg);
    setSel([]);
    pol.reload();
  };

  const removeSelected = async () => {
    const drop = new Set(sel);
    const next = bindings
      .map((b) => viewBy === "roles"
        ? (drop.has(b.role) ? null : b)
        : { ...b, members: b.members.filter((m) => !drop.has(`${b.role}|${m}`)) })
      .filter((b) => b && b.members.length);
    await writeBindings(next, `Removed ${sel.length} role binding${sel.length === 1 ? "" : "s"}`);
  };

  return (
    <>
      <Typography variant="h3" component="h2" sx={{ mb: 1 }}>Permissions for project</Typography>
      <FormControlLabel sx={{ mb: 2 }} control={<Checkbox checked={includeGoogle} onChange={(e) => setIncludeGoogle(e.target.checked)} inputProps={{ "aria-label": "Include Google-provided role grants" }} />}
        label="Include Google-provided role grants" />
      <ErrorAlert error={pol.error} title="Failed to load IAM policy" />
      <Stack direction="row" alignItems="center" spacing={1.5} sx={{ mb: 1.5 }}>
        <ToggleButtonGroup exclusive size="small" value={viewBy} onChange={(_, v) => v && setViewBy(v)} aria-label="View by">
          <ToggleButton value="principals">View by principals</ToggleButton>
          <ToggleButton value="roles">View by roles</ToggleButton>
        </ToggleButtonGroup>
        <Box sx={{ flex: 1 }} />
        <Button startIcon={<AddIcon />} onClick={() => setGrant(true)}>Grant access</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={removeSelected}>Remove access</Button>
      </Stack>
      {viewBy === "principals" ? (
        <ResourceTable resourceName="principals" items={principalRows} rowKey={(r) => r.key} loading={pol.loading} onRetry={pol.reload}
          selectable selected={sel} onSelectedChange={setSel} filterPlaceholder="Enter property name or value"
          columns={[
            { id: "type", header: "Type", sortField: "type", cell: (r) => r.type },
            { id: "principal", header: "Principal", sortField: "member", cell: (r) => r.member },
            { id: "name", header: "Name", sortField: "name", cell: (r) => r.name },
            { id: "role", header: "Role", sortValue: (r) => api.roleTitle(r.role), cell: (r) => api.roleTitle(r.role) },
            { id: "insights", header: "Security insights", cell: () => "–" },
            { id: "inheritance", header: "Inheritance", cell: () => "Direct" },
          ]} />
      ) : (
        <ResourceTable resourceName="roles" items={roleRows} rowKey={(r) => r.key} loading={pol.loading} onRetry={pol.reload}
          selectable selected={sel} onSelectedChange={setSel} filterPlaceholder="Enter property name or value"
          columns={[
            { id: "role", header: "Role", sortValue: (r) => api.roleTitle(r.role), cell: (r) => api.roleTitle(r.role) },
            { id: "members", header: "Principal", wrap: true, cell: (r) => r.members.map((m) => api.parseMember(m).display).join(", ") },
            { id: "insights", header: "Security insights", cell: () => "–" },
            { id: "inheritance", header: "Inheritance", cell: () => "Direct" },
          ]} />
      )}
      {grant && <GrantAccessPanel onClose={() => setGrant(false)} onSave={async (members, role) => {
        const bs = bindings.map((b) => ({ ...b, members: [...b.members] }));
        const hit = bs.find((b) => b.role === role);
        for (const m of members) { if (hit) { if (!hit.members.includes(m)) hit.members.push(m); } else bs.push({ role, members: [m] }); }
        await writeBindings(bs, `Granted ${api.roleTitle(role)} to ${members.length} principal${members.length === 1 ? "" : "s"}`);
      }} />}
    </>
  );
}

const ROLE_CHOICES = Object.entries(api.PREDEFINED_ROLE_TITLES);

function GrantAccessPanel({ onClose, onSave }) {
  const [principals, setPrincipals] = useState("");
  const [role, setRole] = useState("roles/viewer");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const members = principals.split(",").map((s) => s.trim()).filter(Boolean)
    .map((m) => (m === "allUsers" || m === "allAuthenticatedUsers" || /^(user|serviceAccount|group|domain):/.test(m)) ? m : `user:${m}`);
  const ok = members.length > 0;
  const submit = async () => {
    setBusy(true); setError(null);
    try { await onSave(members, role); onClose(); } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Box sx={{ position: "fixed", top: 0, right: 0, bottom: 0, width: { xs: "100%", sm: 460 }, bgcolor: "background.paper", boxShadow: 6, zIndex: 1300, p: 3, overflowY: "auto" }} role="dialog" aria-label="Grant access">
      <Typography variant="h2" component="h2" sx={{ mb: 2 }}>Grant access</Typography>
      <ErrorAlert error={error} />
      <Section title="Add principals">
        <TextField fullWidth label="New principals" value={principals} onChange={(e) => setPrincipals(e.target.value)}
          inputProps={{ "aria-label": "New principals" }} helperText="Comma-separated, e.g. user:dev@example.com, allUsers" />
      </Section>
      <Box sx={{ height: 16 }} />
      <Section title="Assign roles">
        <FormControl fullWidth sx={{ mb: 2 }}>
          <InputLabel id="grant-role-l">Select a role</InputLabel>
          <Select labelId="grant-role-l" label="Select a role" value={role} onChange={(e) => setRole(e.target.value)} inputProps={{ "aria-label": "Select a role" }}>
            {ROLE_CHOICES.map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
          </Select>
        </FormControl>
        <Typography variant="body2" sx={{ fontWeight: 500 }}>IAM condition (optional)</Typography>
        <Button disabled sx={{ mb: 1 }}>Add IAM condition</Button>
        <Box><Button disabled startIcon={<AddIcon />}>Add another role</Button></Box>
      </Section>
      <Stack direction="row" spacing={1} sx={{ mt: 3 }}>
        <Button variant="contained" disabled={!ok || busy} onClick={submit}>{busy ? "Saving…" : "Save"}</Button>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
      </Stack>
    </Box>
  );
}

// ── Deny ──────────────────────────────────────────────────────────────────────────────────
function Deny() {
  const notify = useNotify();
  const list = useAsync(() => api.listDenyPolicies(), []);
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(false);
  const [del, setDel] = useState(false);
  const [simHistory, setSimHistory] = useState(false);
  const rows = list.data || [];
  return (
    <>
      <Stack direction="row" spacing={1} sx={{ mb: 1.5 }}>
        <Button startIcon={<AddIcon />} onClick={() => setCreate(true)}>Create deny policy</Button>
        <Button startIcon={<HistoryIcon />} onClick={() => setSimHistory(true)}>Simulation history</Button>
      </Stack>
      <ErrorAlert error={list.error} title="Failed to load deny policies" />
      <ResourceTable resourceName="deny policies" items={rows} rowKey={(r) => r.name} loading={list.loading} onRetry={list.reload}
        selectable selected={sel} onSelectedChange={setSel} filterPlaceholder="Filter"
        empty={<Stack spacing={1} alignItems="center" sx={{ py: 2 }}>
          <Typography variant="body2" color="text.secondary">No deny policies are attached to this resource</Typography>
          <Button size="small" onClick={() => setCreate(true)}>Create</Button>
        </Stack>}
        columns={[
          { id: "id", header: "Policy ID", cell: (r) => r.name.split("/").pop() },
          { id: "name", header: "Display name", sortField: "displayName", cell: (r) => r.displayName },
          { id: "updated", header: "Last updated", sortField: "updateTime", cell: (r) => fmtDate(r.updateTime) },
          { id: "actions", header: "Actions", cell: (r) => <Button size="small" color="error" onClick={() => setDel(r.name.split("/").pop())}>Delete</Button> },
        ]} />
      {create && <CreateDenyPolicyDialog onClose={() => setCreate(false)} onCreated={() => { notify.success("Created deny policy"); list.reload(); }} />}
      <DeleteDialog open={!!del} onClose={() => setDel(false)} title={`Delete deny policy "${del}"?`} actionLabel="Delete"
        onConfirm={async () => { await api.deleteDenyPolicy(del); notify.success("Deleted deny policy"); setSel([]); list.reload(); }} />
      {simHistory && (
        <Box sx={{ mt: 2 }}>
          <NotSimulatedContainer title="Simulation history" feature="Deny-policy simulation" />
        </Box>
      )}
    </>
  );
}

function CreateDenyPolicyDialog({ onClose, onCreated }) {
  const [policyId, setPolicyId] = useState("");
  const [principal, setPrincipal] = useState("");
  const [permission, setPermission] = useState("storage.objects.delete");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const ok = /^[a-z][a-z0-9-]{2,62}$/.test(policyId) && principal.trim();
  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await api.createDenyPolicy(policyId, {
        displayName: policyId,
        rules: [{ denyRule: { deniedPrincipals: [principal.trim()], deniedPermissions: [permission] } }],
      });
      onCreated(); onClose();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Box sx={{ position: "fixed", top: 0, right: 0, bottom: 0, width: { xs: "100%", sm: 460 }, bgcolor: "background.paper", boxShadow: 6, zIndex: 1300, p: 3, overflowY: "auto" }} role="dialog" aria-label="Create deny policy">
      <Typography variant="h2" component="h2" sx={{ mb: 2 }}>Create deny policy</Typography>
      <ErrorAlert error={error} />
      <Stack spacing={2}>
        <TextField label="Policy ID" value={policyId} onChange={(e) => setPolicyId(e.target.value.trim())}
          helperText="Lowercase letters, numbers and hyphens" />
        <TextField label="Denied principal" value={principal} onChange={(e) => setPrincipal(e.target.value)} helperText="e.g. user:ex-employee@example.com" />
        <TextField label="Denied permission" value={permission} onChange={(e) => setPermission(e.target.value)} />
      </Stack>
      <Stack direction="row" spacing={1} sx={{ mt: 3 }}>
        <Button variant="contained" disabled={!ok || busy} onClick={submit}>{busy ? "Creating…" : "Create"}</Button>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
      </Stack>
    </Box>
  );
}

// ── Recommendations history ────────────────────────────────────────────────────────────────
const WINDOWS = [["1", "1 day"], ["7", "7 days"], ["30", "30 days"], ["60", "60 days"], ["90", "90 days"]];

function RecommendationsHistory() {
  const log = useAsync(() => api.listPolicyActivity(), []);
  const [days, setDays] = useState("30");
  const cutoff = Date.now() - Number(days) * 86400 * 1000;
  const rows = (log.data || []).filter((e) => new Date(e.time).getTime() >= cutoff);
  return (
    <Section title="History of applied recommendations"
      description="Vyomi logs applied IAM policy changes here (grants and removals from the Allow tab); it does not run GCP's IAM Recommender to generate new suggestions on its own.">
      <RadioGroup row value={days} onChange={(e) => setDays(e.target.value)} aria-label="View by" sx={{ mb: 2 }}>
        {WINDOWS.map(([v, l]) => <FormControlLabel key={v} value={v} control={<Radio size="small" />} label={l} />)}
      </RadioGroup>
      <ErrorAlert error={log.error} />
      <ResourceTable resourceName="applied recommendations" items={rows} rowKey={(r) => r.id} loading={log.loading} onRetry={log.reload}
        filterPlaceholder="Filter"
        empty={<Typography variant="body2" color="text.secondary">There is no activity for the recommendations history at this time.</Typography>}
        columns={[
          { id: "time", header: "Date applied", sortField: "time", cell: (r) => fmtDate(r.time) },
          { id: "action", header: "Action", cell: (r) => r.action === "GRANT" ? "Granted role" : "Removed role" },
          { id: "role", header: "Role", cell: (r) => api.roleTitle(r.role) },
          { id: "member", header: "Principal", cell: (r) => api.parseMember(r.member).display },
        ]} />
    </Section>
  );
}
