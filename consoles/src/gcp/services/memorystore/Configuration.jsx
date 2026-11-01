/* Configuration — the instance's redisConfigs, persistence and read-replica settings,
 * with a real Edit dialog that patches the instance (updateMask redisConfigs,persistenceConfig). */
import { useState } from "react";
import {
  Alert, Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, FormControl, IconButton, InputLabel,
  MenuItem, Radio, RadioGroup, FormControlLabel, Select, Stack, Table, TableBody, TableCell, TableHead, TableRow,
  TextField, Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, KeyValue, Section } from "../../kit/common.jsx";
import InstanceNav from "./InstanceNav.jsx";
import * as api from "./api.js";

export default function Configuration({ params }) {
  const { location: loc, id } = params;
  const notify = useNotify();
  const [edit, setEdit] = useState(false);
  const inst = useAsync(() => api.getInstance(loc, id), [loc, id]);
  const i = inst.data;

  return (
    <>
      <InstanceNav location={loc} id={id} active="configuration" actions={
        i && <Button onClick={() => setEdit(true)}>Edit configuration</Button>
      } />
      <Typography variant="h2" component="h2" sx={{ fontSize: 20, mb: 1.5 }}>Configuration</Typography>
      <ErrorAlert error={inst.error} title="Failed to load instance" />
      {i && (
        <Stack spacing={2}>
          <Section title="Redis configuration parameters">
            <Table size="small" aria-label="Redis configuration parameters">
              <TableHead><TableRow><TableCell>Parameter</TableCell><TableCell>Value</TableCell></TableRow></TableHead>
              <TableBody>
                {Object.entries(i.redisConfigs || {}).map(([k, v]) => <TableRow key={k}><TableCell>{k}</TableCell><TableCell>{v}</TableCell></TableRow>)}
              </TableBody>
            </Table>
          </Section>
          <Section title="Data persistence">
            <KeyValue items={[
              ["Persistence mode", i.persistenceConfig?.persistenceMode === "RDB" ? "RDB snapshot" : "Disabled"],
              ["Snapshot period", i.persistenceConfig?.rdbSnapshotPeriod ? api.snapshotPeriodLabel(i.persistenceConfig.rdbSnapshotPeriod) : "—"],
              ["Next snapshot time", i.persistenceConfig?.rdbNextSnapshotTime || "—"],
            ]} />
          </Section>
          <Section title="Read replicas">
            <KeyValue items={[
              ["Read replicas", i.readReplicasMode === "READ_REPLICAS_ENABLED" ? "Enabled" : "Disabled"],
              ["Replica count", i.replicaCount ?? 0],
            ]} />
          </Section>
        </Stack>
      )}
      {i && <EditConfigDialog open={edit} instance={i} onClose={() => setEdit(false)}
        onSaved={() => { notify.success(`Updated configuration for "${id}"`); setEdit(false); inst.reload(); }} />}
    </>
  );
}

function EditConfigDialog({ open, instance, onClose, onSaved }) {
  const [policy, setPolicy] = useState(instance.redisConfigs?.["maxmemory-policy"] || "volatile-lru");
  const [rows, setRows] = useState(Object.entries(instance.redisConfigs || {}).filter(([k]) => k !== "maxmemory-policy").map(([Parameter, Value]) => ({ Parameter, Value })));
  const [persistence, setPersistence] = useState(instance.persistenceConfig?.persistenceMode === "RDB" ? "RDB snapshot" : "Disabled");
  const [period, setPeriod] = useState(instance.persistenceConfig?.rdbSnapshotPeriod || "TWENTY_FOUR_HOURS");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const save = async () => {
    setBusy(true); setError(null);
    const redisConfigs = { "maxmemory-policy": policy };
    for (const r of rows) if (r.Parameter) redisConfigs[r.Parameter] = r.Value || "";
    const { location: loc, id } = api.parseName(instance.name);
    try {
      await api.patchInstance(loc, id, {
        redisConfigs,
        persistenceConfig: { persistenceMode: persistence === "Disabled" ? "DISABLED" : "RDB", rdbSnapshotPeriod: persistence === "Disabled" ? undefined : period },
      }, "redisConfigs,persistenceConfig");
      onSaved();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} maxWidth="xs" fullWidth aria-labelledby="ec-title">
      <DialogTitle id="ec-title">Edit configuration</DialogTitle>
      <DialogContent>
        <Stack spacing={2.5} sx={{ pt: 1 }}>
          <FormControl fullWidth>
            <InputLabel id="ec-policy">maxmemory-policy</InputLabel>
            <Select labelId="ec-policy" label="maxmemory-policy" value={policy} onChange={(e) => setPolicy(e.target.value)}>
              {api.MAXMEMORY_POLICIES.map((v) => <MenuItem key={v} value={v}>{v}</MenuItem>)}
            </Select>
          </FormControl>
          <Box>
            <Typography variant="body2" sx={{ fontWeight: 500, mb: 1 }}>Additional parameters</Typography>
            <Stack spacing={1}>
              {rows.map((r, idx) => (
                <Stack key={idx} direction="row" spacing={1} alignItems="center">
                  <TextField size="small" label="Parameter" value={r.Parameter} onChange={(e) => setRows(rows.map((x, j) => j === idx ? { ...x, Parameter: e.target.value } : x))} />
                  <TextField size="small" label="Value" value={r.Value} onChange={(e) => setRows(rows.map((x, j) => j === idx ? { ...x, Value: e.target.value } : x))} />
                  <IconButton aria-label={`Delete row ${idx + 1}`} onClick={() => setRows(rows.filter((_, j) => j !== idx))}><DeleteIcon fontSize="small" /></IconButton>
                </Stack>
              ))}
              <Box><Button size="small" startIcon={<AddIcon />} onClick={() => setRows([...rows, { Parameter: "", Value: "" }])}>Add a parameter</Button></Box>
            </Stack>
          </Box>
          <Box>
            <Typography variant="body2" sx={{ fontWeight: 500, mb: 1 }}>Persistence mode</Typography>
            <RadioGroup row value={persistence} onChange={(e) => setPersistence(e.target.value)} aria-label="Persistence mode">
              <FormControlLabel value="Disabled" control={<Radio size="small" />} label="Disabled" />
              <FormControlLabel value="RDB snapshot" control={<Radio size="small" />} label="RDB snapshot" />
            </RadioGroup>
          </Box>
          <FormControl disabled={persistence === "Disabled"}>
            <InputLabel id="ec-period">Snapshot period</InputLabel>
            <Select labelId="ec-period" label="Snapshot period" value={period} onChange={(e) => setPeriod(e.target.value)}>
              {api.SNAPSHOT_PERIODS.map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
            </Select>
          </FormControl>
          {error && <Alert severity="error"><b>{error.code || "Error"}</b>: {error.message}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" onClick={save} disabled={busy}>{busy ? "Saving…" : "Save"}</Button>
      </DialogActions>
    </Dialog>
  );
}
