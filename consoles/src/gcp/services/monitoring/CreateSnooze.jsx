/* Create snooze — real create against the Snoozes API (v1). */
import { useState } from "react";
import {
  Box, Button, Checkbox, FormControl, FormControlLabel, FormHelperText, IconButton, InputLabel, ListItemText,
  MenuItem, Radio, RadioGroup, Select, Stack, TextField,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, PageHeader, Section } from "../../kit/common.jsx";
import * as api from "./api.js";

const DURATIONS = [["1 hr", 3600000], ["2 hrs", 7200000], ["4 hrs", 14400000], ["8 hrs", 28800000], ["1 day", 86400000], ["1 week", 604800000]];

export default function CreateSnooze() {
  const notify = useNotify();
  const { data: policies = [] } = useAsync(() => api.listPolicies(), []);
  const [name, setName] = useState("");
  const [startMode, setStartMode] = useState("now");
  const [startAt, setStartAt] = useState("");
  const [duration, setDuration] = useState("1 hr");
  const [selected, setSelected] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async (ev) => {
    ev.preventDefault();
    if (!name.trim() || !selected.length) return;
    setBusy(true); setError(null);
    try {
      const start = startMode === "now" ? new Date() : new Date(startAt);
      const ms = DURATIONS.find(([l]) => l === duration)[1];
      await api.createSnooze({
        displayName: name,
        criteria: { policies: selected },
        interval: { startTime: start.toISOString(), endTime: new Date(start.getTime() + ms).toISOString() },
      });
      notify.success(`Created snooze "${name}"`);
      location.hash = "/monitoring/alerting";
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Box component="form" onSubmit={submit} noValidate sx={{ maxWidth: 640 }}>
      <PageHeader title="Create snooze" back={<IconButton aria-label="Back" href="#/monitoring/alerting"><ArrowBackIcon /></IconButton>} />
      <ErrorAlert error={error} title="Failed to create snooze" />
      <Stack spacing={2.5}>
        <Section title="Snooze name">
          <TextField label="Snooze name" required fullWidth value={name} onChange={(e) => setName(e.target.value)} inputProps={{ "aria-label": "Snooze name" }} />
        </Section>
        <Section title="Snooze duration">
          <Stack spacing={2}>
            <RadioGroup value={startMode} onChange={(e) => setStartMode(e.target.value)} aria-label="Start time">
              <FormControlLabel value="now" control={<Radio size="small" />} label="Start snooze now" />
              <FormControlLabel value="scheduled" control={<Radio size="small" />} label="Start snooze at defined time" />
            </RadioGroup>
            {startMode === "scheduled" && <TextField type="datetime-local" value={startAt} onChange={(e) => setStartAt(e.target.value)} sx={{ maxWidth: 280 }} />}
            <FormControl sx={{ maxWidth: 220 }}>
              <InputLabel id="duration-label">Duration</InputLabel>
              <Select labelId="duration-label" label="Duration" value={duration} onChange={(e) => setDuration(e.target.value)}>
                {DURATIONS.map(([l]) => <MenuItem key={l} value={l}>{l}</MenuItem>)}
              </Select>
            </FormControl>
          </Stack>
        </Section>
        <Section title="Snooze criteria">
          <FormControl fullWidth>
            <InputLabel id="policies-label">Alert policies</InputLabel>
            <Select labelId="policies-label" label="Alert policies" multiple value={selected}
              onChange={(e) => setSelected(e.target.value.slice(0, 16))}
              renderValue={(v) => v.map((n) => policies.find((p) => p.name === n)?.displayName || n).join(", ")}>
              {policies.map((p) => (
                <MenuItem key={p.name} value={p.name}>
                  <Checkbox size="small" checked={selected.includes(p.name)} />
                  <ListItemText primary={p.displayName} />
                </MenuItem>
              ))}
            </Select>
            <FormHelperText>Select up to 16 alert policies</FormHelperText>
          </FormControl>
        </Section>
      </Stack>
      <Stack direction="row" spacing={1} sx={{ pt: 3 }}>
        <Button type="submit" variant="contained" disabled={busy || !name.trim() || !selected.length}>{busy ? "Creating…" : "Create"}</Button>
        <Button href="#/monitoring/alerting">Cancel</Button>
      </Stack>
    </Box>
  );
}
