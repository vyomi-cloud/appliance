/* Create uptime check — the console's 4-step wizard over the real UptimeCheckConfigs API.
 * Every check target is modeled as a direct URL target (host + path); Vyomi never
 * dispatches the actual probe, so per-region pass/fail isn't simulated (see the Uptime
 * checks list and gcp.monitoring.uptime-checks.probing). */
import { useState } from "react";
import {
  Alert, Box, Button, Checkbox, FormControl, FormControlLabel, IconButton, InputLabel, ListItemText, MenuItem,
  Select, Step, StepLabel, Stepper, Stack, Switch, TextField, Typography,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, PageHeader, Section } from "../../kit/common.jsx";
import * as api from "./api.js";

const STEPS = ["Target", "Response Validation", "Alert & Notification", "Review"];
const FREQUENCIES = [["1 minute", "60s"], ["5 minutes", "300s"], ["10 minutes", "600s"], ["15 minutes", "900s"]];
const RESOURCE_TYPES = ["URL", "Kubernetes LB Service", "Instance", "App Engine", "Elastic Load Balancer"];

export default function CreateUptimeCheck() {
  const notify = useNotify();
  const { data: channels = [] } = useAsync(() => api.listChannels(), []);
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const [protocol, setProtocol] = useState("HTTP");
  const [resourceType, setResourceType] = useState("URL");
  const [hostname, setHostname] = useState("");
  const [path, setPath] = useState("/");
  const [frequency, setFrequency] = useState("1 minute");

  const [timeout_, setTimeout_] = useState(10);
  const [matchEnabled, setMatchEnabled] = useState(false);
  const [matchText, setMatchText] = useState("");

  const [createAlert, setCreateAlert] = useState(true);
  const [channelIds, setChannelIds] = useState([]);

  const [title, setTitle] = useState("");

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const body = {
        displayName: title,
        monitoredResource: { type: "uptime_url", labels: { host: hostname, project_id: "vyomi-project" } },
        period: FREQUENCIES.find(([l]) => l === frequency)[1],
        timeout: `${timeout_}s`,
        ...(protocol === "TCP" ? { tcpCheck: { port: 443 } } : { httpCheck: { path, port: protocol === "HTTPS" ? 443 : 80, useSsl: protocol === "HTTPS" } }),
        ...(matchEnabled && matchText ? { contentMatchers: [{ content: matchText, matcher: "CONTAINS_STRING" }] } : {}),
      };
      const check = await api.createUptimeCheck(body);
      if (createAlert) {
        const checkId = check.name.split("/").pop();
        await api.createPolicy({
          displayName: `${title} uptime failure`, combiner: "OR",
          conditions: [{ displayName: `${title} check failing`, conditionThreshold: {
            filter: `metric.type = "monitoring.googleapis.com/uptime_check/check_passed" AND resource.type = "uptime_url" AND metric.labels.check_id = "${checkId}"`,
            comparison: "COMPARISON_LT", thresholdValue: 1, duration: "60s",
          } }],
          notificationChannels: channelIds,
        });
      }
      notify.success(`Created uptime check "${title}"`);
      location.hash = "/monitoring/uptime";
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Box sx={{ maxWidth: 680 }}>
      <PageHeader title="Create uptime check" back={<IconButton aria-label="Back" href="#/monitoring/uptime"><ArrowBackIcon /></IconButton>} />
      <ErrorAlert error={error} title="Failed to create uptime check" />
      <Stepper activeStep={step} sx={{ mb: 3 }}>{STEPS.map((s) => <Step key={s}><StepLabel>{s}</StepLabel></Step>)}</Stepper>

      {step === 0 && (
        <Section title="Target">
          <Stack spacing={2} sx={{ maxWidth: 420 }}>
            <FormControl><InputLabel id="protocol-label">Protocol</InputLabel>
              <Select labelId="protocol-label" label="Protocol" value={protocol} onChange={(e) => setProtocol(e.target.value)}>
                {["HTTP", "HTTPS", "TCP"].map((p) => <MenuItem key={p} value={p}>{p}</MenuItem>)}
              </Select>
            </FormControl>
            <FormControl><InputLabel id="rtype-label">Resource type</InputLabel>
              <Select labelId="rtype-label" label="Resource type" value={resourceType} onChange={(e) => setResourceType(e.target.value)}>
                {RESOURCE_TYPES.map((r) => <MenuItem key={r} value={r}>{r}</MenuItem>)}
              </Select>
            </FormControl>
            {resourceType !== "URL" && <Alert severity="info">Vyomi models every uptime check as a direct URL target regardless of resource type — enter the address to check below.</Alert>}
            <TextField label="Hostname" required value={hostname} onChange={(e) => setHostname(e.target.value)} inputProps={{ "aria-label": "Hostname" }} />
            {protocol !== "TCP" && <TextField label="Path" value={path} onChange={(e) => setPath(e.target.value)} inputProps={{ "aria-label": "Path" }} />}
            <FormControl><InputLabel id="freq-label">Check frequency</InputLabel>
              <Select labelId="freq-label" label="Check frequency" value={frequency} onChange={(e) => setFrequency(e.target.value)}>
                {FREQUENCIES.map(([l]) => <MenuItem key={l} value={l}>{l}</MenuItem>)}
              </Select>
            </FormControl>
          </Stack>
        </Section>
      )}

      {step === 1 && (
        <Section title="Response Validation">
          <Stack spacing={2} sx={{ maxWidth: 420 }}>
            <TextField label="Response Timeout" type="number" value={timeout_} onChange={(e) => setTimeout_(Number(e.target.value))} inputProps={{ "aria-label": "Response Timeout" }} />
            <FormControlLabel control={<Switch checked={matchEnabled} onChange={(e) => setMatchEnabled(e.target.checked)} />} label="Content matching is enabled" />
            {matchEnabled && <TextField label="Response must contain" value={matchText} onChange={(e) => setMatchText(e.target.value)} />}
          </Stack>
        </Section>
      )}

      {step === 2 && (
        <Section title="Alert & Notification">
          <Stack spacing={2} sx={{ maxWidth: 420 }}>
            <FormControlLabel control={<Switch checked={createAlert} onChange={(e) => setCreateAlert(e.target.checked)} />} label="Create an alert" />
            {createAlert && (
              <FormControl><InputLabel id="uc-channels-label">Notification channels</InputLabel>
                <Select labelId="uc-channels-label" label="Notification channels" multiple value={channelIds} onChange={(e) => setChannelIds(e.target.value)}
                  renderValue={(v) => v.map((n) => api.channelLabel(channels.find((c) => c.name === n) || {})).join(", ")}>
                  {channels.map((c) => <MenuItem key={c.name} value={c.name}><Checkbox size="small" checked={channelIds.includes(c.name)} /><ListItemText primary={api.channelLabel(c)} /></MenuItem>)}
                </Select>
              </FormControl>
            )}
          </Stack>
        </Section>
      )}

      {step === 3 && (
        <Section title="Review">
          <Stack spacing={2} sx={{ maxWidth: 420 }}>
            <Typography variant="body2" color="text.secondary">{protocol} check of {hostname || "(no host)"}{protocol !== "TCP" ? path : ""}, every {frequency}.</Typography>
            <TextField label="Title" required value={title} onChange={(e) => setTitle(e.target.value)} inputProps={{ "aria-label": "Title" }} />
          </Stack>
        </Section>
      )}

      <Stack direction="row" spacing={1} sx={{ pt: 3 }}>
        {step > 0 && <Button onClick={() => setStep(step - 1)}>Back</Button>}
        {step < 3 ? <Button variant="contained" onClick={() => setStep(step + 1)}>Continue</Button>
          : <Button variant="contained" disabled={busy || !title.trim()} onClick={submit}>{busy ? "Creating…" : "Create"}</Button>}
        <Button href="#/monitoring/uptime">Cancel</Button>
      </Stack>
    </Box>
  );
}
