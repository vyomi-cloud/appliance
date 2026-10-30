/* Privileged Access Manager — Entitlements tab is real (native PAM v1 entitlements
 * CRUD); Grants / Approve grants / Audit Logs / Settings aren't modeled (requesting,
 * approving and time-boxed activation of a grant). */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogContent, DialogTitle, Stack, Tab, Tabs, TextField, ToggleButton, ToggleButtonGroup } from "@mui/material";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import AddIcon from "@mui/icons-material/esm/Add.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, PageHeader } from "../../kit/common.jsx";
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
      {tab === "grants" && <CapabilityContainer id="gcp.iam-admin.pam-workflow" title="Grants" />}
      {tab === "approve" && <CapabilityContainer id="gcp.iam-admin.pam-workflow" title="Approve grants" />}
      {tab === "audit" && <CapabilityContainer id="gcp.iam-admin.pam-workflow" title="Audit Logs" />}
      {tab === "settings" && <CapabilityContainer id="gcp.iam-admin.pam-workflow" title="Settings" />}
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
