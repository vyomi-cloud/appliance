/* Uptime checks list — real UptimeCheckConfigs, with a Policies column cross-referencing
 * any alert policy created alongside a check. Per-region health is an honest gap: Vyomi
 * never dispatches the configured probe, so there's no real pass/fail per region. */
import { useState } from "react";
import { Box, Button, IconButton, Menu, MenuItem, Stack, Tooltip, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import MoreVertIcon from "@mui/icons-material/esm/MoreVert.js";
import CheckCircleOutlineIcon from "@mui/icons-material/esm/CheckCircleOutline.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { PageHeader } from "../../kit/common.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

const REGION_COLUMNS = [["Asia Pacific", ["ASIA_PACIFIC"]], ["Europe", ["EUROPE"]], ["North America", ["USA", "USA_OREGON", "USA_IOWA", "USA_VIRGINIA"]], ["South America", ["SOUTH_AMERICA"]]];

function RegionCell({ check, regions }) {
  const selected = check.selectedRegions || [];
  const configured = !selected.length || regions.some((r) => selected.includes(r));
  return configured ? <Tooltip title="Configured; Vyomi doesn't run probes so no pass/fail is reported"><CheckCircleOutlineIcon fontSize="small" color="disabled" /></Tooltip> : <Typography variant="body2" color="text.secondary">—</Typography>;
}

function RowMenu({ check, policyCount, onDeleted }) {
  const notify = useNotify();
  const [anchor, setAnchor] = useState(null);
  const [del, setDel] = useState(false);
  const id = check.name.split("/").pop();
  return (
    <>
      <IconButton size="small" aria-label={`Actions for ${check.displayName}`} onClick={(e) => setAnchor(e.currentTarget)}><MoreVertIcon fontSize="small" /></IconButton>
      <Menu anchorEl={anchor} open={!!anchor} onClose={() => setAnchor(null)}>
        <MenuItem onClick={() => { setAnchor(null); setDel(true); }}>Delete</MenuItem>
      </Menu>
      <DeleteDialog open={del} onClose={() => setDel(false)} title="Delete uptime check?" confirmText={check.displayName}
        onConfirm={async () => { await api.deleteUptimeCheck(id); notify.success(`Deleted uptime check "${check.displayName}"`); onDeleted(); }}>
        <Typography variant="body2">Uptime check <b>{check.displayName}</b> {policyCount > 0 ? `and its ${policyCount} associated alert policy(ies) reference` : "will"} be permanently deleted.</Typography>
      </DeleteDialog>
    </>
  );
}

export default function UptimeChecks() {
  const project = useProject();
  const { data, loading, error, reload } = useAsync(async () => ({ checks: await api.listUptimeChecks(), policies: await api.listPolicies() }), [project]);
  const checks = data?.checks || [];
  const policies = data?.policies || [];
  const policyCount = (check) => policies.filter((p) => (p.conditions || []).some((c) => (c.conditionThreshold?.filter || "").includes(check.name))).length;

  return (
    <>
      <PageHeader title="Uptime checks" actions={<>
        <Button startIcon={<AddIcon />} href="#/monitoring/uptime/create">Create uptime check</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
      </>} />
      <ResourceTable
        resourceName="uptime checks"
        items={checks}
        loading={loading}
        error={error}
        onRetry={reload}
        rowKey={(c) => c.name}
        filterPlaceholder="Filter"
        columns={[
          { id: "name", header: "Display Name", sortField: "displayName", cell: (c) => c.displayName },
          ...REGION_COLUMNS.map(([label, regions]) => ({ id: label, header: label, cell: (c) => <RegionCell check={c} regions={regions} /> })),
          { id: "policies", header: "Policies", cell: (c) => policyCount(c) || "—" },
          { id: "actions", header: "", cell: (c) => <RowMenu check={c} policyCount={policyCount(c)} onDeleted={reload} /> },
        ]}
        empty={
          <Stack spacing={1.5} alignItems="center">
            <Typography variant="body2" color="text.secondary">No rows to display</Typography>
            <Button variant="contained" startIcon={<AddIcon />} href="#/monitoring/uptime/create">Create uptime check</Button>
          </Stack>
        }
      />
    </>
  );
}
