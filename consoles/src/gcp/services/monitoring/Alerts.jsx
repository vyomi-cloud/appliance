/* Alerts — open/closed incidents from the real alert-evaluation engine (see
 * gcp.monitoring.incidents): a policy's condition_threshold/condition_absent conditions are
 * evaluated against the time series they filter every time this page loads, opening and
 * closing incidents exactly like the real engine (snoozes suppress new ones, too). */
import { useState } from "react";
import { Button, IconButton, Menu, MenuItem, Typography } from "@mui/material";
import MoreVertIcon from "@mui/icons-material/esm/MoreVert.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { PageHeader } from "../../kit/common.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

const SEVERITY_LABEL = { CRITICAL: "Critical", ERROR: "Error", WARNING: "Warning" };

function RowMenu({ incident, onChanged }) {
  const notify = useNotify();
  const [anchor, setAnchor] = useState(null);
  if (incident.state !== "OPEN" || incident.acknowledged) return null;
  const id = incident.name.split("/").pop();
  return (
    <>
      <IconButton size="small" aria-label={`Actions for ${incident.summary}`} onClick={(e) => setAnchor(e.currentTarget)}><MoreVertIcon fontSize="small" /></IconButton>
      <Menu anchorEl={anchor} open={!!anchor} onClose={() => setAnchor(null)}>
        <MenuItem onClick={async () => { setAnchor(null); await api.acknowledgeIncident(id); notify.success("Alert acknowledged"); onChanged(); }}>Acknowledge</MenuItem>
      </Menu>
    </>
  );
}

export default function Alerts() {
  const project = useProject();
  const [showClosed, setShowClosed] = useState(false);
  const { data = [], loading, error, reload } = useAsync(() => api.listIncidents(), [project]);
  const shown = showClosed ? data : data.filter((i) => i.state === "OPEN");

  return (
    <>
      <PageHeader title={<>Alerts <CapabilityBadge id="gcp.monitoring.incidents" /></>} actions={<>
        <Button href="#/monitoring/alerting/policies/create">Create policy</Button>
        <Button size="small" onClick={() => setShowClosed((v) => !v)}>{showClosed ? "Hide closed alerts" : "Show closed alerts"}</Button>
      </>} />
      <ResourceTable
        resourceName="alerts"
        items={shown}
        loading={loading}
        error={error}
        onRetry={reload}
        rowKey={(i) => i.name}
        filterPlaceholder="Filter"
        columns={[
          { id: "state", header: "State", cell: (i) => i.state === "OPEN" ? (i.acknowledged ? "Open (acknowledged)" : "Open") : "Closed" },
          { id: "severity", header: "Severity", cell: (i) => SEVERITY_LABEL[i.severity] || "No severity" },
          { id: "policy", header: "Policy Name", sortField: "policyDisplayName", cell: (i) => i.policyDisplayName },
          { id: "summary", header: "Alert Summary", cell: (i) => i.summary },
          { id: "opened", header: "Opened", sortField: "startedAt", cell: (i) => new Date(i.startedAt).toLocaleString() },
          { id: "labels", header: "Labels", cell: (i) => Object.keys(i.userLabels || {}).length ? Object.entries(i.userLabels).map(([k, v]) => `${k}=${v}`).join(", ") : "—" },
          { id: "actions", header: "", cell: (i) => <RowMenu incident={i} onChanged={reload} /> },
        ]}
        empty={<Typography variant="body2" color="text.secondary">No rows to display</Typography>}
      />
    </>
  );
}
