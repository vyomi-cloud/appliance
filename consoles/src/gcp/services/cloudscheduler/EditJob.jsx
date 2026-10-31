/* Edit job — a flat form (the native console's edit page has no step numbers), reusing
 * the same field groups as the create wizard and saving with a full-replace PATCH. */
import { useState } from "react";
import { Box, Button, CircularProgress, Divider, IconButton, Stack, Typography } from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, PageHeader, Section } from "../../kit/common.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import { hashHref } from "../../link.jsx";
import * as api from "./api.js";
import { jobBody, RetryFields, ScheduleFields, stateFromJob, targetError, TargetFields } from "./JobFormFields.jsx";

export default function EditJob({ params }) {
  const { region, name } = params;
  const job = useAsync(() => api.getJob(region, name), [region, name]);
  if (job.loading) return <Box sx={{ textAlign: "center", py: 8 }}><CircularProgress /></Box>;
  if (job.error) return <ErrorAlert error={job.error} title="Failed to load job" />;
  return <Form job={job.data} />;
}

function Form({ job }) {
  const notify = useNotify();
  const [s, set] = useState(() => stateFromJob(job));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const detailHref = hashHref("cloudscheduler", "jobs", s.region, s.name);
  const tErr = targetError(s);

  const submit = async (ev) => {
    ev.preventDefault();
    if (!s.schedule.trim() || tErr) return;
    setBusy(true); setError(null);
    try {
      await api.patchJob(s.region, s.name, jobBody(s), api.FULL_UPDATE_MASK);
      notify.success(`Saved job "${s.name}"`);
      location.hash = detailHref.slice(1);
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Box component="form" onSubmit={submit} noValidate sx={{ maxWidth: 880 }}>
      <PageHeader title="Edit job" back={<IconButton aria-label="Back" href={detailHref}><ArrowBackIcon /></IconButton>} />
      <ErrorAlert error={error} title="Failed to save job" />

      <Section title="Define the schedule">
        <Stack spacing={2.5}><ScheduleFields s={s} set={set} editing /></Stack>
      </Section>
      <Box sx={{ py: 1.5 }}><Divider /></Box>

      <Section title={<Stack direction="row" spacing={1} alignItems="center" component="span"><span>Configure the execution</span><CapabilityBadge id="gcp.cloudscheduler.jobs.targets" /></Stack>}>
        <Stack spacing={2.5}><TargetFields s={s} set={set} /></Stack>
      </Section>
      <Box sx={{ py: 1.5 }}><Divider /></Box>

      <Section title="Retry config">
        <Stack spacing={2.5}><RetryFields s={s} set={set} /></Stack>
      </Section>

      <Stack direction="row" spacing={1} sx={{ pt: 3 }}>
        <Button type="submit" variant="contained" disabled={busy || !s.schedule.trim() || !!tErr}>{busy ? "Saving…" : "Save"}</Button>
        <Button href={detailHref}>Cancel</Button>
      </Stack>
      {!s.schedule.trim() && <Typography variant="caption" color="error">A schedule is required.</Typography>}
    </Box>
  );
}
