/* IAM enforcement (Off / Audit / Enforce) + decision audit list, Material-native.
 *   <EnforcementPanel service resource />  compact panel for resource Permissions tabs and the IAM page
 *   default export                          IAM & Admin > Enforcement page (global, space, per-service, per-resource, Audit tab) */
import { useEffect, useState } from "react";
import { Alert, Autocomplete, Box, Button, Chip, MenuItem, Select, Stack, Tab, Table, TableBody, TableCell, TableHead, TableRow, Tabs, TextField, ToggleButton, ToggleButtonGroup, Typography } from "@mui/material";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import { MODES, MODE_LABEL, MODE_HELP, SOURCE_LABEL, SERVICES, auditLabel, filterAudit } from "../../../common/iamEnforce.js";
import { useAudit, useEnforcement } from "../../../common/iamEnforceHooks.js";
import { PageHeader, Section } from "../../kit/common.jsx";
import { usePickerData } from "./usePickerData.js";
import { searchAssets } from "./api.js";
import { getProject } from "../../project.js";

const CLOUD = "gcp";
const COLOR = { off: "default", audit: "warning", enforce: "success" };
export const ModeChip = ({ mode }) => <Chip size="small" color={COLOR[mode] || "default"} variant={mode === "off" ? "outlined" : "filled"} label={MODE_LABEL[mode] || mode} />;

function ModeToggle({ value, onChange, disabled, inherit, label }) {
  return (
    <ToggleButtonGroup exclusive size="small" value={value} disabled={disabled} aria-label={label} onChange={(_, v) => v && onChange(v)}>
      {inherit && <ToggleButton value="inherit">Inherit</ToggleButton>}
      {MODES.map((m) => <ToggleButton key={m} value={m}>{MODE_LABEL[m]}</ToggleButton>)}
    </ToggleButtonGroup>
  );
}

export function EnforcementPanel({ service, resource, title = "IAM enforcement" }) {
  const e = useEnforcement(CLOUD);
  if (e.loading) return <Section title={title}><Typography variant="body2">Loading…</Typography></Section>;
  if (e.error && !e.settings) return <Section title={title}><Alert severity="error">Could not load enforcement settings: {e.error.message}</Alert></Section>;
  const eff = e.resolve(service, resource);
  return (
    <Section title={title} description="Evaluate this resource's allow and deny policies on every request. Off by default." >
      <div data-testid="iam-enforce-panel">
        <Stack spacing={1.5}>
          <Stack direction="row" spacing={1} alignItems="center"><Typography variant="body2" color="text.secondary">Effective mode</Typography><ModeChip mode={eff.mode} />
            <Typography variant="body2" color="text.secondary">set by {SOURCE_LABEL[eff.source]}</Typography></Stack>
          <Typography variant="caption" color="text.secondary">{MODE_HELP[eff.mode]}</Typography>
          <Box><Typography variant="body2" sx={{ mb: 0.5 }}>Resource override</Typography>
            <ModeToggle label="Resource enforcement mode" value={e.settings.resources[resource] || "inherit"} inherit disabled={e.saving} onChange={(m) => e.set("resource", resource, m)} /></Box>
          {e.error && <Alert severity="error">{e.error.message}</Alert>}
        </Stack>
      </div>
    </Section>
  );
}

function SettingsTab() {
  const e = useEnforcement(CLOUD);
  const [res, setRes] = useState("");
  const data = usePickerData();
  const [resOptions, setResOptions] = useState([`//cloudresourcemanager.googleapis.com/projects/${getProject()}`]);
  useEffect(() => { searchAssets("", { assetTypes: "storage.googleapis.com/Bucket" }).then((r) => setResOptions((o) => [...new Set([...o, ...r.map((x) => x.name).filter(Boolean)])]), () => {}); }, []);
  if (e.loading) return <Typography variant="body2">Loading…</Typography>;
  if (e.error && !e.settings) return <Alert severity="error">Could not load enforcement settings: {e.error.message}</Alert>;
  const s = e.settings;
  const svcs = [...new Set([...SERVICES[CLOUD], ...Object.keys(s.services), ...data.services])];
  return (
    <Stack spacing={2}>
      {e.error && <Alert severity="error">{e.error.message}</Alert>}
      <Section title="Default modes" description="Most specific wins: resource, then service, then space, then global.">
        <Stack spacing={2}>
          <Box><Typography variant="body2" sx={{ mb: 0.5 }}>Global</Typography><ModeToggle label="Global enforcement mode" value={s.global} disabled={e.saving} onChange={(m) => e.set("global", null, m)} /></Box>
          <Box><Typography variant="body2" sx={{ mb: 0.5 }}>This space</Typography><ModeToggle label="Space enforcement mode" value={s.space} disabled={e.saving} onChange={(m) => e.set("space", null, m)} /></Box>
        </Stack>
      </Section>
      <Section title="Per-service">
        <Table size="small"><TableHead><TableRow><TableCell>Service</TableCell><TableCell>Effective mode</TableCell><TableCell>Override</TableCell></TableRow></TableHead>
          <TableBody>{svcs.map((k) => { const x = e.resolve(k); return (
            <TableRow key={k}><TableCell>{k}</TableCell>
              <TableCell><Stack direction="row" spacing={1} alignItems="center"><ModeChip mode={x.mode} /><Typography variant="caption" color="text.secondary">{SOURCE_LABEL[x.source]}</Typography></Stack></TableCell>
              <TableCell><ModeToggle label={`${k} enforcement mode`} value={s.services[k] || "inherit"} inherit disabled={e.saving} onChange={(m) => e.set("service", k, m)} /></TableCell></TableRow>); })}</TableBody></Table>
      </Section>
      <Section title="Per-resource overrides" actions={<Stack direction="row" spacing={1}>
        <Autocomplete freeSolo size="small" sx={{ width: 380 }} options={resOptions} inputValue={res} onInputChange={(_, v) => setRes(v)} renderInput={(p) => <TextField {...p} placeholder="//storage.googleapis.com/projects/_/buckets/my-bucket" inputProps={{ ...p.inputProps, "aria-label": "Resource name" }} />} />
        <Button variant="outlined" disabled={!res} onClick={() => { e.set("resource", res, "audit"); setRes(""); }}>Add override</Button></Stack>}>
        {Object.keys(s.resources).length === 0 ? <Typography variant="body2" color="text.secondary">No resource overrides. Resources follow their service, space or global mode.</Typography> :
          <Table size="small"><TableHead><TableRow><TableCell>Resource</TableCell><TableCell>Mode</TableCell></TableRow></TableHead>
            <TableBody>{Object.entries(s.resources).map(([k, m]) => (
              <TableRow key={k}><TableCell sx={{ fontFamily: "monospace", wordBreak: "break-all" }}>{k}</TableCell>
                <TableCell><ModeToggle label={`${k} enforcement mode`} value={m} inherit disabled={e.saving} onChange={(v) => e.set("resource", k, v)} /></TableCell></TableRow>))}</TableBody></Table>}
      </Section>
    </Stack>
  );
}

export function AuditList({ limit = 100 }) {
  const a = useAudit(CLOUD, limit);
  const [mode, setMode] = useState("all");
  const [dec, setDec] = useState("all");
  const rows = filterAudit(a.data || [], { mode, decision: dec });
  return (
    <Section title={`Audit (${rows.length})`} description={`Last ${limit} IAM decisions. Read-only.`} actions={<>
      <Select size="small" value={mode} onChange={(ev) => setMode(ev.target.value)} inputProps={{ "aria-label": "Filter by mode" }}>
        <MenuItem value="all">All modes</MenuItem>{MODES.map((m) => <MenuItem key={m} value={m}>{MODE_LABEL[m]}</MenuItem>)}</Select>
      <Select size="small" value={dec} onChange={(ev) => setDec(ev.target.value)} inputProps={{ "aria-label": "Filter by decision" }}>
        <MenuItem value="all">All decisions</MenuItem><MenuItem value="allow">Allowed</MenuItem><MenuItem value="deny">Denied or would deny</MenuItem><MenuItem value="would_deny">Would deny (audit)</MenuItem></Select>
      <Button startIcon={<RefreshIcon />} onClick={a.reload}>Refresh</Button></>}>
      {rows.length === 0 ? <Typography variant="body2" color="text.secondary">No decisions recorded. Decisions appear here once a mode other than Off is set.</Typography> :
        <Table size="small"><TableHead><TableRow>{["Time", "Principal", "Permission", "Resource", "Mode", "Decision", "Reason"].map((h) => <TableCell key={h}>{h}</TableCell>)}</TableRow></TableHead>
          <TableBody>{rows.map((r, i) => (
            <TableRow key={i}><TableCell>{r.ts}</TableCell><TableCell>{r.principal}</TableCell><TableCell>{r.action}</TableCell><TableCell sx={{ wordBreak: "break-all" }}>{r.resource}</TableCell>
              <TableCell>{MODE_LABEL[r.mode] || r.mode}</TableCell>
              <TableCell><Chip size="small" color={r.allowed ? "success" : r.wouldDeny ? "warning" : "error"} label={auditLabel(r)} /></TableCell><TableCell>{r.reason}</TableCell></TableRow>))}</TableBody></Table>}
    </Section>
  );
}

export default function Enforcement() {
  const [tab, setTab] = useState("settings");
  return (
    <>
      <PageHeader title="Enforcement" />
      <Tabs value={tab} onChange={(_, t) => setTab(t)} sx={{ borderBottom: 1, borderColor: "divider", mb: 2.5 }} aria-label="Enforcement tabs">
        <Tab value="settings" label="Settings" /><Tab value="audit" label="Audit" />
      </Tabs>
      {tab === "settings" ? <SettingsTab /> : <AuditList />}
    </>
  );
}
