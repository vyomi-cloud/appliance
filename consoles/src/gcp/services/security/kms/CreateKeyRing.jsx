/* Create a key ring — name, location type (region / multi-region) and region, as in the
 * console's single-step form. */
import { useState } from "react";
import { Box, Button, FormControl, FormControlLabel, IconButton, InputLabel, MenuItem, Radio, RadioGroup, Select, Stack, TextField, Typography } from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import { useNotify } from "../../../../common/notify.jsx";
import { ErrorAlert, PageHeader, Section } from "../../../kit/common.jsx";
import * as api from "./api.js";

const MULTI = ["global", "us", "europe", "asia"];
const NAME_RE = /^[a-zA-Z0-9_-]{1,63}$/;

export default function CreateKeyRing() {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [touched, setTouched] = useState(false);
  const [locType, setLocType] = useState("region");
  const [region, setRegion] = useState(api.LOCATIONS.find(([v]) => !MULTI.includes(v))[0]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const options = api.LOCATIONS.filter(([v]) => (locType === "multi-region" ? MULTI.includes(v) : !MULTI.includes(v)));
  const nameErr = touched && !NAME_RE.test(name) ? "Use letters, numbers, underscores and hyphens (max 63 characters)." : null;

  const submit = async (ev) => {
    ev.preventDefault();
    setTouched(true);
    if (!NAME_RE.test(name)) return;
    setBusy(true); setError(null);
    try {
      await api.createKeyRing(region, name);
      notify.success(`Created key ring "${name}"`);
      location.hash = `/security/kms/keyring/manage/${region}/${name}`;
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Box component="form" onSubmit={submit} noValidate sx={{ maxWidth: 640 }}>
      <PageHeader title="Create key ring" back={<IconButton aria-label="Back" href="#/security/kms/keyrings"><ArrowBackIcon /></IconButton>} />
      <ErrorAlert error={error} title="Failed to create key ring" />
      <Section title="Key ring">
        <Stack spacing={2.5}>
          <TextField label="Key ring name" required value={name} onChange={(e) => setName(e.target.value.trim())} onBlur={() => setTouched(true)}
            error={!!nameErr} helperText={nameErr || "A key ring organizes keys in a specific location."} />
          <Box>
            <Typography variant="body2" sx={{ fontWeight: 500, mb: 1 }}>Location type</Typography>
            <RadioGroup row value={locType} onChange={(e) => { setLocType(e.target.value); setRegion(api.LOCATIONS.find(([v]) => (e.target.value === "multi-region" ? MULTI.includes(v) : !MULTI.includes(v)))[0]); }} aria-label="Location type">
              <FormControlLabel value="region" control={<Radio size="small" />} label="Region" />
              <FormControlLabel value="multi-region" control={<Radio size="small" />} label="Multi-region" />
            </RadioGroup>
          </Box>
          <FormControl sx={{ maxWidth: 360 }}>
            <InputLabel id="region-l">Region</InputLabel>
            <Select labelId="region-l" label="Region" value={region} onChange={(e) => setRegion(e.target.value)} inputProps={{ "aria-label": "Region" }}>
              {options.map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
            </Select>
          </FormControl>
        </Stack>
      </Section>
      <Stack direction="row" spacing={1} sx={{ pt: 3 }}>
        <Button type="submit" variant="contained" disabled={busy}>{busy ? "Creating…" : "Create"}</Button>
        <Button href="#/security/kms/keyrings">Cancel</Button>
      </Stack>
    </Box>
  );
}
