/* Monitoring: Application Insights is a real "logger" sub-resource (service/loggers); Alerts
 * are real Microsoft.Insights/metricAlerts scoped to this service. Metrics/Logs/Analytics are
 * real dashboards over this service's own stored data (API/product/subscription counts, the
 * real Activity log) — NOT the real APIM gateway request/latency metrics, which Vyomi's APIs
 * never carry live traffic to emit. See azure.apim.monitoring.* in core/capabilities/azure/apim.json. */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Select, ToolbarButton } from "@fluentui/react-components";
import { Add20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { KV, Loading, fmtDate } from "../../kit/common.jsx";
import * as api from "./api.js";

const ID_RE = /^[a-zA-Z0-9][a-zA-Z0-9-._]{0,255}$/;

export function ApplicationInsights({ rg, svc }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.Loggers.list(rg, svc), [rg, svc]);
  const [add, setAdd] = useState(false);
  return (
    <CapabilityContainer id="azure.apim.monitoring.appinsights" title={`${svc} | Application Insights`}>
      <BrowseGrid
        resourceName="logger" rowKey={(r) => r.name} filterPlaceholder="Search loggers"
        items={data || []} loading={loading} error={error} onRefresh={reload}
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add</ToolbarButton>}
        onDelete={async (sel) => {
          for (const r of sel) await api.Loggers.remove(rg, svc, r.name);
          notify.success(`Deleted ${sel.length} logger${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
          reload();
        }}
        csvName="loggers.csv"
        columns={[
          { key: "name", label: "Name" },
          { key: "type", label: "Type", value: (r) => r.properties?.loggerType || "applicationInsights" },
          { key: "resourceId", label: "Resource ID", value: (r) => r.properties?.resourceId || "--" },
        ]}
      />
      <AddLoggerDialog open={add} onClose={() => setAdd(false)} existing={data || []}
        onCreate={async (id, body) => { await api.Loggers.put(rg, svc, id, body); reload(); }} />
    </CapabilityContainer>
  );
}

function AddLoggerDialog({ open, onClose, onCreate, existing }) {
  const notify = useNotify();
  const [f, setF] = useState({ id: "", loggerType: "applicationInsights", instrumentationKey: "" });
  const [busy, setBusy] = useState(false);
  const valid = ID_RE.test(f.id) && !existing.some((l) => l.name.toLowerCase() === f.id.toLowerCase());
  const go = async () => {
    setBusy(true);
    try {
      await onCreate(f.id, { properties: {
        loggerType: f.loggerType, description: `Logger '${f.id}'`,
        credentials: f.loggerType === "applicationInsights" ? { instrumentationKey: f.instrumentationKey || "00000000-0000-0000-0000-000000000000" } : { connectionString: f.instrumentationKey },
      } });
      notify.success(`Logger '${f.id}' was created.`, "Create succeeded");
      setF({ id: "", loggerType: "applicationInsights", instrumentationKey: "" });
      onClose();
    } catch (e) { notify.error(e, "Create failed"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Add logger">
        <DialogBody>
          <DialogTitle>Add logger</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Name" required><Input value={f.id} onChange={(_, d) => setF((x) => ({ ...x, id: d.value }))} aria-label="Name" /></Field>
              <Field label="Type" required>
                <Select value={f.loggerType} onChange={(_, d) => setF((x) => ({ ...x, loggerType: d.value }))} aria-label="Type">
                  <option value="applicationInsights">Application Insights</option>
                  <option value="azureEventHub">Event Hub</option>
                </Select>
              </Field>
              <Field label={f.loggerType === "applicationInsights" ? "Instrumentation key" : "Connection string"}>
                <Input value={f.instrumentationKey} onChange={(_, d) => setF((x) => ({ ...x, instrumentationKey: d.value }))} aria-label="Credentials" />
              </Field>
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!valid || busy} onClick={go}>Create</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

const SEVERITIES = [[0, "0 - Critical"], [1, "1 - Error"], [2, "2 - Warning"], [3, "3 - Informational"], [4, "4 - Verbose"]];

export function Alerts({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listResourceAlerts(a.resourceGroup, a.name), [a.id]);
  const [add, setAdd] = useState(false);
  return (
    <CapabilityContainer id="azure.apim.monitoring.alerts" title={`${a.name} | Alerts`}>
      <BrowseGrid
        resourceName="alert rule" rowKey={(r) => r.id} filterPlaceholder="Search alert rules"
        items={data || []} loading={loading} error={error} onRefresh={reload}
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>New alert rule</ToolbarButton>}
        onDelete={async (sel) => {
          for (const r of sel) await api.deleteResourceAlert(a.resourceGroup, r.name);
          notify.success(`Deleted ${sel.length} alert rule${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
          reload();
        }}
        csvName="alert-rules.csv"
        columns={[
          { key: "name", label: "Name" },
          { key: "severity", label: "Severity", value: (r) => SEVERITIES.find(([s]) => s === r.properties?.severity)?.[1] || r.properties?.severity },
          { key: "enabled", label: "Enabled", value: (r) => (r.properties?.enabled === false ? "No" : "Yes") },
        ]}
      />
      <AddAlertDialog open={add} onClose={() => setAdd(false)} existing={data || []} a={a}
        onCreate={async (id, body) => { await api.putResourceAlert(a.resourceGroup, id, body); reload(); }} />
    </CapabilityContainer>
  );
}

function AddAlertDialog({ open, onClose, onCreate, existing, a }) {
  const notify = useNotify();
  const [f, setF] = useState({ id: "", severity: 3 });
  const [busy, setBusy] = useState(false);
  const valid = ID_RE.test(f.id) && !existing.some((r) => r.name.toLowerCase() === f.id.toLowerCase());
  const go = async () => {
    setBusy(true);
    try {
      await onCreate(f.id, { location: "global", properties: {
        description: `Alert rule '${f.id}' for ${a.name}`, severity: Number(f.severity), enabled: true,
        scopes: [a.id], evaluationFrequency: "PT1M", windowSize: "PT5M",
        criteria: { "odata.type": "Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria", allOf: [
          { criterionType: "StaticThresholdCriterion", name: "Crit1", metricName: "Capacity", operator: "GreaterThan", threshold: 80, timeAggregation: "Average" },
        ] },
      } });
      notify.success(`Alert rule '${f.id}' was created.`, "Create succeeded");
      setF({ id: "", severity: 3 });
      onClose();
    } catch (e) { notify.error(e, "Create failed"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="New alert rule">
        <DialogBody>
          <DialogTitle>New alert rule</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Name" required><Input value={f.id} onChange={(_, d) => setF((x) => ({ ...x, id: d.value }))} aria-label="Name" /></Field>
              <Field label="Severity">
                <Select value={String(f.severity)} onChange={(_, d) => setF((x) => ({ ...x, severity: d.value }))} aria-label="Severity">
                  {SEVERITIES.map(([s, label]) => <option key={s} value={s}>{label}</option>)}
                </Select>
              </Field>
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!valid || busy} onClick={go}>Create</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

function useApimCounts(rg, svc) {
  const apis = useAsync(() => api.Apis.list(rg, svc), [rg, svc]);
  const products = useAsync(() => api.Products.list(rg, svc), [rg, svc]);
  const subs = useAsync(() => api.Subscriptions.list(rg, svc), [rg, svc]);
  return { apis, products, subs, loading: apis.loading || products.loading || subs.loading };
}

export function Metrics({ a }) {
  const { apis, products, subs, loading } = useApimCounts(a.resourceGroup, a.name);
  const activity = useAsync(() => api.listActivityLog(a.resourceGroup, a.name), [a.id]);
  if (loading || activity.loading) return <Loading />;
  const active = (subs.data || []).filter((s) => (s.properties?.state || "active") === "active").length;
  return (
    <CapabilityContainer id="azure.apim.monitoring" title={`${a.name} | Metrics`}>
      <p style={{ fontSize: 13 }} className="vy-muted">Real configuration counts for this service — not live gateway request/latency metrics (Vyomi's APIs don't carry gateway traffic).</p>
      <div className="vy-props" style={{ marginTop: 12 }}>
        <KV label="APIs" value={(apis.data || []).length} />
        <KV label="Products" value={(products.data || []).length} />
        <KV label="Subscriptions" value={(subs.data || []).length} />
        <KV label="Active subscriptions" value={active} />
        <KV label="Management operations recorded" value={(activity.data || []).length} />
      </div>
    </CapabilityContainer>
  );
}

export function Logs({ a }) {
  const { data, loading, error, reload } = useAsync(() => api.listActivityLog(a.resourceGroup, a.name), [a.id]);
  const rows = data || [];
  return (
    <CapabilityContainer id="azure.apim.monitoring" title={`${a.name} | Logs`}>
      <p style={{ fontSize: 13 }} className="vy-muted">Real management-plane operations recorded for this service (the same data as Activity log) — Vyomi has no Log Analytics KQL engine for the real Azure Monitor Logs experience.</p>
      <BrowseGrid
        resourceName="log entry" rowKey={(r) => r.id} filterPlaceholder="Search logs"
        items={rows} loading={loading} error={error} onRefresh={reload}
        csvName="logs.csv"
        columns={[
          { key: "operation", label: "Operation", value: (r) => r.operationName?.localizedValue || r.operationName?.value },
          { key: "status", label: "Status", value: (r) => r.status?.localizedValue || r.status?.value },
          { key: "time", label: "Time", value: (r) => fmtDate(r.eventTimestamp) },
        ]}
      />
    </CapabilityContainer>
  );
}

export function Analytics({ a }) {
  const { apis, products, subs, loading } = useApimCounts(a.resourceGroup, a.name);
  if (loading) return <Loading />;
  const byType = {};
  for (const r of apis.data || []) { const t = r.properties?.apiType || "http"; byType[t] = (byType[t] || 0) + 1; }
  const byScope = {};
  for (const s of subs.data || []) {
    const scope = (s.properties?.scope || "").includes("/products/") ? s.properties.scope.split("/products/")[1] : "All APIs";
    byScope[scope] = (byScope[scope] || 0) + 1;
  }
  const productName = (id) => (products.data || []).find((p) => p.name === id)?.properties?.displayName || id;
  return (
    <CapabilityContainer id="azure.apim.monitoring" title={`${a.name} | Analytics`}>
      <p style={{ fontSize: 13 }} className="vy-muted">Real breakdowns of this service's own configuration — not call-volume analytics (Vyomi's APIs don't carry gateway traffic).</p>
      <section className="vy-section">
        <h3>APIs by type</h3>
        <table className="vy-grid"><thead><tr><th>Type</th><th>Count</th></tr></thead>
          <tbody>{Object.entries(byType).map(([t, c]) => <tr key={t}><td>{t}</td><td>{c}</td></tr>)}
            {!Object.keys(byType).length && <tr><td colSpan={2} className="vy-muted">No APIs to display</td></tr>}</tbody>
        </table>
      </section>
      <section className="vy-section">
        <h3>Subscriptions by product</h3>
        <table className="vy-grid"><thead><tr><th>Product</th><th>Subscriptions</th></tr></thead>
          <tbody>{Object.entries(byScope).map(([s, c]) => <tr key={s}><td>{s === "All APIs" ? s : productName(s)}</td><td>{c}</td></tr>)}
            {!Object.keys(byScope).length && <tr><td colSpan={2} className="vy-muted">No subscriptions to display</td></tr>}</tbody>
        </table>
      </section>
    </CapabilityContainer>
  );
}
