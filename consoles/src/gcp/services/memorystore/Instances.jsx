/* Instances list — columns, row actions (Failover / Upgrade / Export / Import / Reschedule
 * maintenance / Delete) and the create flow entry point, as in the Memorystore console. */
import { useState } from "react";
import { Box, Button, Chip, IconButton, Menu, MenuItem, Stack, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import MoreVertIcon from "@mui/icons-material/esm/MoreVert.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { PageHeader } from "../../kit/common.jsx";
import { Link } from "../../link.jsx";
import { useProject } from "../../project.js";
import { instanceHref } from "./InstanceNav.jsx";
import { FailoverDialog, UpgradeDialog, ExportDialog, ImportDialog, RescheduleDialog } from "./ActionDialogs.jsx";
import * as api from "./api.js";

export default function Instances() {
  const notify = useNotify();
  const project = useProject();
  const [del, setDel] = useState(null);
  const [menu, setMenu] = useState(null);
  const [dialog, setDialog] = useState(null);   // "failover" | "upgrade" | "export" | "import" | "reschedule"
  const { data = [], loading, error, reload } = useAsync(() => api.listInstances(), [project]);

  const openDialog = (name) => { setDialog(name); setMenu((m) => ({ ...m, open: false })); };
  const closeDialog = () => setDialog(null);
  const onDone = (msg) => { notify.success(msg); closeDialog(); reload(); };

  return (
    <>
      <PageHeader title="Instances" actions={<>
        <Button startIcon={<AddIcon />} href="#/memorystore/create">Create instance</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
      </>} />
      <ResourceTable
        resourceName="instances"
        items={data}
        rowKey={(i) => i.name}
        loading={loading}
        error={error}
        onRetry={reload}
        filterPlaceholder="Filter"
        columns={[
          { id: "name", header: "Name", sortField: "name", cell: (i) => { const { location, id } = api.parseName(i.name); return <Link href={instanceHref(location, id)}>{id}</Link>; } },
          { id: "status", header: "Status", cell: (i) => api.stateLabel(i.state) },
          { id: "tier", header: "Tier", sortField: "tier", cell: (i) => api.tierLabel(i.tier) },
          { id: "version", header: "Version", cell: (i) => api.versionLabel(i.redisVersion) },
          { id: "capacity", header: "Capacity", cell: (i) => api.capacityLabel(i) },
          { id: "region", header: "Region", cell: (i) => api.regionLabel(api.parseName(i.name).location) },
          { id: "zone", header: "Zone", cell: (i) => i.currentLocationId },
          { id: "network", header: "Network", cell: (i) => api.networkName(i) },
          { id: "labels", header: "Labels", cell: (i) => {
            const ls = Object.entries(i.labels || {});
            return ls.length ? <Stack direction="row" spacing={0.5}>{ls.slice(0, 2).map(([k, v]) => <Chip key={k} size="small" label={`${k}: ${v}`} />)}</Stack> : "—";
          } },
          {
            id: "actions", header: "Actions", cell: (i) => (
              <IconButton size="small" aria-label={`Actions for ${api.parseName(i.name).id}`} onClick={(e) => setMenu({ anchor: e.currentTarget, open: true, instance: i })}><MoreVertIcon fontSize="small" /></IconButton>
            ),
          },
        ]}
        empty={
          <Stack spacing={1.5} alignItems="center">
            <Typography variant="body2" color="text.secondary">No instances in this project</Typography>
            <Button variant="contained" startIcon={<AddIcon />} href="#/memorystore/create">Create instance</Button>
          </Stack>
        }
      />
      <Menu anchorEl={menu?.anchor} open={!!menu?.open} onClose={() => setMenu((m) => ({ ...m, open: false }))}>
        <MenuItem disabled={menu?.instance.tier !== "STANDARD_HA"} onClick={() => openDialog("failover")}>Failover</MenuItem>
        <MenuItem onClick={() => openDialog("upgrade")}>Upgrade</MenuItem>
        <MenuItem onClick={() => openDialog("export")}>Export</MenuItem>
        <MenuItem onClick={() => openDialog("import")}>Import</MenuItem>
        <MenuItem onClick={() => openDialog("reschedule")}>Reschedule maintenance</MenuItem>
        <MenuItem onClick={() => { setDel(menu.instance); setMenu((m) => ({ ...m, open: false })); }}>Delete</MenuItem>
      </Menu>
      <FailoverDialog open={dialog === "failover"} instance={menu?.instance} onClose={closeDialog} onDone={onDone} />
      <UpgradeDialog open={dialog === "upgrade"} instance={menu?.instance} onClose={closeDialog} onDone={onDone} />
      <ExportDialog open={dialog === "export"} instance={menu?.instance} onClose={closeDialog} onDone={onDone} />
      <ImportDialog open={dialog === "import"} instance={menu?.instance} onClose={closeDialog} onDone={onDone} />
      <RescheduleDialog open={dialog === "reschedule"} instance={menu?.instance} onClose={closeDialog} onDone={onDone} />
      <DeleteDialog
        open={!!del}
        onClose={() => setDel(null)}
        title="Delete instance?"
        confirmText={del ? api.parseName(del.name).id : ""}
        warning="This can't be undone."
        onConfirm={async () => {
          const { location, id } = api.parseName(del.name);
          await api.deleteInstance(location, id);
          notify.success(`Deleted instance "${id}"`);
          setDel(null); reload();
        }}
      >
        <Box><Typography variant="body2">Instance <b>{del ? api.parseName(del.name).id : ""}</b> will be permanently deleted.</Typography></Box>
      </DeleteDialog>
    </>
  );
}
