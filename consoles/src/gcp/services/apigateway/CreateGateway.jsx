/* Create gateway: gateway ID, region and the API config it serves. */
import { useEffect, useState } from "react";
import { Box, Button, FormControl, IconButton, InputLabel, MenuItem, Select, Stack, TextField, Typography } from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, PageHeader } from "../../kit/common.jsx";
import { hashHref } from "../../link.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

export default function CreateGateway() {
  const notify = useNotify();
  const project = useProject();
  const [name, setName] = useState("");
  const [display, setDisplay] = useState("");
  const [region, setRegion] = useState(api.DEFAULT_REGION);
  const [config, setConfig] = useState("");
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const cfgs = useAsync(() => api.listAllConfigs(), [project]);
  const items = cfgs.data || [];
  useEffect(() => { if (!config && items.length) setConfig(items[0].name); }, [items]);

  const nameErr = touched && !api.ID.test(name) ? "1-63 characters: lowercase letters, numbers and hyphens, starting with a letter." : null;
  const submit = async (ev) => {
    ev.preventDefault(); setTouched(true);
    if (!api.ID.test(name) || !config) return;
    setBusy(true); setError(null);
    try {
      await api.createGateway(region, name, { apiConfig: config, ...(display.trim() ? { displayName: display.trim() } : {}) });
      notify.success(`Created gateway "${name}"`);
      location.hash = hashHref("apigateway", "gateways", region, name).slice(1);
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <Box component="form" onSubmit={submit} noValidate sx={{ maxWidth: 720 }}>
      <PageHeader title="Create gateway" back={<IconButton aria-label="Back" href="#/apigateway"><ArrowBackIcon /></IconButton>} />
      <ErrorAlert error={error} title="Failed to create gateway" />
      <Stack spacing={2.5} sx={{ py: 2 }}>
        <TextField required label="Gateway ID" value={name} onChange={(e) => setName(e.target.value.trim())} error={!!nameErr} helperText={nameErr || "Lowercase letters, numbers and hyphens"} />
        <TextField label="Display name" value={display} onChange={(e) => setDisplay(e.target.value)} />
        <FormControl><InputLabel id="gw-cfg-l">API config</InputLabel>
          <Select labelId="gw-cfg-l" label="API config" value={config} onChange={(e) => setConfig(e.target.value)}>
            {items.map((c) => <MenuItem key={c.name} value={c.name}>{api.apiOfConfig(c.name)} / {api.last(c.name)}</MenuItem>)}</Select>
          {!items.length && <Typography variant="caption" color="text.secondary">No API configs yet — create an API and a config first.</Typography>}</FormControl>
        <FormControl><InputLabel id="gw-region-l">Location</InputLabel>
          <Select labelId="gw-region-l" label="Location" value={region} onChange={(e) => setRegion(e.target.value)}>{api.REGIONS.map((r) => <MenuItem key={r} value={r}>{r}</MenuItem>)}</Select></FormControl>
      </Stack>
      <Stack direction="row" spacing={1}><Button type="submit" variant="contained" disabled={busy || !items.length}>{busy ? "Creating…" : "Create gateway"}</Button><Button href="#/apigateway">Cancel</Button></Stack>
    </Box>
  );
}
