/* Instance Overview — basic information and a Monitoring gap (Vyomi has no Redis runtime
 * telemetry), plus the header actions shared with the Instances list row menu. */
import { useState } from "react";
import { Box, Button, Stack, Typography } from "@mui/material";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, KeyValue, Section } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import InstanceNav from "./InstanceNav.jsx";
import { FailoverDialog, UpgradeDialog, ExportDialog, ImportDialog, RescheduleDialog } from "./ActionDialogs.jsx";
import * as api from "./api.js";

export default function InstanceOverview({ params }) {
  const { location: loc, id } = params;
  const notify = useNotify();
  const [del, setDel] = useState(false);
  const [dialog, setDialog] = useState(null);
  const inst = useAsync(() => api.getInstance(loc, id), [loc, id]);
  const i = inst.data;

  const onDone = (msg) => { notify.success(msg); setDialog(null); inst.reload(); };

  return (
    <>
      <InstanceNav location={loc} id={id} active="overview" actions={
        i && <>
          <Button disabled={i.tier !== "STANDARD_HA"} onClick={() => setDialog("failover")}>Failover</Button>
          <Button onClick={() => setDialog("upgrade")}>Upgrade Redis version</Button>
          <Button onClick={() => setDialog("export")}>Export</Button>
          <Button onClick={() => setDialog("import")}>Import</Button>
          <Button onClick={() => setDialog("reschedule")}>Reschedule maintenance</Button>
          <Button startIcon={<DeleteIcon />} onClick={() => setDel(true)}>Delete</Button>
          <Button startIcon={<RefreshIcon />} onClick={() => inst.reload()}>Refresh</Button>
        </>
      } />
      <ErrorAlert error={inst.error} title="Failed to load instance" />
      {i && (
        <Stack spacing={2}>
          <Section title="Basic information">
            <KeyValue items={[
              ["Display name", i.displayName],
              ["Status", api.stateLabel(i.state)],
              ["Tier", api.tierLabel(i.tier)],
              ["Redis version", api.versionLabel(i.redisVersion)],
              ["Capacity", api.capacityLabel(i)],
              ["Region", api.regionLabel(loc)],
              ["Zone", i.currentLocationId],
              ["Alternative zone", i.alternativeLocationId || "None (Basic tier)"],
              ["Created", i.createTime],
              ["Labels", api.labelsText(i)],
            ]} />
          </Section>
          <CapabilityContainer id="gcp.memorystore.monitoring" title="Monitoring" />
        </Stack>
      )}
      <FailoverDialog open={dialog === "failover"} instance={i} onClose={() => setDialog(null)} onDone={onDone} />
      <UpgradeDialog open={dialog === "upgrade"} instance={i} onClose={() => setDialog(null)} onDone={onDone} />
      <ExportDialog open={dialog === "export"} instance={i} onClose={() => setDialog(null)} onDone={onDone} />
      <ImportDialog open={dialog === "import"} instance={i} onClose={() => setDialog(null)} onDone={onDone} />
      <RescheduleDialog open={dialog === "reschedule"} instance={i} onClose={() => setDialog(null)} onDone={onDone} />
      <DeleteDialog open={del} onClose={() => setDel(false)} title="Delete instance?" confirmText={id}
        warning="This can't be undone."
        onConfirm={async () => { await api.deleteInstance(loc, id); notify.success(`Deleted instance "${id}"`); window.location.hash = "/memorystore"; }}>
        <Box><Typography variant="body2">Instance <b>{id}</b> will be permanently deleted.</Typography></Box>
      </DeleteDialog>
    </>
  );
}
