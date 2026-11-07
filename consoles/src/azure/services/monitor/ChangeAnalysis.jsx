import { useEffect, useState } from "react";
import MonitorShell from "./MonitorShell.jsx";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { listActivityLog } from "./api.js";
import { parseId } from "../../kit/arm.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { fmtDate } from "../../kit/common.jsx";
import { Select, ToolbarButton } from "@fluentui/react-components";
import { openInLogs } from "./Logs.jsx";

const CHANGE_TYPE = (op) => (/delete/i.test(op) ? "Delete" : /create/i.test(op) ? "Create" : "Update");
const resourceType = (id) => { const p = (id || "").split("/").filter(Boolean); const i = p.findIndex((x) => x.toLowerCase() === "providers"); return i >= 0 && p[i + 2] ? `${p[i + 1]}/${p[i + 2]}` : "--"; };

export default function ChangeAnalysis() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [groupBy, setGroupBy] = useState("none");
  const load = () => { setLoading(true); setError(null); listActivityLog().then((ev) => setItems(ev.map((e, i) => ({ ...e, _key: e.id || i })))).catch(setError).finally(() => setLoading(false)); };
  useEffect(load, []);

  const columns = [
    { key: "name", label: "Name", value: (e) => parseId(e.resourceId || "").name || e.resourceId },
    { key: "type", label: "Resource type", value: (e) => resourceType(e.resourceId) },
    { key: "change", label: "Change type", value: (e) => CHANGE_TYPE(e.operationName?.value || "") },
    { key: "by", label: "Changed by", value: (e) => e.caller },
    { key: "time", label: "Time", value: (e) => fmtDate(e.eventTimestamp) },
  ];

  const GROUPS = { none: null, type: columns[1], change: columns[2], by: columns[3], name: columns[0] };
  const grouped = GROUPS[groupBy] ? Object.entries(items.reduce((g, e) => { const k = String(GROUPS[groupBy].value(e) ?? "--"); (g[k] ||= []).push(e); return g; }, {})).sort((a, b) => b[1].length - a[1].length) : null;

  return (
    <MonitorShell active="changeanalysis">
      <CapabilityContainer id="azure.monitor.change_analysis" title="Change Analysis" actions={
        <div className="vy-cmdbar" role="toolbar" aria-label="Command bar">
          <ToolbarButton onClick={() => openInLogs("AzureActivity\n| where OperationName endswith 'write' or OperationName endswith 'delete'\n| summarize count() by ResourceGroup, OperationName\n| order by count_ desc")}>Open query</ToolbarButton>
          <label style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>Group by
            <Select value={groupBy} onChange={(_, d) => setGroupBy(d.value)} aria-label="Group by">
              <option value="none">None</option><option value="type">Resource type</option><option value="change">Change type</option><option value="by">Changed by</option><option value="name">Name</option>
            </Select>
          </label>
        </div>
      }>
        {grouped ? (
          <table className="vy-table" aria-label={`Changes grouped by ${GROUPS[groupBy].label}`}>
            <thead><tr><th>{GROUPS[groupBy].label}</th><th>Changes</th><th>Latest</th></tr></thead>
            <tbody>{grouped.map(([k, es]) => <tr key={k}><td>{k}</td><td>{es.length}</td><td>{fmtDate(es.map((e) => e.eventTimestamp).sort().pop())}</td></tr>)}</tbody>
          </table>
        ) : (
          <BrowseGrid resourceName="change" rowKey={(e) => e._key} items={items} columns={columns} loading={loading} error={error}
            onRefresh={load} csvName="change-analysis.csv" />
        )}
      </CapabilityContainer>
    </MonitorShell>
  );
}
