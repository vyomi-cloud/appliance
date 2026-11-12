/* Create a firewall rule — a native firewalls.insert call. Settings Vyomi doesn't
 * model (service-account targets) are declared gaps, not controls. */
import { useState } from "react";
import {
  Box, Button, Checkbox, Chip, Divider, FormControl, FormControlLabel, IconButton, InputLabel, MenuItem,
  Radio, RadioGroup, Select, Stack, TextField, Typography,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, NotSimulated, PageHeader } from "../../kit/common.jsx";
import * as api from "./api.js";

function TagsInput({ label, value, onChange, placeholder }) {
  const [draft, setDraft] = useState("");
  const commit = () => { const v = draft.trim(); if (v) { onChange([...value, v]); setDraft(""); } };
  return (
    <Box>
      <Stack useFlexGap direction="row" spacing={1} alignItems="center" sx={{ flexWrap: "wrap", mb: 1 }}>
        {value.map((t, i) => <Chip key={i} size="small" label={t} onDelete={() => onChange(value.filter((_, j) => j !== i))} />)}
      </Stack>
      <TextField size="small" label={label} placeholder={placeholder} value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); commit(); } }}
        onBlur={commit} sx={{ maxWidth: 420 }} />
    </Box>
  );
}

export default function CreateFirewallRule() {
  const notify = useNotify();
  const { data: networks = [] } = useAsync(api.listNetworks, []);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [logs, setLogs] = useState("Off");
  const [network, setNetwork] = useState("default");
  const [priority, setPriority] = useState(1000);
  const [direction, setDirection] = useState("Ingress");
  const [action, setAction] = useState("Allow");
  const [targets, setTargets] = useState("Specified target tags");
  const [targetTags, setTargetTags] = useState([]);
  const [sourceFilter, setSourceFilter] = useState("IPv4 ranges");
  const [sourceRanges, setSourceRanges] = useState([]);
  const [protoMode, setProtoMode] = useState("Allow all");
  const [tcp, setTcp] = useState(false); const [tcpPorts, setTcpPorts] = useState("");
  const [udp, setUdp] = useState(false); const [udpPorts, setUdpPorts] = useState("");
  const [other, setOther] = useState(false); const [otherProto, setOtherProto] = useState("");
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const nameErr = touched ? api.validName(name, "Name") : null;

  const protoList = () => {
    if (protoMode === "Allow all") return [{ IPProtocol: "all" }];
    const xs = [];
    if (tcp) xs.push({ IPProtocol: "tcp", ...(tcpPorts ? { ports: tcpPorts.split(",").map((s) => s.trim()).filter(Boolean) } : {}) });
    if (udp) xs.push({ IPProtocol: "udp", ...(udpPorts ? { ports: udpPorts.split(",").map((s) => s.trim()).filter(Boolean) } : {}) });
    if (other && otherProto) xs.push({ IPProtocol: otherProto });
    return xs;
  };

  const submit = async (ev) => {
    ev.preventDefault();
    setTouched(true);
    if (api.validName(name, "Name") || !network) return;
    setBusy(true); setError(null);
    try {
      const body = {
        name, description, network,
        priority: Number(priority) || 1000,
        direction: direction === "Ingress" ? "INGRESS" : "EGRESS",
        logConfig: { enable: logs === "On" },
        ...(targets === "Specified target tags" && targetTags.length ? { targetTags } : {}),
        ...(sourceFilter === "IPv4 ranges" && sourceRanges.length ? { sourceRanges } : {}),
      };
      const proto = protoList();
      if (action === "Allow") body.allowed = proto; else body.denied = proto;
      await api.insertFirewall(body);
      notify.success(`Created firewall rule "${name}"`);
      window.location.hash = "#/networking/firewall";
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Box component="form" onSubmit={submit} noValidate sx={{ maxWidth: 760 }}>
      <PageHeader title="Create a firewall rule" back={<IconButton aria-label="Back" href="#/networking/firewall"><ArrowBackIcon /></IconButton>} />
      <ErrorAlert error={error} title="Failed to create firewall rule" />

      <Stack spacing={2.5}>
        <Typography variant="h3" component="h2">Rule</Typography>
        <TextField label="Name" required value={name} onChange={(e) => setName(e.target.value.trim())} onBlur={() => setTouched(true)}
          error={!!nameErr} helperText={nameErr} sx={{ maxWidth: 480 }} />
        <TextField label="Description" value={description} onChange={(e) => setDescription(e.target.value)} sx={{ maxWidth: 480 }} />

        <Box>
          <Typography variant="body2" sx={{ fontWeight: 500, mb: 1 }}>Logs</Typography>
          <RadioGroup row value={logs} onChange={(e) => setLogs(e.target.value)} aria-label="Logs">
            <FormControlLabel value="On" control={<Radio size="small" />} label="On" />
            <FormControlLabel value="Off" control={<Radio size="small" />} label="Off" />
          </RadioGroup>
        </Box>

        <FormControl required sx={{ maxWidth: 320 }}>
          <InputLabel id="net-label">Network</InputLabel>
          <Select labelId="net-label" label="Network" value={network} onChange={(e) => setNetwork(e.target.value)}>
            {networks.map((n) => <MenuItem key={n.name} value={n.name}>{n.name}</MenuItem>)}
            {!networks.some((n) => n.name === "default") && <MenuItem value="default">default</MenuItem>}
          </Select>
        </FormControl>

        <TextField label="Priority" type="number" value={priority} onChange={(e) => setPriority(e.target.value)} sx={{ maxWidth: 200 }} />

        <Box>
          <Typography variant="body2" sx={{ fontWeight: 500, mb: 1 }}>Direction of traffic</Typography>
          <RadioGroup row value={direction} onChange={(e) => setDirection(e.target.value)} aria-label="Direction of traffic">
            <FormControlLabel value="Ingress" control={<Radio size="small" />} label="Ingress" />
            <FormControlLabel value="Egress" control={<Radio size="small" />} label="Egress" />
          </RadioGroup>
        </Box>

        <Box>
          <Typography variant="body2" sx={{ fontWeight: 500, mb: 1 }}>Action on match</Typography>
          <RadioGroup row value={action} onChange={(e) => setAction(e.target.value)} aria-label="Action on match">
            <FormControlLabel value="Allow" control={<Radio size="small" />} label="Allow" />
            <FormControlLabel value="Deny" control={<Radio size="small" />} label="Deny" />
          </RadioGroup>
        </Box>

        <FormControl sx={{ maxWidth: 320 }}>
          <InputLabel id="targets-label">Targets</InputLabel>
          <Select labelId="targets-label" label="Targets" value={targets} onChange={(e) => setTargets(e.target.value)}>
            <MenuItem value="All instances in the network">All instances in the network</MenuItem>
            <MenuItem value="Specified target tags">Specified target tags</MenuItem>
            <MenuItem value="Specified service account">Specified service account</MenuItem>
          </Select>
        </FormControl>
        {targets === "Specified target tags" && <TagsInput label="Target tags" value={targetTags} onChange={setTargetTags} placeholder="web-server" />}
        {targets === "Specified service account" && <NotSimulated compact feature="Specified service account targets" note="Target by tag instead; service-account-scoped targeting isn't modeled." />}

        <FormControl sx={{ maxWidth: 320 }}>
          <InputLabel id="srcfilter-label">Source filter</InputLabel>
          <Select labelId="srcfilter-label" label="Source filter" value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value)}>
            <MenuItem value="IPv4 ranges">IPv4 ranges</MenuItem>
            <MenuItem value="Source tags">Source tags</MenuItem>
          </Select>
        </FormControl>
        {sourceFilter === "IPv4 ranges" && <TagsInput label="Source IPv4 ranges" value={sourceRanges} onChange={setSourceRanges} placeholder="0.0.0.0/0" />}

        <Divider />
        <Box>
          <Typography variant="body2" sx={{ fontWeight: 500, mb: 1 }}>Protocols and ports</Typography>
          <RadioGroup value={protoMode} onChange={(e) => setProtoMode(e.target.value)} aria-label="Protocols and ports">
            <FormControlLabel value="Allow all" control={<Radio size="small" />} label="Allow all" />
            <FormControlLabel value="Specified protocols and ports" control={<Radio size="small" />} label="Specified protocols and ports" />
          </RadioGroup>
          <Stack spacing={1} sx={{ ml: 4, mt: 1, opacity: protoMode === "Allow all" ? 0.5 : 1 }}>
            <Stack direction="row" spacing={1} alignItems="center">
              <FormControlLabel control={<Checkbox size="small" checked={tcp} disabled={protoMode === "Allow all"} onChange={(e) => setTcp(e.target.checked)} />} label="TCP" />
              <TextField size="small" label="Ports" placeholder="all" value={tcpPorts} onChange={(e) => setTcpPorts(e.target.value)} disabled={protoMode === "Allow all" || !tcp} />
            </Stack>
            <Stack direction="row" spacing={1} alignItems="center">
              <FormControlLabel control={<Checkbox size="small" checked={udp} disabled={protoMode === "Allow all"} onChange={(e) => setUdp(e.target.checked)} />} label="UDP" />
              <TextField size="small" label="Ports" placeholder="all" value={udpPorts} onChange={(e) => setUdpPorts(e.target.value)} disabled={protoMode === "Allow all" || !udp} />
            </Stack>
            <Stack direction="row" spacing={1} alignItems="center">
              <FormControlLabel control={<Checkbox size="small" checked={other} disabled={protoMode === "Allow all"} onChange={(e) => setOther(e.target.checked)} />} label="Other" />
              <TextField size="small" label="Protocol" placeholder="esp" value={otherProto} onChange={(e) => setOtherProto(e.target.value)} disabled={protoMode === "Allow all" || !other} />
            </Stack>
          </Stack>
        </Box>
      </Stack>

      <Stack direction="row" spacing={1} sx={{ pt: 3 }}>
        <Button type="submit" variant="contained" disabled={busy}>{busy ? "Creating…" : "Create"}</Button>
        <Button href="#/networking/firewall">Cancel</Button>
      </Stack>
    </Box>
  );
}
