/* Uptime checks list — real UptimeCheckConfigs, with a Policies column cross-referencing
 * any alert policy created alongside a check. Per-region health is real too: each check is
 * actually probed (core/gcp_monitoring_core.py run_uptime_probes), writing a real
 * monitoring.googleapis.com/uptime_check/check_passed point per region — see
 * gcp.monitoring.uptime-checks.probing for what "probed" means without outbound network. */
import { useState } from "react";
import { Box, Button, IconButton, Menu, MenuItem, Stack, Tooltip, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import MoreVertIcon from "@mui/icons-material/esm/MoreVert.js";
import CheckCircleOutlineIcon from "@mui/icons-material/esm/CheckCircleOutline.js";
import CancelOutlinedIcon from "@mui/icons-material/esm/CancelOutlined.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { PageHeader } from "../../kit/common.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

const REGION_COLUMNS = [["Asia Pacific", ["ASIA_PACIFIC"]], ["Europe", ["EUROPE"]], ["North America", ["USA", "USA_OREGON", "USA_IOWA", "USA_VIRGINIA"]], ["South America", ["SOUTH_AMERICA"]]];

function RegionCell({ check, regions, passedByRegion }) {
  const selected = check.selectedRegions || [];
  const applicable = regions.filter((r) => !selected.length || selected.includes(r));
  if (!applicable.length) return <Typography variant="body2" color="text.secondary">—</Typography>;
  const results = applicable.map((r) => passedByRegion[r]).filter((v) => v !== undefined);
  if (!results.length) return <Tooltip title="Probed on the next refresh"><Typography variant="body2" color="text.secondary">…</Typography></Tooltip>;
  const up = results.every(Boolean);
  return up
    ? <Tooltip title="Passing"><CheckCircleOutlineIcon fontSize="small" color="success" /></Tooltip>
    : <Tooltip title="Failing — see gcp.monitoring.uptime-checks.probing for how Vyomi probes a check without outbound network"><CancelOutlinedIcon fontSize="small" color="error" /></Tooltip>;
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
  const { data, loading, error, reload } = useAsync(async () => {
    const [checks, policies, checkPassed] = await Promise.all([
      api.listUptimeChecks(), api.listPolicies(),
      api.listTimeSeries({ filter: 'metric.type = "monitoring.googleapis.com/uptime_check/check_passed"', endTime: new Date().toISOString() }),
    ]);
    return { checks, policies, checkPassed };
  }, [project]);
  const checks = data?.checks || [];
  const policies = data?.policies || [];
  const policyCount = (check) => policies.filter((p) => (p.conditions || []).some((c) => (c.conditionThreshold?.filter || "").includes(check.name))).length;
  const passedByRegion = (check) => {
    const checkId = check.name.split("/").pop();
    const out = {};
    for (const s of data?.checkPassed || []) {
      if (s.metric?.labels?.check_id !== checkId) continue;
      out[s.metric.labels.checked_region] = s.points?.[0]?.value?.boolValue;
    }
    return out;
  };

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
          ...REGION_COLUMNS.map(([label, regions]) => ({ id: label, header: label, cell: (c) => <RegionCell check={c} regions={regions} passedByRegion={passedByRegion(c)} /> })),
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
