/* Create (or edit) a Log Router sink — one long form with numbered steps, mirroring the
 * GCP storage pilot's CreateBucket. Every writable field maps straight onto LogSink. */
import { useEffect, useState } from "react";
import { Box, Button, Divider, FormControl, IconButton, InputLabel, MenuItem, Select, Stack, TextField, Typography } from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { ErrorAlert, NotSimulated, PageHeader } from "../../kit/common.jsx";
import * as api from "./api.js";

function Step({ n, title, children }) {
  return (
    <Box component="section" sx={{ display: "grid", gridTemplateColumns: "32px 1fr", columnGap: 2, py: 2.5 }}>
      <Box sx={{ width: 28, height: 28, borderRadius: "50%", bgcolor: "primary.main", color: "primary.contrastText", display: "grid", placeItems: "center", fontSize: 13, fontWeight: 500 }}>{n}</Box>
      <Box sx={{ minWidth: 0 }}>
        <Typography variant="h3" component="h2" sx={{ mb: 2, lineHeight: "28px" }}>{title}</Typography>
        <Stack spacing={2.5}>{children}</Stack>
      </Box>
    </Box>
  );
}

export default function CreateSink({ query }) {
  const notify = useNotify();
  const editing = query.edit || "";
  const existing = useAsync(() => (editing ? api.getSink(editing) : Promise.resolve(null)), [editing]);
  const [name, setName] = useState(editing);
  const [description, setDescription] = useState("");
  const [service, setService] = useState("bucket");
  const [dest, setDest] = useState("");
  const [inclusion, setInclusion] = useState("");
  const [exName, setExName] = useState("");
  const [exFilter, setExFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!existing.data) return;
    setDescription(existing.data.description || "");
    setInclusion(existing.data.filter || "");
    const ex = existing.data.exclusions?.[0];
    if (ex) { setExName(ex.name); setExFilter(ex.filter || ""); }
  }, [existing.data]);

  const svc = api.SINK_SERVICES.find(([id]) => id === service);
  const supported = !!svc[3];

  const submit = async (ev) => {
    ev.preventDefault();
    if (!name.trim() || !supported || !dest.trim()) return;
    setBusy(true); setError(null);
    try {
      const body = {
        name: name.trim(), description, filter: inclusion.trim(), destination: svc[2](dest.trim()),
        exclusions: exName.trim() ? [{ name: exName.trim(), filter: exFilter.trim() }] : [],
      };
      if (editing) await api.patchSink(editing, body);
      else await api.createSink(body);
      notify.success(`${editing ? "Updated" : "Created"} sink "${name}"`);
      location.hash = "#/logs/router";
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Box component="form" onSubmit={submit} noValidate sx={{ maxWidth: 820 }}>
      <PageHeader title={editing ? "Edit logs routing sink" : "Create logs routing sink"} back={<IconButton aria-label="Back" href="#/logs/router"><ArrowBackIcon /></IconButton>} />
      <ErrorAlert error={error} title="Failed to save sink" />

      <Step n={1} title="Sink details">
        <TextField label="Sink name" required value={name} disabled={!!editing} onChange={(e) => setName(e.target.value.trim())} inputProps={{ "aria-label": "Sink name" }} sx={{ maxWidth: 420 }} />
        <TextField label="Sink description" value={description} onChange={(e) => setDescription(e.target.value)} inputProps={{ "aria-label": "Sink description" }} sx={{ maxWidth: 560 }} />
      </Step>
      <Divider />

      <Step n={2} title="Sink destination">
        <FormControl sx={{ maxWidth: 320 }}>
          <InputLabel id="svc-l">Select sink service</InputLabel>
          <Select labelId="svc-l" label="Select sink service" value={service} onChange={(e) => setService(e.target.value)} inputProps={{ "aria-label": "Select sink service" }}>
            {api.SINK_SERVICES.map(([id, label]) => <MenuItem key={id} value={id}>{label}</MenuItem>)}
          </Select>
        </FormControl>
        {supported
          ? <TextField label="Sink destination" required value={dest} onChange={(e) => setDest(e.target.value)} inputProps={{ "aria-label": "Sink destination" }} sx={{ maxWidth: 420 }}
              helperText={service === "bucket" ? "An existing log bucket ID" : service === "bigquery" ? "A BigQuery dataset ID" : service === "storage" ? "A Cloud Storage bucket name" : "A Pub/Sub topic ID"} />
          : <NotSimulated compact feature={svc[1]} note="This destination type isn't backed by a real integration yet — pick Cloud Logging bucket, BigQuery dataset, Cloud Storage bucket or Pub/Sub topic." />}
      </Step>
      <Divider />

      <Step n={3} title="Choose logs to include in sink">
        <TextField label="Build inclusion filter" multiline minRows={3} value={inclusion} onChange={(e) => setInclusion(e.target.value)} inputProps={{ "aria-label": "Build inclusion filter" }} />
      </Step>
      <Divider />

      <Step n={4} title="Choose logs to filter out of sink (optional)">
        <Typography variant="body2" sx={{ fontWeight: 500 }}>Exclusion filters</Typography>
        <TextField label="Exclusion filter name" value={exName} onChange={(e) => setExName(e.target.value)} inputProps={{ "aria-label": "Exclusion filter name" }} sx={{ maxWidth: 420 }} />
        <TextField label="Build an exclusion filter" multiline minRows={2} value={exFilter} onChange={(e) => setExFilter(e.target.value)} inputProps={{ "aria-label": "Build an exclusion filter" }} />
      </Step>
      <Divider />

      <Stack direction="row" spacing={1} sx={{ pt: 3 }}>
        <Button type="submit" variant="contained" disabled={busy || !name.trim() || !supported || !dest.trim()}>{busy ? "Saving…" : "Create sink"}</Button>
        <Button href="#/logs/router">Cancel</Button>
      </Stack>
    </Box>
  );
}
