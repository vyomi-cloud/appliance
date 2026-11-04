/* Managed Workload Identities — real, stateful managed identities nested under a
 * workload identity pool, each with a certificate lifecycle (issue on create, rotate
 * on demand). Certificate material is synthetic, not issued by a real CA. Shows
 * identities across every pool by default, with a pool filter. */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem, Stack, TextField, Typography } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, PageHeader, fmtDate } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

export default function ManagedWorkloadIdentities() {
  const notify = useNotify();
  const pools = useAsync(() => api.listWorkloadIdentityPools(), []);
  const [filterPool, setFilterPool] = useState("");
  const [createPool, setCreatePool] = useState("");
  const list = useAsync(async () => {
    const names = (pools.data || []).map((p) => p.name);
    const lists = await Promise.all(names.map((n) => api.listManagedIdentities(n)));
    return lists.flat();
  }, [pools.data]);
  const shown = filterPool ? (list.data || []).filter((mi) => mi.name.startsWith(filterPool + "/")) : (list.data || []);
  const [create, setCreate] = useState(false);
  const [del, setDel] = useState(null);

  return (
    <>
      <PageHeader title="Managed Workload Identities" />
      <CapabilityContainer id="gcp.iam-admin.managed-workload-identities" title="Managed Workload Identities" actions={
        <Button variant="contained" disabled={!pools.data?.length} onClick={() => { setCreatePool(filterPool || pools.data?.[0]?.name || ""); setCreate(true); }}>
          Create managed identity
        </Button>}>
        {!pools.loading && !pools.data?.length ? (
          <Typography variant="body2" color="text.secondary">
            Managed identities live inside a workload identity pool (trust domain). Create one on the{" "}
            <a href="#/iam-admin/workload-identity-pools">Workload Identity Federation</a> page first.
          </Typography>
        ) : (
          <>
            <TextField select label="Pool (trust domain)" value={filterPool} onChange={(e) => setFilterPool(e.target.value)}
              sx={{ mb: 2, minWidth: 320 }} size="small">
              <MenuItem value="">All pools</MenuItem>
              {(pools.data || []).map((p) => <MenuItem key={p.name} value={p.name}>{p.displayName || p.name.split("/").pop()}</MenuItem>)}
            </TextField>
            <ErrorAlert error={list.error} />
            <ResourceTable resourceName="managed identities" items={shown} rowKey={(mi) => mi.name} loading={list.loading} onRetry={list.reload}
              filterPlaceholder="Filter" empty="No managed identities yet."
              columns={[
                { id: "id", header: "Managed identity", cell: (mi) => mi.name.split("/").pop() },
                { id: "pool", header: "Pool", cell: (mi) => mi.name.split("/managedIdentities/")[0].split("/").pop() },
                { id: "spiffe", header: "SPIFFE ID", cell: (mi) => mi.spiffeId },
                { id: "certs", header: "Certificates", cell: (mi) => mi.certificates.length },
                { id: "latest", header: "Latest cert expires", cell: (mi) => fmtDate(mi.certificates[0]?.notAfter) },
                {
                  id: "actions", header: "", cell: (mi) => (
                    <Stack direction="row" spacing={1}>
                      <Button size="small" onClick={async () => { await api.rotateManagedIdentityCert(mi.name); notify.success("Rotated certificate"); list.reload(); }}>Rotate cert</Button>
                      <Button size="small" color="error" onClick={() => setDel(mi)}>Delete</Button>
                    </Stack>
                  ),
                },
              ]} />
          </>
        )}
      </CapabilityContainer>
      {create && <CreateIdentityDialog pools={pools.data || []} defaultPool={createPool} onClose={() => setCreate(false)} onCreated={() => { notify.success("Created managed identity"); list.reload(); }} />}
      <DeleteDialog open={!!del} onClose={() => setDel(null)} title={`Delete managed identity ${del?.name.split("/").pop()}?`} actionLabel="Delete"
        onConfirm={async () => { await api.deleteManagedIdentity(del.name); notify.success("Deleted managed identity"); list.reload(); }} />
    </>
  );
}

function CreateIdentityDialog({ pools, defaultPool, onClose, onCreated }) {
  const [pool, setPool] = useState(defaultPool || pools[0]?.name || "");
  const [id, setId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const ok = pool && /^[a-z][a-z0-9-]{1,62}$/.test(id);
  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Create managed identity</DialogTitle>
      <DialogContent>
        <ErrorAlert error={error} />
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField select label="Pool" value={pool} onChange={(e) => setPool(e.target.value)}>
            {pools.map((p) => <MenuItem key={p.name} value={p.name}>{p.displayName || p.name.split("/").pop()}</MenuItem>)}
          </TextField>
          <TextField label="Managed identity ID" value={id} onChange={(e) => setId(e.target.value.trim())}
            helperText="Lowercase letters, numbers, hyphens" />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={!ok || busy} onClick={async () => {
          setBusy(true); setError(null);
          try { await api.createManagedIdentity(pool, id); onCreated(); onClose(); }
          catch (e) { setError(e); } finally { setBusy(false); }
        }}>{busy ? "Creating…" : "Create"}</Button>
      </DialogActions>
    </Dialog>
  );
}
