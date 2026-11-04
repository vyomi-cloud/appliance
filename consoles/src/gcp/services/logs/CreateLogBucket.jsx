/* Create log bucket — one real buckets.create call (Logging Config API v2). */
import { useState } from "react";
import { Box, Button, Checkbox, Divider, FormControl, FormControlLabel, IconButton, InputLabel, MenuItem, Select, Stack, TextField, Typography } from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, PageHeader } from "../../kit/common.jsx";
import { hashHref } from "../../link.jsx";
import * as api from "./api.js";

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

export default function CreateLogBucket() {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [touched, setTouched] = useState(false);
  const [description, setDescription] = useState("");
  const [analytics, setAnalytics] = useState(false);
  const [region, setRegion] = useState(api.REGIONS[0][0]);
  const [retention, setRetention] = useState(30);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const nameErr = touched ? api.validBucketId(name) : null;

  const submit = async (ev) => {
    ev.preventDefault();
    setTouched(true);
    if (api.validBucketId(name)) return;
    setBusy(true); setError(null);
    try {
      await api.createBucket(name, { description, analyticsEnabled: analytics, retentionDays: Number(retention) || 30 }, region);
      notify.success(`Created log bucket "${name}"`);
      location.hash = hashHref("logs", "storage", "bucket", name).slice(1) + `?loc=${region}`;
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Box component="form" onSubmit={submit} noValidate sx={{ maxWidth: 760 }}>
      <PageHeader title="Create log bucket" back={<IconButton aria-label="Back" href="#/logs/storage"><ArrowBackIcon /></IconButton>} />
      <ErrorAlert error={error} title="Failed to create log bucket" />

      <Step n={1} title="Bucket details">
        <TextField label="Name" required value={name} onChange={(e) => setName(e.target.value.trim())} onBlur={() => setTouched(true)}
          error={!!nameErr} helperText={nameErr || "Ex. 'example' or 'example_bucket-1'"} inputProps={{ "aria-label": "Name" }} sx={{ maxWidth: 420 }} />
        <TextField label="Description" value={description} onChange={(e) => setDescription(e.target.value)} inputProps={{ "aria-label": "Description" }} sx={{ maxWidth: 560 }} />
        <FormControlLabel control={<Checkbox size="small" checked={analytics} onChange={(e) => setAnalytics(e.target.checked)} />} label="Upgrade to use Observability Analytics" />
        <FormControl sx={{ maxWidth: 420 }}>
          <InputLabel id="region-l">Region</InputLabel>
          <Select labelId="region-l" label="Region" required value={region} onChange={(e) => setRegion(e.target.value)} inputProps={{ "aria-label": "Region" }}>
            {api.REGIONS.map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
          </Select>
          <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5 }}>Log bucket regions can't be changed later.</Typography>
        </FormControl>
      </Step>
      <Divider />

      <Step n={2} title="Set the retention period">
        <TextField label="Retention period" type="number" value={retention} onChange={(e) => setRetention(e.target.value)} helperText="days" inputProps={{ "aria-label": "Retention period" }} sx={{ maxWidth: 240 }} />
      </Step>
      <Divider />

      <Stack direction="row" spacing={1} sx={{ pt: 3 }}>
        <Button type="submit" variant="contained" disabled={busy}>{busy ? "Creating…" : "Create bucket"}</Button>
        <Button href="#/logs/storage">Cancel</Button>
      </Stack>
    </Box>
  );
}
