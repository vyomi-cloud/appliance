import { useEffect, useMemo, useState } from "react";
import { Button, Checkbox, Input, Menu, MenuItem, MenuList, MenuPopover, MenuTrigger, Select, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow, ToolbarButton } from "@fluentui/react-components";
import { ArrowClockwise20Regular, ArrowDownload20Regular } from "@fluentui/react-icons";
import MonitorShell from "./MonitorShell.jsx";
import { listActivityLog } from "./api.js";
import { openInLogs } from "./Logs.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { downloadCsv, ErrorBar, fmtDate, Loading } from "../../kit/common.jsx";

const COLUMNS = [
  { key: "op", label: "Operation name", csv: (e) => e.operationName?.localizedValue, cell: (e) => e.operationName?.localizedValue || e.operationName?.value },
  { key: "status", label: "Status", csv: (e) => e.status?.value, cell: (e) => e.status?.value },
  { key: "time", label: "Time", csv: (e) => fmtDate(e.eventTimestamp), cell: (e) => fmtDate(e.eventTimestamp) },
  { key: "stamp", label: "Time stamp", csv: (e) => e.submissionTimestamp, cell: (e) => fmtDate(e.submissionTimestamp) },
  { key: "sub", label: "Subscription", csv: (e) => e.subscriptionId, cell: (e) => e.subscriptionId },
  { key: "by", label: "Event initiated by", csv: (e) => e.caller, cell: (e) => e.caller },
  { key: "level", label: "Level", csv: (e) => e.level, cell: (e) => e.level },
  { key: "category", label: "Category", csv: (e) => e.category?.value || "Administrative", cell: (e) => e.category?.value || "Administrative" },
  { key: "resource", label: "Resource", csv: (e) => e.resourceId, cell: (e) => (e.resourceId || "").split("/").pop() },
];
const DEFAULT_VISIBLE = ["op", "status", "time", "stamp", "sub", "by"];
const SPANS = { "Last 1 hour": 3600e3, "Last 6 hours": 6 * 3600e3, "Last 24 hours": 24 * 3600e3, "Last 7 days": 7 * 864e5, "Last 30 days": 30 * 864e5, "All time": 0 };
const PIN_KEY = "vyomi.azure.activitylog.filters";
const EMPTY = { span: "All time", status: "", level: "", caller: "" };
const readPinned = () => { try { return { ...EMPTY, ...JSON.parse(localStorage.getItem(PIN_KEY) || "{}") }; } catch { return EMPTY; } };

/** OData $filter the backend enforces (core/azure_monitor_core.py _activity_log_list). */
const odata = (f) => [
  SPANS[f.span] ? `eventTimestamp ge '${new Date(Date.now() - SPANS[f.span]).toISOString()}'` : null,
  f.status ? `status eq '${f.status}'` : null, f.level ? `level eq '${f.level}'` : null, f.caller.trim() ? `caller eq '${f.caller.trim()}'` : null,
].filter(Boolean).join(" and ");

export default function ActivityLog() {
  const [events, setEvents] = useState(null);
  const [error, setError] = useState(null);
  const [filters, setFilters] = useState(readPinned);
  const [visible, setVisible] = useState(new Set(DEFAULT_VISIBLE));
  const [pinned, setPinned] = useState(() => { try { return !!localStorage.getItem(PIN_KEY); } catch { return false; } });
  const load = (f = filters) => { setError(null); listActivityLog(null, odata(f)).then(setEvents).catch(setError); };
  useEffect(() => load(), []);
  const cols = useMemo(() => COLUMNS.filter((c) => visible.has(c.key)), [visible]);
  const setF = (k) => (_, d) => { const n = { ...filters, [k]: d.value }; setFilters(n); load(n); };
  const reset = () => { setFilters(EMPTY); load(EMPTY); };
  const pin = () => { try { localStorage.setItem(PIN_KEY, JSON.stringify(filters)); setPinned(true); } catch { /* storage blocked */ } };
  const unpin = () => { try { localStorage.removeItem(PIN_KEY); setPinned(false); } catch { /* storage blocked */ } };
  const downloadJson = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(events || [], null, 2)], { type: "application/json" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: "activity-log.json" });
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
  };

  return (
    <MonitorShell active="activitylog">
      <CapabilityContainer id="azure.monitor.activity_log" title="Activity log" actions={
        <div className="vy-cmdbar" role="toolbar" aria-label="Command bar">
          <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={() => load()}>Refresh</ToolbarButton>
          <Menu>
            <MenuTrigger disableButtonEnhancement><ToolbarButton>Edit columns</ToolbarButton></MenuTrigger>
            <MenuPopover><MenuList>
              {COLUMNS.map((c) => (
                <MenuItem key={c.key} persistOnClick onClick={() => setVisible((v) => { const n = new Set(v); n.has(c.key) ? n.delete(c.key) : n.add(c.key); return n.size ? n : v; })}>
                  <Checkbox checked={visible.has(c.key)} label={c.label} />
                </MenuItem>
              ))}
            </MenuList></MenuPopover>
          </Menu>
          <Menu>
            <MenuTrigger disableButtonEnhancement><ToolbarButton icon={<ArrowDownload20Regular />} disabled={!events?.length}>Activity</ToolbarButton></MenuTrigger>
            <MenuPopover><MenuList>
              <MenuItem onClick={() => downloadCsv("activity-log.csv", cols, events || [])}>Download as CSV</MenuItem>
              <MenuItem onClick={downloadJson}>Export Activity Logs (JSON)</MenuItem>
            </MenuList></MenuPopover>
          </Menu>
          <ToolbarButton onClick={() => openInLogs("AzureActivity\n| summarize count() by OperationName\n| order by count_ desc")}>Insights</ToolbarButton>
          <ToolbarButton onClick={() => openInLogs("AzureActivity\n| where TimeGenerated > ago(24h)\n| order by TimeGenerated desc\n| take 100")}>Export to Log Analytics (query AzureActivity)</ToolbarButton>
          <ToolbarButton onClick={pinned ? unpin : pin}>{pinned ? "Unpin current filters" : "Pin current filters"}</ToolbarButton>
          <ToolbarButton onClick={reset}>Reset filters</ToolbarButton>
          <ToolbarButton as="a" href="#/monitor/support">Feedback</ToolbarButton>
        </div>
      }>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
          <Select value={filters.span} onChange={setF("span")} aria-label="Timespan">{Object.keys(SPANS).map((k) => <option key={k}>{k}</option>)}</Select>
          <Select value={filters.status} onChange={setF("status")} aria-label="Status"><option value="">Status: all</option>{["Succeeded", "Failed", "Started", "Accepted"].map((k) => <option key={k}>{k}</option>)}</Select>
          <Select value={filters.level} onChange={setF("level")} aria-label="Event severity"><option value="">Event severity: all</option>{["Critical", "Error", "Warning", "Informational", "Verbose"].map((k) => <option key={k}>{k}</option>)}</Select>
          <Input value={filters.caller} onChange={setF("caller")} placeholder="Event initiated by (exact)" aria-label="Event initiated by" />
        </div>
        <ErrorBar error={error} title="Failed to load the activity log" />
        {events === null ? <Loading /> : !events.length ? <p>No events to display</p> : (
          <Table size="small" aria-label="Activity log">
            <TableHeader><TableRow>{cols.map((c) => <TableHeaderCell key={c.key}>{c.label}</TableHeaderCell>)}</TableRow></TableHeader>
            <TableBody>
              {events.map((e) => <TableRow key={e.id}>{cols.map((c) => <TableCell key={c.key}>{c.cell(e)}</TableCell>)}</TableRow>)}
            </TableBody>
          </Table>
        )}
      </CapabilityContainer>
    </MonitorShell>
  );
}
