/* Privileged Access Manager: Entitlements, Grants and Approve grants are real (native
 * PAM v1 — requesting a grant, approving/denying it and its time-boxed activation
 * really add/remove the requester's IAM binding on the project, with lazy expiry).
 * Audit Logs renders the grant lifecycle Vyomi actually recorded (not the full Cloud
 * Audit Log trail). Settings (notification channels) isn't modeled. */
import { useState } from "react";
import { Button, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, MenuItem, Stack, Tab, Tabs, TextField, ToggleButton, ToggleButtonGroup } from "@mui/material";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import AddIcon from "@mui/icons-material/esm/Add.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, PageHeader, fmtDate } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

const TABS = [["entitlements", "Entitlements"], ["grants", "Grants"], ["approve", "Approve grants"], ["audit", "Audit Logs"], ["settings", "Settings"]];

export default function Pam() {
  const [tab, setTab] = useState("entitlements");
  return (
    <>
      <PageHeader title="Privileged Access Manager" />
      <Tabs value={tab} onChange={(_, t) => setTab(t)} sx={{ borderBottom: 1, borderColor: "divider", mb: 2.5 }} aria-label="PAM tabs">
        {TABS.map(([id, label]) => <Tab key={id} value={id} label={label} />)}
      </Tabs>
      {tab === "entitlements" && <Entitlements />}
      {tab === "grants" && <Grants />}
      {tab === "approve" && <ApproveGrants />}
      {tab === "audit" && <AuditLogs />}
      {tab === "settings" && <Settings />}
    </>
  );
}

function Entitlements() {
  const notify = useNotify();
  const list = useAsync(() => api.listEntitlements(), []);
  const [filter, setFilter] = useState("all");
  const [create, setCreate] = useState(false);
  const [del, setDel] = useState(false);

  return (
    <>
      <Stack direction="row" alignItems="center" spacing={1.5} sx={{ mb: 1.5 }}>
        <ToggleButtonGroup exclusive size="small" value={filter} onChange={(_, v) => v && setFilter(v)} aria-label="Entitlements filter">
          <ToggleButton value="all">Entitlements for all users</ToggleButton>
          <ToggleButton value="mine">My Entitlements</ToggleButton>
        </ToggleButtonGroup>
        <Stack direction="row" spacing={1} sx={{ ml: "auto" }}>
          <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreate(true)}>Create</Button>
          <Button startIcon={<RefreshIcon />} onClick={list.reload}>Refresh</Button>
        </Stack>
      </Stack>
      <ErrorAlert error={list.error} title="Failed to load entitlements" />
      <ResourceTable resourceName="entitlements" items={list.data || []} rowKey={(e) => e.name} loading={list.loading} onRetry={list.reload}
        filterPlaceholder="Filter" empty="No entitlements"
        columns={[
          { id: "name", header: "Entitlement name", cell: (e) => e.name.split("/").pop() },
          { id: "inheritance", header: "Inheritance", cell: () => "Direct" },
          { id: "roles", header: "Role(s) & condition(s)", cell: (e) => (e.privilegedAccess?.gcpIamAccess?.roleBindings || []).map((r) => r.role).join(", ") || "—" },
          { id: "duration", header: "Maximum duration", cell: (e) => e.maxRequestDuration },
          { id: "approvers", header: "Approver(s)", cell: (e) => (e.approvalWorkflow?.manualApprovals?.steps || []).flatMap((s) => s.approvers || []).flatMap((a) => a.principals || []).join(", ") || "None (auto-approved)" },
          { id: "status", header: "Status", cell: (e) => e.state },
          { id: "actions", header: "", cell: (e) => <Button size="small" color="error" onClick={() => setDel(e.name)}>Delete</Button> },
        ]} />
      {create && <CreateEntitlementDialog onClose={() => setCreate(false)} onCreated={() => { notify.success("Created entitlement"); list.reload(); }} />}
      <DeleteDialog open={!!del} onClose={() => setDel(false)} title="Delete this entitlement?" actionLabel="Delete"
        onConfirm={async () => { await api.deleteEntitlement(del); notify.success("Deleted entitlement"); list.reload(); }} />
    </>
  );
}

function CreateEntitlementDialog({ onClose, onCreated }) {
  const [id, setId] = useState("");
  const [role, setRole] = useState("roles/owner");
  const [hours, setHours] = useState("1");
  const [approver, setApprover] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const ok = /^[a-z][a-z0-9-]{2,62}$/.test(id) && Number(hours) > 0;
  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Create entitlement</DialogTitle>
      <DialogContent>
        <ErrorAlert error={error} />
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField label="Entitlement ID" value={id} onChange={(e) => setId(e.target.value.trim())} helperText="Lowercase letters, numbers, hyphens" />
          <TextField label="Role" value={role} onChange={(e) => setRole(e.target.value)} />
          <TextField label="Maximum duration (hours)" type="number" value={hours} onChange={(e) => setHours(e.target.value)} />
          <TextField label="Approver (optional)" value={approver} onChange={(e) => setApprover(e.target.value)} helperText="e.g. user:boss@example.com — blank means auto-approved" />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={!ok || busy} onClick={async () => {
          setBusy(true); setError(null);
          try {
            await api.createEntitlement(id, {
              maxRequestDuration: `${Number(hours) * 3600}s`,
              privilegedAccess: { gcpIamAccess: { roleBindings: [{ role }] } },
              approvalWorkflow: approver ? { manualApprovals: { steps: [{ approvers: [{ principals: [approver] }] }] } } : {},
            });
            onCreated(); onClose();
          } catch (e) { setError(e); } finally { setBusy(false); }
        }}>{busy ? "Creating…" : "Create"}</Button>
      </DialogActions>
    </Dialog>
  );
}

const grantRole = (g) => (g.privilegedAccess?.gcpIamAccess?.roleBindings || []).map((r) => r.role).join(", ") || "—";
const grantEntitlement = (g) => api.grantEntitlementId(g.name);

function Grants() {
  const notify = useNotify();
  const entitlements = useAsync(() => api.listEntitlements(), []);
  const list = useAsync(() => api.listAllGrants(), []);
  const [request, setRequest] = useState(false);
  const [revoke, setRevoke] = useState(false);

  return (
    <>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1.5 }}>
        <Button variant="contained" startIcon={<AddIcon />} disabled={!entitlements.data?.length} onClick={async () => { await entitlements.reload(); setRequest(true); }}>Request access</Button>
        <Button startIcon={<RefreshIcon />} onClick={() => { list.reload(); entitlements.reload(); }}>Refresh</Button>
      </Stack>
      <ErrorAlert error={list.error} title="Failed to load grants" />
      <ResourceTable resourceName="grants" items={list.data || []} rowKey={(g) => g.name} loading={list.loading} onRetry={list.reload}
        filterPlaceholder="Filter" empty="No grants"
        columns={[
          { id: "entitlement", header: "Entitlement", cell: grantEntitlement },
          { id: "role", header: "Role(s)", cell: grantRole },
          { id: "requester", header: "Requester", cell: (g) => g.requester },
          { id: "state", header: "Status", cell: (g) => g.state },
          { id: "expires", header: "Expires", cell: (g) => (g.state === "ACTIVATED" ? fmtDate(g.scheduledExpireTime) : "—") },
          { id: "actions", header: "", cell: (g) => g.state === "ACTIVATED" ? <Button size="small" color="error" onClick={() => setRevoke(g.name)}>Revoke</Button> : null },
        ]} />
      {request && <RequestGrantDialog entitlements={entitlements.data || []} onClose={() => setRequest(false)}
        onCreated={() => { notify.success("Requested access"); list.reload(); }} />}
      <DeleteDialog open={!!revoke} onClose={() => setRevoke(false)} title="Revoke this grant?" actionLabel="Revoke"
        onConfirm={async () => { await api.revokeGrant(revoke); notify.success("Revoked grant"); list.reload(); }} />
    </>
  );
}

function RequestGrantDialog({ entitlements, onClose, onCreated }) {
  const [entitlement, setEntitlement] = useState(entitlements[0]?.name || "");
  const [requester, setRequester] = useState("user:me@example.com");
  const [justification, setJustification] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Request access</DialogTitle>
      <DialogContent>
        <ErrorAlert error={error} />
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField select label="Entitlement" value={entitlement} onChange={(e) => setEntitlement(e.target.value)}
            SelectProps={{ inputProps: { "aria-label": "Entitlement" } }}>
            {entitlements.map((e) => <MenuItem key={e.name} value={e.name}>{e.name.split("/").pop()}</MenuItem>)}
          </TextField>
          <TextField label="Requester" value={requester} onChange={(e) => setRequester(e.target.value)} helperText="e.g. user:me@example.com" />
          <TextField label="Justification" value={justification} onChange={(e) => setJustification(e.target.value)} multiline minRows={2} />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={!entitlement || busy} onClick={async () => {
          setBusy(true); setError(null);
          try {
            await api.createGrant(entitlement, { requester, justification: { unstructuredJustification: justification } });
            onCreated(); onClose();
          } catch (e) { setError(e); } finally { setBusy(false); }
        }}>{busy ? "Requesting…" : "Submit request"}</Button>
      </DialogActions>
    </Dialog>
  );
}

function ApproveGrants() {
  const notify = useNotify();
  const list = useAsync(() => api.listAllGrants(), []);
  const pending = (list.data || []).filter((g) => g.state === "APPROVAL_AWAITED");

  return (
    <>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1.5 }}>
        <Button startIcon={<RefreshIcon />} onClick={list.reload}>Refresh</Button>
      </Stack>
      <ErrorAlert error={list.error} title="Failed to load grants" />
      <ResourceTable resourceName="grant requests" items={pending} rowKey={(g) => g.name} loading={list.loading} onRetry={list.reload}
        filterPlaceholder="Filter" empty="No grants awaiting approval"
        columns={[
          { id: "entitlement", header: "Entitlement", cell: grantEntitlement },
          { id: "role", header: "Role(s)", cell: grantRole },
          { id: "requester", header: "Requester", cell: (g) => g.requester },
          { id: "justification", header: "Justification", cell: (g) => g.justification?.unstructuredJustification || "—" },
          { id: "requested", header: "Requested", cell: (g) => fmtDate(g.createTime) },
          {
            id: "actions", header: "", cell: (g) => (
              <Stack direction="row" spacing={1}>
                <Button size="small" variant="contained" onClick={async () => { await api.approveGrant(g.name); notify.success("Approved grant"); list.reload(); }}>Approve</Button>
                <Button size="small" color="error" onClick={async () => { await api.denyGrant(g.name); notify.success("Denied grant"); list.reload(); }}>Deny</Button>
              </Stack>
            ),
          },
        ]} />
    </>
  );
}

function Settings() {
  const notify = useNotify();
  const settings = useAsync(() => api.getPamSettings(), []);
  const notifs = useAsync(() => api.listPamNotifications(), []);
  const [channels, setChannels] = useState(null);
  const [requireJustification, setRequireJustification] = useState(null);
  const [busy, setBusy] = useState(false);
  if (settings.data && channels === null) setChannels(settings.data.notificationChannels.join(", "));
  if (settings.data && requireJustification === null) setRequireJustification(settings.data.requireJustification);
  return (
    <CapabilityContainer id="gcp.iam-admin.pam-settings" title="Settings" actions={
      <Button variant="contained" size="small" disabled={busy || !settings.data} onClick={async () => {
        setBusy(true);
        try {
          await api.patchPamSettings({
            notificationChannels: channels.split(",").map((c) => c.trim()).filter(Boolean),
            requireJustification: !!requireJustification,
          });
          notify.success("Saved PAM settings");
          settings.reload(); notifs.reload();
        } catch (e) { notify.error(e); } finally { setBusy(false); }
      }}>Save</Button>}>
      <ErrorAlert error={settings.error} title="Failed to load settings" />
      <Stack spacing={2} sx={{ maxWidth: 480, mb: 3 }}>
        <TextField label="Notification channels" value={channels ?? ""} onChange={(e) => setChannels(e.target.value)}
          helperText="Comma-separated email addresses notified on grant lifecycle events" />
        <FormControlLabel control={<Checkbox checked={!!requireJustification} onChange={(e) => setRequireJustification(e.target.checked)} />}
          label="Require a justification to request a grant" />
      </Stack>
      <Stack sx={{ fontWeight: 500, mb: 1 }}>Recent notifications</Stack>
      <ResourceTable resourceName="notifications" items={notifs.data || []} rowKey={(n) => `${n.grant}#${n.event}#${n.time}`}
        loading={notifs.loading} empty="No notifications recorded yet" filterPlaceholder="Filter"
        columns={[
          { id: "time", header: "Time", cell: (n) => fmtDate(n.time) },
          { id: "event", header: "Event", cell: (n) => n.event },
          { id: "grant", header: "Grant", cell: (n) => n.grant.split("/").pop() },
          { id: "channels", header: "Notified channels", cell: (n) => n.channels.join(", ") },
        ]} />
    </CapabilityContainer>
  );
}

function AuditLogs() {
  const list = useAsync(() => api.listAllGrants(), []);
  const events = (list.data || []).flatMap((g) => (g.timeline?.events || []).map((ev, i) => ({ ...ev, grant: g.name, _key: `${g.name}#${i}` })))
    .sort((a, b) => (a.eventTime < b.eventTime ? 1 : -1));

  return (
    <CapabilityContainer id="gcp.iam-admin.pam-audit-logs" title="Audit Logs">
      <ErrorAlert error={list.error} title="Failed to load audit logs" />
      <ResourceTable resourceName="log entries" items={events} rowKey={(ev) => ev._key} loading={list.loading} onRetry={list.reload}
        filterPlaceholder="Filter" empty="No PAM activity yet"
        columns={[
          { id: "time", header: "Time", cell: (ev) => fmtDate(ev.eventTime) },
          { id: "event", header: "Event", cell: (ev) => ev.event },
          { id: "entitlement", header: "Entitlement", cell: (ev) => api.grantEntitlementId(ev.grant) },
          { id: "grant", header: "Grant", cell: (ev) => ev.grant.split("/").pop() },
          { id: "actor", header: "Actor", cell: (ev) => ev.actor },
        ]} />
    </CapabilityContainer>
  );
}
