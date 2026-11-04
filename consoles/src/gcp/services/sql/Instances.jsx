/* Instances list — columns, row actions (Restart / Stop / Start / Delete) and the create
 * flow entry point, as in the console's Instances page. */
import { useState } from "react";
import { Box, Button, Chip, IconButton, Menu, MenuItem, Stack, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import MoreVertIcon from "@mui/icons-material/esm/MoreVert.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { PageHeader } from "../../kit/common.jsx";
import { Link, hashHref } from "../../link.jsx";
import { useProject } from "../../project.js";
import { instanceHref } from "./InstanceNav.jsx";
import * as api from "./api.js";

export default function Instances() {
  const notify = useNotify();
  const project = useProject();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [menu, setMenu] = useState(null);
  const { data = [], loading, error, reload } = useAsync(() => api.listInstances(), [project]);

  const act = async (fn, name, msg) => {
    try { await fn(name); notify.success(msg); reload(); }
    catch (e) { notify.error(e); }
    setMenu(null);
  };

  const labels = (i) => {
    const ls = Object.entries(i.settings?.userLabels || {});
    if (!ls.length) return "—";
    return <Stack direction="row" spacing={0.5}>{ls.slice(0, 2).map(([k, v]) => <Chip key={k} size="small" label={`${k}: ${v}`} />)}</Stack>;
  };

  return (
    <>
      <PageHeader title="Instances" actions={<>
        <Button startIcon={<AddIcon />} href="#/sql/create">Create instance</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
      </>} />
      <ResourceTable
        resourceName="instances"
        items={data}
        rowKey={(i) => i.name}
        loading={loading}
        error={error}
        onRetry={reload}
        selectable
        selected={sel}
        onSelectedChange={setSel}
        filterPlaceholder="Filter"
        columns={[
          { id: "name", header: "Instance ID", sortField: "name", cell: (i) => <Link href={instanceHref(i.name)}>{i.name}</Link> },
          { id: "edition", header: "Cloud SQL edition", cell: () => api.editionLabel() },
          { id: "type", header: "Type", sortField: "databaseVersion", cell: (i) => api.versionLabel(i.databaseVersion) },
          { id: "publicIp", header: "Public IP address", cell: (i) => api.publicIp(i) },
          { id: "privateIp", header: "Private IP address", cell: (i) => api.privateIp(i) },
          { id: "connName", header: "Instance connection name", cell: (i) => i.connectionName },
          { id: "ha", header: "High availability", cell: (i) => i.settings?.availabilityType === "REGIONAL" ? "Enabled" : "Disabled" },
          { id: "location", header: "Location", sortField: "region", cell: (i) => i.gceZone || i.region },
          { id: "storage", header: "Storage used", cell: (i) => api.diskGb(i) },
          { id: "labels", header: "Labels", cell: labels },
          { id: "state", header: "Status", cell: (i) => api.stateLabel(i.state) },
          {
            id: "actions", header: "Actions", cell: (i) => (
              <>
                <IconButton size="small" aria-label={`Actions for ${i.name}`} onClick={(e) => setMenu({ anchor: e.currentTarget, instance: i })}><MoreVertIcon fontSize="small" /></IconButton>
              </>
            ),
          },
        ]}
        empty={
          <Stack spacing={1.5} alignItems="center">
            <Typography variant="body2" color="text.secondary">There are no Cloud SQL instances in this project.</Typography>
            <Button variant="contained" startIcon={<AddIcon />} href="#/sql/create">Create instance</Button>
          </Stack>
        }
      />
      <Menu anchorEl={menu?.anchor} open={!!menu} onClose={() => setMenu(null)}>
        <MenuItem onClick={() => act(api.restartInstance, menu.instance.name, `Restarting "${menu.instance.name}"`)}>Restart</MenuItem>
        {menu?.instance.state === "STOPPED"
          ? <MenuItem onClick={() => act(api.startInstance, menu.instance.name, `Starting "${menu.instance.name}"`)}>Start</MenuItem>
          : <MenuItem onClick={() => act(api.stopInstance, menu?.instance.name, `Stopping "${menu?.instance.name}"`)}>Stop</MenuItem>}
        <MenuItem onClick={() => { setSel([menu.instance.name]); setMenu(null); setDel(true); }}>Delete</MenuItem>
      </Menu>
      <DeleteDialog
        open={del}
        onClose={() => setDel(false)}
        title={sel.length === 1 ? "Delete instance?" : `Delete ${sel.length} instances?`}
        confirmText={sel.length === 1 ? sel[0] : "DELETE"}
        warning="All databases, users and backups on this instance are deleted as well. This can't be undone."
        onConfirm={async () => {
          for (const name of sel) await api.deleteInstance(name);
          notify.success(sel.length === 1 ? `Deleted instance "${sel[0]}"` : `Deleted ${sel.length} instances`);
          setSel([]); reload();
        }}
      >
        <Box><Typography variant="body2">{sel.length === 1 ? <>Instance <b>{sel[0]}</b> will be permanently deleted.</> : <>{sel.join(", ")} will be permanently deleted.</>}</Typography></Box>
      </DeleteDialog>
    </>
  );
}
