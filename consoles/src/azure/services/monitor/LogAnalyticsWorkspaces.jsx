import { useEffect, useState } from "react";
import { Button, Select } from "@fluentui/react-components";
import MonitorShell from "./MonitorShell.jsx";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { deleteWorkspace, listWorkspaces } from "./api.js";
import { locationLabel } from "../../kit/arm.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { NotSimulatedContainer } from "../../kit/common.jsx";

const TIME_RANGES = ["Last 24 hours", "Last 7 days", "Last 30 days", "All time"];
const RANGE_MS = { "Last 24 hours": 864e5, "Last 7 days": 6048e5, "Last 30 days": 2592e6 };

export default function LogAnalyticsWorkspaces() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [timeRange, setTimeRange] = useState("All time");
  const load = () => { setLoading(true); setError(null); listWorkspaces().then(setItems).catch(setError).finally(() => setLoading(false)); };
  useEffect(load, []);

  const limit = RANGE_MS[timeRange];
  const visible = limit ? items.filter((w) => Date.now() - new Date(w.properties.createdDate).getTime() <= limit) : items;

  const columns = [
    { key: "name", label: "Name" },
    { key: "rg", label: "Resource group", value: (w) => w.resourceGroup },
    { key: "loc", label: "Location", value: (w) => locationLabel(w.location) },
    { key: "sku", label: "Pricing tier", value: (w) => w.properties.sku?.name },
    { key: "retention", label: "Retention (days)", value: (w) => w.properties.retentionInDays },
  ];

  return (
    <MonitorShell active="loganalyticsworkspaces">
      <CapabilityContainer id="azure.monitor.log_analytics_workspaces" title="Filters" actions={
        <div className="vy-cmdbar" role="toolbar" aria-label="Command bar">
          <span className="vy-pill vy-pill-static">Auto refresh: Off</span>
        </div>
      }>
        <div className="vy-form-row"><label>Subscriptions</label><div><span className="vy-pill vy-pill-static" title="Vyomi simulates one subscription">Vyomi subscription</span></div></div>
        <div className="vy-form-row"><label>Time Range</label><div>
          <Select value={timeRange} onChange={(_, d) => setTimeRange(d.value)} aria-label="Time Range">{TIME_RANGES.map((t) => <option key={t}>{t}</option>)}</Select>
        </div></div>

        <BrowseGrid resourceName="workspace" items={visible} columns={columns} loading={loading} error={error}
          onRefresh={load} onCreate={() => { location.hash = "#/monitor/createloganalyticsworkspace"; }}
          onDelete={async (rows) => { await Promise.all(rows.map((r) => deleteWorkspace(r.resourceGroup, r.name))); load(); }}
          emptyAction={<Button appearance="primary" as="a" href="#/monitor/createloganalyticsworkspace">Create workspace</Button>}
          csvName="log-analytics-workspaces.csv" />
      </CapabilityContainer>
      <NotSimulatedContainer title="Workbooks" note="Customize is not simulated either." />
    </MonitorShell>
  );
}
