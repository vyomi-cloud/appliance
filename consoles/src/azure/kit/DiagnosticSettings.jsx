/* Diagnostic settings blade body shared by every Azure resource blade: list / add / edit / delete
 * Microsoft.Insights/diagnosticSettings scoped to this resource's id (real ARM extension resource,
 * core/azure_monitor_core.py). Destination validation is the engine's; delivery is not modelled. */
import { useState } from "react";
import { Button, Checkbox, Field, Input, Select } from "@fluentui/react-components";
import { useAsync } from "../../common/useAsync.js";
import { useNotify } from "../../common/notify.jsx";
import { deleteDiagnosticSetting, listDiagnosticSettings, listWorkspaces, putDiagnosticSetting } from "../services/monitor/api.js";
import BrowseGrid from "./BrowseGrid.jsx";
import { CapabilityContainer } from "./Capability.jsx";

const CATEGORIES = {
  "microsoft.keyvault/vaults": ["AuditEvent", "AzurePolicyEvaluationDetails"],
  "microsoft.sql/servers": ["SQLInsights", "AutomaticTuning", "Errors", "Timeouts", "Blocks", "Deadlocks"],
  "microsoft.documentdb/databaseaccounts": ["DataPlaneRequests", "QueryRuntimeStatistics", "PartitionKeyStatistics", "ControlPlaneRequests"],
  "microsoft.containerservice/managedclusters": ["kube-apiserver", "kube-audit", "kube-controller-manager", "kube-scheduler", "cluster-autoscaler", "guard"],
  "microsoft.appconfiguration/configurationstores": ["HttpRequest", "Audit"],
  "microsoft.cognitiveservices/accounts": ["Audit", "RequestResponse", "Trace"],
  "microsoft.resources/subscriptions/resourcegroups": [],
};
const typeOf = (id) => { const p = (id || "").split("/").filter(Boolean); const i = p.findIndex((x) => x.toLowerCase() === "providers"); return i < 0 ? "" : `${p[i + 1]}/${p[i + 2]}`.toLowerCase(); };

export default function DiagnosticSettings({ id, name, title }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => listDiagnosticSettings(id), [id]);
  const ws = useAsync(() => listWorkspaces().catch(() => []), []);
  const [form, setForm] = useState(null);
  const cats = CATEGORIES[typeOf(id)] || [];
  const open = (s) => setForm(s ? { name: s.name, ws: s.properties.workspaceId || "", sa: s.properties.storageAccountId || "", eh: s.properties.eventHubAuthorizationRuleId || "", useWs: !!s.properties.workspaceId, useSa: !!s.properties.storageAccountId, useEh: !!s.properties.eventHubAuthorizationRuleId, all: (s.properties.logs || []).some((l) => l.categoryGroup === "allLogs" && l.enabled), cats: (s.properties.logs || []).filter((l) => l.category && l.enabled).map((l) => l.category), metrics: (s.properties.metrics || []).some((m) => m.enabled), edit: true }
    : { name: "", ws: ws.data?.[0]?.id || "", sa: "", eh: "", useWs: true, useSa: false, useEh: false, all: true, cats: [], metrics: true });
  const save = async () => {
    const p = { logs: [...(form.all ? [{ categoryGroup: "allLogs", enabled: true }] : []), ...form.cats.map((c) => ({ category: c, enabled: true }))], metrics: form.metrics ? [{ category: "AllMetrics", enabled: true }] : [] };
    if (form.useWs) p.workspaceId = form.ws;
    if (form.useSa) p.storageAccountId = form.sa;
    if (form.useEh) p.eventHubAuthorizationRuleId = form.eh;
    try { await putDiagnosticSetting(id, form.name, { properties: p }); notify.success(`Diagnostic setting '${form.name}' saved.`, "Save succeeded"); setForm(null); reload(); }
    catch (e) { notify.error(e, "Failed to save the diagnostic setting"); }
  };
  const set = (patch) => setForm((f) => ({ ...f, ...patch }));
  return (
    <>
      <div className="vy-panel-title">{title || `${name} | Diagnostic settings`}</div>
      <CapabilityContainer id="azure.common.diagnostic_settings" title="Diagnostic settings">
        {!form ? (
          <BrowseGrid
            resourceName="diagnostic setting" rowKey={(s) => s.name} items={data || []} loading={loading} error={error} onRefresh={reload} onCreate={() => open(null)}
            onDelete={async (rows) => { await Promise.all(rows.map((r) => deleteDiagnosticSetting(id, r.name))); reload(); }}
            csvName="diagnostic-settings.csv"
            columns={[
              { key: "name", label: "Name", render: (s) => <a href="#" onClick={(e) => { e.preventDefault(); open(s); }}>{s.name}</a>, value: (s) => s.name },
              { key: "dest", label: "Destination details", value: (s) => [s.properties.workspaceId && "Log Analytics workspace", s.properties.storageAccountId && "Storage account", s.properties.eventHubAuthorizationRuleId && "Event hub"].filter(Boolean).join(", ") || "--" },
              { key: "logs", label: "Log categories", value: (s) => (s.properties.logs || []).filter((l) => l.enabled).length },
              { key: "metrics", label: "Metric categories", value: (s) => (s.properties.metrics || []).filter((m) => m.enabled).length },
            ]}
          />
        ) : (
          <section className="vy-form-section" aria-label="Diagnostic setting">
            <h3>{form.edit ? "Edit" : "Add"} diagnostic setting</h3>
            <Field label="Diagnostic setting name"><Input value={form.name} disabled={form.edit} onChange={(_, d) => set({ name: d.value })} aria-label="Diagnostic setting name" /></Field>
            <h4>Logs</h4>
            <Checkbox label="allLogs (category group)" checked={form.all} onChange={(_, d) => set({ all: !!d.checked })} />
            {cats.map((c) => <div key={c}><Checkbox label={c} checked={form.cats.includes(c)} onChange={(_, d) => set({ cats: d.checked ? [...form.cats, c] : form.cats.filter((x) => x !== c) })} /></div>)}
            <h4>Metrics</h4>
            <Checkbox label="AllMetrics" checked={form.metrics} onChange={(_, d) => set({ metrics: !!d.checked })} />
            <h4>Destination details</h4>
            <Checkbox label="Send to Log Analytics workspace" checked={form.useWs} onChange={(_, d) => set({ useWs: !!d.checked })} />
            {form.useWs && <Select value={form.ws} onChange={(_, d) => set({ ws: d.value })} aria-label="Log Analytics workspace">{!form.ws && <option value="">Select a workspace</option>}{(ws.data || []).map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}</Select>}
            <div><Checkbox label="Archive to a storage account" checked={form.useSa} onChange={(_, d) => set({ useSa: !!d.checked })} /></div>
            {form.useSa && <Input value={form.sa} placeholder="Storage account resource id" onChange={(_, d) => set({ sa: d.value })} aria-label="Storage account id" />}
            <div><Checkbox label="Stream to an event hub" checked={form.useEh} onChange={(_, d) => set({ useEh: !!d.checked })} /></div>
            {form.useEh && <Input value={form.eh} placeholder="Event hub authorization rule id" onChange={(_, d) => set({ eh: d.value })} aria-label="Event hub rule id" />}
            <div className="vy-cmdbar" style={{ marginTop: 12 }}>
              <Button appearance="primary" disabled={!form.name || !(form.useWs || form.useSa || form.useEh)} onClick={save}>Save</Button>
              <Button onClick={() => setForm(null)}>Discard</Button>
            </div>
          </section>
        )}
      </CapabilityContainer>
    </>
  );
}
