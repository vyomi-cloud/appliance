/* Alerting overview — summary counters and open alerts come from the real alert-evaluation
 * engine (see gcp.monitoring.incidents); snoozes and policies are real resources below. */
import { useState } from "react";
import { Box, Button, FormControlLabel, Stack, Switch, Table, TableBody, TableCell, TableHead, TableRow, Typography } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import { PageHeader, Section } from "../../kit/common.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

const SEVERITY_LABEL = { CRITICAL: "Critical", ERROR: "Error", WARNING: "Warning" };

export default function Alerting() {
  const project = useProject();
  const [showClosed, setShowClosed] = useState(false);
  const [showPast, setShowPast] = useState(false);
  const { data } = useAsync(async () => ({
    policies: await api.listPolicies(), snoozes: await api.listSnoozes(), incidents: await api.listIncidents(),
  }), [project]);
  const policies = data?.policies || [];
  const snoozes = data?.snoozes || [];
  const incidents = data?.incidents || [];
  const firing = incidents.filter((i) => i.state === "OPEN");
  const acknowledged = firing.filter((i) => i.acknowledged);
  const visibleIncidents = showClosed ? incidents : firing;
  const now = Date.now();
  const visibleSnoozes = showPast ? snoozes : snoozes.filter((s) => new Date(s.interval.endTime).getTime() >= now);

  return (
    <>
      <PageHeader title="Alerting" actions={<>
        <Button href="#/monitoring/alerting/policies/create">Create policy</Button>
        <Button disabled>Edit notification channels</Button>
      </>} />
      <Stack spacing={2.5}>
        <Section title="Summary">
          <Stack direction="row" spacing={4}>
            <Box><Typography variant="h3">{firing.length}</Typography><Typography variant="body2" color="text.secondary">Alerts firing</Typography></Box>
            <Box><Typography variant="h3">{acknowledged.length}</Typography><Typography variant="body2" color="text.secondary">Alerts acknowledged</Typography></Box>
            <Box><Typography variant="h3">{policies.length}</Typography><Typography variant="body2" color="text.secondary">Alert policies</Typography></Box>
          </Stack>
        </Section>

        <Section title={<Stack component="span" direction="row" spacing={1} alignItems="center"><span>Alerts</span><CapabilityBadge id="gcp.monitoring.incidents" /></Stack>}
          actions={<Button size="small" onClick={() => setShowClosed((v) => !v)}>{showClosed ? "Hide closed alerts" : "Show closed alerts"}</Button>}>
          <Table size="small">
            <TableHead><TableRow><TableCell>State</TableCell><TableCell>Severity</TableCell><TableCell>Policy name</TableCell><TableCell>Alert summary</TableCell><TableCell>Opened</TableCell></TableRow></TableHead>
            <TableBody>
              {visibleIncidents.length ? visibleIncidents.map((i) => (
                <TableRow key={i.name}>
                  <TableCell>{i.state === "OPEN" ? (i.acknowledged ? "Open (acknowledged)" : "Open") : "Closed"}</TableCell>
                  <TableCell>{SEVERITY_LABEL[i.severity] || "No severity"}</TableCell>
                  <TableCell>{i.policyDisplayName}</TableCell>
                  <TableCell>{i.summary}</TableCell>
                  <TableCell>{new Date(i.startedAt).toLocaleString()}</TableCell>
                </TableRow>
              )) : <TableRow><TableCell colSpan={5}><Typography variant="body2" color="text.secondary">No rows to display</Typography></TableCell></TableRow>}
            </TableBody>
          </Table>
        </Section>

        <Section title="Snoozes" actions={<Button size="small" href="#/monitoring/alerting/snooze/create">Create snooze</Button>}>
          <FormControlLabel control={<Switch size="small" checked={showPast} onChange={(e) => setShowPast(e.target.checked)} />} label="Show past snoozes" />
          <Table size="small">
            <TableHead><TableRow><TableCell>State</TableCell><TableCell>Name</TableCell><TableCell>Start time</TableCell><TableCell>End time</TableCell></TableRow></TableHead>
            <TableBody>
              {visibleSnoozes.length ? visibleSnoozes.map((s) => (
                <TableRow key={s.name}>
                  <TableCell>{new Date(s.interval.endTime).getTime() < now ? "Expired" : "Active"}</TableCell>
                  <TableCell>{s.displayName}</TableCell>
                  <TableCell>{new Date(s.interval.startTime).toLocaleString()}</TableCell>
                  <TableCell>{new Date(s.interval.endTime).toLocaleString()}</TableCell>
                </TableRow>
              )) : <TableRow><TableCell colSpan={4}><Typography variant="body2" color="text.secondary">No rows to display</Typography></TableCell></TableRow>}
            </TableBody>
          </Table>
        </Section>

        <Section title="Policies" actions={<Button size="small" href="#/monitoring/alerting/policies/create">Create policy</Button>}>
          <Table size="small">
            <TableHead><TableRow><TableCell>Display name</TableCell><TableCell>Type</TableCell><TableCell>Last modified on</TableCell><TableCell>Labels</TableCell><TableCell>Enabled</TableCell></TableRow></TableHead>
            <TableBody>
              {policies.length ? policies.map((p) => (
                <TableRow key={p.name}>
                  <TableCell>{p.displayName}</TableCell>
                  <TableCell>{p.conditions?.[0]?.conditionThreshold ? "Metric threshold" : p.conditions?.[0]?.conditionAbsent ? "Metric absence" : "Condition"}</TableCell>
                  <TableCell>{p.mutationRecord?.mutateTime ? new Date(p.mutationRecord.mutateTime).toLocaleString() : "—"}</TableCell>
                  <TableCell>{Object.keys(p.userLabels || {}).length ? Object.entries(p.userLabels).map(([k, v]) => `${k}=${v}`).join(", ") : "—"}</TableCell>
                  <TableCell>{p.enabled ? "Enabled" : "Disabled"}</TableCell>
                </TableRow>
              )) : <TableRow><TableCell colSpan={5}><Typography variant="body2" color="text.secondary">No policies yet.</Typography></TableCell></TableRow>}
            </TableBody>
          </Table>
        </Section>
      </Stack>
    </>
  );
}
