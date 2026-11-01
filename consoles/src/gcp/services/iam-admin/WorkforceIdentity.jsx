/* Workforce Identity Federation — pool creation under the project's real backing
 * organization (native iam.googleapis.com locations/global/workforcePools CRUD);
 * connecting an external OIDC/SAML workforce identity provider is not modeled
 * (same limitation as the project-scoped Workload Identity Federation pools). */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogContent, DialogTitle, Stack, TextField, Typography } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, NotSimulated, PageHeader, Section } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

export default function WorkforceIdentity() {
  const notify = useNotify();
  const list = useAsync(() => api.listWorkforcePools(), []);
  const [open, setOpen] = useState(false);
  const [del, setDel] = useState(null);

  return (
    <>
      <PageHeader title="Workforce Identity Federation" />
      <CapabilityContainer id="gcp.iam-admin.workforce-identity-federation" title="Workforce Identity Federation" actions={
        <Button variant="contained" onClick={() => setOpen(true)}>Create pool</Button>}>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          A workforce identity pool manages external workforce identities (your own employees and partners) for
          workforce identity federation, under this project's organization.
        </Typography>
        <Section title="Connect an identity provider">
          <NotSimulated compact feature="Connecting an external OIDC/SAML workforce identity provider" />
        </Section>
        <ErrorAlert error={list.error} />
        <ResourceTable resourceName="workforce pools" items={list.data || []} rowKey={(p) => p.name} loading={list.loading} onRetry={list.reload}
          empty="No workforce pools yet."
          columns={[
            { id: "name", header: "Pool", cell: (p) => p.displayName || p.name.split("/").pop() },
            { id: "id", header: "Pool ID", cell: (p) => p.name.split("/").pop() },
            { id: "state", header: "State", cell: (p) => p.state },
            { id: "actions", header: "", cell: (p) => <Button size="small" color="error" onClick={() => setDel(p)}>Delete</Button> },
          ]} />
      </CapabilityContainer>
      {open && <CreatePoolDialog onClose={() => setOpen(false)} onCreated={() => { notify.success("Created workforce pool"); list.reload(); }} />}
      <DeleteDialog open={!!del} onClose={() => setDel(null)} title={`Delete pool ${del?.name.split("/").pop()}?`} actionLabel="Delete"
        onConfirm={async () => { await api.deleteWorkforcePool(del.name); notify.success("Deleted workforce pool"); list.reload(); }} />
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
      <DialogTitle>Create a workforce pool</DialogTitle>
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
          try { await api.createWorkforcePool(id, displayName || id); onCreated(); onClose(); }
          catch (e) { setError(e); } finally { setBusy(false); }
        }}>{busy ? "Creating…" : "Create pool"}</Button>
      </DialogActions>
    </Dialog>
  );
}
