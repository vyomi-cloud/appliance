import { useEffect, useState } from "react";
import { Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow, ToolbarButton } from "@fluentui/react-components";
import { ArrowClockwise20Regular } from "@fluentui/react-icons";
import MonitorShell from "./MonitorShell.jsx";
import { listAlertRules, listAllResources } from "./api.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ErrorBar, Loading } from "../../kit/common.jsx";

export default function AdvisorRecommendations() {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);

  const load = () => {
    setError(null); setRows(null);
    Promise.all([listAllResources(), listAlertRules()]).then(([resources, rules]) => {
      const covered = new Set(rules.flatMap((r) => r.scopes || []).map((s) => s.toLowerCase()));
      setRows(resources.filter((r) => !covered.has(r.id.toLowerCase())));
    }).catch(setError);
  };
  useEffect(load, []);

  return (
    <MonitorShell active="advisor">
      <CapabilityContainer id="azure.monitor.advisor_recommendations" title="Advisor recommendations" actions={
        <div className="vy-cmdbar" role="toolbar" aria-label="Command bar">
          <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={load}>Refresh</ToolbarButton>
        </div>
      }>
        <ErrorBar error={error} title="Failed to load recommendations" />
        {rows === null ? <Loading /> : !rows.length ? <p>No recommendations — every resource in your inventory has at least one alert rule.</p> : (
          <Table size="small" aria-label="Advisor recommendations">
            <TableHeader><TableRow><TableHeaderCell>Resource</TableHeaderCell><TableHeaderCell>Type</TableHeaderCell><TableHeaderCell>Recommendation</TableHeaderCell></TableRow></TableHeader>
            <TableBody>
              {rows.map((r) => (
                <TableRow key={r.id}><TableCell>{r.name}</TableCell><TableCell>{r.typeLabel}</TableCell>
                  <TableCell>Create an alert rule for this resource so you hear about a problem before it becomes an outage.</TableCell></TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CapabilityContainer>
    </MonitorShell>
  );
}
