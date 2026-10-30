/* Create a key — key ring context, name, protection level, key material, purpose/algorithm,
 * rotation and labels, as in the console's single long form. Vyomi backs symmetric,
 * software-protected, generated keys for real; the other options are declared gaps. */
import { useState } from "react";
import {
  Box, Button, Divider, FormControl, FormControlLabel, FormHelperText, IconButton, InputLabel, MenuItem,
  Radio, RadioGroup, Select, Stack, TextField, Typography,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useNotify } from "../../../../common/notify.jsx";
import { useAsync } from "../../../../common/useAsync.js";
import { ErrorAlert, NotSimulated, PageHeader } from "../../../kit/common.jsx";
import * as api from "./api.js";

function Step({ title, children }) {
  return (
    <Box component="section" sx={{ py: 2.5 }}>
      <Typography variant="h3" component="h2" sx={{ mb: 2 }}>{title}</Typography>
      <Stack spacing={2}>{children}</Stack>
    </Box>
  );
}

export default function CreateKey({ query }) {
  const notify = useNotify();
  const rings = useAsync(() => api.listKeyRings(), []);
  const ringOptions = (rings.data || []).map((r) => api.parseRingName(r.name));

  const [name, setName] = useState("");
  const [touched, setTouched] = useState(false);
  const [sel, setSel] = useState(query.keyring && query.location ? `${query.location}/${query.keyring}` : "");
  const [protection, setProtection] = useState("SOFTWARE");
  const [material, setMaterial] = useState("GENERATED");
  const [purpose, setPurpose] = useState("ENCRYPT_DECRYPT");
  const [rotationPeriod, setRotationPeriod] = useState("2592000s");
  const [startDate, setStartDate] = useState("");
  const [destroyDays, setDestroyDays] = useState("30");
  const [labels, setLabels] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const ring = sel ? { location: sel.split("/")[0], keyRing: sel.split("/")[1] } : ringOptions[0];
  const nameErr = touched && !/^[a-zA-Z0-9_-]{1,63}$/.test(name) ? "Use letters, numbers, underscores and hyphens (max 63 characters)." : null;

  const submit = async (ev) => {
    ev.preventDefault();
    setTouched(true);
    if (!/^[a-zA-Z0-9_-]{1,63}$/.test(name) || !ring) return;
    setBusy(true); setError(null);
    try {
      await api.createKey(ring.location, ring.keyRing, name, {
        purpose,
        versionTemplate: { algorithm: "GOOGLE_SYMMETRIC_ENCRYPTION" },
        ...(rotationPeriod ? { rotationPeriod, nextRotationTime: new Date((startDate ? new Date(startDate).getTime() : Date.now()) + Number(rotationPeriod.replace("s", "")) * 1000).toISOString() } : {}),
        destroyScheduledDuration: `${Math.max(1, Number(destroyDays) || 30) * 86400}s`,
        ...(labels.length ? { labels: Object.fromEntries(labels.map((l) => [l.key, l.value])) } : {}),
      });
      notify.success(`Created key "${name}"`);
      location.hash = `/security/kms/key/manage/${ring.location}/${ring.keyRing}/${name}`;
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Box component="form" onSubmit={submit} noValidate sx={{ maxWidth: 760 }}>
      <PageHeader title="Create key" back={<IconButton aria-label="Back" href="#/security/kms/keyrings"><ArrowBackIcon /></IconButton>} />
      <ErrorAlert error={error} title="Failed to create key" />

      <Step title="Key name">
        {!query.keyring && (
          <FormControl sx={{ maxWidth: 420 }}>
            <InputLabel id="kr-l">Key ring</InputLabel>
            <Select labelId="kr-l" label="Key ring" value={sel || (ringOptions[0] ? `${ringOptions[0].location}/${ringOptions[0].keyRing}` : "")}
              onChange={(e) => setSel(e.target.value)} inputProps={{ "aria-label": "Key ring" }}>
              {ringOptions.map((r) => <MenuItem key={`${r.location}/${r.keyRing}`} value={`${r.location}/${r.keyRing}`}>{r.keyRing} ({r.location})</MenuItem>)}
            </Select>
          </FormControl>
        )}
        <TextField label="Key name" required value={name} onChange={(e) => setName(e.target.value.trim())} onBlur={() => setTouched(true)}
          error={!!nameErr} helperText={nameErr || " "} sx={{ maxWidth: 420 }} />
      </Step>
      <Divider />

      <Step title="Protection level">
        <RadioGroup value={protection} onChange={(e) => setProtection(e.target.value)} aria-label="Protection level">
          <FormControlLabel value="SOFTWARE" control={<Radio size="small" />} label="Software" />
          <FormControlLabel value="HSM" disabled control={<Radio size="small" />} label="HSM" />
          <FormControlLabel value="EXTERNAL" disabled control={<Radio size="small" />} label="External" />
          <FormControlLabel value="EXTERNAL_VPC" disabled control={<Radio size="small" />} label="External via VPC" />
        </RadioGroup>
        <NotSimulated compact feature="HSM, External and External via VPC protection levels" note="Vyomi's key material always lives in its own software store; every key it creates is Software-protected." />
      </Step>
      <Divider />

      <Step title="Key material">
        <RadioGroup value={material} onChange={(e) => setMaterial(e.target.value)} aria-label="Key material">
          <FormControlLabel value="GENERATED" control={<Radio size="small" />} label="Generated key" />
          <FormControlLabel value="IMPORTED" disabled control={<Radio size="small" />} label="Imported key" />
        </RadioGroup>
        <NotSimulated compact feature="Imported key material" note="Vyomi always generates its own key material." />
      </Step>
      <Divider />

      <Step title="Purpose and algorithm">
        <FormControl sx={{ maxWidth: 420 }}>
          <InputLabel id="purpose-l">Purpose</InputLabel>
          <Select labelId="purpose-l" label="Purpose" value={purpose} onChange={(e) => setPurpose(e.target.value)} inputProps={{ "aria-label": "Purpose" }}>
            {api.PURPOSES.map(([v, l]) => <MenuItem key={v} value={v} disabled={v !== "ENCRYPT_DECRYPT"}>{l}</MenuItem>)}
          </Select>
        </FormControl>
        <FormControl sx={{ maxWidth: 420 }} disabled>
          <InputLabel id="algo-l">Algorithm</InputLabel>
          <Select labelId="algo-l" label="Algorithm" value="GOOGLE_SYMMETRIC_ENCRYPTION" inputProps={{ "aria-label": "Algorithm" }}>
            <MenuItem value="GOOGLE_SYMMETRIC_ENCRYPTION">Google symmetric key</MenuItem>
          </Select>
        </FormControl>
        {purpose !== "ENCRYPT_DECRYPT" && <NotSimulated compact feature="Asymmetric sign, asymmetric decrypt, MAC signing and raw encrypt/decrypt purposes" />}
      </Step>
      <Divider />

      <Step title="Versions">
        <FormControl sx={{ maxWidth: 420 }}>
          <InputLabel id="rot-l">Key rotation period</InputLabel>
          <Select labelId="rot-l" label="Key rotation period" value={rotationPeriod} onChange={(e) => setRotationPeriod(e.target.value)} inputProps={{ "aria-label": "Key rotation period" }}>
            {api.ROTATION_PERIODS.map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
          </Select>
        </FormControl>
        <TextField label="Starting on" type="date" disabled={!rotationPeriod} value={startDate} onChange={(e) => setStartDate(e.target.value)}
          InputLabelProps={{ shrink: true }} helperText="Defaults to today if left blank." sx={{ maxWidth: 240 }} />
      </Step>
      <Divider />

      <Step title="Additional settings">
        <TextField label="Duration of 'scheduled for destruction' state" type="number" value={destroyDays} onChange={(e) => setDestroyDays(e.target.value)}
          helperText="days" sx={{ maxWidth: 320 }} />
        <Box>
          <Typography variant="body2" sx={{ fontWeight: 500, mb: 1 }}>Labels</Typography>
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
        </Box>
      </Step>
      <Divider />

      {!ring && !rings.loading && <FormHelperText error sx={{ mt: 1 }}>Create a key ring first.</FormHelperText>}
      <Stack direction="row" spacing={1} sx={{ pt: 3 }}>
        <Button type="submit" variant="contained" disabled={busy || !ring}>{busy ? "Creating…" : "Create"}</Button>
        <Button href="#/security/kms/keyrings">Cancel</Button>
      </Stack>
    </Box>
  );
}
