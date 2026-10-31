/* Replicas — read replicas are real Cloud SQL instances (instances.insert with
 * masterInstanceName, core/gcp_cloudsql_core.py), listed from the same instances
 * collection filtered to this instance's master. The primary's databases/users mirror to
 * every replica synchronously on write, so lag is always "0s" (see
 * core/capabilities/gcp/sql.json: gcp.sql.replicas). */
import { useState } from "react";
import { Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, Stack, TextField, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { Link } from "../../link.jsx";
import * as api from "./api.js";
import InstanceNav, { instanceHref } from "./InstanceNav.jsx";

export default function Replicas({ params }) {
  const name = params.name;
  const notify = useNotify();
  const [create, setCreate] = useState(false);
  const { data = [], loading, error, reload } = useAsync(() => api.listReplicas(name), [name]);

  return (
    <>
      <InstanceNav name={name} active="replicas" />
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1.5 }}>
        <Typography variant="h2" component="h2" sx={{ flex: 1, fontSize: 20 }}>Replicas</Typography>
        <Button startIcon={<AddIcon />} onClick={() => setCreate(true)}>Create read replica</Button>
      </Stack>
      <CapabilityContainer id="gcp.sql.replicas" title="Read replicas">
        <ResourceTable
          resourceName="replicas"
          items={data}
          rowKey={(i) => i.name}
          loading={loading}
          error={error}
          onRetry={reload}
          filterPlaceholder="Filter replicas"
          columns={[
            { id: "name", header: "Instance ID", sortField: "name", cell: (i) => <Link href={instanceHref(i.name)}>{i.name}</Link> },
            { id: "type", header: "Type", cell: () => "Read replica" },
            { id: "region", header: "Region", sortField: "region", cell: (i) => i.region },
            { id: "lag", header: "Replication lag", cell: () => "0s" },
            { id: "status", header: "Status", cell: (i) => api.stateLabel(i.state) },
          ]}
          empty={<Typography variant="body2" color="text.secondary">This instance has no read replicas.</Typography>}
        />
      </CapabilityContainer>
      <CreateReplicaDialog open={create} master={name} onClose={() => setCreate(false)}
        onCreated={() => { setCreate(false); reload(); }} notify={notify} />
    </>
  );
}

function CreateReplicaDialog({ open, master, onClose, onCreated, notify }) {
  const [id, setId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await api.createReplica(master, id);
      notify.success(`Creating read replica "${id}"`);
      setId("");
      onCreated();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} maxWidth="xs" fullWidth aria-labelledby="crr-title">
      <DialogTitle id="crr-title">Create read replica</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField autoFocus fullWidth required label="Replica instance ID" value={id}
            onChange={(e) => setId(e.target.value.trim())} inputProps={{ "aria-label": "Replica instance ID" }} />
          {error && <Alert severity="error">{error.message}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" onClick={submit} disabled={busy || !id}>{busy ? "Creating…" : "Create"}</Button>
      </DialogActions>
    </Dialog>
  );
}
