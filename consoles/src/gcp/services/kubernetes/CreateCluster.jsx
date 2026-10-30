/* Create an Autopilot cluster — the console's numbered-step form. Every real setting goes
 * into ONE native clusters.create body; settings Vyomi doesn't model (fleet registration,
 * restricting access by DNS/IPv4) are declared gaps, not controls. */
import { useState } from "react";
import {
  Box, Button, Divider, FormControl, FormControlLabel, IconButton, InputLabel, MenuItem,
  Radio, RadioGroup, Select, Stack, TextField, Typography,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, PageHeader } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { hashHref } from "../../link.jsx";
import { getProject } from "../../project.js";
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

export default function CreateCluster({ query = {} }) {
  const notify = useNotify();
  const [name, setName] = useState(query.name ? `${query.name}-copy` : "autopilot-cluster-1");
  const [touched, setTouched] = useState(false);
  const [region, setRegion] = useState(query.region || "us-central1");
  const [network, setNetwork] = useState(query.network || "default");
  const [subnet, setSubnet] = useState(query.subnet || "default");
  const [channel, setChannel] = useState(query.channel || "REGULAR");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const nameErr = touched ? api.validClusterName(name) : null;

  const submit = async (ev) => {
    ev.preventDefault();
    setTouched(true);
    if (api.validClusterName(name)) return;
    setBusy(true); setError(null);
    try {
      await api.createCluster(region, { name, autopilot: { enabled: true }, network, subnetwork: subnet, releaseChannel: { channel } });
      notify.success(`Creating cluster "${name}"…`);
      location.hash = hashHref("kubernetes", "clusters", region, name).slice(1);
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Box component="form" onSubmit={submit} noValidate sx={{ maxWidth: 880 }}>
      <PageHeader title="Create an Autopilot cluster" back={<IconButton aria-label="Back" href={hashHref("kubernetes", "clusters")}><ArrowBackIcon /></IconButton>} />
      <ErrorAlert error={error} title="Failed to create cluster" />

      <Step n={1} title="Cluster basics">
        <TextField label="Name" required value={name} onChange={(e) => setName(e.target.value.trim())} onBlur={() => setTouched(true)}
          error={!!nameErr} inputProps={{ "aria-label": "Name" }} sx={{ maxWidth: 420 }}
          helperText={nameErr || "Lowercase letters, numbers and hyphens."} />
        <FormControl sx={{ maxWidth: 420 }}>
          <InputLabel id="region-l">Region</InputLabel>
          <Select labelId="region-l" label="Region" value={region} onChange={(e) => setRegion(e.target.value)} inputProps={{ "aria-label": "Region" }}>
            {api.REGIONS.map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
          </Select>
        </FormControl>
      </Step>
      <Divider />

      <Step n={2} title="Fleet registration">
        <CapabilityContainer id="gcp.kubernetes.fleet-registration" title="Register to the fleet" />
      </Step>
      <Divider />

      <Step n={3} title="Networking">
        <FormControl sx={{ maxWidth: 420 }}>
          <InputLabel id="net-l">Network</InputLabel>
          <Select labelId="net-l" label="Network" value={network} onChange={(e) => setNetwork(e.target.value)} inputProps={{ "aria-label": "Network" }}>
            <MenuItem value="default">default</MenuItem>
          </Select>
        </FormControl>
        <FormControl sx={{ maxWidth: 420 }}>
          <InputLabel id="sub-l">Node subnet</InputLabel>
          <Select labelId="sub-l" label="Node subnet" value={subnet} onChange={(e) => setSubnet(e.target.value)} inputProps={{ "aria-label": "Node subnet" }}>
            <MenuItem value="default">default</MenuItem>
          </Select>
        </FormControl>
        <CapabilityContainer id="gcp.kubernetes.cluster.private-networking" title="Access using DNS" description="Access using IPv4 addresses" />
      </Step>
      <Divider />

      <Step n={4} title="Advanced settings">
        <Typography variant="body2" sx={{ fontWeight: 500 }}>Release channel</Typography>
        <RadioGroup value={channel} onChange={(e) => setChannel(e.target.value)} aria-label="Release channel">
          {api.CHANNELS.map(([v, l]) => <FormControlLabel key={v} value={v} control={<Radio size="small" />} label={l} />)}
        </RadioGroup>
      </Step>
      <Divider />

      <Step n={5} title="Review and create">
        <Stack spacing={1}>
          <Typography variant="body2"><b>Name:</b> {name || "—"}</Typography>
          <Typography variant="body2"><b>Region:</b> {region}</Typography>
          <Typography variant="body2"><b>Network:</b> {network} / {subnet}</Typography>
          <Typography variant="body2"><b>Release channel:</b> {api.channelLabel(channel)}</Typography>
          <Typography variant="body2"><b>Project:</b> {getProject()}</Typography>
        </Stack>
      </Step>

      <Stack direction="row" spacing={1} sx={{ pt: 3 }}>
        <Button type="submit" variant="contained" disabled={busy}>{busy ? "Creating…" : "Create"}</Button>
        <Button href={hashHref("kubernetes", "clusters")}>Cancel</Button>
      </Stack>
    </Box>
  );
}
