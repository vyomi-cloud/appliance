/* Reserve a static address — a native addresses.insert / globalAddresses.insert call. */
import { useState } from "react";
import { Box, Button, FormControl, FormControlLabel, IconButton, InputLabel, MenuItem, Radio, RadioGroup, Select, Stack, TextField, Typography } from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, PageHeader } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function ReserveAddress({ query }) {
  const notify = useNotify();
  const internal = query?.type === "internal";
  const { data: networks = [] } = useAsync(internal ? api.listNetworks : async () => [], []);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [tier, setTier] = useState("Premium");
  const [ipVersion, setIpVersion] = useState("IPv4");
  const [type, setType] = useState("Regional");
  const [region, setRegion] = useState(api.REGIONS[0]);
  const [network, setNetwork] = useState("default");
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const nameErr = touched ? api.validName(name, "Name") : null;

  const submit = async (ev) => {
    ev.preventDefault();
    setTouched(true);
    if (api.validName(name, "Name")) return;
    setBusy(true); setError(null);
    try {
      const body = {
        name, description,
        addressType: internal ? "INTERNAL" : "EXTERNAL",
        ipVersion: ipVersion === "IPv6" ? "IPV6" : "IPV4",
        ...(internal ? {} : { networkTier: tier.toUpperCase() }),
        ...(internal ? { network: `global/networks/${network}` } : {}),
      };
      const scopePath = (internal || type === "Regional") ? `regions/${region}` : "global";
      await api.insertAddress(scopePath, body);
      notify.success(`Reserved address "${name}"`);
      window.location.hash = "#/networking/addresses/list";
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Box component="form" onSubmit={submit} noValidate sx={{ maxWidth: 640 }}>
      <PageHeader title="Reserve a static address" back={<IconButton aria-label="Back" href="#/networking/addresses/list"><ArrowBackIcon /></IconButton>} />
      <ErrorAlert error={error} title="Failed to reserve address" />

      <Stack spacing={2.5}>
        <Typography variant="h3" component="h2">Address</Typography>
        <TextField label="Name" required value={name} onChange={(e) => setName(e.target.value.trim())} onBlur={() => setTouched(true)}
          error={!!nameErr} helperText={nameErr} sx={{ maxWidth: 480 }} />
        <TextField label="Description" value={description} onChange={(e) => setDescription(e.target.value)} sx={{ maxWidth: 480 }} />

        {!internal && (
          <Box>
            <Typography variant="body2" sx={{ fontWeight: 500, mb: 1 }}>Network Service Tier</Typography>
            <RadioGroup row value={tier} onChange={(e) => setTier(e.target.value)} aria-label="Network Service Tier">
              <FormControlLabel value="Premium" control={<Radio size="small" />} label="Premium" />
              <FormControlLabel value="Standard" control={<Radio size="small" />} label="Standard" />
            </RadioGroup>
          </Box>
        )}

        <Box>
          <Typography variant="body2" sx={{ fontWeight: 500, mb: 1 }}>IP version</Typography>
          <RadioGroup row value={ipVersion} onChange={(e) => setIpVersion(e.target.value)} aria-label="IP version">
            <FormControlLabel value="IPv4" control={<Radio size="small" />} label="IPv4" />
            <FormControlLabel value="IPv6" control={<Radio size="small" />} label="IPv6" />
          </RadioGroup>
        </Box>

        {!internal && (
          <Box>
            <Typography variant="body2" sx={{ fontWeight: 500, mb: 1 }}>Type</Typography>
            <RadioGroup row value={type} onChange={(e) => setType(e.target.value)} aria-label="Type">
              <FormControlLabel value="Regional" control={<Radio size="small" />} label="Regional" />
              <FormControlLabel value="Global" control={<Radio size="small" />} label="Global" />
            </RadioGroup>
          </Box>
        )}

        {(internal || type === "Regional") && (
          <FormControl sx={{ maxWidth: 320 }}>
            <InputLabel id="region-label">Region</InputLabel>
            <Select labelId="region-label" label="Region" value={region} onChange={(e) => setRegion(e.target.value)}>
              {api.REGIONS.map((r) => <MenuItem key={r} value={r}>{r}</MenuItem>)}
            </Select>
          </FormControl>
        )}

        {internal ? (
          <FormControl sx={{ maxWidth: 320 }}>
            <InputLabel id="net-label">Network</InputLabel>
            <Select labelId="net-label" label="Network" value={network} onChange={(e) => setNetwork(e.target.value)}>
              {networks.map((n) => <MenuItem key={n.name} value={n.name}>{n.name}</MenuItem>)}
              {!networks.some((n) => n.name === "default") && <MenuItem value="default">default</MenuItem>}
            </Select>
          </FormControl>
        ) : (
          <FormControl sx={{ maxWidth: 320 }}>
            <InputLabel id="attach-label">Attached to</InputLabel>
            <Select labelId="attach-label" label="Attached to" value="None" disabled>
              <MenuItem value="None">None</MenuItem>
            </Select>
          </FormControl>
        )}
      </Stack>

      <Stack direction="row" spacing={1} sx={{ pt: 3 }}>
        <Button type="submit" variant="contained" disabled={busy}>{busy ? "Reserving…" : "Reserve"}</Button>
        <Button href="#/networking/addresses/list">Cancel</Button>
      </Stack>
    </Box>
  );
}
