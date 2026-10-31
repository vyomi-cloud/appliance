/* Organization policies — native Org Policy v2 policies CRUD on the project. Custom
 * constraints are config_only (stored/returned, not evaluated). Two predefined boolean
 * constraints — iam.disableServiceAccountCreation, iam.disableServiceAccountKeyCreation —
 * are ENFORCED for real: core/gcp_iam_core.org_policy_enforced() checks them before
 * serviceAccounts.create / keys.create on both Nano and the offline substrate. */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, MenuItem, Stack, Switch, TextField } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, NotSimulated, PageHeader } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

const ENFORCED_CONSTRAINTS = [
  { id: "iam.disableServiceAccountCreation", label: "Disable service account creation" },
  { id: "iam.disableServiceAccountKeyCreation", label: "Disable service account key creation" },
];

export default function OrgPolicies() {
  const notify = useNotify();
  const list = useAsync(() => api.listOrgPolicies(), []);
  const [create, setCreate] = useState(false);
  const [createPredefined, setCreatePredefined] = useState(false);
  const [del, setDel] = useState(false);
  const [simulate, setSimulate] = useState(false);
  const [simHistory, setSimHistory] = useState(false);

  const constraintType = (p) => {
    const id = p.name.split("/policies/")[1] || "";
    if (id.startsWith("constraints/")) return "Boolean";
    return "Custom";
  };

  return (
    <>
      <PageHeader title="Organization policies" actions={
        <Stack direction="row" spacing={1}>
          <Button onClick={() => setCreatePredefined(true)}>Enforce predefined constraint</Button>
          <Button onClick={() => setCreate(true)}>Custom constraint</Button>
          <Button onClick={() => setSimulate((v) => !v)}>Simulate constraint</Button>
          <Button onClick={() => setSimHistory((v) => !v)}>Simulation history</Button>
        </Stack>} />
      {simulate && <NotSimulated feature="Simulating a constraint change against existing resources" />}
      {simHistory && <NotSimulated feature="Constraint simulation history" />}
      <ErrorAlert error={list.error} title="Failed to load organization policies" />
      <CapabilityContainer id="gcp.iam-admin.organization-policies" title="Organization policies">
        <ResourceTable resourceName="policies" items={list.data || []} rowKey={(p) => p.name} loading={list.loading} onRetry={list.reload} filterPlaceholder="Filter"
          columns={[
            { id: "state", header: "Enforcement state", cell: (p) => p.spec?.rules?.[0]?.enforce ? "Enforced" : "Not enforced" },
            { id: "name", header: "Name", cell: (p) => p.name.split("/").pop() },
            { id: "id", header: "ID", cell: (p) => p.name },
            { id: "insights", header: "Security insights", cell: () => "–" },
            { id: "type", header: "Constraint type", cell: constraintType },
            { id: "source", header: "Policy source", cell: () => "This resource" },
            { id: "actions", header: "Actions", cell: (p) => <Button size="small" color="error" onClick={() => setDel(p.name)}>Delete</Button> },
          ]} />
      </CapabilityContainer>
      {create && <CreateConstraintDialog onClose={() => setCreate(false)} onCreated={() => { notify.success("Created organization policy"); list.reload(); }} />}
      {createPredefined && (
        <EnforcePredefinedDialog onClose={() => setCreatePredefined(false)}
          onCreated={() => { notify.success("Organization policy enforced"); list.reload(); }} />
      )}
      <DeleteDialog open={!!del} onClose={() => setDel(false)} title="Delete this policy?" actionLabel="Delete"
        onConfirm={async () => { await api.deleteOrgPolicy(del); notify.success("Deleted policy"); list.reload(); }} />
    </>
  );
}

function EnforcePredefinedDialog({ onClose, onCreated }) {
  const [id, setId] = useState(ENFORCED_CONSTRAINTS[0].id);
  const [enforce, setEnforce] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Enforce a predefined constraint</DialogTitle>
      <DialogContent>
        <ErrorAlert error={error} />
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField select label="Constraint" value={id} onChange={(e) => setId(e.target.value)}
            helperText="Vyomi evaluates these two constraints for real on serviceAccounts.create / keys.create.">
            {ENFORCED_CONSTRAINTS.map((c) => <MenuItem key={c.id} value={c.id}>{c.label}</MenuItem>)}
          </TextField>
          <FormControlLabel control={<Switch checked={enforce} onChange={(e) => setEnforce(e.target.checked)} />} label="Enforce" />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy} onClick={async () => {
          setBusy(true); setError(null);
          try { await api.createOrgPolicy(`constraints/${id}`, { spec: { rules: [{ enforce }] } }); onCreated(); onClose(); }
          catch (e) { setError(e); } finally { setBusy(false); }
        }}>{busy ? "Creating…" : "Create"}</Button>
      </DialogActions>
    </Dialog>
  );
}

function CreateConstraintDialog({ onClose, onCreated }) {
  const [id, setId] = useState("");
  const [enforce, setEnforce] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const ok = /^custom\.[a-zA-Z][a-zA-Z0-9]{2,62}$/.test(id);
  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Create a custom constraint</DialogTitle>
      <DialogContent>
        <ErrorAlert error={error} />
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField label="Constraint ID" value={id} onChange={(e) => setId(e.target.value.trim())} error={!!id && !ok}
            helperText='e.g. "custom.disableExternalIps"' />
          <FormControlLabel control={<Switch checked={enforce} onChange={(e) => setEnforce(e.target.checked)} />} label="Enforce" />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={!ok || busy} onClick={async () => {
          setBusy(true); setError(null);
          try { await api.createOrgPolicy(id, { spec: { rules: [{ enforce }] } }); onCreated(); onClose(); }
          catch (e) { setError(e); } finally { setBusy(false); }
        }}>{busy ? "Creating…" : "Create"}</Button>
      </DialogActions>
    </Dialog>
  );
}
