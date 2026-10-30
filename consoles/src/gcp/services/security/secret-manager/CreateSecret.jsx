/* Create a secret — the console's single long form. Every real setting goes into ONE
 * native secrets.create body (+ secrets.addVersion if a value/file was given); settings
 * Vyomi doesn't enforce are declared config_only gaps via CapabilityBadge, not silent. */
import { useRef, useState } from "react";
import {
  Alert, Box, Button, Checkbox, Divider, FormControl, FormControlLabel, FormLabel, IconButton, InputLabel, MenuItem,
  Radio, RadioGroup, Select, Stack, TextField, Typography,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import UploadFileIcon from "@mui/icons-material/esm/UploadFile.js";
import AddIcon from "@mui/icons-material/esm/Add.js";
import { useNotify } from "../../../../common/notify.jsx";
import { ErrorAlert, PageHeader, Section } from "../../../kit/common.jsx";
import { CapabilityBadge } from "../../../kit/Capability.jsx";
import { hashHref } from "../../../link.jsx";
import { KeyValueRows, toMap } from "./Shared.jsx";
import * as api from "./api.js";

export default function CreateSecret() {
  const notify = useNotify();
  const file = useRef(null);
  const [name, setName] = useState("");
  const [touched, setTouched] = useState(false);
  const [value, setValue] = useState("");
  const [fileName, setFileName] = useState("");
  const [auto, setAuto] = useState(true);
  const [locations, setLocations] = useState([]);
  const [encryption, setEncryption] = useState("google");
  const [kmsKey, setKmsKey] = useState("");
  const [rotation, setRotation] = useState(false);
  const [rotationDays, setRotationDays] = useState("90");
  const [topics, setTopics] = useState([]);
  const [expiration, setExpiration] = useState(false);
  const [expireAt, setExpireAt] = useState("");
  const [labels, setLabels] = useState([]);
  const [annotations, setAnnotations] = useState([]);
  const [aliases, setAliases] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const nameErr = touched ? api.validSecretId(name) : null;
  const labelErr = labels.some((r) => r.key && !api.validLabelKey(r.key)) ? "Label keys must start with a lowercase letter and contain only lowercase letters, numbers, underscores and dashes." : null;

  const onFile = async (f) => {
    setFileName(f.name);
    setValue(await f.text());
  };

  const submit = async (ev) => {
    ev.preventDefault();
    setTouched(true);
    if (api.validSecretId(name) || labelErr) return;
    setBusy(true); setError(null);
    try {
      const replication = auto || !locations.length
        ? { automatic: {} }
        : { userManaged: { replicas: locations.map((loc) => ({ location: loc, ...(encryption === "cmek" && kmsKey ? { customerManagedEncryption: { kmsKeyName: kmsKey } } : {}) })) } };
      const body = {
        replication,
        labels: toMap(labels),
        annotations: toMap(annotations),
        ...(rotation ? { rotation: { rotationPeriod: `${Math.round(Number(rotationDays) * 86400)}s` } } : {}),
        ...(topics.length ? { topics: topics.filter((t) => t.key).map((t) => ({ name: t.key })) } : {}),
        ...(expiration && expireAt ? { expireTime: `${expireAt}T00:00:00.000000Z` } : {}),
        ...(aliases.length ? { versionAliases: Object.fromEntries(aliases.filter((a) => a.key && a.value).map((a) => [a.key, Number(a.value)])) } : {}),
      };
      await api.createSecret(name, body);
      if (value) await api.addVersion(name, value);
      notify.success(`Created secret "${name}"`);
      location.hash = hashHref("security", "secret-manager", "secret", name).slice(1);
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Box component="form" onSubmit={submit} noValidate sx={{ maxWidth: 820 }}>
      <PageHeader title="Create secret" back={<IconButton aria-label="Back" href={hashHref("security", "secret-manager")}><ArrowBackIcon /></IconButton>} />
      <ErrorAlert error={error} title="Failed to create secret" />

      <Stack spacing={2.5}>
        <Section title="Secret details">
          <Stack spacing={2}>
            <TextField label="Name" required value={name} onChange={(e) => setName(e.target.value.trim())} onBlur={() => setTouched(true)}
              error={!!nameErr} helperText={nameErr || "Use letters, numbers, hyphens and underscores."} sx={{ maxWidth: 480 }} />
            <Box>
              <Button startIcon={<UploadFileIcon />} onClick={() => file.current?.click()}>Browse</Button>
              <Typography component="span" variant="body2" sx={{ ml: 1 }}>{fileName || "Upload file"}</Typography>
              <input ref={file} type="file" hidden aria-label="Upload file" onChange={(e) => e.target.files[0] && onFile(e.target.files[0])} />
            </Box>
            <TextField label="Secret value" multiline minRows={3} value={value} onChange={(e) => { setValue(e.target.value); setFileName(""); }} sx={{ maxWidth: 480 }} />
          </Stack>
        </Section>

        <Section title="Replication policy">
          <Stack spacing={1.5}>
            <FormControlLabel control={<Checkbox checked={auto} onChange={(e) => setAuto(e.target.checked)} />} label="Automatically manage locations for this secret" />
            <FormControl disabled={auto} sx={{ maxWidth: 420 }}>
              <InputLabel id="loc-l">Locations</InputLabel>
              <Select labelId="loc-l" label="Locations" multiple value={locations} onChange={(e) => setLocations(e.target.value)}>
                {api.LOCATIONS.map((l) => <MenuItem key={l} value={l}>{l}</MenuItem>)}
              </Select>
            </FormControl>
          </Stack>
        </Section>

        <Section title={<Stack direction="row" spacing={1} alignItems="center"><span>Encryption</span><CapabilityBadge id="gcp.secret-manager.replication" /></Stack>}>
          <FormLabel component="legend" sx={{ fontSize: 14, mb: 0.5 }}>Encryption</FormLabel>
          <RadioGroup value={encryption} onChange={(e) => setEncryption(e.target.value)} aria-label="Encryption">
            <FormControlLabel value="google" control={<Radio size="small" />} label="Google-managed encryption key" />
            <FormControlLabel value="cmek" control={<Radio size="small" />} label="Customer-managed encryption key (CMEK)" />
          </RadioGroup>
          {encryption === "cmek" && <TextField size="small" label="Cloud KMS key" value={kmsKey} onChange={(e) => setKmsKey(e.target.value)}
            helperText="projects/{p}/locations/{l}/keyRings/{r}/cryptoKeys/{k}" sx={{ mt: 1, maxWidth: 480 }} />}
        </Section>

        <Section title={<Stack direction="row" spacing={1} alignItems="center"><span>Rotation</span><CapabilityBadge id="gcp.secret-manager.rotation" /></Stack>}>
          <FormControlLabel control={<Checkbox checked={rotation} onChange={(e) => setRotation(e.target.checked)} />} label="Set rotation period" />
          {rotation && <TextField size="small" type="number" label="Rotation period (days)" value={rotationDays} onChange={(e) => setRotationDays(e.target.value)} sx={{ ml: 4, width: 220 }} />}
        </Section>

        <Section title={<Stack direction="row" spacing={1} alignItems="center"><span>Notifications</span><CapabilityBadge id="gcp.secret-manager.notifications" /></Stack>}>
          <Stack spacing={1}>
            {topics.map((t, i) => (
              <Stack key={i} direction="row" spacing={1} alignItems="center">
                <TextField size="small" label={`Topic ${i + 1}`} value={t.key} onChange={(e) => setTopics(topics.map((x, j) => (j === i ? { ...x, key: e.target.value } : x)))}
                  helperText="projects/{p}/topics/{topic}" sx={{ width: 420 }} />
              </Stack>
            ))}
            <Box><Button size="small" startIcon={<AddIcon />} onClick={() => setTopics([...topics, { key: "", value: "" }])}>Add topic</Button></Box>
          </Stack>
        </Section>

        <Section title={<Stack direction="row" spacing={1} alignItems="center"><span>Expiration</span><CapabilityBadge id="gcp.secret-manager.expiration" /></Stack>}>
          <FormControlLabel control={<Checkbox checked={expiration} onChange={(e) => setExpiration(e.target.checked)} />} label="Set expiration date" />
          {expiration && <TextField size="small" type="date" label="Expiration date" value={expireAt} onChange={(e) => setExpireAt(e.target.value)} InputLabelProps={{ shrink: true }} sx={{ ml: 4, width: 220 }} />}
        </Section>

        <Section title="Labels">
          <KeyValueRows rows={labels} setRows={setLabels} addText="Add label" keyError={labelErr} />
        </Section>

        <Section title={<Stack direction="row" spacing={1} alignItems="center"><span>Annotations</span><CapabilityBadge id="gcp.secret-manager.annotations" /></Stack>}>
          <KeyValueRows rows={annotations} setRows={setAnnotations} addText="Add annotation" />
        </Section>

        <Section title={<Stack direction="row" spacing={1} alignItems="center"><span>Version aliases</span><CapabilityBadge id="gcp.secret-manager.version-aliases" /></Stack>}>
          <KeyValueRows rows={aliases} setRows={setAliases} addText="Add alias" keyLabel="Alias" valueLabel="Version" />
        </Section>

        <Divider />
        <Stack direction="row" spacing={1}>
          <Button type="submit" variant="contained" disabled={busy}>{busy ? "Creating…" : "Create secret"}</Button>
          <Button href={hashHref("security", "secret-manager")}>Cancel</Button>
        </Stack>
      </Stack>
    </Box>
  );
}
