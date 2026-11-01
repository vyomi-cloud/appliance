/* Create an instance — the console's left-step form. Every real setting goes into ONE
 * native instances.insert body; settings Vyomi doesn't model are declared gaps (NotSimulated),
 * not fake controls. Pattern follows gcp/storage/CreateBucket.jsx. */
import { useEffect, useState } from "react";
import {
  Alert, Box, Button, Checkbox, Divider, FormControl, FormControlLabel, FormHelperText, IconButton, InputLabel, MenuItem,
  Paper, Radio, RadioGroup, Select, Stack, Table, TableBody, TableCell, TableHead, TableRow, TextField, Typography,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, NotSimulated, PageHeader } from "../../kit/common.jsx";
import { hashHref } from "../../link.jsx";
import { useProject } from "../../project.js";
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

const defaultName = () => {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `instance-${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
};

export default function CreateInstance() {
  const notify = useNotify();
  const project = useProject();
  const [name, setName] = useState(defaultName());
  const [touched, setTouched] = useState(false);
  const [labels, setLabels] = useState([]);
  const [region, setRegion] = useState(api.DEFAULT_REGION);
  const [zone, setZone] = useState(api.DEFAULT_ZONE);
  const [family, setFamily] = useState("General purpose");
  const [machineTypes, setMachineTypes] = useState([]);
  const [machineType, setMachineType] = useState("e2-medium");
  const [osIdx, setOsIdx] = useState(0);
  const [diskType, setDiskType] = useState("pd-balanced");
  const [diskSize, setDiskSize] = useState(10);
  const [httpTag, setHttpTag] = useState(false);
  const [httpsTag, setHttpsTag] = useState(false);
  const [netTags, setNetTags] = useState([]);
  const [hostname, setHostname] = useState("");
  const [ipForward, setIpForward] = useState(false);
  const [secureBoot, setSecureBoot] = useState(false);
  const [vtpm, setVtpm] = useState(true);
  const [integrity, setIntegrity] = useState(true);
  const [accessScope, setAccessScope] = useState("default");
  const [manageAccess, setManageAccess] = useState(false);
  const [sshKeys, setSshKeys] = useState([]);
  const [provisioning, setProvisioning] = useState("STANDARD");
  const [deletionProtection, setDeletionProtection] = useState(false);
  const [metadata, setMetadataItems] = useState([]);
  const [startupScript, setStartupScript] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => { setZone(api.ZONES_BY_REGION[region]?.[0] || api.DEFAULT_ZONE); }, [region]);
  useEffect(() => { api.listMachineTypes(zone).then(setMachineTypes).catch(() => setMachineTypes([])); }, [zone]);

  const series = machineTypes.filter((m) => api.machineFamilyFor(m.name) === family);
  useEffect(() => { if (series.length && !series.some((m) => m.name === machineType)) setMachineType(series[0].name); }, [family, machineTypes]);

  const nameErr = touched ? api.validResourceName(name) : null;

  const submit = async (ev) => {
    ev.preventDefault();
    setTouched(true);
    if (api.validResourceName(name)) return;
    setBusy(true); setError(null);
    const [osProject, osFamily] = api.OS_IMAGES[osIdx];
    const tagItems = [...(httpTag ? ["http-server"] : []), ...(httpsTag ? ["https-server"] : []), ...netTags];
    const metaItems = [...metadata.filter((m) => m.key), ...(startupScript ? [{ key: "startup-script", value: startupScript }] : []),
      ...(manageAccess && sshKeys.length ? [{ key: "ssh-keys", value: sshKeys.map((k) => `${k.user}:${k.key}`).join("\n") }] : [])];
    const body = {
      name, description: "",
      machineType, zone,
      labels: labels.length ? Object.fromEntries(labels.map((l) => [l.key, l.value])) : undefined,
      disks: [{ boot: true, autoDelete: true, initializeParams: { sourceImage: api.osImageSource(osProject, osFamily), diskType, diskSizeGb: Number(diskSize) } }],
      networkInterfaces: [{}],
      tags: tagItems.length ? { items: tagItems } : undefined,
      hostname: hostname || undefined,
      canIpForward: ipForward,
      shieldedInstanceConfig: { enableSecureBoot: secureBoot, enableVtpm: vtpm, enableIntegrityMonitoring: integrity },
      serviceAccounts: [{ email: "default", scopes: accessScope === "full" ? ["https://www.googleapis.com/auth/cloud-platform"] : ["https://www.googleapis.com/auth/devstorage.read_only", "https://www.googleapis.com/auth/logging.write", "https://www.googleapis.com/auth/monitoring.write"] }],
      scheduling: { provisioningModel: provisioning, automaticRestart: provisioning === "STANDARD" },
      deletionProtection,
      metadata: metaItems.length ? { items: metaItems } : undefined,
    };
    try {
      await api.insertInstance(zone, body);
      notify.success(`Created instance "${name}"`);
      window.location.hash = hashHref("compute", "instances", zone, name).slice(1);
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Box component="form" onSubmit={submit} noValidate sx={{ maxWidth: 920 }}>
      <PageHeader title="Create an instance" back={<IconButton aria-label="Back" href="#/compute/instances"><ArrowBackIcon /></IconButton>} />
      <ErrorAlert error={error} title="Failed to create instance" />

      <Step n={1} title="Machine configuration">
        <TextField label="Name" required value={name} onChange={(e) => setName(e.target.value.trim())} onBlur={() => setTouched(true)}
          error={!!nameErr} helperText={nameErr || " "} sx={{ maxWidth: 420 }} inputProps={{ "aria-label": "Name" }} />
        <Sub title="Labels">
          <Stack spacing={1}>
            {labels.map((l, i) => (
              <Stack key={i} direction="row" spacing={1} alignItems="center">
                <TextField label={`Key ${i + 1}`} value={l.key} onChange={(e) => setLabels(labels.map((x, j) => j === i ? { ...x, key: e.target.value } : x))} />
                <TextField label={`Value ${i + 1}`} value={l.value} onChange={(e) => setLabels(labels.map((x, j) => j === i ? { ...x, value: e.target.value } : x))} />
                <IconButton aria-label={`Delete label ${i + 1}`} onClick={() => setLabels(labels.filter((_, j) => j !== i))}><DeleteIcon fontSize="small" /></IconButton>
              </Stack>
            ))}
            <Box><Button startIcon={<AddIcon />} onClick={() => setLabels([...labels, { key: "", value: "" }])}>Add labels</Button></Box>
          </Stack>
        </Sub>
        <Stack direction="row" spacing={2}>
          <FormControl sx={{ minWidth: 260 }}>
            <InputLabel id="region-l">Region</InputLabel>
            <Select labelId="region-l" label="Region" value={region} onChange={(e) => setRegion(e.target.value)}>
              {api.REGIONS.map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
            </Select>
          </FormControl>
          <FormControl sx={{ minWidth: 200 }}>
            <InputLabel id="zone-l">Zone</InputLabel>
            <Select labelId="zone-l" label="Zone" value={zone} onChange={(e) => setZone(e.target.value)}>
              {(api.ZONES_BY_REGION[region] || []).map((z) => <MenuItem key={z} value={z}>{z}</MenuItem>)}
            </Select>
          </FormControl>
        </Stack>
        <Sub title="Machine family">
          <RadioGroup row value={family} onChange={(e) => setFamily(e.target.value)} aria-label="Machine family">
            {api.MACHINE_FAMILIES.map(([f]) => <FormControlLabel key={f} value={f} control={<Radio size="small" />} label={f} disabled={!machineTypes.some((m) => api.machineFamilyFor(m.name) === f)} />)}
          </RadioGroup>
        </Sub>
        <Sub title="Series">
          <Paper variant="outlined">
            <Table size="small">
              <TableHead><TableRow><TableCell>Series</TableCell><TableCell>Description</TableCell><TableCell>vCPUs</TableCell><TableCell>Memory</TableCell><TableCell>CPU Platform</TableCell></TableRow></TableHead>
              <TableBody>
                {[...new Set(series.map((m) => api.seriesLabel(m.name.split("-")[0])))].map((s) => (
                  <TableRow key={s}><TableCell>{s}</TableCell><TableCell>General-purpose workloads</TableCell><TableCell>2-32</TableCell><TableCell>Up to 128 GB</TableCell><TableCell>Intel/AMD</TableCell></TableRow>
                ))}
                {!series.length && <TableRow><TableCell colSpan={5}><Typography variant="body2" color="text.secondary">No series available for this family in {zone}.</Typography></TableCell></TableRow>}
              </TableBody>
            </Table>
          </Paper>
        </Sub>
        <FormControl sx={{ minWidth: 420 }}>
          <InputLabel id="mt-l">Machine type</InputLabel>
          <Select labelId="mt-l" label="Machine type" value={machineType} onChange={(e) => setMachineType(e.target.value)}>
            {series.map((m) => <MenuItem key={m.name} value={m.name}>{m.name} ({m.guestCpus} vCPU, {Math.round(m.memoryMb / 1024)} GB memory)</MenuItem>)}
          </Select>
        </FormControl>
      </Step>
      <Divider />

      <Step n={2} title="OS and storage">
        <Typography variant="subtitle1" sx={{ fontWeight: 500 }}>Operating system and storage</Typography>
        <Sub title="Boot disk">
          <Stack useFlexGap direction="row" spacing={2} flexWrap="wrap">
            <FormControl sx={{ minWidth: 220 }}>
              <InputLabel id="os-l">Operating system</InputLabel>
              <Select labelId="os-l" label="Operating system" value={osIdx} onChange={(e) => setOsIdx(Number(e.target.value))}>
                {api.OS_IMAGES.map(([, , name], i) => <MenuItem key={i} value={i}>{name}</MenuItem>)}
              </Select>
            </FormControl>
            <TextField label="Version" value={api.OS_IMAGES[osIdx][3]} slotProps={{ input: { readOnly: true } }} sx={{ minWidth: 260 }} />
            <FormControl sx={{ minWidth: 220 }}>
              <InputLabel id="bdt-l">Boot disk type</InputLabel>
              <Select labelId="bdt-l" label="Boot disk type" value={diskType} onChange={(e) => setDiskType(e.target.value)}>
                {api.DISK_TYPES.map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
              </Select>
            </FormControl>
            <TextField label="Size (GB)" type="number" value={diskSize} onChange={(e) => setDiskSize(e.target.value)} sx={{ width: 140 }} />
          </Stack>
        </Sub>
        <NotSimulated compact feature="Additional storage and VM backups" note="Attaching extra disks and VM-level backup plans at create time aren't modeled; create and attach a disk afterwards from the Disks page." />
      </Step>
      <Divider />

      <Step n={3} title="Data protection">
        <NotSimulated compact feature="Back up your data" note="Choose a backup policy after creation isn't modeled; snapshots are available from the Snapshots page." />
      </Step>
      <Divider />

      <Step n={4} title="Networking">
        <Sub title="Firewall">
          <Stack spacing={0.5}>
            <FormControlLabel control={<Checkbox size="small" checked={httpTag} onChange={(e) => setHttpTag(e.target.checked)} />} label="Allow HTTP traffic" />
            <FormControlLabel control={<Checkbox size="small" checked={httpsTag} onChange={(e) => setHttpsTag(e.target.checked)} />} label="Allow HTTPS traffic" />
            <NotSimulated compact feature="Allow Load Balancer Health Checks" note="No load balancer or firewall rules are modeled." />
          </Stack>
        </Sub>
        <TextField label="Network tags" placeholder="Comma-separated" value={netTags.join(", ")}
          onChange={(e) => setNetTags(e.target.value.split(",").map((s) => s.trim()).filter(Boolean))} sx={{ maxWidth: 420 }} />
        <TextField label="Hostname" value={hostname} onChange={(e) => setHostname(e.target.value)} sx={{ maxWidth: 420 }} />
        <FormControlLabel control={<Checkbox size="small" checked={ipForward} onChange={(e) => setIpForward(e.target.checked)} />} label="IP forwarding" />
        <Sub title="Network interfaces">
          <Paper variant="outlined">
            <Table size="small">
              <TableHead><TableRow><TableCell>Network</TableCell><TableCell>Subnetwork</TableCell><TableCell>IP stack type</TableCell><TableCell>Primary internal IPv4 address</TableCell><TableCell>External IPv4 address</TableCell></TableRow></TableHead>
              <TableBody><TableRow><TableCell>default</TableCell><TableCell>default</TableCell><TableCell>IPv4 (single-stack)</TableCell><TableCell>Ephemeral (auto)</TableCell><TableCell>Ephemeral (auto)</TableCell></TableRow></TableBody>
            </Table>
          </Paper>
          <NotSimulated compact feature="Add a network interface" note="Only a single default network interface is modeled." />
        </Sub>
      </Step>
      <Divider />

      <Step n={5} title="Observability">
        <Sub title="Observability - Ops Agent">
          <NotSimulated compact feature="Install Ops Agent for Monitoring and Logging" note="Metrics/logging agent installation isn't modeled." />
        </Sub>
      </Step>
      <Divider />

      <Step n={6} title="Security">
        <Sub title="Shielded VM">
          <Stack spacing={0.5}>
            <FormControlLabel control={<Checkbox size="small" checked={secureBoot} onChange={(e) => setSecureBoot(e.target.checked)} />} label="Turn on Secure Boot" />
            <FormControlLabel control={<Checkbox size="small" checked={vtpm} onChange={(e) => setVtpm(e.target.checked)} />} label="Turn on vTPM" />
            <FormControlLabel control={<Checkbox size="small" checked={integrity} onChange={(e) => setIntegrity(e.target.checked)} />} label="Turn on Integrity Monitoring" />
          </Stack>
        </Sub>
        <TextField label="Service account" value="Compute Engine default service account" slotProps={{ input: { readOnly: true } }} sx={{ maxWidth: 420 }} />
        <Sub title="Access scopes">
          <RadioGroup value={accessScope} onChange={(e) => setAccessScope(e.target.value)} aria-label="Access scopes">
            <FormControlLabel value="default" control={<Radio size="small" />} label="Allow default access" />
            <FormControlLabel value="full" control={<Radio size="small" />} label="Allow full access to all Cloud APIs" />
            <FormControlLabel value="per-api" control={<Radio size="small" />} label="Set access for each API" />
          </RadioGroup>
          {accessScope === "per-api" && <NotSimulated compact feature="Set access for each API" note="Per-API OAuth scope selection isn't modeled; full access is granted instead." />}
        </Sub>
        <Sub title="Manage access">
          <FormControlLabel control={<Checkbox size="small" checked={manageAccess} onChange={(e) => setManageAccess(e.target.checked)} />} label="Manage access" />
          {manageAccess && (
            <Stack spacing={1} sx={{ mt: 1 }}>
              {sshKeys.map((k, i) => (
                <Stack key={i} direction="row" spacing={1}>
                  <TextField label="User" value={k.user} onChange={(e) => setSshKeys(sshKeys.map((x, j) => j === i ? { ...x, user: e.target.value } : x))} />
                  <TextField label="Public key" value={k.key} fullWidth onChange={(e) => setSshKeys(sshKeys.map((x, j) => j === i ? { ...x, key: e.target.value } : x))} />
                  <IconButton aria-label={`Delete SSH key ${i + 1}`} onClick={() => setSshKeys(sshKeys.filter((_, j) => j !== i))}><DeleteIcon fontSize="small" /></IconButton>
                </Stack>
              ))}
              <Box><Button startIcon={<AddIcon />} onClick={() => setSshKeys([...sshKeys, { user: "", key: "" }])}>Add manually generated SSH keys</Button></Box>
            </Stack>
          )}
        </Sub>
      </Step>
      <Divider />

      <Step n={7} title="Advanced">
        <FormControl sx={{ minWidth: 220 }}>
          <InputLabel id="prov-l">Provisioning model</InputLabel>
          <Select labelId="prov-l" label="Provisioning model" value={provisioning} onChange={(e) => setProvisioning(e.target.value)}>
            <MenuItem value="STANDARD">Standard</MenuItem>
            <MenuItem value="SPOT">Spot</MenuItem>
          </Select>
        </FormControl>
        <FormControlLabel control={<Checkbox size="small" checked={deletionProtection} onChange={(e) => setDeletionProtection(e.target.checked)} />} label="Enable deletion protection" />
        <Sub title="Metadata">
          <Stack spacing={1}>
            {metadata.map((m, i) => (
              <Stack key={i} direction="row" spacing={1}>
                <TextField label="Key" value={m.key} onChange={(e) => setMetadataItems(metadata.map((x, j) => j === i ? { ...x, key: e.target.value } : x))} />
                <TextField label="Value" value={m.value} fullWidth onChange={(e) => setMetadataItems(metadata.map((x, j) => j === i ? { ...x, value: e.target.value } : x))} />
                <IconButton aria-label={`Delete metadata item ${i + 1}`} onClick={() => setMetadataItems(metadata.filter((_, j) => j !== i))}><DeleteIcon fontSize="small" /></IconButton>
              </Stack>
            ))}
            <Box><Button startIcon={<AddIcon />} onClick={() => setMetadataItems([...metadata, { key: "", value: "" }])}>Add item</Button></Box>
          </Stack>
        </Sub>
        <TextField label="Startup script" value={startupScript} onChange={(e) => setStartupScript(e.target.value)} multiline minRows={3}
          helperText="Automation" sx={{ maxWidth: 640 }} />
      </Step>

      <Stack direction="row" spacing={1} sx={{ pt: 3 }}>
        <Button type="submit" variant="contained" disabled={busy}>{busy ? "Creating…" : "Create"}</Button>
        <Button href="#/compute/instances">Cancel</Button>
      </Stack>
    </Box>
  );
}
