/* Shared action dialogs for an instance — failover, upgrade, export, import, reschedule
 * maintenance. Used from both the Instances list (row menu) and the instance Overview page
 * (header actions), so the native call and its validation live in one place. */
import { useState } from "react";
import { Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, FormControl, FormControlLabel, InputLabel, MenuItem, Radio, RadioGroup, Select, Stack, TextField, Typography } from "@mui/material";
import * as api from "./api.js";

function ActionDialog({ open, onClose, title, onConfirm, confirmLabel = "Confirm", disabled, children }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const go = async () => {
    setBusy(true); setError(null);
    try { await onConfirm(); onClose(); } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} maxWidth="xs" fullWidth aria-labelledby="ms-action-title">
      <DialogTitle id="ms-action-title">{title}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {children}
          {error && <Alert severity="error"><b>{error.code || "Error"}</b>: {error.message}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" onClick={go} disabled={busy || disabled}>{busy ? "Working…" : confirmLabel}</Button>
      </DialogActions>
    </Dialog>
  );
}

export function FailoverDialog({ open, instance, onClose, onDone }) {
  const [mode, setMode] = useState("LIMITED_DATA_LOSS");
  if (!instance) return null;
  const { location, id } = api.parseName(instance.name);
  return (
    <ActionDialog open={open} onClose={onClose} title={`Initiate failover for "${id}"?`} confirmLabel="Initiate failover"
      onConfirm={async () => { await api.failoverInstance(location, id, { dataProtectionMode: mode }); onDone(`Failover started for "${id}"`); }}>
      <Typography variant="body2">The instance fails over to its alternative zone. This may briefly interrupt connections.</Typography>
      <RadioGroup value={mode} onChange={(e) => setMode(e.target.value)} aria-label="Data protection mode">
        <FormControlLabel value="LIMITED_DATA_LOSS" control={<Radio size="small" />} label="Limited data loss" />
        <FormControlLabel value="FORCE_DATA_LOSS" control={<Radio size="small" />} label="Force data loss" />
      </RadioGroup>
    </ActionDialog>
  );
}

export function UpgradeDialog({ open, instance, onClose, onDone }) {
  const current = instance?.redisVersion;
  const options = api.VERSIONS.filter((v) => api.VERSIONS.indexOf(v) < api.VERSIONS.indexOf(current));
  const [version, setVersion] = useState(options[0] || "");
  if (!instance) return null;
  const { location, id } = api.parseName(instance.name);
  return (
    <ActionDialog open={open} onClose={onClose} title={`Upgrade Redis version for "${id}"`} confirmLabel="Upgrade" disabled={!version}
      onConfirm={async () => { await api.upgradeInstance(location, id, version); onDone(`Upgrading "${id}" to ${api.versionLabel(version)}`); }}>
      <FormControl fullWidth disabled={!options.length}>
        <InputLabel id="ms-upgrade-version">Target version</InputLabel>
        <Select labelId="ms-upgrade-version" label="Target version" value={version} onChange={(e) => setVersion(e.target.value)}>
          {options.map((v) => <MenuItem key={v} value={v}>{api.versionLabel(v)}</MenuItem>)}
        </Select>
      </FormControl>
      {!options.length && <Alert severity="info">"{id}" is already on the newest supported version.</Alert>}
    </ActionDialog>
  );
}

export function ExportDialog({ open, instance, onClose, onDone }) {
  const [uri, setUri] = useState("");
  if (!instance) return null;
  const { location, id } = api.parseName(instance.name);
  return (
    <ActionDialog open={open} onClose={onClose} title={`Export "${id}"`} confirmLabel="Export" disabled={!uri}
      onConfirm={async () => { await api.exportInstance(location, id, uri); onDone(`Exporting "${id}" to ${uri}`); }}>
      <TextField autoFocus fullWidth required label="Destination" placeholder="gs://bucket/dump.rdb" value={uri}
        onChange={(e) => setUri(e.target.value.trim())} helperText="A Cloud Storage object URI to export the RDB snapshot to." />
    </ActionDialog>
  );
}

export function ImportDialog({ open, instance, onClose, onDone }) {
  const [uri, setUri] = useState("");
  if (!instance) return null;
  const { location, id } = api.parseName(instance.name);
  return (
    <ActionDialog open={open} onClose={onClose} title={`Import into "${id}"`} confirmLabel="Import" disabled={!uri}
      onConfirm={async () => { await api.importInstance(location, id, uri); onDone(`Importing into "${id}" from ${uri}`); }}>
      <TextField autoFocus fullWidth required label="Source" placeholder="gs://bucket/dump.rdb" value={uri}
        onChange={(e) => setUri(e.target.value.trim())} helperText="A Cloud Storage object URI to import an RDB snapshot from." />
      <Alert severity="warning">This overwrites the data currently in the instance.</Alert>
    </ActionDialog>
  );
}

export function RescheduleDialog({ open, instance, onClose, onDone }) {
  const [type, setType] = useState("NEXT_AVAILABLE_WINDOW");
  const [time, setTime] = useState("");
  if (!instance) return null;
  const { location, id } = api.parseName(instance.name);
  return (
    <ActionDialog open={open} onClose={onClose} title={`Reschedule maintenance for "${id}"`} confirmLabel="Reschedule"
      disabled={type === "SPECIFIC_TIME" && !time}
      onConfirm={async () => {
        const body = { rescheduleType: type };
        if (type === "SPECIFIC_TIME") body.scheduleTime = new Date(time).toISOString();
        await api.rescheduleMaintenance(location, id, body);
        onDone(`Rescheduled maintenance for "${id}"`);
      }}>
      <RadioGroup value={type} onChange={(e) => setType(e.target.value)} aria-label="Reschedule type">
        <FormControlLabel value="IMMEDIATE" control={<Radio size="small" />} label="Immediate" />
        <FormControlLabel value="NEXT_AVAILABLE_WINDOW" control={<Radio size="small" />} label="Next available window" />
        <FormControlLabel value="SPECIFIC_TIME" control={<Radio size="small" />} label="Specific time" />
      </RadioGroup>
      {type === "SPECIFIC_TIME" && <TextField type="datetime-local" label="Scheduled time" value={time} onChange={(e) => setTime(e.target.value)} InputLabelProps={{ shrink: true }} />}
    </ActionDialog>
  );
}
