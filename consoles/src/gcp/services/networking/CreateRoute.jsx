/* Create a route — a native routes.insert call. Next-hop targets Vyomi doesn't model
 * (VPN tunnels, forwarding rules, named instances) are declared gaps, not controls. */
import { useState } from "react";
import { Box, Button, Chip, FormControl, IconButton, InputLabel, MenuItem, Select, Stack, TextField, Typography } from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, NotSimulated, PageHeader } from "../../kit/common.jsx";
import * as api from "./api.js";

const NEXT_HOPS = [
  "Default internet gateway", "Specify an instance", "Specify IP address of an instance",
  "Specify VPN tunnel", "Specify a forwarding rule of internal TCP/UDP load balancer",
];

export default function CreateRoute() {
  const notify = useNotify();
  const { data: networks = [] } = useAsync(api.listNetworks, []);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [network, setNetwork] = useState("");
  const [destRange, setDestRange] = useState("");
  const [priority, setPriority] = useState(1000);
  const [tags, setTags] = useState([]);
  const [tagDraft, setTagDraft] = useState("");
  const [nextHop, setNextHop] = useState(NEXT_HOPS[0]);
  const [nextHopIp, setNextHopIp] = useState("");
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const nameErr = touched ? api.validName(name, "Name") : null;

  const submit = async (ev) => {
    ev.preventDefault();
    setTouched(true);
    if (api.validName(name, "Name") || !network || !destRange) return;
    setBusy(true); setError(null);
    try {
      const body = { name, description, network, destRange, priority: Number(priority) || 1000, ...(tags.length ? { tags } : {}) };
      if (nextHop === "Specify IP address of an instance" && nextHopIp) body.nextHopIp = nextHopIp;
      else body.nextHopGateway = "default-internet-gateway";
      await api.insertRoute(body);
      notify.success(`Created route "${name}"`);
      window.location.hash = "#/networking/routes/list";
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Box component="form" onSubmit={submit} noValidate sx={{ maxWidth: 640 }}>
      <PageHeader title="Create a route" back={<IconButton aria-label="Back" href="#/networking/routes/list"><ArrowBackIcon /></IconButton>} />
      <ErrorAlert error={error} title="Failed to create route" />

      <Stack spacing={2.5}>
        <Typography variant="h3" component="h2">Route</Typography>
        <TextField label="Name" required value={name} onChange={(e) => setName(e.target.value.trim())} onBlur={() => setTouched(true)}
          error={!!nameErr} helperText={nameErr} sx={{ maxWidth: 480 }} />
        <TextField label="Description" value={description} onChange={(e) => setDescription(e.target.value)} sx={{ maxWidth: 480 }} />

        <FormControl required sx={{ maxWidth: 320 }}>
          <InputLabel id="net-label">Network</InputLabel>
          <Select labelId="net-label" label="Network" value={network} onChange={(e) => setNetwork(e.target.value)}>
            {networks.map((n) => <MenuItem key={n.name} value={n.name}>{n.name}</MenuItem>)}
          </Select>
        </FormControl>

        <TextField label="Destination IPv4 range" required placeholder="0.0.0.0/0" value={destRange} onChange={(e) => setDestRange(e.target.value)} sx={{ maxWidth: 320 }} />
        <TextField label="Priority" type="number" value={priority} onChange={(e) => setPriority(e.target.value)} sx={{ maxWidth: 200 }} />

        <Box>
          <Stack useFlexGap direction="row" spacing={1} alignItems="center" sx={{ flexWrap: "wrap", mb: 1 }}>
            {tags.map((t, i) => <Chip key={i} size="small" label={t} onDelete={() => setTags(tags.filter((_, j) => j !== i))} />)}
          </Stack>
          <TextField size="small" label="Instance tags" value={tagDraft} onChange={(e) => setTagDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); if (tagDraft.trim()) { setTags([...tags, tagDraft.trim()]); setTagDraft(""); } } }}
            sx={{ maxWidth: 320 }} />
        </Box>

        <FormControl sx={{ maxWidth: 420 }}>
          <InputLabel id="nh-label">Next hop</InputLabel>
          <Select labelId="nh-label" label="Next hop" value={nextHop} onChange={(e) => setNextHop(e.target.value)}>
            {NEXT_HOPS.map((h) => <MenuItem key={h} value={h}>{h}</MenuItem>)}
          </Select>
        </FormControl>
        {nextHop === "Specify IP address of an instance" && (
          <TextField label="Next hop IP address" value={nextHopIp} onChange={(e) => setNextHopIp(e.target.value)} sx={{ maxWidth: 320 }} />
        )}
        {["Specify an instance", "Specify VPN tunnel", "Specify a forwarding rule of internal TCP/UDP load balancer"].includes(nextHop) && (
          <NotSimulated compact feature={nextHop} note="Vyomi models next hops as the default internet gateway or a raw IP address; VM instances, VPN tunnels and load balancer forwarding rules aren't resources here." />
        )}
      </Stack>

      <Stack direction="row" spacing={1} sx={{ pt: 3 }}>
        <Button type="submit" variant="contained" disabled={busy}>{busy ? "Creating…" : "Create"}</Button>
        <Button href="#/networking/routes/list">Cancel</Button>
      </Stack>
    </Box>
  );
}
