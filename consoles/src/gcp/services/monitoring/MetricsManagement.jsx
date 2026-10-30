/* Metrics Management — the real metric catalog (type, domain, labels, referencing alert
 * policies) from metricDescriptors.list; billing/usage figures are an honest gap (no
 * billing pipeline) and "Excluded Metrics" has no public API to back it. */
import { useState } from "react";
import { Button, Stack, Table, TableBody, TableCell, TableHead, TableRow, Tab, Tabs, TextField, Typography } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import { PageHeader } from "../../kit/common.jsx";
import { CapabilityBadge, CapabilityContainer } from "../../kit/Capability.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

export default function MetricsManagement() {
  const project = useProject();
  const [tab, setTab] = useState("metrics");
  const [filter, setFilter] = useState("");
  const { data, loading } = useAsync(async () => ({ metrics: await api.listMetricDescriptors(), policies: await api.listPolicies() }), [project]);
  const metrics = (data?.metrics || []).filter((m) => m.type.toLowerCase().includes(filter.toLowerCase()));
  const policies = data?.policies || [];
  const alertCount = (type) => policies.filter((p) => (p.conditions || []).some((c) => (c.conditionThreshold?.filter || c.conditionAbsent?.filter || "").includes(type))).length;

  return (
    <>
      <PageHeader title="Metrics Management" actions={<><Button disabled>Send Feedback</Button><Button disabled>View Audit Logs</Button></>} />
      <Tabs value={tab} onChange={(_, t) => setTab(t)} sx={{ mb: 2 }}>
        <Tab value="metrics" label="Metrics" />
        <Tab value="excluded" label="Excluded Metrics" />
      </Tabs>
      {tab === "excluded" ? (
        <CapabilityContainer id="gcp.monitoring.metrics-management" title="Excluded metrics" />
      ) : (
        <Stack spacing={1.5}>
          <TextField size="small" placeholder="Filter" value={filter} onChange={(e) => setFilter(e.target.value)}
            inputProps={{ "aria-label": "Filter" }} sx={{ maxWidth: 320 }} />
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Metric</TableCell>
                <TableCell>Bytes billable volume / Total<CapabilityBadge id="gcp.monitoring.metrics-management" /></TableCell>
                <TableCell>Samples billable volume / Total</TableCell>
                <TableCell>Metric reads in the last 30 days</TableCell>
                <TableCell>Alert Policies</TableCell>
                <TableCell>Custom Dashboards</TableCell>
                <TableCell>Domain</TableCell>
                <TableCell>Labels</TableCell>
                <TableCell>Project name</TableCell>
                <TableCell>(Samples) Namespaces</TableCell>
                <TableCell>Cardinality</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {loading ? null : metrics.length ? metrics.map((m) => (
                <TableRow key={m.type}>
                  <TableCell>{m.type}</TableCell>
                  <TableCell>—</TableCell>
                  <TableCell>—</TableCell>
                  <TableCell>—</TableCell>
                  <TableCell>{alertCount(m.type) || "—"}</TableCell>
                  <TableCell>—</TableCell>
                  <TableCell>{m.type.split("/")[0]}</TableCell>
                  <TableCell>{(m.labels || []).map((l) => l.key).join(", ") || "—"}</TableCell>
                  <TableCell>{project}</TableCell>
                  <TableCell>—</TableCell>
                  <TableCell>—</TableCell>
                </TableRow>
              )) : <TableRow><TableCell colSpan={11}><Typography variant="body2" color="text.secondary">No rows to display</Typography></TableCell></TableRow>}
            </TableBody>
          </Table>
        </Stack>
      )}
    </>
  );
}
