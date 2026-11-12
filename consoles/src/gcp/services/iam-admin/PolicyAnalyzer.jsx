/* Policy Analyzer — "who has this role" query over the project's stored IAM policy
 * (native :getIamPolicy). Vyomi does not run full Cloud Asset Inventory analysis. */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogContent, DialogTitle, Stack, TextField, Typography } from "@mui/material";
import { ErrorAlert, NotSimulated, PageHeader, Section } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function PolicyAnalyzer() {
  const [customOpen, setCustomOpen] = useState(false);
  const [queryOpen, setQueryOpen] = useState(false);
  const [result, setResult] = useState(null);

  return (
    <>
      <PageHeader title="Policy Analyzer" />
      <Section title="Analyze policies" actions={
        <Stack direction="row" spacing={1}>
          <Button onClick={() => setCustomOpen(true)}>Create custom query</Button>
          <Button variant="contained" onClick={() => setQueryOpen(true)}>Create query</Button>
        </Stack>}>
        {result && (
          <Stack spacing={1} sx={{ mt: 1 }}>
            <Typography variant="body2" sx={{ fontWeight: 500 }}>Principals with {api.roleTitle(result.role)} on this project:</Typography>
            {result.members.length
              ? result.members.map((m) => <Typography key={m} variant="body2">{m}</Typography>)
              : <Typography variant="body2" color="text.secondary">No principal has this role directly on the project.</Typography>}
          </Stack>
        )}
      </Section>
      <Section title="Analyze organization policies">
        <Typography variant="body2" color="text.secondary">Requires an organization; Vyomi's GCP lens is project-scoped.</Typography>
      </Section>
      {customOpen && (
        <Dialog open onClose={() => setCustomOpen(false)} maxWidth="sm" fullWidth>
          <DialogTitle>Create custom query</DialogTitle>
          <DialogContent><NotSimulated feature="Custom Cloud Asset Inventory queries (full query language)" compact /></DialogContent>
          <DialogActions sx={{ px: 3, pb: 2 }}><Button onClick={() => setCustomOpen(false)}>Close</Button></DialogActions>
        </Dialog>
      )}
      {queryOpen && <QueryDialog onClose={() => setQueryOpen(false)} onResult={(r) => { setResult(r); setQueryOpen(false); }} />}
    </>
  );
}

function QueryDialog({ onClose, onResult }) {
  const [role, setRole] = useState("roles/viewer");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Create query — who has a role</DialogTitle>
      <DialogContent>
        <ErrorAlert error={error} />
        <TextField fullWidth sx={{ mt: 1 }} label="Role" value={role} onChange={(e) => setRole(e.target.value.trim())} helperText="e.g. roles/viewer" />
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy || !role} onClick={async () => {
          setBusy(true); setError(null);
          try {
            const pol = await api.getIamPolicy();
            const members = (pol.bindings || []).filter((b) => b.role === role).flatMap((b) => b.members);
            onResult({ role, members });
          } catch (e) { setError(e); } finally { setBusy(false); }
        }}>{busy ? "Running…" : "Run query"}</Button>
      </DialogActions>
    </Dialog>
  );
}
