/* Create a bucket — the console's single long form with numbered steps. Every real
 * setting goes into ONE native buckets.insert body; settings Vyomi doesn't model are
 * declared gaps, not controls. */
import { useState } from "react";
import {
  Alert, Box, Button, Checkbox, Divider, FormControl, FormControlLabel, FormHelperText, IconButton, InputLabel, MenuItem,
  Radio, RadioGroup, Select, Stack, TextField, Typography,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, NotSimulated, PageHeader } from "../../kit/common.jsx";
import { hashHref } from "../../link.jsx";
import * as api from "./api.js";
import { VyomiMark, vy } from "../../../common/VyomiMark.jsx";

const location_ = window.location;   // `location` is the bucket-location state below
const UNIT_SECS = { seconds: 1, days: 86400, months: 31 * 86400, years: Math.round(365.25 * 86400) };

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
const Sub = ({ title, children, help }) => (
  <Box>
    <Typography variant="body2" sx={{ fontWeight: 500, mb: help ? 0.25 : 1 }}>{title}</Typography>
    {help && <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>{help}</Typography>}
    {children}
  </Box>
);

export default function CreateBucket() {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [touched, setTouched] = useState(false);
  const [labels, setLabels] = useState([]);
  const [locType, setLocType] = useState("multi-region");
  const [location, setLocation] = useState("US");
  const [storageClass, setStorageClass] = useState("STANDARD");
  const [pap, setPap] = useState(true);
  const [access, setAccess] = useState("uniform");
  const [retention, setRetention] = useState(false);
  const [retN, setRetN] = useState("7");
  const [retUnit, setRetUnit] = useState("days");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const nameErr = touched ? api.validBucketName(name) : null;
  const labelErr = labels.some((l) => !/^[a-z][a-z0-9_-]{0,62}$/.test(l.key)) ? "Label keys must start with a lowercase letter and contain only lowercase letters, numbers, underscores and dashes." : null;
  const retErr = retention && !(Number(retN) > 0 && Number.isInteger(Number(retN))) ? "Enter a whole number greater than 0." : null;

  const submit = async (ev) => {
    ev.preventDefault();
    setTouched(true);
    if (api.validBucketName(name) || labelErr || retErr) return;
    setBusy(true); setError(null);
    const body = {
      name, location, storageClass,
      iamConfiguration: { uniformBucketLevelAccess: { enabled: access === "uniform" }, publicAccessPrevention: pap ? "enforced" : "inherited" },
      ...(labels.length ? { labels: Object.fromEntries(labels.map((l) => [l.key, l.value])) } : {}),
      ...(retention ? { retentionPolicy: { retentionPeriod: String(Number(retN) * UNIT_SECS[retUnit]) } } : {}),
    };
    try {
      await api.insertBucket(body);
      notify.success(`Created bucket "${name}"`);
      location_.hash = hashHref("storage", "browser", name).slice(1);
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Box component="form" onSubmit={submit} noValidate sx={{ maxWidth: 880 }}>
      <PageHeader title="Create a bucket" back={<IconButton aria-label="Back" href="#/storage/browser"><ArrowBackIcon /></IconButton>} />
      <ErrorAlert error={error} title="Failed to create bucket" />

      <Step n={1} title="Get started">
        <TextField label="Name your bucket" required value={name} onChange={(e) => setName(e.target.value.trim())} onBlur={() => setTouched(true)}
          error={!!nameErr} inputProps={{ "aria-label": "Bucket name" }} sx={{ maxWidth: 560 }}
          helperText={nameErr || "Pick a globally unique, permanent name. Use lowercase letters, numbers, hyphens, underscores and dots."} />
        <Sub title="Labels (optional)" help="Labels are key:value pairs that help you organize and filter your buckets.">
          <Stack spacing={1}>
            {labels.map((l, i) => (
              <Stack key={i} direction="row" spacing={1} alignItems="center">
                <TextField label={`Key ${i + 1}`} value={l.key} onChange={(e) => setLabels(labels.map((x, j) => j === i ? { ...x, key: e.target.value } : x))} />
                <TextField label={`Value ${i + 1}`} value={l.value} onChange={(e) => setLabels(labels.map((x, j) => j === i ? { ...x, value: e.target.value } : x))} />
                <IconButton aria-label={`Delete label ${i + 1}`} onClick={() => setLabels(labels.filter((_, j) => j !== i))}><DeleteIcon fontSize="small" /></IconButton>
              </Stack>
            ))}
            {labelErr && <FormHelperText error>{labelErr}</FormHelperText>}
            <Box><Button startIcon={<AddIcon />} onClick={() => setLabels([...labels, { key: "", value: "" }])}>Add label</Button></Box>
          </Stack>
        </Sub>
      </Step>
      <Divider />

      <Step n={2} title="Choose where to store your data">
        <Sub title="Location type">
          <RadioGroup value={locType} onChange={(e) => { setLocType(e.target.value); setLocation(api.LOCATIONS[e.target.value][0][0]); }} aria-label="Location type">
            <FormControlLabel value="multi-region" control={<Radio size="small" />} label={<><b>Multi-region</b> — Highest availability across largest area</>} />
            <FormControlLabel value="dual-region" control={<Radio size="small" />} label={<><b>Dual-region</b> — High availability and low latency across 2 regions</>} />
            <FormControlLabel value="region" control={<Radio size="small" />} label={<><b>Region</b> — Lowest latency within a single region</>} />
          </RadioGroup>
        </Sub>
        <FormControl sx={{ maxWidth: 420 }}>
          <InputLabel id="loc-label">Location</InputLabel>
          <Select labelId="loc-label" label="Location" value={location} onChange={(e) => setLocation(e.target.value)} inputProps={{ "aria-label": "Location" }}>
            {api.LOCATIONS[locType].map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
          </Select>
        </FormControl>
        {locType === "dual-region" && <NotSimulated compact feature="Turbo replication" note="Dual-region buckets use default replication (RPO DEFAULT)." />}
      </Step>
      <Divider />

      <Step n={3} title="Choose how to store your data">
        <Sub title="Set a default class" help="Applies to all objects in your bucket unless you manually modify the class per object.">
          <RadioGroup value={storageClass} onChange={(e) => setStorageClass(e.target.value)} aria-label="Default storage class">
            {api.STORAGE_CLASSES.map(([v, l, d]) => <FormControlLabel key={v} value={v} control={<Radio size="small" />} label={<><b>{l}</b> — {d}</>} />)}
          </RadioGroup>
        </Sub>
        <NotSimulated compact feature="Autoclass" note={vy("Vyomi keeps objects in the bucket's default class; storage classes don't change pricing or retrieval here.")} />
        <NotSimulated compact feature="Hierarchical namespace" />
      </Step>
      <Divider />

      <Step n={4} title="Choose how to control access to objects">
        <Sub title="Prevent public access" help="Restrict data from being publicly accessible via the internet.">
          <FormControlLabel control={<Checkbox size="small" checked={pap} onChange={(e) => setPap(e.target.checked)} />} label="Enforce public access prevention on this bucket" />
        </Sub>
        <Sub title="Access control">
          <RadioGroup value={access} onChange={(e) => setAccess(e.target.value)} aria-label="Access control">
            <FormControlLabel value="uniform" control={<Radio size="small" />} label={<><b>Uniform</b> — Ensure uniform access to all objects in the bucket by using only bucket-level permissions (IAM).</>} />
            <FormControlLabel value="fine" control={<Radio size="small" />} label={<><b>Fine-grained</b> — Specify access to individual objects by using object-level permissions (ACLs) in addition to bucket-level permissions (IAM).</>} />
          </RadioGroup>
        </Sub>
        <Alert severity="info" variant="outlined"><VyomiMark /> records these settings and reports them to SDKs; it does not enforce IAM or ACLs on data access.</Alert>
      </Step>
      <Divider />

      <Step n={5} title="Choose how to protect object data">
        <NotSimulated compact feature="Soft delete policy (for data recovery)" />
        <NotSimulated compact feature="Object versioning (for version control)" />
        <Sub title="Data retention" help="Prevent deletion or modification of the bucket's objects for a specified minimum duration of time after being uploaded.">
          <FormControlLabel control={<Checkbox size="small" checked={retention} onChange={(e) => setRetention(e.target.checked)} />} label="Set bucket retention policy" />
          {retention && (
            <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
              <TextField label="Retention period" type="number" value={retN} onChange={(e) => setRetN(e.target.value)} error={!!retErr} helperText={retErr || " "} sx={{ width: 180 }} />
              <FormControl sx={{ width: 160 }}>
                <InputLabel id="ret-unit">Unit</InputLabel>
                <Select labelId="ret-unit" label="Unit" value={retUnit} onChange={(e) => setRetUnit(e.target.value)}>
                  {Object.keys(UNIT_SECS).map((u) => <MenuItem key={u} value={u}>{u[0].toUpperCase() + u.slice(1)}</MenuItem>)}
                </Select>
              </FormControl>
            </Stack>
          )}
        </Sub>
        <NotSimulated compact feature="Object retention (per-object retention and holds)" />
        <NotSimulated compact feature="Data encryption with Cloud KMS keys (CMEK)" note={vy("Vyomi stores object data unencrypted in its local store.")} />
      </Step>
      <Divider />

      <Stack direction="row" spacing={1} sx={{ pt: 3 }}>
        <Button type="submit" variant="contained" disabled={busy}>{busy ? "Creating…" : "Create"}</Button>
        <Button href="#/storage/browser">Cancel</Button>
      </Stack>
    </Box>
  );
}

