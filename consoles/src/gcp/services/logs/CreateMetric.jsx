/* Create log-based metric — one real logMetrics.create call; "Preview logs" runs the
 * filter against real stored entries right in the form, like the console's preview pane. */
import { useState } from "react";
import { Alert, Box, Button, FormControlLabel, IconButton, MenuItem, Radio, RadioGroup, Select, Stack, TextField, Typography } from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, PageHeader, Section } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function CreateMetric() {
  const notify = useNotify();
  const [kind, setKind] = useState("Counter");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [units, setUnits] = useState("1");
  const [scope, setScope] = useState("project");
  const [filter, setFilter] = useState("");
  const [labels, setLabels] = useState([]);
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const previewLogs = async () => {
    const entries = await api.listEntries({ pageSize: 1000 });
    setPreview(entries.filter((en) => api.matchesQuery(en, filter)).slice(0, 10));
  };

  const submit = async (ev) => {
    ev.preventDefault();
    if (!name.trim() || !filter.trim()) return;
    setBusy(true); setError(null);
    try {
      await api.createMetric({
        name: name.trim(), description, filter: filter.trim(),
        labelExtractors: Object.fromEntries(labels.filter((l) => l.key).map((l) => [l.key, l.value])),
        metricDescriptor: { metricKind: kind === "Counter" ? "DELTA" : "DISTRIBUTION", valueType: kind === "Counter" ? "INT64" : "DISTRIBUTION", unit: units || "1" },
      });
      notify.success(`Created metric "${name}"`);
      location.hash = "#/logs/metrics";
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Box component="form" onSubmit={submit} noValidate sx={{ maxWidth: 760 }}>
      <PageHeader title="Create log-based metric" back={<IconButton aria-label="Back" href="#/logs/metrics"><ArrowBackIcon /></IconButton>} />
      <ErrorAlert error={error} title="Failed to create metric" />
      <Stack spacing={2.5}>
        <Section title="Metric Type">
          <RadioGroup value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Metric Type">
            <FormControlLabel value="Counter" control={<Radio size="small" />} label={<><b>Counter</b> — counts the number of matching log entries</>} />
            <FormControlLabel value="Distribution" control={<Radio size="small" />} label={<><b>Distribution</b> — tracks the statistical distribution of a numeric value extracted from matching entries</>} />
          </RadioGroup>
        </Section>
        <Section title="Details">
          <Stack spacing={2}>
            <TextField label="Log-based metric name" required value={name} onChange={(e) => setName(e.target.value.trim())} inputProps={{ "aria-label": "Log-based metric name" }} />
            <TextField label="Description" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Enter a description for this metric (optional)" inputProps={{ "aria-label": "Description" }} />
            <TextField label="Units" value={units} onChange={(e) => setUnits(e.target.value)} sx={{ maxWidth: 240 }} inputProps={{ "aria-label": "Units" }} />
          </Stack>
        </Section>
        <Section title="Filter selection">
          <Stack spacing={2}>
            <Select value={scope} onChange={(e) => setScope(e.target.value)} sx={{ maxWidth: 320 }} inputProps={{ "aria-label": "Select project or log bucket" }}>
              <MenuItem value="project">Project logs</MenuItem>
            </Select>
            <TextField label="Build filter" required multiline minRows={3} value={filter} onChange={(e) => setFilter(e.target.value)} inputProps={{ "aria-label": "Build filter" }} />
            <Box><Button onClick={previewLogs} disabled={!filter.trim()}>Preview logs</Button></Box>
            {preview && (preview.length
              ? <Stack spacing={0.5}>{preview.map((en) => <Typography key={en.insertId} variant="caption" sx={{ fontFamily: "monospace" }}>{en.severity} — {api.summary(en)}</Typography>)}</Stack>
              : <Alert severity="info">No log entries match this filter.</Alert>)}
          </Stack>
        </Section>
        <Section title="Labels">
          <Stack spacing={1}>
            {labels.map((l, i) => (
              <Stack key={i} direction="row" spacing={1} alignItems="center">
                <TextField label={`Key ${i + 1}`} value={l.key} onChange={(e) => setLabels(labels.map((x, j) => j === i ? { ...x, key: e.target.value } : x))} />
                <TextField label={`Value ${i + 1}`} value={l.value} onChange={(e) => setLabels(labels.map((x, j) => j === i ? { ...x, value: e.target.value } : x))} />
                <IconButton aria-label={`Delete label ${i + 1}`} onClick={() => setLabels(labels.filter((_, j) => j !== i))}><DeleteIcon fontSize="small" /></IconButton>
              </Stack>
            ))}
            <Box><Button startIcon={<AddIcon />} onClick={() => setLabels([...labels, { key: "", value: "" }])}>Add label</Button></Box>
          </Stack>
        </Section>
        <Stack direction="row" spacing={1}>
          <Button type="submit" variant="contained" disabled={busy || !name.trim() || !filter.trim()}>{busy ? "Creating…" : "Create metric"}</Button>
          <Button href="#/logs/metrics">Cancel</Button>
        </Stack>
      </Stack>
    </Box>
  );
}
