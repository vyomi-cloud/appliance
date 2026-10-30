/* Create a VPC network — the console's single long form with numbered steps. Every
 * real setting becomes a native networks.insert + subnetworks.insert / firewalls.insert
 * call; settings Vyomi doesn't model are declared gaps, not controls. */
import { useState } from "react";
import {
  Box, Button, Checkbox, Divider, FormControl, FormControlLabel, FormHelperText, IconButton, InputLabel, MenuItem,
  Radio, RadioGroup, Select, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, TextField, Typography,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, PageHeader } from "../../kit/common.jsx";
import { hashHref } from "../../link.jsx";
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
const Sub = ({ title, children, help }) => (
  <Box>
    <Typography variant="body2" sx={{ fontWeight: 500, mb: help ? 0.25 : 1 }}>{title}</Typography>
    {help && <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>{help}</Typography>}
    {children}
  </Box>
);

const DEFAULT_RULES = (net) => [
  { key: "icmp", name: `${net}-allow-icmp`, type: "Ingress", targets: "Apply to all", filters: "IP ranges: 0.0.0.0/0", ports: "icmp", action: "Allow", priority: 65534,
    body: { sourceRanges: ["0.0.0.0/0"], allowed: [{ IPProtocol: "icmp" }] } },
  { key: "internal", name: `${net}-allow-internal`, type: "Ingress", targets: "Apply to all", filters: "IP ranges: 10.128.0.0/9", ports: "tcp:0-65535, udp:0-65535, icmp", action: "Allow", priority: 65534,
    body: { sourceRanges: ["10.128.0.0/9"], allowed: [{ IPProtocol: "tcp", ports: ["0-65535"] }, { IPProtocol: "udp", ports: ["0-65535"] }, { IPProtocol: "icmp" }] } },
  { key: "rdp", name: `${net}-allow-rdp`, type: "Ingress", targets: "Apply to all", filters: "IP ranges: 0.0.0.0/0", ports: "tcp:3389", action: "Allow", priority: 65534,
    body: { sourceRanges: ["0.0.0.0/0"], allowed: [{ IPProtocol: "tcp", ports: ["3389"] }] } },
  { key: "ssh", name: `${net}-allow-ssh`, type: "Ingress", targets: "Apply to all", filters: "IP ranges: 0.0.0.0/0", ports: "tcp:22", action: "Allow", priority: 65534,
    body: { sourceRanges: ["0.0.0.0/0"], allowed: [{ IPProtocol: "tcp", ports: ["22"] }] } },
];

const STACK_LABEL = { v4: "IPv4 (single-stack)", dual: "IPv4 and IPv6 (dual-stack)", v6: "IPv6 (single-stack)" };
const STACK_VALUE = { v4: "IPV4_ONLY", dual: "IPV4_IPV6", v6: "IPV6_ONLY" };

export default function CreateVpcNetwork() {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [mtu, setMtu] = useState("1460");
  const [ula, setUla] = useState("Disabled");
  const [subnetMode, setSubnetMode] = useState("Custom");
  const [pending, setPending] = useState([]);
  const [draft, setDraft] = useState({ name: "", description: "", region: api.REGIONS[0], stack: "v4", range: "", pga: "Off", flowLogs: "Off" });
  const [fwRules, setFwRules] = useState({});
  const [dynRouting, setDynRouting] = useState("Regional");
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const nameErr = touched ? api.validName(name, "Name") : null;

  const addSubnet = () => {
    const err = api.validName(draft.name, "Subnet name") || (!draft.region && "Region is required.") || (!draft.range && "IPv4 range is required.");
    if (err) { notify.error({ message: err }); return; }
    setPending([...pending, draft]);
    setDraft({ name: "", description: "", region: api.REGIONS[0], stack: "v4", range: "", pga: "Off", flowLogs: "Off" });
  };

  const submit = async (ev) => {
    ev.preventDefault();
    setTouched(true);
    if (api.validName(name, "Name")) return;
    setBusy(true); setError(null);
    try {
      await api.insertNetwork({
        name, description, mtu: Number(mtu),
        autoCreateSubnetworks: subnetMode === "Automatic",
        routingConfig: { routingMode: dynRouting.toUpperCase() },
        ...(ula === "Enabled" ? { enableUlaInternalIpv6: true } : {}),
      });
      if (subnetMode === "Custom") {
        for (const s of pending) {
          await api.insertSubnet(s.region, {
            name: s.name, description: s.description, network: name, ipCidrRange: s.range,
            stackType: STACK_VALUE[s.stack], privateIpGoogleAccess: s.pga === "On",
            logConfig: { enable: s.flowLogs === "On" },
          });
        }
      }
      for (const r of DEFAULT_RULES(name)) {
        if (fwRules[r.key]) await api.insertFirewall({ name: r.name, network: name, direction: "INGRESS", priority: r.priority, ...r.body });
      }
      notify.success(`Created network "${name}"`);
      window.location.hash = hashHref("networking", "networks", "details", name).slice(1);
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Box component="form" onSubmit={submit} noValidate sx={{ maxWidth: 880 }}>
      <PageHeader title="Create a VPC network" back={<IconButton aria-label="Back" href="#/networking/networks/list"><ArrowBackIcon /></IconButton>} />
      <ErrorAlert error={error} title="Failed to create network" />

      <Step n={1} title="Network">
        <TextField label="Name" required value={name} onChange={(e) => setName(e.target.value.trim())} onBlur={() => setTouched(true)}
          error={!!nameErr} inputProps={{ "aria-label": "Name" }} sx={{ maxWidth: 560 }}
          helperText={nameErr || "Lowercase letters, numbers and hyphens."} />
        <TextField label="Description" value={description} onChange={(e) => setDescription(e.target.value)} sx={{ maxWidth: 560 }} />
        <FormControl sx={{ maxWidth: 300 }}>
          <InputLabel id="mtu-label">Maximum transmission unit (MTU)</InputLabel>
          <Select labelId="mtu-label" label="Maximum transmission unit (MTU)" value={mtu} onChange={(e) => setMtu(e.target.value)}>
            <MenuItem value="1460">1460 (default)</MenuItem>
            <MenuItem value="1500">1500</MenuItem>
          </Select>
        </FormControl>
        <Sub title="VPC network ULA internal IPv6 range">
          <RadioGroup row value={ula} onChange={(e) => setUla(e.target.value)} aria-label="VPC network ULA internal IPv6 range">
            <FormControlLabel value="Disabled" control={<Radio size="small" />} label="Disabled" />
            <FormControlLabel value="Enabled" control={<Radio size="small" />} label="Enabled" />
          </RadioGroup>
          {ula === "Enabled" && <Typography variant="caption" color="text.secondary">Vyomi assigns a /48 ULA range automatically.</Typography>}
        </Sub>
      </Step>
      <Divider />

      <Step n={2} title="Subnets">
        <Sub title="Subnet creation mode">
          <RadioGroup row value={subnetMode} onChange={(e) => setSubnetMode(e.target.value)} aria-label="Subnet creation mode">
            <FormControlLabel value="Custom" control={<Radio size="small" />} label="Custom" />
            <FormControlLabel value="Automatic" control={<Radio size="small" />} label="Automatic" />
          </RadioGroup>
        </Sub>
        {subnetMode === "Automatic" && (
          <Typography variant="body2" color="text.secondary">Vyomi creates one subnet per supported region automatically, as the real console does.</Typography>
        )}
        {subnetMode === "Custom" && (
          <Sub title="New subnet">
            <Stack spacing={1.5} sx={{ maxWidth: 560 }}>
              <TextField label="Name" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value.trim() })} />
              <TextField label="Description" value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
              <FormControl required>
                <InputLabel id="region-label">Region</InputLabel>
                <Select labelId="region-label" label="Region" value={draft.region} onChange={(e) => setDraft({ ...draft, region: e.target.value })}>
                  {api.REGIONS.map((r) => <MenuItem key={r} value={r}>{r}</MenuItem>)}
                </Select>
              </FormControl>
              <Sub title="IP stack type">
                <RadioGroup value={draft.stack} onChange={(e) => setDraft({ ...draft, stack: e.target.value })} aria-label="IP stack type">
                  {Object.entries(STACK_LABEL).map(([v, l]) => <FormControlLabel key={v} value={v} control={<Radio size="small" />} label={l} />)}
                </RadioGroup>
              </Sub>
              <TextField label="IPv4 range" required placeholder="10.0.0.0/24" value={draft.range} onChange={(e) => setDraft({ ...draft, range: e.target.value })} />
              <Sub title="Private Google Access">
                <RadioGroup row value={draft.pga} onChange={(e) => setDraft({ ...draft, pga: e.target.value })} aria-label="Private Google Access">
                  <FormControlLabel value="On" control={<Radio size="small" />} label="On" />
                  <FormControlLabel value="Off" control={<Radio size="small" />} label="Off" />
                </RadioGroup>
              </Sub>
              <Sub title="Flow logs">
                <RadioGroup row value={draft.flowLogs} onChange={(e) => setDraft({ ...draft, flowLogs: e.target.value })} aria-label="Flow logs">
                  <FormControlLabel value="On" control={<Radio size="small" />} label="On" />
                  <FormControlLabel value="Off" control={<Radio size="small" />} label="Off" />
                </RadioGroup>
              </Sub>
              <Stack direction="row" spacing={1}>
                <Button variant="outlined" onClick={addSubnet}>Done</Button>
                <Button startIcon={<AddIcon />} onClick={addSubnet}>Add subnet</Button>
              </Stack>
            </Stack>
            {pending.length > 0 && (
              <Stack spacing={1} sx={{ mt: 1 }}>
                {pending.map((s, i) => (
                  <Stack key={i} direction="row" spacing={1} alignItems="center">
                    <Typography variant="body2">{s.name} — {s.region} — {s.range}</Typography>
                    <IconButton size="small" aria-label={`Remove subnet ${s.name}`} onClick={() => setPending(pending.filter((_, j) => j !== i))}><DeleteIcon fontSize="small" /></IconButton>
                  </Stack>
                ))}
              </Stack>
            )}
          </Sub>
        )}
      </Step>
      <Divider />

      <Step n={3} title="Firewall rules">
        <Typography variant="body2" color="text.secondary">IPv4 firewall rules — select the default rules to create alongside this network.</Typography>
        <TableContainer sx={{ maxWidth: 880 }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell padding="checkbox" />
                <TableCell>Name</TableCell><TableCell>Type</TableCell><TableCell>Targets</TableCell><TableCell>Filters</TableCell>
                <TableCell>Protocols / ports</TableCell><TableCell>Action</TableCell><TableCell>Priority</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {DEFAULT_RULES(name || "{network}").map((r) => (
                <TableRow key={r.key}>
                  <TableCell padding="checkbox"><Checkbox size="small" checked={!!fwRules[r.key]} onChange={(e) => setFwRules({ ...fwRules, [r.key]: e.target.checked })} inputProps={{ "aria-label": `Create ${r.name}` }} /></TableCell>
                  <TableCell>{r.name}</TableCell><TableCell>{r.type}</TableCell><TableCell>{r.targets}</TableCell><TableCell>{r.filters}</TableCell>
                  <TableCell>{r.ports}</TableCell><TableCell>{r.action}</TableCell><TableCell>{r.priority}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      </Step>
      <Divider />

      <Step n={4} title="Dynamic routing mode">
        <RadioGroup row value={dynRouting} onChange={(e) => setDynRouting(e.target.value)} aria-label="Dynamic routing mode">
          <FormControlLabel value="Regional" control={<Radio size="small" />} label="Regional" />
          <FormControlLabel value="Global" control={<Radio size="small" />} label="Global" />
        </RadioGroup>
      </Step>
      <Divider />

      <Step n={5} title="DNS server policy">
        <FormControl sx={{ maxWidth: 300 }}>
          <InputLabel id="dns-label">DNS server policy</InputLabel>
          <Select labelId="dns-label" label="DNS server policy" value="No server policy" disabled>
            <MenuItem value="No server policy">No server policy</MenuItem>
          </Select>
          <FormHelperText>Custom DNS server policies aren't modeled.</FormHelperText>
        </FormControl>
      </Step>
      <Divider />

      <Stack direction="row" spacing={1} sx={{ pt: 3 }}>
        <Button type="submit" variant="contained" disabled={busy}>{busy ? "Creating…" : "Create"}</Button>
        <Button href="#/networking/networks/list">Cancel</Button>
      </Stack>
    </Box>
  );
}
