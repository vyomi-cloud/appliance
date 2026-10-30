/* Create instance — the console's single long form with numbered sections. Every real
 * setting goes into ONE native instances.insert body; settings Vyomi doesn't model are
 * declared gaps, not controls. */
import { useState } from "react";
import {
  Box, Button, Checkbox, Divider, FormControl, FormControlLabel, IconButton, InputLabel, MenuItem,
  Radio, RadioGroup, Select, Stack, TextField, Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, NotSimulated, PageHeader, Section } from "../../kit/common.jsx";
import * as api from "./api.js";

const ENGINE_LABEL = { MYSQL: "MySQL", POSTGRES: "PostgreSQL", SQLSERVER: "SQL Server" };
const TIER = { "Shared core": "db-f1-micro", "Dedicated core": "db-custom-1-3840", Lightweight: "db-custom-2-4096", Standard: "db-custom-4-15360", "High memory": "db-custom-4-26624" };
const genPassword = () => Array.from({ length: 16 }, () => "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"[Math.floor(Math.random() * 56)]).join("");

const Rows = ({ title, rows, setRows, cols, addLabel }) => (
  <Box>
    <Typography variant="body2" sx={{ fontWeight: 500, mb: 1 }}>{title}</Typography>
    <Stack spacing={1}>
      {rows.map((r, i) => (
        <Stack key={i} direction="row" spacing={1} alignItems="center">
          {cols.map((c) => (
            <TextField key={c} label={c} size="small" value={r[c] || ""} onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, [c]: e.target.value } : x))} />
          ))}
          <IconButton aria-label={`Delete row ${i + 1}`} onClick={() => setRows(rows.filter((_, j) => j !== i))}><DeleteIcon fontSize="small" /></IconButton>
        </Stack>
      ))}
      <Box><Button size="small" startIcon={<AddIcon />} onClick={() => setRows([...rows, {}])}>{addLabel}</Button></Box>
    </Stack>
  </Box>
);

export default function CreateInstance({ query }) {
  const notify = useNotify();
  const engine = ["MYSQL", "POSTGRES", "SQLSERVER"].includes(query?.engine) ? query.engine : "POSTGRES";
  const versions = api.VERSIONS[engine];

  const [edition, setEdition] = useState("Enterprise Plus");
  const [preset, setPreset] = useState("Production");
  const [version, setVersion] = useState(versions[0]);
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [pwdPolicy, setPwdPolicy] = useState(false);
  const [region, setRegion] = useState("us-central1");
  const [zonal, setZonal] = useState("Multiple zones (Highly available)");
  const [machine, setMachine] = useState("Dedicated core");
  const [storageType, setStorageType] = useState("SSD");
  const [storageGb, setStorageGb] = useState(10);
  const [autoResize, setAutoResize] = useState(true);
  const [privateIp, setPrivateIp] = useState(false);
  const [publicIp, setPublicIp] = useState(true);
  const [networks, setNetworks] = useState([]);
  const [autoBackup, setAutoBackup] = useState(true);
  const [pitr, setPitr] = useState(true);
  const [deletionProtection, setDeletionProtection] = useState(true);
  const [maintWindow, setMaintWindow] = useState("Any window");
  const [flags, setFlags] = useState([]);
  const [queryInsights, setQueryInsights] = useState(false);
  const [labels, setLabels] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async (ev) => {
    ev.preventDefault();
    if (!name) return;
    setBusy(true); setError(null);
    const body = {
      name, databaseVersion: version, region,
      settings: {
        tier: TIER[machine], dataDiskType: storageType === "SSD" ? "PD_SSD" : "PD_HDD",
        dataDiskSizeGb: Number(storageGb), storageAutoResize: autoResize,
        availabilityType: zonal.startsWith("Multiple") ? "REGIONAL" : "ZONAL",
        ipConfiguration: { ipv4Enabled: publicIp, privateNetwork: privateIp ? "projects/-/global/networks/default" : null, authorizedNetworks: networks.filter((n) => n.Network).map((n) => ({ name: n.Name || "", value: n.Network })) },
        backupConfiguration: { enabled: autoBackup, pointInTimeRecoveryEnabled: pitr },
        deletionProtectionEnabled: deletionProtection,
        databaseFlags: flags.filter((f) => f.Flag).map((f) => ({ name: f.Flag, value: f.Value || "" })),
        userLabels: Object.fromEntries(labels.filter((l) => l.key).map((l) => [l.key, l.value || ""])),
        insightsConfig: { queryInsightsEnabled: queryInsights },
        maintenanceWindow: { day: maintWindow === "Any window" ? 0 : 1 },
        passwordValidationPolicy: { enablePasswordPolicy: pwdPolicy },
      },
    };
    try {
      const inst = await api.insertInstance(body);
      notify.success(`Created instance "${inst.name}"`);
      location.hash = `#/sql/instances/${encodeURIComponent(inst.name)}/overview`;
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <Box component="form" onSubmit={submit} noValidate sx={{ maxWidth: 880 }}>
      <PageHeader title={`Create a ${ENGINE_LABEL[engine]} instance`} />
      <ErrorAlert error={error} title="Failed to create instance" />
      <Stack spacing={2.5}>
        <Section title="Choose a Cloud SQL edition">
          <Stack spacing={2}>
            <Box>
              <Typography variant="body2" sx={{ fontWeight: 500, mb: 1 }}>Cloud SQL edition</Typography>
              <RadioGroup row value={edition} onChange={(e) => setEdition(e.target.value)} aria-label="Cloud SQL edition">
                <FormControlLabel value="Enterprise Plus" control={<Radio size="small" />} label="Enterprise Plus" />
                <FormControlLabel value="Enterprise" control={<Radio size="small" />} label="Enterprise" />
              </RadioGroup>
            </Box>
            <Box>
              <Typography variant="body2" sx={{ fontWeight: 500, mb: 1 }}>Edition preset</Typography>
              <RadioGroup row value={preset} onChange={(e) => setPreset(e.target.value)} aria-label="Edition preset">
                {["Production", "Development", "Sandbox"].map((v) => <FormControlLabel key={v} value={v} control={<Radio size="small" />} label={v} />)}
              </RadioGroup>
            </Box>
          </Stack>
        </Section>

        <Section title="Choose your database version">
          <FormControl sx={{ maxWidth: 420 }}>
            <InputLabel id="ci-version">Database version</InputLabel>
            <Select labelId="ci-version" label="Database version" value={version} onChange={(e) => setVersion(e.target.value)}>
              {versions.map((v) => <MenuItem key={v} value={v}>{api.versionLabel(v)}</MenuItem>)}
            </Select>
          </FormControl>
        </Section>

        <Section title="Instance info">
          <Stack spacing={2}>
            <TextField label="Instance ID" required value={name} onChange={(e) => setName(e.target.value.trim())} sx={{ maxWidth: 420 }}
              helperText="Lowercase letters, numbers, hyphens; start with a letter" inputProps={{ "aria-label": "Instance ID" }} />
            <Stack direction="row" spacing={1} alignItems="flex-start">
              <TextField label="Password" required value={password} onChange={(e) => setPassword(e.target.value)} sx={{ maxWidth: 420 }} inputProps={{ "aria-label": "Password" }} />
              <Button sx={{ mt: 1 }} onClick={() => setPassword(genPassword())}>Generate</Button>
            </Stack>
            <FormControlLabel control={<Checkbox size="small" checked={pwdPolicy} onChange={(e) => setPwdPolicy(e.target.checked)} />} label="Password policy" />
          </Stack>
        </Section>

        <Section title="Choose region and zonal availability">
          <Stack spacing={2}>
            <FormControl sx={{ maxWidth: 420 }}>
              <InputLabel id="ci-region">Region</InputLabel>
              <Select labelId="ci-region" label="Region" value={region} onChange={(e) => setRegion(e.target.value)}>
                {api.REGIONS.map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
              </Select>
            </FormControl>
            <Box>
              <Typography variant="body2" sx={{ fontWeight: 500, mb: 1 }}>Zonal availability</Typography>
              <RadioGroup value={zonal} onChange={(e) => setZonal(e.target.value)} aria-label="Zonal availability">
                <FormControlLabel value="Single zone" control={<Radio size="small" />} label="Single zone" />
                <FormControlLabel value="Multiple zones (Highly available)" control={<Radio size="small" />} label="Multiple zones (Highly available)" />
              </RadioGroup>
            </Box>
          </Stack>
        </Section>

        <Section title="Customize your instance">
          <Stack spacing={2.5}>
            <Box>
              <Typography variant="body2" sx={{ fontWeight: 500, mb: 1 }}>Machine configuration</Typography>
              <RadioGroup row value={machine} onChange={(e) => setMachine(e.target.value)} aria-label="Machine configuration">
                {Object.keys(TIER).map((v) => <FormControlLabel key={v} value={v} control={<Radio size="small" />} label={v} />)}
              </RadioGroup>
            </Box>
            <Box>
              <Typography variant="body2" sx={{ fontWeight: 500, mb: 1 }}>Storage type</Typography>
              <RadioGroup row value={storageType} onChange={(e) => setStorageType(e.target.value)} aria-label="Storage type">
                <FormControlLabel value="SSD" control={<Radio size="small" />} label="SSD" />
                <FormControlLabel value="HDD" control={<Radio size="small" />} label="HDD" />
              </RadioGroup>
            </Box>
            <TextField label="Storage capacity" type="number" value={storageGb} onChange={(e) => setStorageGb(e.target.value)} helperText="GB" sx={{ maxWidth: 240 }} />
            <FormControlLabel control={<Checkbox size="small" checked={autoResize} onChange={(e) => setAutoResize(e.target.checked)} />} label="Enable automatic storage increases" />

            <Box>
              <Typography variant="body2" sx={{ fontWeight: 500, mb: 1 }}>Connections</Typography>
              <Stack spacing={1}>
                <FormControlLabel control={<Checkbox size="small" checked={privateIp} onChange={(e) => setPrivateIp(e.target.checked)} />} label="Private IP" />
                <FormControlLabel control={<Checkbox size="small" checked={publicIp} onChange={(e) => setPublicIp(e.target.checked)} />} label="Public IP" />
                <Rows title="Authorized networks" rows={networks} setRows={setNetworks} cols={["Name", "Network"]} addLabel="Add a network" />
              </Stack>
            </Box>

            <Box>
              <Typography variant="body2" sx={{ fontWeight: 500, mb: 1 }}>Data protection</Typography>
              <Stack spacing={1}>
                <FormControlLabel control={<Checkbox size="small" checked={autoBackup} onChange={(e) => setAutoBackup(e.target.checked)} />} label="Automate daily backups" />
                <FormControlLabel control={<Checkbox size="small" checked={pitr} onChange={(e) => setPitr(e.target.checked)} />} label="Enable point-in-time recovery" />
                <FormControlLabel control={<Checkbox size="small" checked={deletionProtection} onChange={(e) => setDeletionProtection(e.target.checked)} />} label="Enable deletion protection" />
              </Stack>
            </Box>

            <Box>
              <Typography variant="body2" sx={{ fontWeight: 500, mb: 1 }}>Maintenance</Typography>
              <FormControl sx={{ maxWidth: 300 }}>
                <InputLabel id="ci-maint">Preferred window</InputLabel>
                <Select labelId="ci-maint" label="Preferred window" value={maintWindow} onChange={(e) => setMaintWindow(e.target.value)}>
                  <MenuItem value="Any window">Any window</MenuItem>
                  <MenuItem value="Sunday 02:00-06:00">Sunday 02:00-06:00</MenuItem>
                </Select>
              </FormControl>
            </Box>

            <Rows title="Flags" rows={flags} setRows={setFlags} cols={["Flag", "Value"]} addLabel="Add a database flag" />
            <FormControlLabel control={<Checkbox size="small" checked={queryInsights} onChange={(e) => setQueryInsights(e.target.checked)} />} label="Query insights" />
            <Rows title="Labels" rows={labels.map((l) => ({ Name: l.key, Value: l.value }))} setRows={(rs) => setLabels(rs.map((r) => ({ key: r.Name, value: r.Value })))} cols={["Name", "Value"]} addLabel="Add label" />
            <NotSimulated compact feature="Custom machine shapes, SSL/TLS enforcement and Cloud KMS customer-managed encryption" />
          </Stack>
        </Section>

        <Divider />
        <Stack direction="row" spacing={1}>
          <Button type="submit" variant="contained" disabled={busy || !name || !password}>{busy ? "Creating…" : "Create instance"}</Button>
          <Button href="#/sql">Cancel</Button>
        </Stack>
      </Stack>
    </Box>
  );
}
