/* Application Insights for an App Service / Function app: a real Microsoft.Insights/components ARM resource, linked to the
 * app through its APPLICATIONINSIGHTS_CONNECTION_STRING setting, with telemetry read from the observability store
 * (core/observability_core.appinsights_query: OTLP spans / logs posted to /_obs plus requests Vyomi measured for the app).
 * No data -> empty tables. There is no Kusto engine, so there is no free-form Logs query here. */
import { useEffect, useState } from "react";
import { Button, Input, Tab, TabList, ToolbarButton } from "@fluentui/react-components";
import { ArrowClockwise20Regular } from "@fluentui/react-icons";
import { restJson } from "../../common/wire.js";
import { useNotify } from "../../common/notify.jsx";
import { useAsync } from "../../common/useAsync.js";
import { armType } from "./arm.js";
import { CapabilityContainer } from "./Capability.jsx";
import { ErrorBar, Loading } from "./common.jsx";

export const Components = armType("Microsoft.Insights", "components", "2020-02-02");
const KEY = "APPLICATIONINSIGHTS_CONNECTION_STRING";
const ikeyOf = (cs) => (/InstrumentationKey=([0-9a-f-]+)/i.exec(cs || "") || [])[1];
export const queryTelemetry = (names, ikey, windowSeconds = 3600) =>
  restJson("GET", "/_obs/appinsights/query", { query: { names: names.join(","), ikey: ikey || "", window: String(windowSeconds) } });

const fmt = (t) => new Date(t * 1000).toLocaleString();
const Tile = ({ t, v, id }) => <div className="vy-section"><h3>{t}</h3><div style={{ fontSize: 24, fontWeight: 600 }} data-testid={id}>{v}</div></div>;
const Grid = ({ cols, rows, empty, label, id }) => (
  <table className="vy-grid" aria-label={label}>
    <thead><tr>{cols.map(([h]) => <th key={h}>{h}</th>)}</tr></thead>
    <tbody>
      {rows.length ? rows.map((r, i) => <tr key={i} data-testid={id + "-row"}>{cols.map(([h, f]) => <td key={h}>{f(r)}</td>)}</tr>)
        : <tr><td colSpan={cols.length} className="vy-muted" data-testid={id + "-empty"}>{empty}</td></tr>}
    </tbody>
  </table>
);

/** `site`: the ARM site (id, name, resourceGroup); `settings`: {get, put} app-settings accessors for the app. */
export default function AppInsights({ site, getSettings, putSettings, capId }) {
  const notify = useNotify();
  const settings = useAsync(getSettings, [site.id]);
  const comps = useAsync(() => Components.list(), [site.id]);
  const [tab, setTab] = useState("overview");
  const [name, setName] = useState(`${site.name}-ai`);
  const ik = ikeyOf((settings.data || {})[KEY]);
  const comp = (comps.data || []).find((c) => ik && c.properties?.InstrumentationKey === ik);
  const names = [site.name, comp?.name].filter(Boolean);
  const tel = useAsync(() => (comp ? queryTelemetry(names, ik) : Promise.resolve(null)), [comp?.id]);
  useEffect(() => { if (!comp) return undefined; const id = setInterval(tel.reload, 5000); return () => clearInterval(id); }, [comp?.id, tel.reload]);

  const enable = async () => {
    try {
      const c = await Components.put(site.resourceGroup, name, { location: "eastus", kind: "web", properties: { Application_Type: "web", Flow_Type: "Bluefield", Request_Source: "rest" } });
      await putSettings({ ...(settings.data || {}), [KEY]: c.properties.ConnectionString, APPINSIGHTS_INSTRUMENTATIONKEY: c.properties.InstrumentationKey });
      notify.success(`Application Insights '${name}' created and linked.`, "Application Insights enabled");
      settings.reload(); comps.reload();
    } catch (e) { notify.error(e, "Failed to enable Application Insights"); }
  };
  const disable = async () => {
    try {
      const s = { ...(settings.data || {}) }; delete s[KEY]; delete s.APPINSIGHTS_INSTRUMENTATIONKEY;
      await putSettings(s); notify.success("Application Insights is no longer linked to this app.", "Disabled"); settings.reload();
    } catch (e) { notify.error(e, "Failed"); }
  };

  const t = tel.data, s = t?.summary || {};
  return (
    <>
      <div className="vy-panel-title">{site.name} | Application Insights</div>
      <CapabilityContainer id={capId} title="Application Insights">
        <ErrorBar error={settings.error || comps.error || tel.error} />
        {settings.loading || comps.loading ? <Loading /> : !comp ? (
          <section className="vy-form-section" aria-label="Enable Application Insights">
            <p style={{ fontSize: 13 }}>This app is not linked to an Application Insights resource. Turning it on creates a real Microsoft.Insights/components resource and sets the app's connection string.</p>
            <Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Application Insights resource name" />
            <Button appearance="primary" onClick={enable} style={{ marginLeft: 8 }}>Turn on Application Insights</Button>
          </section>
        ) : (
          <>
            <p style={{ fontSize: 13 }} data-testid="ai-linked">Linked resource: <b>{comp.name}</b> - instrumentation key {ik}. Send OpenTelemetry (OTLP/HTTP JSON) to <code>{"<host>"}/_obs</code> with service.name = {site.name}.</p>
            <div className="vy-cmdbar" role="toolbar" aria-label="Application Insights commands">
              <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={tel.reload}>Refresh</ToolbarButton>
              <ToolbarButton onClick={disable}>Turn off</ToolbarButton>
            </div>
            <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Application Insights tabs">
              {[["overview", "Overview"], ["requests", "Performance (requests)"], ["failures", "Failures"], ["dependencies", "Dependencies"], ["events", "Events"], ["traces", "Traces"]].map(([id, l]) => <Tab key={id} value={id}>{l}</Tab>)}
            </TabList>
            {!t ? <Loading /> : (
              <>
                {tab === "overview" && (
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 12, margin: "8px 0" }}>
                    <Tile t="Server requests" v={s.requests} id="ai-requests" /><Tile t="Failed requests" v={s.failedRequests} id="ai-failed" />
                    <Tile t="Avg response (ms)" v={s.avgDurationMs} /><Tile t="p95 response (ms)" v={s.p95DurationMs} />
                    <Tile t="Dependency calls" v={s.dependencies} /><Tile t="Exceptions" v={s.exceptions} /><Tile t="Events" v={s.events} />
                  </div>
                )}
                {tab === "requests" && <Grid id="ai-req" label="Requests" empty="No requests in the last hour." cols={[["Time", (r) => fmt(r.timestamp)], ["Name", (r) => r.name], ["Result", (r) => String(r.resultCode)], ["Duration (ms)", (r) => r.durationMs], ["Success", (r) => (r.success ? "Yes" : "No")], ["Operation ID", (r) => r.operationId]]} rows={t.requests} />}
                {tab === "failures" && <Grid id="ai-fail" label="Failures" empty="No failures or exceptions in the last hour." cols={[["Time", (r) => fmt(r.timestamp)], ["Name", (r) => r.name], ["Type", (r) => r.type || "exception"], ["Message", (r) => r.message || ""]]} rows={t.exceptions} />}
                {tab === "dependencies" && <Grid id="ai-dep" label="Dependencies" empty="No dependency calls in the last hour." cols={[["Time", (r) => fmt(r.timestamp)], ["Name", (r) => r.name], ["Duration (ms)", (r) => r.durationMs], ["Success", (r) => (r.success ? "Yes" : "No")]]} rows={t.dependencies} />}
                {tab === "events" && <Grid id="ai-ev" label="Events" empty="No custom events (span events) in the last hour." cols={[["Time", (r) => fmt(r.timestamp)], ["Event", (r) => r.name], ["Operation ID", (r) => r.operationId]]} rows={t.events} />}
                {tab === "traces" && <Grid id="ai-tr" label="Traces" empty="No log records in the last hour." cols={[["Time", (r) => fmt(r.timestamp)], ["Severity", (r) => r.severity], ["Message", (r) => r.message]]} rows={t.traces} />}
              </>
            )}
          </>
        )}
      </CapabilityContainer>
    </>
  );
}
