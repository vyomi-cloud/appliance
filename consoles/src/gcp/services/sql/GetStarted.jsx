/* "Get Started" — shown when the project has no instances yet (nav: Get Started, Backups).
 * The quick-create form posts straight to instances.insert, same as "Create instance". */
import { useState } from "react";
import { Box, Button, FormControl, InputLabel, MenuItem, Radio, RadioGroup, FormControlLabel, Select, Stack, TextField, Typography } from "@mui/material";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, Section } from "../../kit/common.jsx";
import * as api from "./api.js";

const ENGINE_VERSION = { MySQL: "MYSQL_8_4", PostgreSQL: "POSTGRES_17", "SQL Server": "SQLSERVER_2022_STANDARD" };
const genPassword = () => Array.from({ length: 16 }, () => "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"[Math.floor(Math.random() * 56)]).join("");

export default function GetStarted() {
  const notify = useNotify();
  const [engine, setEngine] = useState("MySQL");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [region, setRegion] = useState("us-east1");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const create = async (preset) => {
    setBusy(true); setError(null);
    try {
      const id = name || `${preset.toLowerCase()}-${Math.random().toString(36).slice(2, 7)}`;
      await api.insertInstance({   // native API returns an Operation — route by the requested ID
        name: id,
        databaseVersion: ENGINE_VERSION[engine], region,
        settings: { tier: "db-f1-micro", userLabels: { preset: preset.toLowerCase() } },
      });
      notify.success(`Created instance "${id}"`);
      location.hash = `#/sql/instances/${encodeURIComponent(id)}/overview`;
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <Box sx={{ pt: 2, maxWidth: 880 }}>
      <Typography variant="h1" component="h1" sx={{ mb: 2 }}>Get Started</Typography>
      <ErrorAlert error={error} title="Failed to create instance" />
      <Stack spacing={2.5}>
        <Section title="Experience Cloud SQL at no cost for 30 days">
          <Stack spacing={2}>
            <Box>
              <Typography variant="body2" sx={{ fontWeight: 500, mb: 1 }}>Database Engine</Typography>
              <RadioGroup row value={engine} onChange={(e) => setEngine(e.target.value)} aria-label="Database Engine">
                {["MySQL", "PostgreSQL", "SQL Server"].map((v) => <FormControlLabel key={v} value={v} control={<Radio size="small" />} label={v} />)}
              </RadioGroup>
            </Box>
            <TextField label="Instance ID" required value={name} onChange={(e) => setName(e.target.value.trim())} sx={{ maxWidth: 420 }}
              helperText="Use lowercase letters, numbers, and hyphens. Start with a letter." inputProps={{ "aria-label": "Instance ID" }} />
            <Stack direction="row" spacing={1} alignItems="flex-start">
              <TextField label="Password" required value={password} onChange={(e) => setPassword(e.target.value)} sx={{ maxWidth: 420 }}
                helperText="Set a password for the root user." inputProps={{ "aria-label": "Password" }} />
              <Button sx={{ mt: 1 }} onClick={() => setPassword(genPassword())}>Generate</Button>
            </Stack>
            <FormControl sx={{ maxWidth: 420 }}>
              <InputLabel id="gs-region">Region</InputLabel>
              <Select labelId="gs-region" label="Region" value={region} onChange={(e) => setRegion(e.target.value)}>
                {api.REGIONS.map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
              </Select>
            </FormControl>
          </Stack>
          <Box sx={{ mt: 2 }}>
            <Button variant="contained" disabled={busy || !name} onClick={() => create("Sandbox")}>{busy ? "Creating…" : "Create free instance"}</Button>
          </Box>
        </Section>
        <Section title="Sandbox"><Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>A low-cost instance for exploring Cloud SQL.</Typography><Button variant="outlined" disabled={busy || !name} onClick={() => create("Sandbox")}>Create Sandbox instance</Button></Section>
        <Section title="Development"><Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>A right-sized instance for development workloads.</Typography><Button variant="outlined" disabled={busy || !name} onClick={() => create("Development")}>Create Development instance</Button></Section>
        <Section title="Production"><Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>A highly available instance for production workloads.</Typography><Button variant="outlined" disabled={busy || !name} onClick={() => create("Production")}>Create Production instance</Button></Section>
        <Section title="Looking for other ways to get started?">
          <Button href="#/sql/create">Create custom instance</Button>
        </Section>
      </Stack>
    </Box>
  );
}
