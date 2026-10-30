/* Create a disk — numbered steps like CreateInstance.jsx. Only a blank, single-zone,
 * Google-managed-encryption disk is modeled; every other option is an honest gap. */
import { useEffect, useState } from "react";
import {
  Box, Button, Divider, FormControl, FormControlLabel, IconButton, InputLabel, MenuItem,
  Radio, RadioGroup, Select, Stack, TextField, Typography,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, NotSimulated, PageHeader } from "../../kit/common.jsx";
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

const SOURCE_TYPES = ["Blank disk", "Image", "Snapshot", "Instant snapshot", "Disk"];

export default function CreateDisk() {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [touched, setTouched] = useState(false);
  const [description, setDescription] = useState("");
  const [locType, setLocType] = useState("zonal");
  const [region, setRegion] = useState(api.DEFAULT_REGION);
  const [zone, setZone] = useState(api.DEFAULT_ZONE);
  const [sourceType, setSourceType] = useState("Blank disk");
  const [diskType, setDiskType] = useState(api.DISK_TYPES[0][0]);
  const [size, setSize] = useState(10);
  const [snapSchedule, setSnapSchedule] = useState(false);
  const [encryption, setEncryption] = useState("google");
  const [labels, setLabels] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => { setZone(api.ZONES_BY_REGION[region]?.[0] || api.DEFAULT_ZONE); }, [region]);

  const nameErr = touched ? api.validResourceName(name) : null;

  const submit = async (ev) => {
    ev.preventDefault();
    setTouched(true);
    if (api.validResourceName(name)) return;
    setBusy(true); setError(null);
    const body = {
      name, sizeGb: Number(size), type: diskType,
      labels: labels.length ? Object.fromEntries(labels.map((l) => [l.key, l.value])) : undefined,
    };
    try {
      await api.insertDisk(zone, body);
      notify.success(`Created disk "${name}"`);
      window.location.hash = hashHref("compute", "disks").slice(1);
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Box component="form" onSubmit={submit} noValidate sx={{ maxWidth: 920 }}>
      <PageHeader title="Create a disk" back={<IconButton aria-label="Back" href="#/compute/disks"><ArrowBackIcon /></IconButton>} />
      <ErrorAlert error={error} title="Failed to create disk" />

      <Step n={1} title="Disk details">
        <TextField label="Name" required value={name} onChange={(e) => setName(e.target.value.trim())} onBlur={() => setTouched(true)}
          error={!!nameErr} helperText={nameErr || " "} sx={{ maxWidth: 420 }} inputProps={{ "aria-label": "Name" }} />
        <TextField label="Description" value={description} onChange={(e) => setDescription(e.target.value)} sx={{ maxWidth: 420 }} />
        <Sub title="Location">
          <RadioGroup row value={locType} onChange={(e) => setLocType(e.target.value)} aria-label="Location">
            <FormControlLabel value="zonal" control={<Radio size="small" />} label="Single zone" />
            <FormControlLabel value="regional" control={<Radio size="small" />} label="Regional" />
          </RadioGroup>
          {locType === "regional" && <NotSimulated compact feature="Regional disks" note="Only single-zone disks are modeled; a single-zone disk will be created instead." />}
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
      </Step>
      <Divider />

      <Step n={2} title="Source">
        <FormControl sx={{ minWidth: 260 }}>
          <InputLabel id="src-l">Disk source type</InputLabel>
          <Select labelId="src-l" label="Disk source type" value={sourceType} onChange={(e) => setSourceType(e.target.value)}>
            {SOURCE_TYPES.map((s) => <MenuItem key={s} value={s}>{s}</MenuItem>)}
          </Select>
        </FormControl>
        {sourceType !== "Blank disk" && (
          <NotSimulated compact feature={`Create disk from ${sourceType}`} note="Sourcing a disk from an image, snapshot or another disk isn't modeled; a blank disk will be created instead." />
        )}
      </Step>
      <Divider />

      <Step n={3} title="Disk settings">
        <FormControl sx={{ minWidth: 260 }}>
          <InputLabel id="dt-l">Disk type</InputLabel>
          <Select labelId="dt-l" label="Disk type" value={diskType} onChange={(e) => setDiskType(e.target.value)}>
            {api.DISK_TYPES.map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
          </Select>
        </FormControl>
        <TextField label="Size (GB)" type="number" value={size} onChange={(e) => setSize(e.target.value)} sx={{ width: 160 }} />
      </Step>
      <Divider />

      <Step n={4} title="Snapshot schedule">
        <NotSimulated compact feature="Enable snapshot schedule" note="Automatic recurring snapshots aren't modeled; create snapshots manually from the Snapshots page." />
      </Step>
      <Divider />

      <Step n={5} title="Encryption">
        <RadioGroup value={encryption} onChange={(e) => setEncryption(e.target.value)} aria-label="Encryption">
          <FormControlLabel value="google" control={<Radio size="small" />} label="Google-managed encryption key" />
          <FormControlLabel value="kms" control={<Radio size="small" />} label="Cloud KMS key" />
          <FormControlLabel value="csek" control={<Radio size="small" />} label="Customer-supplied encryption key (CSEK)" />
        </RadioGroup>
        {encryption !== "google" && (
          <NotSimulated compact feature="Customer-managed encryption" note="Only Google-managed encryption is modeled; the disk will be created with Google-managed encryption." />
        )}
      </Step>
      <Divider />

      <Step n={6} title="Labels">
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
      </Step>

      <Stack direction="row" spacing={1} sx={{ pt: 3 }}>
        <Button type="submit" variant="contained" disabled={busy}>{busy ? "Creating…" : "Create"}</Button>
        <Button href="#/compute/disks">Cancel</Button>
      </Stack>
    </Box>
  );
}
