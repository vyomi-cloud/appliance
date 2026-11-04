/* Maintenance — the weekly maintenance window policy and any scheduled maintenance,
 * with real Edit / Reschedule actions (maintenancePolicy patch, rescheduleMaintenance). */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogContent, DialogTitle, FormControl, InputLabel, MenuItem, Select, Stack, Typography } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, KeyValue, Section } from "../../kit/common.jsx";
import InstanceNav from "./InstanceNav.jsx";
import { RescheduleDialog } from "./ActionDialogs.jsx";
import * as api from "./api.js";

const TIMES = ["00:00", "04:00", "08:00", "12:00", "16:00", "20:00"];

export default function Maintenance({ params }) {
  const { location: loc, id } = params;
  const notify = useNotify();
  const [edit, setEdit] = useState(false);
  const [reschedule, setReschedule] = useState(false);
  const inst = useAsync(() => api.getInstance(loc, id), [loc, id]);
  const i = inst.data;
  const sched = i?.maintenanceSchedule;

  return (
    <>
      <InstanceNav location={loc} id={id} active="maintenance" actions={
        i && <Button onClick={() => setEdit(true)}>Edit maintenance policy</Button>
      } />
      <Typography variant="h2" component="h2" sx={{ fontSize: 20, mb: 1.5 }}>Maintenance</Typography>
      <ErrorAlert error={inst.error} title="Failed to load instance" />
      {i && (
        <Stack spacing={2}>
          <Section title="Maintenance window">
            <KeyValue items={[["Preferred window", api.maintenanceWindowLabel(i)]]} />
          </Section>
          <Section title="Scheduled maintenance" actions={<Button size="small" onClick={() => setReschedule(true)}>Reschedule</Button>}>
            <KeyValue items={[
              ["Scheduled start", sched?.startTime || "No maintenance scheduled"],
              ["Can reschedule", sched ? (sched.canReschedule ? "Yes" : "No") : "—"],
            ]} />
          </Section>
        </Stack>
      )}
      {i && <EditMaintenanceDialog open={edit} instance={i} onClose={() => setEdit(false)}
        onSaved={() => { notify.success(`Updated maintenance window for "${id}"`); setEdit(false); inst.reload(); }} />}
      <RescheduleDialog open={reschedule} instance={i} onClose={() => setReschedule(false)}
        onDone={(msg) => { notify.success(msg); setReschedule(false); inst.reload(); }} />
    </>
  );
}

function EditMaintenanceDialog({ open, instance, onClose, onSaved }) {
  const current = (instance.maintenancePolicy?.weeklyMaintenanceWindow || [])[0];
  const [day, setDay] = useState(current?.day || "No preference");
  const [time, setTime] = useState(current ? `${String(current.startTime.hours).padStart(2, "0")}:${String(current.startTime.minutes || 0).padStart(2, "0")}` : "00:00");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const save = async () => {
    setBusy(true); setError(null);
    const { location: loc, id } = api.parseName(instance.name);
    try {
      const policy = day === "No preference" ? {} : (() => {
        const [h, m] = time.split(":").map(Number);
        return { weeklyMaintenanceWindow: [{ day, startTime: { hours: h, minutes: m } }] };
      })();
      await api.patchInstance(loc, id, { maintenancePolicy: policy }, "maintenancePolicy");
      onSaved();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} maxWidth="xs" fullWidth aria-labelledby="em-title">
      <DialogTitle id="em-title">Edit maintenance policy</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <FormControl fullWidth>
            <InputLabel id="em-day">Day</InputLabel>
            <Select labelId="em-day" label="Day" value={day} onChange={(e) => setDay(e.target.value)}>
              <MenuItem value="No preference">No preference</MenuItem>
              {api.DAYS.map((d) => <MenuItem key={d} value={d}>{d.charAt(0) + d.slice(1).toLowerCase()}</MenuItem>)}
            </Select>
          </FormControl>
          <FormControl disabled={day === "No preference"}>
            <InputLabel id="em-time">Start time</InputLabel>
            <Select labelId="em-time" label="Start time" value={time} onChange={(e) => setTime(e.target.value)}>
              {TIMES.map((t) => <MenuItem key={t} value={t}>{t}</MenuItem>)}
            </Select>
          </FormControl>
          {error && <Typography color="error" variant="body2"><b>{error.code || "Error"}</b>: {error.message}</Typography>}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" onClick={save} disabled={busy}>{busy ? "Saving…" : "Save"}</Button>
      </DialogActions>
    </Dialog>
  );
}
