/* Permissions — real project IAM bindings via the resourcemanager-style getIamPolicy /
 * setIamPolicy round-trip (the same generic IAM policy store every Vyomi GCP resource
 * shares). Vyomi stores and lists grants for real; it never evaluates them against an
 * actual API call (see gcp.monitoring.permissions). */
import { useState } from "react";
import { Button, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, Stack, TextField, Typography } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { PageHeader, Section } from "../../kit/common.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

const typeOf = (m) => ({ user: "User", serviceAccount: "Service account", group: "Group", domain: "Domain" }[m.split(":")[0]] || "Principal");

function GrantDialog({ open, onClose, onGranted }) {
  const notify = useNotify();
  const [principal, setPrincipal] = useState("");
  const [role, setRole] = useState("roles/monitoring.editor");
  const [busy, setBusy] = useState(false);
  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>Grant access</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <TextField label="New principals" placeholder="user:alice@example.com" value={principal} onChange={(e) => setPrincipal(e.target.value)} />
          <TextField label="Role" value={role} onChange={(e) => setRole(e.target.value)} helperText="e.g. roles/monitoring.editor, roles/monitoring.viewer" />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" disabled={!principal.trim() || !role.trim() || busy} onClick={async () => {
          setBusy(true);
          const policy = await api.getProjectIamPolicy();
          const bindings = policy.bindings || [];
          const b = bindings.find((x) => x.role === role);
          if (b) b.members = [...new Set([...b.members, principal])]; else bindings.push({ role, members: [principal] });
          await api.setProjectIamPolicy(bindings);
          notify.success(`Granted ${role} to ${principal}`);
          setBusy(false); onGranted();
        }}>Save</Button>
      </DialogActions>
    </Dialog>
  );
}

export default function Permissions() {
  const project = useProject();
  const notify = useNotify();
  const [grantOpen, setGrantOpen] = useState(false);
  const [onlyMonitoring, setOnlyMonitoring] = useState(false);
  const [sel, setSel] = useState([]);
  const { data, loading, error, reload } = useAsync(() => api.getProjectIamPolicy(), [project]);

  const rows = (data?.bindings || []).flatMap((b) => b.members.map((m) => ({ key: `${b.role}|${m}`, role: b.role, member: m })))
    .filter((r) => !onlyMonitoring || /monitoring/i.test(r.role));

  const removeSelected = async () => {
    const policy = await api.getProjectIamPolicy();
    const bindings = (policy.bindings || []).map((b) => ({ ...b, members: b.members.filter((m) => !sel.includes(`${b.role}|${m}`)) })).filter((b) => b.members.length);
    await api.setProjectIamPolicy(bindings);
    notify.success(`Removed ${sel.length} binding(s)`);
    setSel([]); reload();
  };

  return (
    <>
      <PageHeader title="Permissions" />
      <Section title="Permissions for project">
        <FormControlLabel control={<Checkbox checked={onlyMonitoring} onChange={(e) => setOnlyMonitoring(e.target.checked)} />} label="Include all roles with Monitoring permissions" />
      </Section>
      <Stack direction="row" spacing={1} sx={{ mt: 2, mb: 1 }}>
        <Button onClick={() => setGrantOpen(true)}>Grant access</Button>
        <Button disabled={!sel.length} onClick={removeSelected}>Remove access</Button>
      </Stack>
      <ResourceTable
        resourceName="permissions"
        items={rows}
        loading={loading}
        error={error}
        onRetry={reload}
        selectable
        selected={sel}
        onSelectedChange={setSel}
        rowKey={(r) => r.key}
        filterPlaceholder="Filter"
        columns={[
          { id: "type", header: "Type", cell: (r) => typeOf(r.member) },
          { id: "principal", header: "Principal", cell: (r) => r.member },
          { id: "name", header: "Name", cell: (r) => r.member.split(":").slice(1).join(":") },
          { id: "role", header: "Role", sortField: "role", cell: (r) => r.role },
          { id: "inheritance", header: "Inheritance", cell: () => "Direct" },
        ]}
        empty={<Typography variant="body2" color="text.secondary">No principals have been granted access yet.</Typography>}
      />
      <GrantDialog open={grantOpen} onClose={() => setGrantOpen(false)} onGranted={() => { setGrantOpen(false); reload(); }} />
    </>
  );
}
