/* Create alerting policy — the console's 4-step wizard, wired to the real AlertPolicy
 * resource (conditions, aggregations, notification channels, user labels, severity,
 * documentation, alertStrategy). PromQL query mode and Application labels (which need the
 * separate, unmodeled Application Monitoring resources) are declared gaps. */
import { useState } from "react";
import {
  Alert, Box, Button, Checkbox, Collapse, FormControl, FormControlLabel, IconButton, InputLabel,
  ListItemText, MenuItem, Radio, RadioGroup, Select, Step, StepLabel, Stepper, Switch, Table, TableBody, TableCell,
  TableHead, TableRow, TextField, Stack, Typography,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, PageHeader, Section } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

const STEPS = ["New condition", "Configure trigger", "Notifications and name", "Review alert"];
const AUTOCLOSE = [["30 minutes", 1800], ["1 hour", 3600], ["1 day", 86400], ["1 week", 604800]];

export default function CreateAlertPolicy() {
  const notify = useNotify();
  const { data: channels = [] } = useAsync(() => api.listChannels(), []);
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  // step 1
  const [mode, setMode] = useState("Builder");
  const [metricType, setMetricType] = useState("");
  // step 2
  const [conditionType, setConditionType] = useState("Threshold");
  const [trigger, setTrigger] = useState("Any time series violates");
  const [position, setPosition] = useState("Above threshold");
  const [threshold, setThreshold] = useState("");
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [triggerCount, setTriggerCount] = useState("1");
  const [conditionName, setConditionName] = useState("");
  // step 3
  const [useChannel, setUseChannel] = useState(true);
  const [channelIds, setChannelIds] = useState([]);
  const [subject, setSubject] = useState("");
  const [notifyClosure, setNotifyClosure] = useState(false);
  const [autoClose, setAutoClose] = useState("1 day");
  const [labels, setLabels] = useState([]);
  const [severity, setSeverity] = useState("No severity");
  const [documentation, setDocumentation] = useState("");
  const [policyName, setPolicyName] = useState("");

  const builtin = api.BUILTIN_METRICS.find(([t]) => t === metricType);
  const resourceType = builtin?.[3] || "global";

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const filter = `metric.type = "${metricType}" AND resource.type = "${resourceType}"`;
      const body = {
        displayName: policyName,
        combiner: "OR",
        conditions: [{
          displayName: conditionName || `${policyName} [${metricType.split("/").pop()}]`,
          ...(conditionType === "Metric absence"
            ? { conditionAbsent: { filter, duration: "300s" } }
            : { conditionThreshold: {
                filter, comparison: position === "Above threshold" ? "COMPARISON_GT" : "COMPARISON_LT",
                thresholdValue: Number(threshold), duration: "300s",
                trigger: trigger === "Any time series violates" ? { count: Number(triggerCount) || 1 } : { percent: 100 },
              } }),
        }],
        notificationChannels: useChannel ? channelIds : [],
        userLabels: Object.fromEntries(labels.filter((l) => l.key).map((l) => [l.key, l.value])),
        alertStrategy: { autoClose: `${AUTOCLOSE.find(([l]) => l === autoClose)[1]}s`, notifyOnClosure: notifyClosure },
      };
      if (severity !== "No severity") body.severity = severity.toUpperCase();
      if (documentation || subject) body.documentation = { content: documentation, mimeType: "text/markdown", subject };
      await api.createPolicy(body);
      notify.success(`Created alerting policy "${policyName}"`);
      location.hash = "/monitoring/alerting";
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Box sx={{ maxWidth: 760 }}>
      <PageHeader title="Create alerting policy" back={<IconButton aria-label="Back" href="#/monitoring/alerting"><ArrowBackIcon /></IconButton>}
        actions={<><Button size="small" startIcon={<AddIcon />} disabled>Add alert condition</Button><Button size="small" startIcon={<DeleteIcon />} disabled>Delete alert condition</Button><Button size="small" disabled>View Code</Button></>} />
      <ErrorAlert error={error} title="Failed to create policy" />
      <Stepper activeStep={step} sx={{ mb: 3 }}>{STEPS.map((s) => <Step key={s}><StepLabel>{s}</StepLabel></Step>)}</Stepper>

      {step === 0 && (
        <Stack spacing={2.5}>
          <Section title="Policy configuration mode">
            <Stack spacing={2}>
              <RadioGroup row value={mode} onChange={(e) => setMode(e.target.value)} aria-label="Policy configuration mode">
                <FormControlLabel value="Builder" control={<Radio size="small" />} label="Builder" />
                <FormControlLabel value="PromQL" control={<Radio size="small" />} label="PromQL" />
              </RadioGroup>
              {mode === "PromQL" ? <CapabilityContainer id="gcp.monitoring.metrics-explorer" title="PromQL condition" /> : (
                <FormControl sx={{ maxWidth: 420 }} required>
                  <InputLabel id="metric-label">Select a metric</InputLabel>
                  <Select labelId="metric-label" label="Select a metric" value={metricType} onChange={(e) => setMetricType(e.target.value)} inputProps={{ "aria-label": "Select a metric" }}>
                    {api.BUILTIN_METRICS.map(([t, , name]) => <MenuItem key={t} value={t}>{name} ({t})</MenuItem>)}
                  </Select>
                </FormControl>
              )}
            </Stack>
          </Section>
          <Section title="Looking to alert on other types of data?">
            <Stack direction="row" spacing={1}><Button size="small" disabled>Create log-based alert</Button><Button size="small" disabled>Create SQL alert</Button></Stack>
          </Section>
        </Stack>
      )}

      {step === 1 && (
        <Section title="Configure alert trigger">
          <Stack spacing={2} sx={{ maxWidth: 420 }}>
            <RadioGroup value={conditionType} onChange={(e) => setConditionType(e.target.value)} aria-label="Condition Types">
              <FormControlLabel value="Threshold" control={<Radio size="small" />} label="Threshold" />
              <FormControlLabel value="Metric absence" control={<Radio size="small" />} label="Metric absence" />
              <FormControlLabel value="Forecast" control={<Radio size="small" />} label="Forecast" />
            </RadioGroup>
            {conditionType === "Forecast" && <Alert severity="info">Vyomi evaluates a forecast condition the same way as Threshold (metric value vs. threshold) — it does not model trend extrapolation.</Alert>}
            <FormControl>
              <InputLabel id="trigger-label">Alert trigger</InputLabel>
              <Select labelId="trigger-label" label="Alert trigger" value={trigger} onChange={(e) => setTrigger(e.target.value)} inputProps={{ "aria-label": "Alert trigger" }}>
                <MenuItem value="Any time series violates">Any time series violates</MenuItem>
                <MenuItem value="All time series violate">All time series violate</MenuItem>
              </Select>
            </FormControl>
            {conditionType !== "Metric absence" && (
              <>
                <FormControl>
                  <InputLabel id="position-label">Threshold position</InputLabel>
                  <Select labelId="position-label" label="Threshold position" value={position} onChange={(e) => setPosition(e.target.value)} inputProps={{ "aria-label": "Threshold position" }}>
                    <MenuItem value="Above threshold">Above threshold</MenuItem>
                    <MenuItem value="Below threshold">Below threshold</MenuItem>
                  </Select>
                </FormControl>
                <TextField label="Threshold value" type="number" required value={threshold} onChange={(e) => setThreshold(e.target.value)} inputProps={{ "aria-label": "Threshold value" }} />
              </>
            )}
            <Box>
              <Button size="small" onClick={() => setAdvancedOpen((v) => !v)}>Advanced Options</Button>
              <Collapse in={advancedOpen}><TextField label="Trigger count" type="number" size="small" value={triggerCount} onChange={(e) => setTriggerCount(e.target.value)} sx={{ mt: 1 }} /></Collapse>
            </Box>
            <TextField label="Condition name" value={conditionName} onChange={(e) => setConditionName(e.target.value)} inputProps={{ "aria-label": "Condition name" }} />
          </Stack>
        </Section>
      )}

      {step === 2 && (
        <Section title="Configure notifications and finalize alert">
          <Stack spacing={2} sx={{ maxWidth: 480 }}>
            <FormControlLabel control={<Switch checked={useChannel} onChange={(e) => setUseChannel(e.target.checked)} />} label="Use notification channel" />
            {useChannel && (
              <FormControl>
                <InputLabel id="channels-label">Notification Channels</InputLabel>
                <Select labelId="channels-label" label="Notification Channels" multiple value={channelIds} onChange={(e) => setChannelIds(e.target.value)}
                  renderValue={(v) => v.map((n) => api.channelLabel(channels.find((c) => c.name === n) || {})).join(", ")}>
                  {channels.map((c) => (
                    <MenuItem key={c.name} value={c.name}><Checkbox size="small" checked={channelIds.includes(c.name)} /><ListItemText primary={api.channelLabel(c)} secondary={c.type} /></MenuItem>
                  ))}
                </Select>
              </FormControl>
            )}
            <TextField label="Notification subject line" value={subject} onChange={(e) => setSubject(e.target.value)} />
            <FormControlLabel control={<Checkbox checked={notifyClosure} onChange={(e) => setNotifyClosure(e.target.checked)} />} label="Notify on alert closure" />
            <FormControl sx={{ maxWidth: 220 }}>
              <InputLabel id="autoclose-label">Alert autoclose duration</InputLabel>
              <Select labelId="autoclose-label" label="Alert autoclose duration" value={autoClose} onChange={(e) => setAutoClose(e.target.value)}>
                {AUTOCLOSE.map(([l]) => <MenuItem key={l} value={l}>{l}</MenuItem>)}
              </Select>
            </FormControl>
            <CapabilityContainer id="gcp.monitoring.application-monitoring" title="Application labels" />
            <Box>
              <Typography variant="body2" sx={{ fontWeight: 500, mb: 1 }}>Policy user labels</Typography>
              <Stack spacing={1}>
                {labels.map((l, i) => (
                  <Stack key={i} direction="row" spacing={1}>
                    <TextField size="small" label={`Key ${i + 1}`} value={l.key} onChange={(e) => setLabels(labels.map((x, j) => j === i ? { ...x, key: e.target.value } : x))} />
                    <TextField size="small" label={`Value ${i + 1}`} value={l.value} onChange={(e) => setLabels(labels.map((x, j) => j === i ? { ...x, value: e.target.value } : x))} />
                    <IconButton size="small" aria-label={`Remove label ${i + 1}`} onClick={() => setLabels(labels.filter((_, j) => j !== i))}><DeleteIcon fontSize="small" /></IconButton>
                  </Stack>
                ))}
                <Box><Button size="small" startIcon={<AddIcon />} onClick={() => setLabels([...labels, { key: "", value: "" }])}>Add Label</Button></Box>
              </Stack>
            </Box>
            <FormControl sx={{ maxWidth: 220 }}>
              <InputLabel id="severity-label">Severity</InputLabel>
              <Select labelId="severity-label" label="Severity" value={severity} onChange={(e) => setSeverity(e.target.value)}>
                {["No severity", "Critical", "Error", "Warning"].map((s) => <MenuItem key={s} value={s}>{s}</MenuItem>)}
              </Select>
            </FormControl>
            <TextField label="Documentation" multiline minRows={3} value={documentation} onChange={(e) => setDocumentation(e.target.value)} />
            <TextField label="Alert policy name" required value={policyName} onChange={(e) => setPolicyName(e.target.value)} inputProps={{ "aria-label": "Alert policy name" }} />
          </Stack>
        </Section>
      )}

      {step === 3 && (
        <Section title="Policy Details">
          <Stack spacing={1.5}>
            <Box><Typography variant="body2" color="text.secondary">Alert Policy Name</Typography><Typography>{policyName || "—"}</Typography></Box>
            <Box><Typography variant="body2" color="text.secondary">Severity</Typography><Typography>{severity}</Typography></Box>
            <Box>
              <Typography variant="body2" sx={{ mb: 0.5 }}>Notification channels</Typography>
              <Table size="small">
                <TableHead><TableRow><TableCell>Display name</TableCell><TableCell>Type</TableCell></TableRow></TableHead>
                <TableBody>
                  {useChannel && channelIds.length ? channelIds.map((id) => { const c = channels.find((x) => x.name === id); return <TableRow key={id}><TableCell>{api.channelLabel(c || {})}</TableCell><TableCell>{c?.type}</TableCell></TableRow>; })
                    : <TableRow><TableCell colSpan={2}><Typography variant="body2" color="text.secondary">No notification channels</Typography></TableCell></TableRow>}
                </TableBody>
              </Table>
            </Box>
            <Box><Typography variant="body2" color="text.secondary">Documentation</Typography><Typography>{documentation || "No documentation"}</Typography></Box>
          </Stack>
        </Section>
      )}

      <Stack direction="row" spacing={1} sx={{ pt: 3 }}>
        {step > 0 && <Button onClick={() => setStep(step - 1)}>Back</Button>}
        {step < 3 ? <Button variant="contained" onClick={() => setStep(step + 1)}>Continue</Button>
          : <Button variant="contained" disabled={busy || !policyName.trim()} onClick={submit}>{busy ? "Creating…" : "Create Policy"}</Button>}
        <Button href="#/monitoring/alerting">Cancel</Button>
      </Stack>
    </Box>
  );
}
