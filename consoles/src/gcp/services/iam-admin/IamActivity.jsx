/* IAM & Admin > Activity: Cloud Audit Logs entries for IAM admin, IAM Credentials (impersonation, keys) and STS exchanges, from GET /api/iam/gcp/events.
 * Material-native. Each row expands to the native LogEntry (protoPayload.methodName / authenticationInfo / status). */
import { Fragment, useState } from "react";
import { Alert, Box, Button, Chip, MenuItem, Stack, Table, TableBody, TableCell, TableHead, TableRow, TextField } from "@mui/material";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import { EVENT_COPY, OUTCOMES, OUTCOME_LABEL, eventTime } from "../../../common/iamEvents.js";
import { useIamEvents } from "../../../common/iamEventsHooks.js";
import { PageHeader, Section } from "../../kit/common.jsx";

const CLOUD = "gcp";
const COLOR = { success: "success", denied: "error", error: "error", would_deny: "warning" };

export default function IamActivity() {
  const copy = EVENT_COPY[CLOUD];
  const [draft, setDraft] = useState({ name: "", principal: "", resource: "", outcome: "all" });
  const [f, setF] = useState(draft);
  const [open, setOpen] = useState(null);
  const ev = useIamEvents(CLOUD, f);
  const rows = ev.data?.events || [];
  const apply = (n) => { setDraft(n); setF(n); };
  return (
    <>
      <PageHeader title="Activity" actions={<Stack direction="row" spacing={1}>
        <Button size="small" startIcon={<RefreshIcon />} onClick={ev.reload}>Refresh</Button>
        <Button size="small" href={ev.api.exportUrl(f, "csv")} target="_blank">Export CSV</Button>
        <Button size="small" href={ev.api.exportUrl(f, "json")} target="_blank">Export JSON</Button></Stack>} />
      <Section title="IAM audit log" description={copy.info}>
        <Stack direction="row" spacing={1.5} sx={{ mb: 2, flexWrap: "wrap" }} data-testid="iam-events-filters">
          <TextField size="small" label="Method" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} onKeyDown={(e) => e.key === "Enter" && setF(draft)} />
          <TextField size="small" label="Principal" value={draft.principal} onChange={(e) => setDraft({ ...draft, principal: e.target.value })} onKeyDown={(e) => e.key === "Enter" && setF(draft)} />
          <TextField size="small" label="Resource" value={draft.resource} onChange={(e) => setDraft({ ...draft, resource: e.target.value })} onKeyDown={(e) => e.key === "Enter" && setF(draft)} />
          <TextField size="small" select label="Outcome" value={draft.outcome} sx={{ minWidth: 150 }} onChange={(e) => apply({ ...draft, outcome: e.target.value })}>
            <MenuItem value="all">All outcomes</MenuItem>{OUTCOMES.map((o) => <MenuItem key={o} value={o}>{OUTCOME_LABEL[o]}</MenuItem>)}</TextField>
          <Button size="small" variant="outlined" onClick={() => setF(draft)}>Apply</Button>
        </Stack>
        {ev.error && <Alert severity="error">{ev.error.message}</Alert>}
        {ev.loading ? <Box>Loading events</Box> : !rows.length ? <Box color="text.secondary">No audit entries match. IAM admin calls, key creation, impersonation and STS exchanges appear here.</Box> :
          <Table size="small" data-testid="iam-events-table"><TableHead><TableRow>{["Time", "Method", "Principal", "Resource", "Outcome"].map((h) => <TableCell key={h}>{h}</TableCell>)}</TableRow></TableHead>
            <TableBody>{rows.map((r) => (
              <Fragment key={r.id}>
                <TableRow hover sx={{ cursor: "pointer" }} onClick={() => setOpen(open === r.id ? null : r.id)}>
                  <TableCell sx={{ whiteSpace: "nowrap" }}>{eventTime(r)}</TableCell><TableCell>{r.native?.protoPayload?.methodName || r.name}</TableCell>
                  <TableCell>{r.principal || "-"}</TableCell><TableCell sx={{ wordBreak: "break-all" }}>{r.resource || "-"}</TableCell>
                  <TableCell><Chip size="small" color={COLOR[r.outcome] || "default"} label={r.errorCode || OUTCOME_LABEL[r.outcome] || r.outcome} /></TableCell></TableRow>
                {open === r.id && <TableRow><TableCell colSpan={5}><pre style={{ margin: 0, fontSize: 12, overflow: "auto" }}>{JSON.stringify(r.native || r, null, 2)}</pre></TableCell></TableRow>}
              </Fragment>))}</TableBody></Table>}
        {ev.data?.truncated && <Alert severity="info" sx={{ mt: 1 }}>Showing the most recent {rows.length} matching entries. Narrow the filters or export for the full set.</Alert>}
      </Section>
    </>
  );
}
