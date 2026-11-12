/* Principal Access Boundary — org-scoped policies + bindings that REALLY narrow a
 * bound principal's access (core/gcp_iam_core.py's testIamPermissions consults these
 * on every call) — resource-type boundaries and the CEL condition language aren't evaluated. */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem, Stack, TextField } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, PageHeader, Section } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

export default function PrincipalAccessBoundary() {
  const notify = useNotify();
  const policies = useAsync(() => api.listPabPolicies(), []);
  const bindings = useAsync(() => api.listPabBindings(), []);
  const [createPolicy, setCreatePolicy] = useState(false);
  const [createBinding, setCreateBinding] = useState(false);
  const [delPolicy, setDelPolicy] = useState(null);
  const [delBinding, setDelBinding] = useState(null);
  const reloadAll = () => { policies.reload(); bindings.reload(); };

  return (
    <>
      <PageHeader title="Principal Access Boundary" />
      <CapabilityContainer id="gcp.iam-admin.principal-access-boundary" title="Principal Access Boundary">
        <Section title="Policies" actions={<Button variant="contained" onClick={() => setCreatePolicy(true)}>Create policy</Button>}>
          <ErrorAlert error={policies.error} />
          <ResourceTable resourceName="policies" items={policies.data || []} rowKey={(p) => p.name} loading={policies.loading}
            empty="No Principal Access Boundary policies yet."
            columns={[
              { id: "name", header: "Policy", cell: (p) => p.displayName || p.name.split("/").pop() },
              { id: "resources", header: "In-boundary resources", cell: (p) => (p.details?.rules || []).flatMap((r) => r.resources || []).join(", ") || "—" },
              { id: "actions", header: "", cell: (p) => <Button size="small" color="error" onClick={() => setDelPolicy(p)}>Delete</Button> },
            ]} />
        </Section>
        <Section title="Policy bindings" actions={<Button variant="contained" disabled={!policies.data?.length} onClick={() => setCreateBinding(true)}>Create binding</Button>}>
          <ErrorAlert error={bindings.error} />
          <ResourceTable resourceName="policy bindings" items={bindings.data || []} rowKey={(b) => b.name} loading={bindings.loading}
            empty="No policy bindings yet."
            columns={[
              { id: "principal", header: "Principal", cell: (b) => b.target.principal },
              { id: "policy", header: "Policy", cell: (b) => b.policy.split("/").pop() },
              { id: "actions", header: "", cell: (b) => <Button size="small" color="error" onClick={() => setDelBinding(b)}>Delete</Button> },
            ]} />
        </Section>
      </CapabilityContainer>
      {createPolicy && <CreatePolicyDialog onClose={() => setCreatePolicy(false)} onCreated={() => { notify.success("Created policy"); policies.reload(); }} />}
      {createBinding && <CreateBindingDialog policies={policies.data || []} onClose={() => setCreateBinding(false)} onCreated={() => { notify.success("Created policy binding"); bindings.reload(); }} />}
      <DeleteDialog open={!!delPolicy} onClose={() => setDelPolicy(null)} title={`Delete policy ${delPolicy?.name.split("/").pop()}?`}
        warning="Deleting a policy also deletes every binding that references it." actionLabel="Delete"
        onConfirm={async () => { await api.deletePabPolicy(delPolicy.name); notify.success("Deleted policy"); reloadAll(); }} />
      <DeleteDialog open={!!delBinding} onClose={() => setDelBinding(null)} title="Delete this policy binding?" actionLabel="Delete"
        onConfirm={async () => { await api.deletePabBinding(delBinding.name); notify.success("Deleted policy binding"); bindings.reload(); }} />
    </>
  );
}

function CreatePolicyDialog({ onClose, onCreated }) {
  const [id, setId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [resources, setResources] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const ok = /^[a-z][a-z0-9-]{3,62}$/.test(id) && resources.trim();
  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Create Principal Access Boundary policy</DialogTitle>
      <DialogContent>
        <ErrorAlert error={error} />
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField label="Policy ID" value={id} onChange={(e) => setId(e.target.value.trim())} helperText="Lowercase letters, numbers, hyphens" />
          <TextField label="Display name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
          <TextField label="In-boundary resources" value={resources} onChange={(e) => setResources(e.target.value)}
            helperText="Comma-separated resource names, e.g. projects/my-project" />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={!ok || busy} onClick={async () => {
          setBusy(true); setError(null);
          try {
            await api.createPabPolicy(id, displayName || id, resources.split(",").map((r) => r.trim()).filter(Boolean));
            onCreated(); onClose();
          } catch (e) { setError(e); } finally { setBusy(false); }
        }}>{busy ? "Creating…" : "Create"}</Button>
      </DialogActions>
    </Dialog>
  );
}

function CreateBindingDialog({ policies, onClose, onCreated }) {
  const [policy, setPolicy] = useState(policies[0]?.name || "");
  const [principal, setPrincipal] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const ok = policy && /^(user|serviceAccount|group|domain):.+/.test(principal);
  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Create policy binding</DialogTitle>
      <DialogContent>
        <ErrorAlert error={error} />
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField select label="Policy" value={policy} onChange={(e) => setPolicy(e.target.value)}>
            {policies.map((p) => <MenuItem key={p.name} value={p.name}>{p.displayName || p.name.split("/").pop()}</MenuItem>)}
          </TextField>
          <TextField label="Principal" value={principal} onChange={(e) => setPrincipal(e.target.value.trim())} helperText="e.g. user:alice@example.com" />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={!ok || busy} onClick={async () => {
          setBusy(true); setError(null);
          try { await api.createPabBinding(`b-${Date.now().toString(36)}`, policy, principal); onCreated(); onClose(); }
          catch (e) { setError(e); } finally { setBusy(false); }
        }}>{busy ? "Creating…" : "Create"}</Button>
      </DialogActions>
    </Dialog>
  );
}
