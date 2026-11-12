/* Workload Identity Federation — pool creation is real (native iam.googleapis.com
 * workloadIdentityPools CRUD); connecting an external OIDC/SAML provider is not modeled. */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogContent, DialogTitle, Stack, TextField, Typography } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { ErrorAlert, PageHeader, Section } from "../../kit/common.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import ProviderDialog from "./ProviderDialog.jsx";
import * as api from "./api.js";

export default function WorkloadIdentity() {
  const notify = useNotify();
  const list = useAsync(() => api.listWorkloadIdentityPools(), []);
  const [open, setOpen] = useState(false);
  const [provFor, setProvFor] = useState(null);
  const [provKey, setProvKey] = useState(0);

  return (
    <>
      <PageHeader title="Workload Identity Federation" />
      <Section title="1. Create a workload identity pool">
        <Typography variant="body2" color="text.secondary">A workload identity pool is an entity that lets you manage external identities.</Typography>
      </Section>
      <Section title={<>2. Connect an identity provider <CapabilityBadge id="gcp.iam-admin.workload-identity-providers" /></>}
        description="Add an OIDC, SAML or AWS provider to a pool, with its attribute mapping and condition (step 3). Exchange a provider's token for a federated access token at /v1/token.">
        <Typography variant="body2" color="text.secondary">Use "Add provider" on a pool in step 4.</Typography>
      </Section>
      <Section title="3. Configure provider mapping">
        <Typography variant="body2" color="text.secondary">Attribute mapping and the attribute condition are set when the provider is added.</Typography>
      </Section>
      <Section title="4. Grant access" actions={<Button variant="contained" onClick={() => setOpen(true)}>Get started</Button>}>
        <ErrorAlert error={list.error} />
        <ResourceTable resourceName="workload identity pools" items={list.data || []} rowKey={(p) => p.name} loading={list.loading} onRetry={list.reload}
          empty="No workload identity pools yet."
          columns={[
            { id: "name", header: "Pool", cell: (p) => p.displayName || p.name.split("/").pop() },
            { id: "id", header: "Pool ID", cell: (p) => p.name.split("/").pop() },
            { id: "state", header: "State", cell: (p) => p.state },
            { id: "providers", header: "Providers", cell: (p) => <PoolProviders pool={p} reloadKey={provKey} /> },
            { id: "actions", header: "", cell: (p) => <Button size="small" onClick={() => setProvFor(p.name)}>Add provider</Button> },
          ]} />
      </Section>
      {provFor && <ProviderDialog poolName={provFor} onClose={() => setProvFor(null)} onCreated={() => { notify.success("Added provider"); setProvKey((k) => k + 1); }} />}
      {open && <CreatePoolDialog onClose={() => setOpen(false)} onCreated={() => { notify.success("Created workload identity pool"); list.reload(); }} />}
    </>
  );
}

function CreatePoolDialog({ onClose, onCreated }) {
  const [id, setId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const ok = /^[a-z][a-z0-9-]{3,31}$/.test(id);
  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Create a pool</DialogTitle>
      <DialogContent>
        <ErrorAlert error={error} />
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField label="Pool ID" value={id} onChange={(e) => setId(e.target.value.trim())} error={!!id && !ok} helperText="4-32 characters: lowercase letters, numbers, hyphens" />
          <TextField label="Display name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={!ok || busy} onClick={async () => {
          setBusy(true); setError(null);
          try { await api.createWorkloadIdentityPool(id, { displayName: displayName || id }); onCreated(); onClose(); }
          catch (e) { setError(e); } finally { setBusy(false); }
        }}>{busy ? "Creating…" : "Create pool"}</Button>
      </DialogActions>
    </Dialog>
  );
}

function PoolProviders({ pool, reloadKey }) {
  const list = useAsync(() => api.listProviders(pool.name), [pool.name, reloadKey]);
  const items = list.data || [];
  if (!items.length) return "—";
  return <span data-pool-providers={pool.name}>{items.map((p) => `${p.name.split("/").pop()} (${p.oidc ? "OIDC" : p.saml ? "SAML" : "AWS"})`).join(", ")}</span>;
}
