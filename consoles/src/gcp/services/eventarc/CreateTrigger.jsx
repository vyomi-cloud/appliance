/* Create trigger: name + region, event provider/type (from the native providers catalogue), the filters that event type requires,
 * and a Cloud Run destination. Everything goes into ONE native triggers.create body. */
import { useEffect, useState } from "react";
import { Box, Button, FormControl, IconButton, InputLabel, MenuItem, Select, Stack, TextField, Typography } from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, PageHeader } from "../../kit/common.jsx";
import { hashHref } from "../../link.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

const ID = /^[a-z]([a-z0-9-]{0,61}[a-z0-9])?$/;
const lastSeg = (n) => String(n || "").split("/").pop();

export default function CreateTrigger() {
  const notify = useNotify();
  const project = useProject();
  const [name, setName] = useState("");
  const [region, setRegion] = useState(api.DEFAULT_REGION);
  const [provider, setProvider] = useState("storage.googleapis.com");
  const [etype, setEtype] = useState("");
  const [filters, setFilters] = useState({});
  const [destKind, setDestKind] = useState("cloudRun");
  const [dest, setDest] = useState("");
  const [sa, setSa] = useState("");
  const [topic, setTopic] = useState("");
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const providers = useAsync(() => api.listProviders(region), [region, project]);
  const prov = useAsync(() => api.getProvider(region, provider), [region, provider, project]);
  const targets = useAsync(() => (destKind === "cloudRun" ? api.listRunServices(region) : api.listRunJobs(region)).catch(() => []), [region, destKind, project]);
  const buckets = useAsync(() => api.listBuckets().catch(() => []), [project]);

  const types = prov.data?.eventTypes || [];
  useEffect(() => { if (types.length && !types.some((t) => t.type === etype)) { setEtype(types[0].type); setFilters({}); } }, [types]);
  const required = (types.find((t) => t.type === etype)?.filteringAttributes || []).filter((a) => a.required).map((a) => a.attribute);
  const targetNames = (targets.data || []).map((x) => lastSeg(x.name));
  useEffect(() => { setDest(targetNames[0] || ""); }, [destKind, region, targets.data]);

  const nameErr = touched && !ID.test(name) ? "1-63 characters: lowercase letters, numbers and hyphens, starting with a letter." : null;
  const missing = required.filter((a) => !String(filters[a] || "").trim());

  const submit = async (ev) => {
    ev.preventDefault();
    setTouched(true);
    if (!ID.test(name) || missing.length || !dest) return;
    setBusy(true); setError(null);
    try {
      const body = {
        eventFilters: [{ attribute: "type", value: etype }, ...required.map((a) => ({ attribute: a, value: String(filters[a]).trim() }))],
        destination: destKind === "cloudRun" ? { cloudRun: { service: dest, region } } : { cloudRunJob: { job: dest, region } },
        ...(sa.trim() ? { serviceAccount: sa.trim() } : {}),
        ...(topic.trim() ? { transport: { pubsub: { topic: topic.trim() } } } : {}),
      };
      await api.createTrigger(region, name, body);
      notify.success(`Created trigger "${name}"`);
      location.hash = hashHref("eventarc", "triggers", region, name).slice(1);
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Box component="form" onSubmit={submit} noValidate sx={{ maxWidth: 760 }}>
      <PageHeader title="Create trigger" back={<IconButton aria-label="Back" href="#/eventarc"><ArrowBackIcon /></IconButton>} />
      <ErrorAlert error={error} title="Failed to create trigger" />
      <Stack spacing={2.5} sx={{ py: 2 }}>
        <TextField required label="Trigger name" value={name} onChange={(e) => setName(e.target.value.trim())} error={!!nameErr} helperText={nameErr || "Lowercase letters, numbers and hyphens"} />
        <FormControl><InputLabel id="ea-region-l">Region</InputLabel>
          <Select labelId="ea-region-l" label="Region" value={region} onChange={(e) => setRegion(e.target.value)}>{api.LOCATIONS.map((r) => <MenuItem key={r} value={r}>{r}</MenuItem>)}</Select></FormControl>
        <Typography variant="h3" component="h2">Event provider</Typography>
        <FormControl><InputLabel id="ea-prov-l">Event provider</InputLabel>
          <Select labelId="ea-prov-l" label="Event provider" value={provider} onChange={(e) => { setProvider(e.target.value); setFilters({}); }}>
            {(providers.data || []).map((p) => <MenuItem key={lastSeg(p.name)} value={lastSeg(p.name)}>{p.displayName}</MenuItem>)}</Select></FormControl>
        <FormControl><InputLabel id="ea-type-l">Event</InputLabel>
          <Select labelId="ea-type-l" label="Event" value={types.some((t) => t.type === etype) ? etype : ""} onChange={(e) => { setEtype(e.target.value); setFilters({}); }}>
            {types.map((t) => <MenuItem key={t.type} value={t.type}>{t.type}</MenuItem>)}</Select></FormControl>
        {required.map((a) => a === "bucket"
          ? <FormControl key={a}><InputLabel id="ea-bucket-l">Bucket</InputLabel>
              <Select labelId="ea-bucket-l" label="Bucket" value={filters.bucket || ""} onChange={(e) => setFilters({ ...filters, bucket: e.target.value })}>
                {(buckets.data || []).map((b) => <MenuItem key={b.name} value={b.name}>{b.name}</MenuItem>)}</Select></FormControl>
          : <TextField key={a} required label={a} value={filters[a] || ""} onChange={(e) => setFilters({ ...filters, [a]: e.target.value })} helperText={`Required for ${etype}`} />)}
        {etype.endsWith("messagePublished") && <TextField label="Pub/Sub topic (optional)" value={topic} onChange={(e) => setTopic(e.target.value)} helperText="Leave empty to have Eventarc create a topic" />}
        <Typography variant="h3" component="h2">Event destination</Typography>
        <FormControl><InputLabel id="ea-dk-l">Destination type</InputLabel>
          <Select labelId="ea-dk-l" label="Destination type" value={destKind} onChange={(e) => setDestKind(e.target.value)}>
            <MenuItem value="cloudRun">Cloud Run service</MenuItem><MenuItem value="cloudRunJob">Cloud Run job</MenuItem></Select></FormControl>
        <FormControl error={touched && !dest}><InputLabel id="ea-dest-l">{destKind === "cloudRun" ? "Service" : "Job"}</InputLabel>
          <Select labelId="ea-dest-l" label={destKind === "cloudRun" ? "Service" : "Job"} value={dest} onChange={(e) => setDest(e.target.value)}>
            {targetNames.map((n) => <MenuItem key={n} value={n}>{n}</MenuItem>)}</Select>
          {!targetNames.length && <Typography variant="caption" color="text.secondary">No Cloud Run {destKind === "cloudRun" ? "services" : "jobs"} in {region} — create one first.</Typography>}</FormControl>
        <TextField label="Service account (optional)" value={sa} onChange={(e) => setSa(e.target.value.trim())} helperText="Defaults to the Compute Engine default service account" />
        {touched && missing.length > 0 && <Typography variant="body2" color="error">Fill in: {missing.join(", ")}</Typography>}
      </Stack>
      <Stack direction="row" spacing={1}><Button type="submit" variant="contained" disabled={busy}>{busy ? "Creating…" : "Create"}</Button><Button href="#/eventarc">Cancel</Button></Stack>
    </Box>
  );
}
