/* Instance Overview — connection info, configuration summary, recent operations. */
import { useState } from "react";
import { Box, Button, Stack, Typography } from "@mui/material";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import RestartAltIcon from "@mui/icons-material/esm/RestartAlt.js";
import StopIcon from "@mui/icons-material/esm/Stop.js";
import PlayArrowIcon from "@mui/icons-material/esm/PlayArrow.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, KeyValue, Section } from "../../kit/common.jsx";
import InstanceNav from "./InstanceNav.jsx";
import * as api from "./api.js";

const TIER_SHAPE = {
  "db-f1-micro": ["Shared", "0.6 GB"], "db-custom-1-3840": ["1", "3.75 GB"], "db-custom-2-4096": ["2", "4 GB"],
  "db-custom-4-15360": ["4", "15 GB"], "db-custom-4-26624": ["4", "26 GB"],
};

export default function InstanceOverview({ params }) {
  const name = params.name;
  const notify = useNotify();
  const [del, setDel] = useState(false);
  const inst = useAsync(() => api.getInstance(name), [name]);
  const ops = useAsync(() => api.listOperations(name), [name]);
  const i = inst.data;
  const shape = TIER_SHAPE[i?.settings?.tier] || ["—", "—"];

  const act = async (fn, msg) => { try { await fn(name); notify.success(msg); inst.reload(); } catch (e) { notify.error(e); } };

  return (
    <>
      <InstanceNav name={name} active="overview" actions={
        i && <>
          <Button startIcon={<RestartAltIcon />} onClick={() => act(api.restartInstance, `Restarting "${name}"`)}>Restart</Button>
          {i.state === "STOPPED"
            ? <Button startIcon={<PlayArrowIcon />} onClick={() => act(api.startInstance, `Starting "${name}"`)}>Start</Button>
            : <Button startIcon={<StopIcon />} onClick={() => act(api.stopInstance, `Stopping "${name}"`)}>Stop</Button>}
          <Button startIcon={<DeleteIcon />} onClick={() => setDel(true)}>Delete</Button>
          <Button startIcon={<RefreshIcon />} onClick={() => { inst.reload(); ops.reload(); }}>Refresh</Button>
        </>
      } />
      <ErrorAlert error={inst.error} title="Failed to load instance" />
      {i && (
        <Stack spacing={2}>
          <Section title="Connect to this instance">
            <KeyValue items={[
              ["Public IP address", api.publicIp(i)],
              ["Private IP address", api.privateIp(i)],
              ["Connection name", i.connectionName],
              ["Default TCP database port", i.databaseVersion?.startsWith("MYSQL") ? "3306" : i.databaseVersion?.startsWith("SQLSERVER") ? "1433" : "5432"],
            ]} />
          </Section>
          <Section title="Configuration">
            <KeyValue items={[
              ["vCPUs", shape[0]], ["Memory", shape[1]], ["Data cache", "Disabled"],
              ["Storage", api.diskGb(i)], ["Network throughput (MB/s)", "250"], ["Disk throughput (MB/s)", "272"], ["IOPS", "7,500"],
              ["Connections", "4,000"], ["Backup", i.settings?.backupConfiguration?.enabled ? "Enabled" : "Disabled"],
              ["Availability", i.settings?.availabilityType === "REGIONAL" ? "Multiple zones" : "Single zone"],
              ["Point-in-time recovery", i.settings?.backupConfiguration?.pointInTimeRecoveryEnabled ? "Enabled" : "Disabled"],
              ["Database version", api.versionLabel(i.databaseVersion)], ["Edition", api.editionLabel()],
              ["Labels", Object.entries(i.settings?.userLabels || {}).map(([k, v]) => `${k}: ${v}`).join(", ") || "None"],
            ]} />
          </Section>
          <Section title="Operations and logs">
            {ops.data?.length
              ? <Stack spacing={0.5}>{ops.data.slice(0, 5).map((o) => <Typography key={o.name} variant="body2">{o.operationType} — {o.status}</Typography>)}</Stack>
              : <Typography variant="body2" color="text.secondary">No operations yet.</Typography>}
          </Section>
        </Stack>
      )}
      <DeleteDialog open={del} onClose={() => setDel(false)} title="Delete instance?" confirmText={name}
        warning="All databases, users and backups on this instance are deleted as well. This can't be undone."
        onConfirm={async () => { await api.deleteInstance(name); notify.success(`Deleted instance "${name}"`); location.hash = "/sql"; }}>
        <Box><Typography variant="body2">Instance <b>{name}</b> will be permanently deleted.</Typography></Box>
      </DeleteDialog>
    </>
  );
}
