/* One resource's own "Diagnostic settings" blade (reached from the Monitor-wide picker,
 * DiagnosticSettings.jsx) — list / add / delete Microsoft.Insights/diagnosticSettings
 * extension resources scoped to this resource's id. */
import { useEffect, useState } from "react";
import { Button, Input, Select } from "@fluentui/react-components";
import MonitorShell from "./MonitorShell.jsx";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { deleteDiagnosticSetting, listDiagnosticSettings, listWorkspaces, putDiagnosticSetting } from "./api.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { Loading } from "../../kit/common.jsx";

export default function DiagnosticSettingsResource() {
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const resourceId = params.get("id") || "";
  const resourceName = params.get("name") || "";
  const resourceType = params.get("type") || "";
  const [items, setItems] = useState(null);
  const [error, setError] = useState(null);
  const [adding, setAdding] = useState(false);
  const [workspaces, setWorkspaces] = useState([]);
  const [name, setName] = useState("");
  const [workspace, setWorkspace] = useState("");

  const load = () => { setError(null); listDiagnosticSettings(resourceId).then(setItems).catch(setError); };
  useEffect(load, [resourceId]);
  useEffect(() => { listWorkspaces().then((ws) => { setWorkspaces(ws); setWorkspace(ws[0]?.id || ""); }).catch(() => setWorkspaces([])); }, []);

  const columns = [
    { key: "name", label: "Name" },
    { key: "dest", label: "Destination details", value: (s) => s.properties.workspaceId ? "Log Analytics workspace" : s.properties.storageAccountId ? "Storage account" : s.properties.eventHubAuthorizationRuleId ? "Event hub" : "--" },
    { key: "logs", label: "Log categories", value: (s) => (s.properties.logs || []).filter((l) => l.enabled).length },
    { key: "metrics", label: "Metric categories", value: (s) => (s.properties.metrics || []).filter((m) => m.enabled).length },
  ];

  return (
    <MonitorShell active="diagnosticsettings" pageTitle={`Diagnostic settings | ${resourceName}`}>
      <p>{resourceType} <b>{resourceName}</b></p>
      <CapabilityContainer id="azure.monitor.diagnostic_settings" title="Diagnostic settings">
        {items === null ? <Loading /> : (
          <BrowseGrid resourceName="diagnostic setting" items={items} columns={columns} loading={false} error={error}
            onRefresh={load} onCreate={() => setAdding(true)}
            onDelete={async (rows) => { await Promise.all(rows.map((r) => deleteDiagnosticSetting(resourceId, r.name))); load(); }}
            csvName="diagnostic-settings.csv" />
        )}
        {adding && (
          <section className="vy-form-section">
            <h3>Add diagnostic setting</h3>
            <div className="vy-form-row"><label>Diagnostic setting name</label>
              <Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Diagnostic setting name" />
            </div>
            <div className="vy-form-row"><label>Log Analytics workspace</label>
              {workspaces.length ? (
                <Select value={workspace} onChange={(_, d) => setWorkspace(d.value)} aria-label="Log Analytics workspace">
                  {workspaces.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
                </Select>
              ) : <p>No Log Analytics workspace yet. <a href="#/monitor/createloganalyticsworkspace">Create one</a></p>}
            </div>
            <div className="vy-cmdbar">
              <Button appearance="primary" disabled={!name || !workspace} onClick={async () => {
                await putDiagnosticSetting(resourceId, name, {
                  properties: { workspaceId: workspace, logs: [{ categoryGroup: "allLogs", enabled: true }], metrics: [{ category: "AllMetrics", enabled: true }] },
                });
                setAdding(false); setName(""); load();
              }}>Save</Button>
              <Button onClick={() => setAdding(false)}>Cancel</Button>
            </div>
          </section>
        )}
      </CapabilityContainer>
    </MonitorShell>
  );
}
