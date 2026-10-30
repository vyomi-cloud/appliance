import { useEffect, useState } from "react";
import { ToolbarButton } from "@fluentui/react-components";
import { Add20Regular, ArrowClockwise20Regular } from "@fluentui/react-icons";
import MonitorShell from "./MonitorShell.jsx";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { deleteActivityLogAlert, deleteMetricAlert, listAlertRules, SEVERITY_LABEL } from "./api.js";
import { parseId } from "../../kit/arm.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { NotSimulatedContainer } from "../../kit/common.jsx";

const affectedResource = (scopes) => (scopes && scopes[0] ? parseId(scopes[0]).name : "--");

export default function Alerts() {
  const [rules, setRules] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const load = () => { setLoading(true); setError(null); listAlertRules().then(setRules).catch(setError).finally(() => setLoading(false)); };
  useEffect(load, []);

  const columns = [
    { key: "name", label: "Name" },
    { key: "severity", label: "Severity", value: (r) => (r.severity != null ? SEVERITY_LABEL[r.severity] : "--") },
    { key: "resource", label: "Affected resource", value: (r) => affectedResource(r.scopes) },
    { key: "condition", label: "Alert condition" },
    { key: "response", label: "User response", value: () => "New" },
    { key: "fire", label: "Fire time", value: () => "--" },
  ];

  return (
    <MonitorShell active="alerts">
      <section className="vy-form-section">
        <h3>Summary</h3>
        <div className="vy-essentials-grid">
          <div>
            <div className="vy-kv"><span>Total alerts</span><span>0</span></div>
            <div className="vy-kv"><span>Critical</span><span>0</span></div>
          </div>
          <div>
            <div className="vy-kv"><span>Error</span><span>0</span></div>
            <div className="vy-kv"><span>Warning</span><span>0</span></div>
            <div className="vy-kv"><span>Informational</span><span>0</span></div>
            <div className="vy-kv"><span>Verbose</span><span>0</span></div>
          </div>
        </div>
        <p style={{ fontSize: 12, marginTop: 6 }}>No alert has ever fired — Vyomi stores alert rules but does not run a live metric-evaluation loop. {rules.length} alert rule{rules.length === 1 ? "" : "s"} configured.</p>
      </section>

      <CapabilityContainer id="azure.monitor.alert_rules" title="Alerts" actions={
        <div className="vy-cmdbar" role="toolbar" aria-label="Command bar">
          <ToolbarButton icon={<Add20Regular />} as="a" href="#/monitor/createalertrule">Create</ToolbarButton>
          <ToolbarButton as="a" href="#/monitor/alerts">Alert rules</ToolbarButton>
          <ToolbarButton as="a" href="#/monitor/actiongroups">Action groups</ToolbarButton>
          <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={load}>Refresh</ToolbarButton>
        </div>
      }>
        <BrowseGrid resourceName="alert rule" items={rules} columns={columns} loading={loading} error={error} onRefresh={load}
          onDelete={async (rows) => { await Promise.all(rows.map((r) => (r.kind === "Metric" ? deleteMetricAlert(r.resourceGroup, r.name) : deleteActivityLogAlert(r.resourceGroup, r.name)))); load(); }}
          csvName="alerts.csv" />
      </CapabilityContainer>

      <NotSimulatedContainer title="Additional alert tools"
        note="Not simulated in Vyomi: View as timeline (preview), Alert processing rules, Prometheus rule groups, Change user response." />
    </MonitorShell>
  );
}
