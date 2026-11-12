/* Identity-Aware Proxy — per-resource toggle + roles/iap.httpsResourceAccessor IAM
 * policy are real and stateful; "Check access" calls the same Allow decision IAP's own
 * proxy would make. Vyomi does not run an actual HTTPS reverse proxy in front of a
 * real backend. */
import { useState } from "react";
import { Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, Stack, Switch, TextField } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, PageHeader } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

export default function IdentityAwareProxy() {
  const notify = useNotify();
  const list = useAsync(() => api.listIapResources(), []);
  const [create, setCreate] = useState(false);
  const [del, setDel] = useState(null);
  const [check, setCheck] = useState(null);

  return (
    <>
      <PageHeader title="Identity-Aware Proxy" />
      <CapabilityContainer id="gcp.iam-admin.identity-aware-proxy" title="HTTPS resources" actions={
        <Button variant="contained" onClick={() => setCreate(true)}>Add resource</Button>}>
        <ErrorAlert error={list.error} title="Failed to load IAP resources" />
        <ResourceTable resourceName="resources" items={list.data || []} rowKey={(r) => r.name} loading={list.loading} onRetry={list.reload}
          empty="No resources protected by IAP yet"
          columns={[
            { id: "name", header: "Resource", cell: (r) => r.displayName },
            { id: "id", header: "Resource ID", cell: (r) => r.name.split("/").pop() },
            {
              id: "iap", header: "IAP", cell: (r) => (
                <Switch checked={r.enabled} onChange={async (e) => { await api.setIapEnabled(r.name, e.target.checked); notify.success(e.target.checked ? "Turned IAP on" : "Turned IAP off"); list.reload(); }} />
              ),
            },
            {
              id: "actions", header: "", cell: (r) => (
                <Stack direction="row" spacing={1}>
                  <Button size="small" onClick={() => setCheck(r)}>Check access</Button>
                  <Button size="small" color="error" onClick={() => setDel(r)}>Delete</Button>
                </Stack>
              ),
            },
          ]} />
      </CapabilityContainer>
      {create && <CreateResourceDialog onClose={() => setCreate(false)} onCreated={() => { notify.success("Added resource"); list.reload(); }} />}
      <DeleteDialog open={!!del} onClose={() => setDel(null)} title={`Remove ${del?.displayName} from IAP?`} actionLabel="Remove"
        onConfirm={async () => { await api.deleteIapResource(del.name); notify.success("Removed resource"); list.reload(); }} />
      {check && <CheckAccessDialog resource={check} onClose={() => setCheck(null)} />}
    </>
  );
}

function CreateResourceDialog({ onClose, onCreated }) {
  const [id, setId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const ok = /^[a-z][a-z0-9-]{1,62}$/.test(id);
  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Add a resource to IAP</DialogTitle>
      <DialogContent>
        <ErrorAlert error={error} />
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField label="Resource ID" value={id} onChange={(e) => setId(e.target.value.trim())} helperText="Lowercase letters, numbers, hyphens" />
          <TextField label="Display name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={!ok || busy} onClick={async () => {
          setBusy(true); setError(null);
          try { await api.createIapResource(id, displayName || id); onCreated(); onClose(); }
          catch (e) { setError(e); } finally { setBusy(false); }
        }}>{busy ? "Adding…" : "Add"}</Button>
      </DialogActions>
    </Dialog>
  );
}

function CheckAccessDialog({ resource, onClose }) {
  const [member, setMember] = useState("user:");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Check access to {resource.displayName}</DialogTitle>
      <DialogContent>
        <Stack direction="row" spacing={1} sx={{ mb: 2 }}>
          <TextField fullWidth size="small" label="Member" value={member} onChange={(e) => setMember(e.target.value.trim())} />
          <Button disabled={busy} onClick={async () => { setBusy(true); try { setResult(await api.checkIapAccess(resource.name, member)); } finally { setBusy(false); } }}>Check</Button>
        </Stack>
        {result && <Alert severity={result.allowed ? "success" : "warning"}>{result.allowed ? "Allowed" : "Denied"} — {result.reason}</Alert>}
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}
