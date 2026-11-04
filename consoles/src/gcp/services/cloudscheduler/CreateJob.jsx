/* Create a job — the console's 3-step wizard. Every setting goes into ONE native
 * jobs.create body; Workflows via HTTP (not a Vyomi product) is a declared gap, not a
 * silent no-op — see JobFormFields.targetError. */
import { useState } from "react";
import { Box, Button, Divider, IconButton, Stack, Typography } from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, PageHeader, Section } from "../../kit/common.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import { hashHref } from "../../link.jsx";
import * as api from "./api.js";
import { initialState, jobBody, RetryFields, ScheduleFields, targetError, TargetFields } from "./JobFormFields.jsx";

function Step({ n, title, children }) {
  return (
    <Box component="section" aria-label={title} sx={{ display: "grid", gridTemplateColumns: "32px 1fr", columnGap: 2, py: 2.5 }}>
      <Box sx={{ width: 28, height: 28, borderRadius: "50%", bgcolor: "primary.main", color: "primary.contrastText", display: "grid", placeItems: "center", fontSize: 13, fontWeight: 500 }}>{n}</Box>
      <Box sx={{ minWidth: 0 }}>
        <Typography variant="h3" component="h2" sx={{ mb: 2, lineHeight: "28px" }}>{title}</Typography>
        <Stack spacing={2.5}>{children}</Stack>
      </Box>
    </Box>
  );
}

export default function CreateJob() {
  const notify = useNotify();
  const [s, set] = useState(initialState());
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const nameErr = touched && !api.validJobId(s.name) ? "Job ID may contain only letters, numbers, hyphens and underscores." : null;
  const scheduleErr = touched && !s.schedule.trim() ? "A schedule is required." : null;
  const tErr = targetError(s);

  const submit = async (ev) => {
    ev.preventDefault();
    setTouched(true);
    if (nameErr || !api.validJobId(s.name) || !s.schedule.trim() || tErr) return;
    setBusy(true); setError(null);
    try {
      await api.createJob(s.region, { name: api.jobName(s.region, s.name), ...jobBody(s) });
      notify.success(`Created job "${s.name}"`);
      location.hash = hashHref("cloudscheduler", "jobs", s.region, s.name).slice(1);
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Box component="form" onSubmit={submit} noValidate sx={{ maxWidth: 880 }}>
      <PageHeader title="Create a job" back={<IconButton aria-label="Back" href="#/cloudscheduler"><ArrowBackIcon /></IconButton>} />
      <ErrorAlert error={error} title="Failed to create job" />

      <Step n={1} title="Define the schedule">
        <ScheduleFields s={s} set={set} />
        {(nameErr || scheduleErr) && <Typography variant="body2" color="error">{nameErr || scheduleErr}</Typography>}
      </Step>
      <Divider />

      <Step n={2} title={<Stack direction="row" spacing={1} alignItems="center" component="span"><span>Configure the execution</span><CapabilityBadge id="gcp.cloudscheduler.jobs.targets" /></Stack>}>
        <TargetFields s={s} set={set} />
      </Step>
      <Divider />

      <Step n={3} title="Configure optional settings">
        <Section title="Retry config">
          <Stack spacing={2.5}>
            <RetryFields s={s} set={set} />
          </Stack>
        </Section>
      </Step>
      <Divider />

      <Stack direction="row" spacing={1} sx={{ pt: 3 }}>
        <Button type="submit" variant="contained" disabled={busy || !!tErr}>{busy ? "Creating…" : "Create"}</Button>
        <Button href="#/cloudscheduler">Cancel</Button>
      </Stack>
    </Box>
  );
}
