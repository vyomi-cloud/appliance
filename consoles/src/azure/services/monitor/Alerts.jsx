import { useEffect, useMemo, useState } from "react";
import {
  Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Input, Select, Tab, TabList, Textarea, ToolbarButton,
} from "@fluentui/react-components";
import { Add20Regular, ArrowClockwise20Regular, Play20Regular } from "@fluentui/react-icons";
import MonitorShell from "./MonitorShell.jsx";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import {
  changeAlertState, deleteActivityLogAlert, deleteMetricAlert, deletePrometheusRuleGroup, deleteProcessingRule, deleteScheduledQueryRule,
  evaluateAlertsNow, getAlertHistory, getAlertsSummary, listActionGroups, listAlertRules, listFiredAlerts, listPrometheusRuleGroups,
  listProcessingRules, listWorkspaces, putPrometheusRuleGroup, putProcessingRule, putScheduledQueryRule, SEVERITY_LABEL,
} from "./api.js";
import { parseId } from "../../kit/arm.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ErrorBar, fmtDate, Loading } from "../../kit/common.jsx";

const SEV_ROWS = ["Sev0", "Sev1", "Sev2", "Sev3", "Sev4"];
const SEV_NAME = { Sev0: "Critical", Sev1: "Error", Sev2: "Warning", Sev3: "Informational", Sev4: "Verbose" };
const STATES = ["New", "Acknowledged", "Closed"];
const affectedResource = (scopes) => (scopes && scopes[0] ? parseId(scopes[0]).name : "--");

/* ── Summary + fired alerts ─────────────────────────────────────────────────────────── */
function FiredAlerts({ onChanged }) {
  const [alerts, setAlerts] = useState(null);
  const [summary, setSummary] = useState(null);
  const [error, setError] = useState(null);
  const [hist, setHist] = useState(null);
  const load = () => {
    setError(null);
    Promise.all([listFiredAlerts(), getAlertsSummary("severity")]).then(([a, s]) => { setAlerts(a); setSummary(s); onChanged?.(a); }).catch(setError);
  };
  useEffect(load, []);
  const bySev = Object.fromEntries((summary?.values || []).map((v) => [v.name, v.count]));
  const cols = [
    { key: "name", label: "Name", value: (a) => parseId(a.properties.essentials.alertRule).name },
    { key: "sev", label: "Severity", value: (a) => `${a.properties.essentials.severity.replace("Sev", "")} - ${SEV_NAME[a.properties.essentials.severity]}` },
    { key: "res", label: "Affected resource", value: (a) => a.properties.essentials.targetResourceName || "--" },
    { key: "cond", label: "Monitor condition", value: (a) => a.properties.essentials.monitorCondition },
    { key: "resp", label: "User response", value: (a) => a.properties.essentials.alertState },
    { key: "svc", label: "Monitor service", value: (a) => a.properties.essentials.monitorService },
    { key: "fire", label: "Fire time", value: (a) => fmtDate(a.properties.essentials.startDateTime) },
    { key: "sup", label: "Notifications", value: (a) => (a.properties.essentials.actionStatus?.isSuppressed ? "Suppressed" : "Sent") },
  ];
  const setState = async (rows, s) => { try { await Promise.all(rows.map((r) => changeAlertState(r.name, s))); load(); } catch (e) { setError(e); } };
  return (
    <>
      <section className="vy-form-section">
        <h3>Summary</h3>
        {!summary ? <Loading /> : (
          <div className="vy-essentials-grid">
            <div>
              <div className="vy-kv"><span>Total alerts</span><span>{summary.total}</span></div>
              <div className="vy-kv"><span>Critical</span><span>{bySev.Sev0 || 0}</span></div>
            </div>
            <div>
              {SEV_ROWS.slice(1).map((s) => <div className="vy-kv" key={s}><span>{SEV_NAME[s]}</span><span>{bySev[s] || 0}</span></div>)}
            </div>
          </div>
        )}
        <p style={{ fontSize: 12, marginTop: 6 }}>Alerts are raised only when a rule's condition is met on real stored data; rules are evaluated each time this page loads and on "Evaluate now".</p>
      </section>
      <ErrorBar error={error} title="Alerts" />
      <CapabilityContainer id="azure.monitor.fired_alerts" title="Alerts">
        {alerts === null ? <Loading /> : (
          <BrowseGrid resourceName="alert" items={alerts} columns={cols} rowKey={(a) => a.name} loading={false} error={null} onRefresh={load} csvName="fired-alerts.csv"
            pills={[{ key: "cond", label: "Monitor condition", value: (a) => a.properties.essentials.monitorCondition },
              { key: "resp", label: "User response", value: (a) => a.properties.essentials.alertState }]}
            extraCommands={(sel) => (
              <>
                {STATES.map((s) => <ToolbarButton key={s} disabled={!sel.length} onClick={() => setState(sel, s)}>{`Change user response: ${s}`}</ToolbarButton>)}
                <ToolbarButton disabled={sel.length !== 1} onClick={async () => setHist({ alert: sel[0], items: await getAlertHistory(sel[0].name) })}>History</ToolbarButton>
              </>
            )} />
        )}
      </CapabilityContainer>
      <Dialog open={!!hist} onOpenChange={(_, d) => !d.open && setHist(null)}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>Alert history</DialogTitle>
            <DialogContent>
              {hist?.items.map((h, i) => (
                <div key={i} style={{ padding: "4px 0", borderBottom: "1px solid var(--colorNeutralStroke2)" }}>
                  <b>{h.properties.eventType}</b> <span style={{ opacity: 0.7 }}>{fmtDate(h.properties.timestamp)}</span><div>{h.properties.description}</div>
                </div>
              ))}
            </DialogContent>
            <DialogActions><Button onClick={() => setHist(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

/* ── View as timeline: every event of every alert's real history, newest first ──────── */
function Timeline() {
  const [events, setEvents] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    (async () => {
      const alerts = await listFiredAlerts();
      const all = await Promise.all(alerts.map(async (a) => (await getAlertHistory(a.name)).map((h) => ({ ...h.properties, alert: parseId(a.properties.essentials.alertRule).name, target: a.properties.essentials.targetResourceName, sev: a.properties.essentials.severity }))));
      setEvents(all.flat().sort((x, y) => String(y.timestamp).localeCompare(String(x.timestamp))));
    })().catch(setError);
  }, []);
  const days = useMemo(() => {
    const g = {};
    (events || []).forEach((e) => { (g[String(e.timestamp).slice(0, 10)] ||= []).push(e); });
    return Object.entries(g);
  }, [events]);
  return (
    <CapabilityContainer id="azure.monitor.alert_timeline" title="Alert timeline">
      <ErrorBar error={error} title="Timeline" />
      {events === null ? <Loading /> : !events.length ? <p>No alert activity yet.</p> : days.map(([day, es]) => (
        <section key={day} className="vy-form-section">
          <h3>{day}</h3>
          {es.map((e, i) => (
            <div key={i} className="vy-kv" style={{ gap: 12 }}>
              <span style={{ minWidth: 90 }}>{String(e.timestamp).slice(11, 19)}</span>
              <span style={{ minWidth: 70 }}>{e.sev}</span>
              <span style={{ minWidth: 160 }}>{e.alert}{e.target ? ` on ${e.target}` : ""}</span>
              <span>{e.description}</span>
            </div>
          ))}
        </section>
      ))}
    </CapabilityContainer>
  );
}

/* ── Alert rules (metric + activity log + log search) ─────────────────────────────── */
function Rules() {
  const [rules, setRules] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [dlg, setDlg] = useState(false);
  const load = () => { setLoading(true); setError(null); listAlertRules().then(setRules).catch(setError).finally(() => setLoading(false)); };
  useEffect(load, []);
  const columns = [
    { key: "name", label: "Name" },
    { key: "kind", label: "Signal type" },
    { key: "severity", label: "Severity", value: (r) => (r.severity != null ? SEVERITY_LABEL[r.severity] : "--") },
    { key: "resource", label: "Target", value: (r) => affectedResource(r.scopes) },
    { key: "condition", label: "Condition" },
    { key: "enabled", label: "Status", value: (r) => (r.enabled ? "Enabled" : "Disabled") },
  ];
  const del = (r) => (r.kind === "Metric" ? deleteMetricAlert(r.resourceGroup, r.name) : r.kind === "Log search" ? deleteScheduledQueryRule(r.resourceGroup, r.name) : deleteActivityLogAlert(r.resourceGroup, r.name));
  return (
    <CapabilityContainer id="azure.monitor.alert_rules" title="Alert rules" actions={
      <div className="vy-cmdbar" role="toolbar" aria-label="Command bar">
        <ToolbarButton icon={<Add20Regular />} as="a" href="#/monitor/createalertrule">Create</ToolbarButton>
        <ToolbarButton icon={<Add20Regular />} onClick={() => setDlg(true)}>Create log search alert</ToolbarButton>
        <ToolbarButton as="a" href="#/monitor/actiongroups">Action groups</ToolbarButton>
      </div>
    }>
      <BrowseGrid resourceName="alert rule" items={rules} columns={columns} loading={loading} error={error} onRefresh={load}
        onDelete={async (rows) => { await Promise.all(rows.map(del)); load(); }} csvName="alert-rules.csv" />
      {dlg && <LogAlertDialog onClose={(saved) => { setDlg(false); if (saved) load(); }} />}
    </CapabilityContainer>
  );
}

function LogAlertDialog({ onClose }) {
  const [workspaces, setWorkspaces] = useState([]);
  const [groups, setGroups] = useState([]);
  const [f, setF] = useState({ name: "", ws: "", query: "AzureActivity\n| where Level == 'Error'", op: "GreaterThan", threshold: "0", window: "PT15M", freq: "PT5M", sev: "2", ag: "" });
  const [err, setErr] = useState(null);
  useEffect(() => { listWorkspaces().then((w) => { setWorkspaces(w); setF((x) => ({ ...x, ws: w[0]?.id || "" })); }); listActionGroups().then(setGroups); }, []);
  const set = (k) => (_, d) => setF((x) => ({ ...x, [k]: d.value }));
  const save = async () => {
    try {
      const ws = workspaces.find((w) => w.id === f.ws);
      if (!f.name.trim() || !ws) throw new Error("A name and a Log Analytics workspace are required.");
      await putScheduledQueryRule(ws.resourceGroup, f.name.trim(), { location: ws.location, properties: {
        displayName: f.name.trim(), severity: Number(f.sev), enabled: true, scopes: [ws.id], evaluationFrequency: f.freq, windowSize: f.window,
        criteria: { allOf: [{ query: f.query, timeAggregation: "Count", operator: f.op, threshold: Number(f.threshold) }] },
        actions: { actionGroups: f.ag ? [f.ag] : [] } } });
      onClose(true);
    } catch (e) { setErr(e); }
  };
  return (
    <Dialog open onOpenChange={(_, d) => !d.open && onClose(false)}>
      <DialogSurface>
        <DialogBody>
          <DialogTitle>Create log search alert rule</DialogTitle>
          <DialogContent>
            <ErrorBar error={err} title="Could not create the rule" />
            <div className="vy-form-row"><label>Name</label><Input value={f.name} onChange={set("name")} aria-label="Rule name" /></div>
            <div className="vy-form-row"><label>Log Analytics workspace</label><Select value={f.ws} onChange={set("ws")} aria-label="Workspace">{workspaces.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}</Select></div>
            <div className="vy-form-row"><label>KQL query</label><Textarea value={f.query} onChange={set("query")} rows={4} style={{ width: "100%", fontFamily: "monospace" }} aria-label="KQL query" /></div>
            <div className="vy-form-row"><label>Fire when number of results is</label>
              <Select value={f.op} onChange={set("op")} aria-label="Operator">{["GreaterThan", "GreaterThanOrEqual", "LessThan", "LessThanOrEqual", "Equals"].map((o) => <option key={o}>{o}</option>)}</Select>
              <Input value={f.threshold} onChange={set("threshold")} aria-label="Threshold" /></div>
            <div className="vy-form-row"><label>Look back / check every</label>
              <Select value={f.window} onChange={set("window")} aria-label="Window">{["PT5M", "PT15M", "PT30M", "PT1H", "PT6H", "P1D"].map((o) => <option key={o}>{o}</option>)}</Select>
              <Select value={f.freq} onChange={set("freq")} aria-label="Frequency">{["PT1M", "PT5M", "PT15M", "PT30M", "PT1H"].map((o) => <option key={o}>{o}</option>)}</Select></div>
            <div className="vy-form-row"><label>Severity</label><Select value={f.sev} onChange={set("sev")} aria-label="Severity">{Object.entries(SEVERITY_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select></div>
            <div className="vy-form-row"><label>Action group</label><Select value={f.ag} onChange={set("ag")} aria-label="Action group"><option value="">(none)</option>{groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}</Select></div>
          </DialogContent>
          <DialogActions><Button onClick={() => onClose(false)}>Cancel</Button><Button appearance="primary" onClick={save}>Create</Button></DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

/* ── Alert processing rules ──────────────────────────────────────────────────────────── */
function ProcessingRules() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [dlg, setDlg] = useState(false);
  const load = () => { setLoading(true); setError(null); listProcessingRules().then(setItems).catch(setError).finally(() => setLoading(false)); };
  useEffect(load, []);
  const columns = [
    { key: "name", label: "Name" },
    { key: "rg", label: "Resource group", value: (r) => r.resourceGroup },
    { key: "action", label: "Rule type", value: (r) => (r.properties.actions[0]?.actionType === "RemoveAllActionGroups" ? "Suppress notifications" : "Apply action group") },
    { key: "scope", label: "Scope", value: (r) => r.properties.scopes.map((s) => parseId(s).name || s).join(", ") },
    { key: "cond", label: "Filters", value: (r) => r.properties.conditions.map((c) => `${c.field} ${c.operator} ${c.values.join("/")}`).join("; ") || "(all alerts)" },
    { key: "en", label: "Status", value: (r) => (r.properties.enabled ? "Enabled" : "Disabled") },
  ];
  return (
    <CapabilityContainer id="azure.monitor.alert_processing_rules" title="Alert processing rules" actions={
      <div className="vy-cmdbar" role="toolbar" aria-label="Command bar"><ToolbarButton icon={<Add20Regular />} onClick={() => setDlg(true)}>Create</ToolbarButton></div>
    }>
      <BrowseGrid resourceName="alert processing rule" items={items} columns={columns} loading={loading} error={error} onRefresh={load}
        onDelete={async (rows) => { await Promise.all(rows.map((r) => deleteProcessingRule(r.resourceGroup, r.name))); load(); }} csvName="alert-processing-rules.csv" />
      {dlg && <ProcessingRuleDialog onClose={(saved) => { setDlg(false); if (saved) load(); }} />}
    </CapabilityContainer>
  );
}

function ProcessingRuleDialog({ onClose }) {
  const [groups, setGroups] = useState([]);
  const [f, setF] = useState({ name: "", rg: "cloudlearn-rg", scope: "", kind: "RemoveAllActionGroups", ag: "", field: "Severity", op: "Equals", values: "", from: "", until: "" });
  const [err, setErr] = useState(null);
  const sub = (typeof location !== "undefined" && (location.hash.match(/subscriptions\/([^/]+)/) || [])[1]) || "00000000-0000-0000-0000-cloudlearn01";
  useEffect(() => { listActionGroups().then((g) => { setGroups(g); setF((x) => ({ ...x, ag: g[0]?.id || "" })); }); }, []);
  const set = (k) => (_, d) => setF((x) => ({ ...x, [k]: d.value }));
  const save = async () => {
    try {
      if (!f.name.trim()) throw new Error("A rule name is required.");
      const scope = f.scope.trim() || `/subscriptions/${sub}/resourceGroups/${f.rg}`;
      const conditions = f.values.trim() ? [{ field: f.field, operator: f.op, values: f.values.split(",").map((v) => v.trim()).filter(Boolean) }] : [];
      const schedule = f.from || f.until ? { effectiveFrom: f.from || undefined, effectiveUntil: f.until || undefined } : undefined;
      await putProcessingRule(f.rg, f.name.trim(), { location: "global", properties: {
        scopes: [scope], conditions, enabled: true, schedule,
        actions: [f.kind === "AddActionGroups" ? { actionType: "AddActionGroups", actionGroupIds: [f.ag] } : { actionType: "RemoveAllActionGroups" }] } });
      onClose(true);
    } catch (e) { setErr(e); }
  };
  return (
    <Dialog open onOpenChange={(_, d) => !d.open && onClose(false)}>
      <DialogSurface>
        <DialogBody>
          <DialogTitle>Create alert processing rule</DialogTitle>
          <DialogContent>
            <ErrorBar error={err} title="Could not create the rule" />
            <div className="vy-form-row"><label>Name</label><Input value={f.name} onChange={set("name")} aria-label="Rule name" /></div>
            <div className="vy-form-row"><label>Resource group</label><Input value={f.rg} onChange={set("rg")} aria-label="Resource group" /></div>
            <div className="vy-form-row"><label>Scope (resource id; blank = the resource group)</label><Input value={f.scope} onChange={set("scope")} aria-label="Scope" /></div>
            <div className="vy-form-row"><label>Rule type</label><Select value={f.kind} onChange={set("kind")} aria-label="Rule type">
              <option value="RemoveAllActionGroups">Suppress notifications</option><option value="AddActionGroups">Apply action group</option></Select></div>
            {f.kind === "AddActionGroups" && <div className="vy-form-row"><label>Action group</label><Select value={f.ag} onChange={set("ag")} aria-label="Action group">{groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}</Select></div>}
            <div className="vy-form-row"><label>Filter</label>
              <Select value={f.field} onChange={set("field")} aria-label="Filter field">{["Severity", "MonitorService", "MonitorCondition", "SignalType", "TargetResourceType", "TargetResource", "TargetResourceGroup", "AlertRuleName", "Description"].map((o) => <option key={o}>{o}</option>)}</Select>
              <Select value={f.op} onChange={set("op")} aria-label="Filter operator">{["Equals", "NotEquals", "Contains", "DoesNotContain"].map((o) => <option key={o}>{o}</option>)}</Select>
              <Input value={f.values} onChange={set("values")} placeholder="Sev2, Sev3 (blank = all alerts)" aria-label="Filter values" /></div>
            <div className="vy-form-row"><label>Active from / until (UTC ISO, optional)</label>
              <Input value={f.from} onChange={set("from")} placeholder="2026-11-07T00:00:00" aria-label="From" /><Input value={f.until} onChange={set("until")} placeholder="2026-11-08T00:00:00" aria-label="Until" /></div>
          </DialogContent>
          <DialogActions><Button onClick={() => onClose(false)}>Cancel</Button><Button appearance="primary" onClick={save}>Create</Button></DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

/* ── Prometheus rule groups ──────────────────────────────────────────────────────────── */
function PrometheusGroups() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [dlg, setDlg] = useState(false);
  const load = () => { setLoading(true); setError(null); listPrometheusRuleGroups().then(setItems).catch(setError).finally(() => setLoading(false)); };
  useEffect(load, []);
  const columns = [
    { key: "name", label: "Name" },
    { key: "rg", label: "Resource group", value: (r) => r.resourceGroup },
    { key: "rules", label: "Rules", value: (r) => r.properties.rules.length },
    { key: "int", label: "Evaluation interval", value: (r) => r.properties.interval },
    { key: "en", label: "Status", value: (r) => (r.properties.enabled ? "Enabled" : "Disabled") },
  ];
  return (
    <CapabilityContainer id="azure.monitor.prometheus_rule_groups" title="Prometheus rule groups" actions={
      <div className="vy-cmdbar" role="toolbar" aria-label="Command bar"><ToolbarButton icon={<Add20Regular />} onClick={() => setDlg(true)}>Create</ToolbarButton></div>
    }>
      <BrowseGrid resourceName="Prometheus rule group" items={items} columns={columns} loading={loading} error={error} onRefresh={load}
        onDelete={async (rows) => { await Promise.all(rows.map((r) => deletePrometheusRuleGroup(r.resourceGroup, r.name))); load(); }} csvName="prometheus-rule-groups.csv" />
      {dlg && <PrometheusDialog onClose={(saved) => { setDlg(false); if (saved) load(); }} />}
    </CapabilityContainer>
  );
}

function PrometheusDialog({ onClose }) {
  const [f, setF] = useState({ name: "", rg: "cloudlearn-rg", workspace: "", alert: "HighErrorRate", expr: "rate(http_requests_errors_total[5m]) > 1", sev: "3" });
  const [err, setErr] = useState(null);
  const set = (k) => (_, d) => setF((x) => ({ ...x, [k]: d.value }));
  const save = async () => {
    try {
      if (!f.name.trim() || !f.workspace.trim()) throw new Error("A name and the Azure Monitor workspace resource id are required.");
      await putPrometheusRuleGroup(f.rg, f.name.trim(), { location: "eastus", properties: {
        scopes: [f.workspace.trim()], interval: "PT1M", enabled: true,
        rules: [{ alert: f.alert, expression: f.expr, severity: Number(f.sev), for: "PT5M", actions: [] }] } });
      onClose(true);
    } catch (e) { setErr(e); }
  };
  return (
    <Dialog open onOpenChange={(_, d) => !d.open && onClose(false)}>
      <DialogSurface>
        <DialogBody>
          <DialogTitle>Create Prometheus rule group</DialogTitle>
          <DialogContent>
            <ErrorBar error={err} title="Could not create the rule group" />
            <div className="vy-form-row"><label>Name</label><Input value={f.name} onChange={set("name")} aria-label="Rule group name" /></div>
            <div className="vy-form-row"><label>Resource group</label><Input value={f.rg} onChange={set("rg")} aria-label="Resource group" /></div>
            <div className="vy-form-row"><label>Azure Monitor workspace id</label><Input value={f.workspace} onChange={set("workspace")} aria-label="Workspace id" /></div>
            <div className="vy-form-row"><label>Alert rule name</label><Input value={f.alert} onChange={set("alert")} aria-label="Alert name" /></div>
            <div className="vy-form-row"><label>PromQL expression</label><Textarea value={f.expr} onChange={set("expr")} rows={3} style={{ width: "100%", fontFamily: "monospace" }} aria-label="Expression" /></div>
          </DialogContent>
          <DialogActions><Button onClick={() => onClose(false)}>Cancel</Button><Button appearance="primary" onClick={save}>Create</Button></DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

export default function Alerts() {
  const [tab, setTab] = useState("alerts");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState(null);
  const [nonce, setNonce] = useState(0);
  const evaluate = async () => {
    setBusy(true);
    try {
      const r = await evaluateAlertsNow();
      setNote(`Evaluated ${r.evaluated} rule(s): ${r.fired} fired, ${r.resolved} resolved${r.errors?.length ? `, ${r.errors.length} error(s): ${r.errors[0]}` : ""}.`);
      setNonce((n) => n + 1);
    } catch (e) { setNote(String(e.message || e)); } finally { setBusy(false); }
  };
  return (
    <MonitorShell active="alerts">
      <div className="vy-cmdbar" role="toolbar" aria-label="Command bar">
        <ToolbarButton icon={<Add20Regular />} as="a" href="#/monitor/createalertrule">Create</ToolbarButton>
        <ToolbarButton as="a" href="#/monitor/actiongroups">Action groups</ToolbarButton>
        <ToolbarButton icon={<Play20Regular />} disabled={busy} onClick={evaluate}>Evaluate now</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={() => setNonce((n) => n + 1)}>Refresh</ToolbarButton>
      </div>
      {note && <p role="status" style={{ fontSize: 12 }}>{note}</p>}
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Alerts">
        <Tab value="alerts">Alerts</Tab>
        <Tab value="timeline">View as timeline</Tab>
        <Tab value="rules">Alert rules</Tab>
        <Tab value="processing">Alert processing rules</Tab>
        <Tab value="prometheus">Prometheus rule groups</Tab>
      </TabList>
      <div key={`${tab}-${nonce}`} style={{ marginTop: 12 }}>
        {tab === "alerts" && <FiredAlerts />}
        {tab === "timeline" && <Timeline />}
        {tab === "rules" && <Rules />}
        {tab === "processing" && <ProcessingRules />}
        {tab === "prometheus" && <PrometheusGroups />}
      </div>
    </MonitorShell>
  );
}
