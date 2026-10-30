/* Disaster recovery — Backups + Backup schedules (a schedule's first tick fires an
 * immediate backup; there's no background scheduler in Vyomi) and Point-in-time recovery
 * (a real toggle on the database resource). */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, Stack, Switch, Tab, Tabs, TextField, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { fmtDate, PageHeader } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

const TABS = [["backups", "Backups"], ["schedules", "Backup schedules"], ["pitr", "Point-in-time recovery"]];

export default function DisasterRecovery({ params, query }) {
  const db = params.name;
  const tab = TABS.some(([t]) => t === query.tab) ? query.tab : "backups";
  const database = useAsync(() => api.getDatabase(db), [db]);
  return (
    <>
      <PageHeader title="Disaster recovery" actions={tab === "schedules" && <CreateScheduleButton db={db} onCreated={database.reload} />} />
      <Tabs value={tab} onChange={(_, t) => { location.hash = `#/firestore/databases/${encodeURIComponent(db)}/disaster-recovery${t === "backups" ? "" : "?tab=" + t}`; }}
        sx={{ borderBottom: 1, borderColor: "divider", mb: 2.5 }} aria-label="Disaster recovery tabs">
        {TABS.map(([id, label]) => <Tab key={id} value={id} label={label} />)}
      </Tabs>
      {tab === "backups" && <Backups db={db} location={database.data?.locationId} />}
      {tab === "schedules" && <Schedules db={db} />}
      {tab === "pitr" && <Pitr db={db} database={database} />}
    </>
  );
}

function CreateScheduleButton({ db, onCreated }) {
  const notify = useNotify();
  const [open, setOpen] = useState(false);
  const [recurrence, setRecurrence] = useState("daily");
  const [days, setDays] = useState("7");
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try {
      await api.createBackupSchedule(db, {
        retention: `${Number(days) * 86400}s`,
        ...(recurrence === "weekly" ? { weeklyRecurrence: { day: "MONDAY" } } : { dailyRecurrence: {} }),
      });
      notify.success("Created backup schedule");
      setOpen(false); onCreated();
    } catch (e) { notify.error(e); }
    finally { setBusy(false); }
  };
  return (
    <>
      <Button startIcon={<AddIcon />} onClick={() => setOpen(true)}>Create backup schedule</Button>
      <Dialog open={open} onClose={busy ? undefined : () => setOpen(false)} maxWidth="xs" fullWidth aria-labelledby="bs-title">
        <DialogTitle id="bs-title">Create a backup schedule</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            <FormControlLabel control={<Switch checked={recurrence === "weekly"} onChange={(e) => setRecurrence(e.target.checked ? "weekly" : "daily")} />} label={recurrence === "weekly" ? "Weekly" : "Daily"} />
            <TextField label="Retention (days)" type="number" value={days} onChange={(e) => setDays(e.target.value)} />
          </Stack>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={() => setOpen(false)} disabled={busy}>Cancel</Button>
          <Button variant="contained" disabled={busy} onClick={go}>{busy ? "Creating…" : "Create"}</Button>
        </DialogActions>
      </Dialog>
    </>
  );
}

function Backups({ db, location }) {
  const { data = [], loading, error, reload } = useAsync(() => (location ? api.listBackups(location) : Promise.resolve([])), [db, location]);
  return (
    <CapabilityContainer id="gcp.firestore.backups" title="Backups">
      <ResourceTable
        resourceName="backups"
        items={data}
        rowKey={(b) => b.name}
        loading={loading}
        error={error}
        onRetry={reload}
        columns={[
          { id: "name", header: "Backup", cell: (b) => b.name.split("/").pop() },
          { id: "database", header: "Database", cell: (b) => b.database.split("/").pop() },
          { id: "snapshot", header: "Snapshot time", sortField: "snapshotTime", cell: (b) => fmtDate(b.snapshotTime) },
          { id: "state", header: "State", cell: (b) => b.state },
        ]}
        empty={<Typography variant="body2" color="text.secondary">No backups yet. Create a backup schedule to take one.</Typography>}
      />
    </CapabilityContainer>
  );
}

function Schedules({ db }) {
  const notify = useNotify();
  const { data = [], loading, error, reload } = useAsync(() => api.listBackupSchedules(db), [db]);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  return (
    <CapabilityContainer id="gcp.firestore.backups" title="Backup schedules">
      <Stack direction="row" spacing={1} sx={{ mb: 1.5 }}>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
      </Stack>
      <ResourceTable
        resourceName="backup schedules"
        items={data}
        rowKey={(s) => s.name}
        loading={loading}
        error={error}
        onRetry={reload}
        selectable
        selected={sel}
        onSelectedChange={setSel}
        columns={[
          { id: "id", header: "Schedule ID", cell: (s) => s.name.split("/").pop() },
          { id: "recurrence", header: "Recurrence", cell: (s) => s.weeklyRecurrence ? "Weekly" : "Daily" },
          { id: "retention", header: "Retention", cell: (s) => `${Math.round(parseInt(s.retention) / 86400)} days` },
          { id: "created", header: "Created", sortField: "createTime", cell: (s) => fmtDate(s.createTime) },
        ]}
        empty={<Typography variant="body2" color="text.secondary">No backup schedules yet.</Typography>}
      />
      <DeleteDialog open={del} onClose={() => setDel(false)} title={`Delete ${sel.length} schedule${sel.length === 1 ? "" : "s"}?`} confirmText="DELETE"
        onConfirm={async () => {
          for (const name of sel) await api.deleteBackupSchedule(db, name.split("/").pop());
          notify.success(`Deleted ${sel.length} schedule${sel.length === 1 ? "" : "s"}`);
          setSel([]); reload();
        }}>
        <Typography variant="body2">{sel.map((n) => n.split("/").pop()).join(", ")}</Typography>
      </DeleteDialog>
    </CapabilityContainer>
  );
}

function Pitr({ db, database }) {
  const notify = useNotify();
  const [busy, setBusy] = useState(false);
  const enabled = database.data?.pointInTimeRecoveryEnablement === "POINT_IN_TIME_RECOVERY_ENABLED";
  return (
    <CapabilityContainer id="gcp.firestore.point-in-time-recovery" title="Point-in-time recovery">
      <Typography variant="body2" sx={{ mb: 1.5 }}>Recover data from any point in time within the past 7 days.</Typography>
      <FormControlLabel
        control={<Switch checked={enabled} disabled={busy || !database.data} onChange={async (e) => {
          setBusy(true);
          try {
            await api.patchDatabase(db, { pointInTimeRecoveryEnablement: e.target.checked ? "POINT_IN_TIME_RECOVERY_ENABLED" : "POINT_IN_TIME_RECOVERY_DISABLED" });
            notify.success(e.target.checked ? "Point-in-time recovery enabled" : "Point-in-time recovery disabled");
            database.reload();
          } catch (err) { notify.error(err); }
          finally { setBusy(false); }
        }} />}
        label={enabled ? "Enabled" : "Disabled"}
      />
    </CapabilityContainer>
  );
}
