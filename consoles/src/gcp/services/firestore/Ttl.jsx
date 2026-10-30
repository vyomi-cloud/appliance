/* Time-to-live (TTL) policies — real per-field config round-trip; Vyomi never runs the
 * background sweep that actually deletes expired documents (see the capability badge). */
import { useState } from "react";
import { Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, Stack, TextField, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { PageHeader } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

export default function Ttl({ params }) {
  const db = params.name;
  const notify = useNotify();
  const { data = [], loading, error, reload } = useAsync(() => api.listTtlPolicies(db), [db]);
  const [open, setOpen] = useState(false);

  return (
    <>
      <PageHeader title="Time-to-live (TTL)" actions={<Button startIcon={<AddIcon />} onClick={() => setOpen(true)}>Create policy</Button>} />
      <CapabilityContainer id="gcp.firestore.ttl" title="TTL policies">
        <ResourceTable
          resourceName="TTL policies"
          items={data}
          rowKey={(f) => f.name}
          loading={loading}
          error={error}
          onRetry={reload}
          filterPlaceholder="Filter policies"
          columns={[
            { id: "group", header: "Collection group", cell: (f) => api.ttlGroupOf(f) },
            { id: "field", header: "Timestamp field", cell: (f) => api.ttlFieldOf(f) },
            { id: "status", header: "Status", cell: (f) => <Chip size="small" color={f.ttlConfig?.state === "ACTIVE" ? "success" : "default"} label={f.ttlConfig?.state || "—"} /> },
            { id: "actions", header: "Actions", cell: (f) => (
              <Button size="small" startIcon={<DeleteIcon />} onClick={async () => {
                await api.setFieldTtl(db, api.ttlGroupOf(f), api.ttlFieldOf(f), false);
                notify.success("Removed TTL policy");
                reload();
              }}>Remove</Button>
            ) },
          ]}
          empty={<Typography variant="body2" color="text.secondary">No TTL policies yet.</Typography>}
        />
      </CapabilityContainer>
      <CreatePolicyDialog open={open} onClose={() => setOpen(false)} onSave={async (group, field) => {
        await api.setFieldTtl(db, group, field, true);
        notify.success(`Created TTL policy on "${field}"`);
        reload();
      }} />
    </>
  );
}

function CreatePolicyDialog({ open, onClose, onSave }) {
  const [group, setGroup] = useState("");
  const [field, setField] = useState("");
  const [busy, setBusy] = useState(false);
  const go = async () => { setBusy(true); try { await onSave(group, field); onClose(); setGroup(""); setField(""); } finally { setBusy(false); } };
  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} maxWidth="xs" fullWidth aria-labelledby="ttl-title">
      <DialogTitle id="ttl-title">Create a TTL policy</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField label="Collection group" autoFocus value={group} onChange={(e) => setGroup(e.target.value.trim())} inputProps={{ "aria-label": "Collection group" }} />
          <TextField label="Timestamp field" value={field} onChange={(e) => setField(e.target.value.trim())} helperText="Must be a timestamp-typed field" inputProps={{ "aria-label": "Timestamp field" }} />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy || !group.trim() || !field.trim()} onClick={go}>{busy ? "Creating…" : "Create"}</Button>
      </DialogActions>
    </Dialog>
  );
}
