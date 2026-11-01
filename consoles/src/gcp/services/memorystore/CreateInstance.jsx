/* Create a Redis instance — the console's single long form with numbered sections. Every
 * setting goes into ONE native instances.insert body (core/gcp_redis_core.py:create_instance);
 * nothing Vyomi doesn't model is offered as a control. */
import { useState } from "react";
import {
  Box, Button, Checkbox, Divider, FormControl, FormControlLabel, IconButton, InputLabel, MenuItem,
  Radio, RadioGroup, Select, Stack, TextField, Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, PageHeader, Section } from "../../kit/common.jsx";
import * as api from "./api.js";

const ZONE_SUFFIXES = ["a", "b", "c"];
const zonesFor = (region) => ZONE_SUFFIXES.map((s) => `${region}-${s}`);
const MAINT_TIMES = ["00:00", "04:00", "08:00", "12:00", "16:00", "20:00"];

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

export default function CreateInstance() {
  const notify = useNotify();

  const [id, setId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [tier, setTier] = useState("Basic");
  const [version, setVersion] = useState("REDIS_7_0");
  const [capacity, setCapacity] = useState(1);
  const [region, setRegion] = useState("us-central1");
  const [zone, setZone] = useState("Any");
  const [altZone, setAltZone] = useState("Any");
  const [network, setNetwork] = useState("default");
  const [connectMode, setConnectMode] = useState("Direct peering");
  const [reservedRange, setReservedRange] = useState("");
  const [auth, setAuth] = useState(false);
  const [encryption, setEncryption] = useState(false);
  const [readReplicas, setReadReplicas] = useState("Disabled");
  const [replicaCount, setReplicaCount] = useState(1);
  const [persistence, setPersistence] = useState("Disabled");
  const [snapshotPeriod, setSnapshotPeriod] = useState("TWENTY_FOUR_HOURS");
  const [maxmemoryPolicy, setMaxmemoryPolicy] = useState("volatile-lru");
  const [params, setParams] = useState([]);
  const [day, setDay] = useState("No preference");
  const [startTime, setStartTime] = useState("00:00");
  const [labels, setLabels] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const zones = zonesFor(region);

  const submit = async (ev) => {
    ev.preventDefault();
    if (!id) return;
    setBusy(true); setError(null);
    const redisConfigs = { "maxmemory-policy": maxmemoryPolicy };
    for (const p of params) if (p.Parameter) redisConfigs[p.Parameter] = p.Value || "";
    const body = {
      displayName: displayName || undefined,
      tier: tier === "Basic" ? "BASIC" : "STANDARD_HA",
      memorySizeGb: Number(capacity),
      redisVersion: version,
      authorizedNetwork: network,
      connectMode: connectMode === "Direct peering" ? "DIRECT_PEERING" : "PRIVATE_SERVICE_ACCESS",
      reservedIpRange: reservedRange || undefined,
      locationId: zone === "Any" ? undefined : zone,
      alternativeLocationId: tier === "Basic" ? undefined : (altZone === "Any" ? undefined : altZone),
      readReplicasMode: readReplicas === "Enabled" ? "READ_REPLICAS_ENABLED" : "READ_REPLICAS_DISABLED",
      replicaCount: tier === "Basic" ? 0 : Number(replicaCount),
      transitEncryptionMode: encryption ? "SERVER_AUTHENTICATION" : "DISABLED",
      authEnabled: auth,
      persistenceConfig: { persistenceMode: persistence === "Disabled" ? "DISABLED" : "RDB", rdbSnapshotPeriod: persistence === "Disabled" ? undefined : snapshotPeriod },
      redisConfigs,
      labels: Object.fromEntries(labels.filter((l) => l.key).map((l) => [l.key, l.value || ""])),
    };
    if (day !== "No preference") {
      const [h, m] = startTime.split(":").map(Number);
      body.maintenancePolicy = { weeklyMaintenanceWindow: [{ day: day.toUpperCase(), startTime: { hours: h, minutes: m } }] };
    }
    try {
      await api.createInstance(region, id, body);
      notify.success(`Creating instance "${id}"`);
      location.hash = `#/memorystore/instances/${encodeURIComponent(region)}/${encodeURIComponent(id)}/overview`;
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <Box component="form" onSubmit={submit} noValidate sx={{ maxWidth: 880 }}>
      <PageHeader title="Create a Redis instance" />
      <ErrorAlert error={error} title="Failed to create instance" />
      <Stack spacing={2.5}>
        <Section title="Instance info">
          <Stack spacing={2}>
            <TextField label="Instance ID" required value={id} onChange={(e) => setId(e.target.value.trim())} sx={{ maxWidth: 420 }}
              helperText="Lowercase letters, numbers, hyphens; start with a letter; up to 40 characters" inputProps={{ "aria-label": "Instance ID" }} />
            <TextField label="Display name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} sx={{ maxWidth: 420 }} />
            <Box>
              <Typography variant="body2" sx={{ fontWeight: 500, mb: 1 }}>Tier</Typography>
              <RadioGroup row value={tier} onChange={(e) => setTier(e.target.value)} aria-label="Tier">
                <FormControlLabel value="Basic" control={<Radio size="small" />} label="Basic" />
                <FormControlLabel value="Standard (high availability)" control={<Radio size="small" />} label="Standard (high availability)" />
              </RadioGroup>
              <Typography variant="caption" color="text.secondary">Standard adds a replica and automatic failover across zones.</Typography>
            </Box>
            <FormControl sx={{ maxWidth: 300 }}>
              <InputLabel id="ci-version">Redis version</InputLabel>
              <Select labelId="ci-version" label="Redis version" value={version} onChange={(e) => setVersion(e.target.value)}>
                {api.VERSIONS.map((v) => <MenuItem key={v} value={v}>{api.versionLabel(v)}</MenuItem>)}
              </Select>
            </FormControl>
          </Stack>
        </Section>

        <Section title="Capacity">
          <TextField label="Capacity (GB)" type="number" required value={capacity} onChange={(e) => setCapacity(e.target.value)}
            helperText="1-300 GB. Memory size per node. Approximate node count and estimated monthly cost update as you change this." sx={{ maxWidth: 260 }} />
        </Section>

        <Section title="Region and zone">
          <Stack spacing={2}>
            <FormControl sx={{ maxWidth: 420 }}>
              <InputLabel id="ci-region">Region</InputLabel>
              <Select labelId="ci-region" label="Region" value={region} onChange={(e) => { setRegion(e.target.value); setZone("Any"); setAltZone("Any"); }}>
                {api.REGIONS.map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
              </Select>
            </FormControl>
            <FormControl sx={{ maxWidth: 300 }}>
              <InputLabel id="ci-zone">Zone</InputLabel>
              <Select labelId="ci-zone" label="Zone" value={zone} onChange={(e) => setZone(e.target.value)}>
                <MenuItem value="Any">Any</MenuItem>
                {zones.map((z) => <MenuItem key={z} value={z}>{z}</MenuItem>)}
              </Select>
            </FormControl>
            <FormControl sx={{ maxWidth: 300 }}>
              <InputLabel id="ci-alt-zone">Alternative zone</InputLabel>
              <Select labelId="ci-alt-zone" label="Alternative zone" value={altZone} onChange={(e) => setAltZone(e.target.value)}>
                <MenuItem value="Any">Any</MenuItem>
                {zones.map((z) => <MenuItem key={z} value={z}>{z}</MenuItem>)}
              </Select>
              <Typography variant="caption" color="text.secondary">Zone for the replica; must differ from Zone. Only used for the Standard tier.</Typography>
            </FormControl>
          </Stack>
        </Section>

        <Section title="Configure instance connection">
          <Stack spacing={2}>
            <TextField label="Network" value={network} onChange={(e) => setNetwork(e.target.value)} sx={{ maxWidth: 300 }}
              helperText="VPC network the instance is reachable from (authorizedNetwork)." />
            <Box>
              <Typography variant="body2" sx={{ fontWeight: 500, mb: 1 }}>Connection mode</Typography>
              <RadioGroup row value={connectMode} onChange={(e) => setConnectMode(e.target.value)} aria-label="Connection mode">
                <FormControlLabel value="Direct peering" control={<Radio size="small" />} label="Direct peering" />
                <FormControlLabel value="Private services access" control={<Radio size="small" />} label="Private services access" />
              </RadioGroup>
            </Box>
            <TextField label="Reserved IP range" placeholder="10.0.0.0/29" value={reservedRange} onChange={(e) => setReservedRange(e.target.value)} sx={{ maxWidth: 300 }}
              helperText="CIDR block reserved for the instance; auto-allocated if left blank." />
            <FormControlLabel control={<Checkbox size="small" checked={auth} onChange={(e) => setAuth(e.target.checked)} />} label="Enable AUTH" />
            <FormControlLabel control={<Checkbox size="small" checked={encryption} onChange={(e) => setEncryption(e.target.checked)} />} label="In-transit encryption" />
          </Stack>
        </Section>

        <Section title="Read replicas (Standard tier only)">
          <Stack spacing={2}>
            <Box>
              <Typography variant="body2" sx={{ fontWeight: 500, mb: 1 }}>Read replicas</Typography>
              <RadioGroup row value={readReplicas} onChange={(e) => setReadReplicas(e.target.value)} aria-label="Read replicas">
                <FormControlLabel value="Disabled" control={<Radio size="small" />} label="Disabled" />
                <FormControlLabel value="Enabled" control={<Radio size="small" />} label="Enabled" />
              </RadioGroup>
            </Box>
            <TextField label="Number of replicas" type="number" value={replicaCount} onChange={(e) => setReplicaCount(e.target.value)}
              helperText="1-5" sx={{ maxWidth: 220 }} disabled={tier === "Basic" || readReplicas === "Disabled"} />
          </Stack>
        </Section>

        <Section title="Data persistence">
          <Stack spacing={2}>
            <Box>
              <Typography variant="body2" sx={{ fontWeight: 500, mb: 1 }}>Persistence mode</Typography>
              <RadioGroup row value={persistence} onChange={(e) => setPersistence(e.target.value)} aria-label="Persistence mode">
                <FormControlLabel value="Disabled" control={<Radio size="small" />} label="Disabled" />
                <FormControlLabel value="RDB snapshot" control={<Radio size="small" />} label="RDB snapshot" />
              </RadioGroup>
            </Box>
            <FormControl sx={{ maxWidth: 260 }} disabled={persistence === "Disabled"}>
              <InputLabel id="ci-snapshot">Snapshot period</InputLabel>
              <Select labelId="ci-snapshot" label="Snapshot period" value={snapshotPeriod} onChange={(e) => setSnapshotPeriod(e.target.value)}>
                {api.SNAPSHOT_PERIODS.map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
              </Select>
            </FormControl>
          </Stack>
        </Section>

        <Section title="Redis configuration">
          <Stack spacing={2}>
            <FormControl sx={{ maxWidth: 260 }}>
              <InputLabel id="ci-maxmemory">maxmemory-policy</InputLabel>
              <Select labelId="ci-maxmemory" label="maxmemory-policy" value={maxmemoryPolicy} onChange={(e) => setMaxmemoryPolicy(e.target.value)}>
                {api.MAXMEMORY_POLICIES.map((v) => <MenuItem key={v} value={v}>{v}</MenuItem>)}
              </Select>
            </FormControl>
            <Rows title="Additional parameters" rows={params} setRows={setParams} cols={["Parameter", "Value"]} addLabel="Add a parameter" />
            <Typography variant="caption" color="text.secondary">notify-keyspace-events, activedefrag, timeout, slowlog-*, stream-node-max-* and others the engine supports.</Typography>
          </Stack>
        </Section>

        <Section title="Maintenance window">
          <Stack spacing={2}>
            <FormControl sx={{ maxWidth: 260 }}>
              <InputLabel id="ci-maint-day">Day</InputLabel>
              <Select labelId="ci-maint-day" label="Day" value={day} onChange={(e) => setDay(e.target.value)}>
                <MenuItem value="No preference">No preference</MenuItem>
                {api.DAYS.map((d) => <MenuItem key={d} value={d}>{d.charAt(0) + d.slice(1).toLowerCase()}</MenuItem>)}
              </Select>
            </FormControl>
            <FormControl sx={{ maxWidth: 200 }} disabled={day === "No preference"}>
              <InputLabel id="ci-maint-time">Start time</InputLabel>
              <Select labelId="ci-maint-time" label="Start time" value={startTime} onChange={(e) => setStartTime(e.target.value)}>
                {MAINT_TIMES.map((t) => <MenuItem key={t} value={t}>{t}</MenuItem>)}
              </Select>
            </FormControl>
          </Stack>
        </Section>

        <Section title="Labels">
          <Rows title="Labels" rows={labels.map((l) => ({ Name: l.key, Value: l.value }))} setRows={(rs) => setLabels(rs.map((r) => ({ key: r.Name, value: r.Value })))} cols={["Name", "Value"]} addLabel="Add label" />
        </Section>

        <Divider />
        <Stack direction="row" spacing={1}>
          <Button type="submit" variant="contained" disabled={busy || !id}>{busy ? "Creating…" : "Create instance"}</Button>
          <Button href="#/memorystore">Cancel</Button>
        </Stack>
      </Stack>
    </Box>
  );
}
