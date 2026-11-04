import { useEffect, useState } from "react";
import { Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow, ToolbarButton } from "@fluentui/react-components";
import { ArrowClockwise20Regular, ArrowDownload20Regular } from "@fluentui/react-icons";
import MonitorShell from "./MonitorShell.jsx";
import { listActivityLog } from "./api.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { downloadCsv, ErrorBar, fmtDate, Loading, NotSimulatedContainer } from "../../kit/common.jsx";

const COLUMNS = [
  { key: "op", label: "Operation name", csv: (e) => e.operationName?.localizedValue },
  { key: "status", label: "Status", csv: (e) => e.status?.value },
  { key: "time", label: "Time", csv: (e) => fmtDate(e.eventTimestamp) },
  { key: "stamp", label: "Time stamp", csv: (e) => e.submissionTimestamp },
  { key: "sub", label: "Subscription", csv: (e) => e.subscriptionId },
  { key: "by", label: "Event initiated by", csv: (e) => e.caller },
];

export default function ActivityLog() {
  const [events, setEvents] = useState(null);
  const [error, setError] = useState(null);
  const load = () => { setError(null); listActivityLog().then(setEvents).catch(setError); };
  useEffect(load, []);

  return (
    <MonitorShell active="activitylog">
      <CapabilityContainer id="azure.monitor.activity_log" title="Activity log" actions={
        <div className="vy-cmdbar" role="toolbar" aria-label="Command bar">
          <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={load}>Refresh</ToolbarButton>
          <ToolbarButton icon={<ArrowDownload20Regular />} disabled={!events?.length}
            onClick={() => downloadCsv("activity-log.csv", COLUMNS, events || [])}>Download as CSV</ToolbarButton>
        </div>
      }>
        <ErrorBar error={error} title="Failed to load the activity log" />
        {events === null ? <Loading /> : !events.length ? <p>No events to display</p> : (
          <Table size="small" aria-label="Activity log">
            <TableHeader><TableRow>{COLUMNS.map((c) => <TableHeaderCell key={c.key}>{c.label}</TableHeaderCell>)}</TableRow></TableHeader>
            <TableBody>
              {events.map((e) => (
                <TableRow key={e.id}>
                  <TableCell>{e.operationName?.localizedValue || e.operationName?.value}</TableCell>
                  <TableCell>{e.status?.value}</TableCell>
                  <TableCell>{fmtDate(e.eventTimestamp)}</TableCell>
                  <TableCell>{fmtDate(e.submissionTimestamp)}</TableCell>
                  <TableCell>{e.subscriptionId}</TableCell>
                  <TableCell>{e.caller}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CapabilityContainer>

      <NotSimulatedContainer title="Quick Insights"
        note="Additional command-bar actions not simulated in Vyomi: Activity, Edit columns, Export Activity Logs (continuous export), Insights, Feedback, Pin current filters, Reset filters." />
    </MonitorShell>
  );
}
