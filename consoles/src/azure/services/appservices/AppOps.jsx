/* App Service operations panels (Web App blade): Default documents, Path mappings, Error pages,
 * Health check, API definition, API Management, App Service plan, Quotas, Authentication,
 * Autoscale, Certificates, Clone App, WebJobs, Service Connector. Each is a native ARM call into
 * core/azure_webapp_core.py (and core/azure_monitor_core.py for autoscale), so az / azure-mgmt-web
 * see exactly what the console wrote. Capability badges come from core/capabilities/azure/appservices.json. */
import { useState } from "react";
import { Button, Field, Input, Radio, RadioGroup, Select, Switch, Textarea } from "@fluentui/react-components";
import { Add20Regular, Delete20Regular, Play20Regular, Save20Regular } from "@fluentui/react-icons";
import { restJson } from "../../../common/wire.js";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { armType, parseId } from "../../kit/arm.js";
import { CapabilityContainer, saveNotice } from "../../kit/Capability.jsx";
import { ErrorBar, KV, Loading, fmtBytes } from "../../kit/common.jsx";
import * as api from "./api.js";
import { getAutoscaleSetting, putAutoscaleSetting, deleteAutoscaleSetting, listAutoscaleSettings } from "../monitor/api.js";

const WEBV = "2023-12-01";
const q = { "api-version": WEBV };
const sitePath = (rg, name) => api.SITES.path(rg, name);
const CERTS = armType("Microsoft.Web", "certificates", WEBV);
const title = (name, t) => <div className="vy-panel-title">{name} | {t}</div>;
const SaveBar = ({ onSave, busy, onDiscard }) => (
  <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
    <Button appearance="primary" icon={<Save20Regular />} disabled={busy} onClick={onSave}>{busy ? "Saving..." : "Save"}</Button>
    {onDiscard && <Button onClick={onDiscard}>Discard</Button>}
  </div>
);
function useSave(reload) {
  const notify = useNotify();
  const [busy, setBusy] = useState(false);
  return [busy, async (fn, ok, capId) => {
    setBusy(true);
    try { await fn(); notify.success(ok + (capId ? saveNotice(capId) : ""), "Save succeeded"); reload && reload(); }
    catch (e) { notify.error(e, "Save failed"); }
    finally { setBusy(false); }
  }];
}
const CFG = "azure.appservices.webapp.siteconfigpanels";

// ── Configuration tabs: Default documents / Path mappings / Error pages ─────────────────────
export function DefaultDocuments({ a, rg, name, reload }) {
  const [docs, setDocs] = useState([...(a.properties?.siteConfig?.defaultDocuments || []), ""]);
  const [busy, save] = useSave(reload);
  const upd = (i, v) => { const x = docs.map((d, j) => (j === i ? v : d)); if (x[x.length - 1]) x.push(""); setDocs(x); };
  return (
    <CapabilityContainer id={CFG} title="Default documents">
      <p style={{ fontSize: 13 }}>Files served when a request names a directory, in order.</p>
      {docs.map((d, i) => <div key={i} style={{ marginBottom: 6 }}><Input value={d} placeholder="Add a document name" aria-label={`Default document ${i + 1}`} onChange={(_, x) => upd(i, x.value)} /></div>)}
      <SaveBar busy={busy} onDiscard={reload} onSave={() => save(() => api.updateSiteConfig(rg, name, { defaultDocuments: docs.filter(Boolean) }), "Default documents were saved.", CFG)} />
    </CapabilityContainer>
  );
}
export function PathMappings({ a, rg, name, reload }) {
  const c = a.properties?.siteConfig || {};
  const [apps, setApps] = useState(c.virtualApplications || [{ virtualPath: "/", physicalPath: "site\\wwwroot", preloadEnabled: true }]);
  const [maps, setMaps] = useState(c.handlerMappings || []);
  const [busy, save] = useSave(reload);
  return (
    <CapabilityContainer id={CFG} title="Path mappings">
      <h4>Virtual applications and directories</h4>
      {apps.map((v, i) => (
        <div key={i} style={{ display: "flex", gap: 8, marginBottom: 6 }}>
          <Input value={v.virtualPath} aria-label={`Virtual path ${i + 1}`} onChange={(_, d) => setApps(apps.map((x, j) => j === i ? { ...x, virtualPath: d.value } : x))} />
          <Input value={v.physicalPath} aria-label={`Physical path ${i + 1}`} onChange={(_, d) => setApps(apps.map((x, j) => j === i ? { ...x, physicalPath: d.value } : x))} />
          <Button icon={<Delete20Regular />} aria-label={`Remove virtual path ${i + 1}`} onClick={() => setApps(apps.filter((_, j) => j !== i))} />
        </div>))}
      <Button icon={<Add20Regular />} onClick={() => setApps([...apps, { virtualPath: "/", physicalPath: "site\\wwwroot", preloadEnabled: false }])}>New virtual application or directory</Button>
      <h4>Handler mappings</h4>
      {maps.map((m, i) => (
        <div key={i} style={{ display: "flex", gap: 8, marginBottom: 6 }}>
          {["extension", "scriptProcessor", "arguments"].map((k) => <Input key={k} placeholder={k} value={m[k] || ""} aria-label={`${k} ${i + 1}`} onChange={(_, d) => setMaps(maps.map((x, j) => j === i ? { ...x, [k]: d.value } : x))} />)}
          <Button icon={<Delete20Regular />} aria-label={`Remove handler mapping ${i + 1}`} onClick={() => setMaps(maps.filter((_, j) => j !== i))} />
        </div>))}
      <Button icon={<Add20Regular />} onClick={() => setMaps([...maps, { extension: "", scriptProcessor: "", arguments: "" }])}>Add handler mapping</Button>
      <SaveBar busy={busy} onDiscard={reload} onSave={() => save(() => api.updateSiteConfig(rg, name, { virtualApplications: apps, handlerMappings: maps }), "Path mappings were saved.", CFG)} />
    </CapabilityContainer>
  );
}
const ERR_CODES = ["403", "404", "500"];
export function ErrorPages({ a, rg, name, reload }) {
  const [pages, setPages] = useState(a.properties?.siteConfig?.errorPages || {});
  const [busy, save] = useSave(reload);
  return (
    <CapabilityContainer id={CFG} title="Error pages (preview)">
      <p style={{ fontSize: 13 }}>Custom HTML returned for an HTTP status code.</p>
      {ERR_CODES.map((c) => (
        <Field key={c} label={`${c} error page (HTML)`}><Textarea rows={3} value={pages[c] || ""} aria-label={`${c} error page`} onChange={(_, d) => setPages({ ...pages, [c]: d.value })} /></Field>))}
      <SaveBar busy={busy} onDiscard={reload} onSave={() => save(() => api.updateSiteConfig(rg, name, { errorPages: pages }), "Error pages were saved.", CFG)} />
    </CapabilityContainer>
  );
}

// ── Health check / API definition / API Management ───────────────────────────────────────
export function HealthCheck({ a, rg, name, reload }) {
  const c = a.properties?.siteConfig || {};
  const [on, setOn] = useState(!!c.healthCheckPath);
  const [path, setPath] = useState(c.healthCheckPath || "/");
  const [busy, save] = useSave(reload);
  return (
    <>
      {title(name, "Health check")}
      <CapabilityContainer id={CFG} title="Health check">
        <p style={{ fontSize: 13, maxWidth: 640 }}>Health check pings this path on each instance and removes unhealthy ones from the load balancer.</p>
        <Field label="Enable"><Switch checked={on} onChange={(_, d) => setOn(d.checked)} aria-label="Enable health check" /></Field>
        {on && <Field label="Path"><Input value={path} onChange={(_, d) => setPath(d.value)} aria-label="Health check path" /></Field>}
        <SaveBar busy={busy} onDiscard={reload} onSave={() => save(() => api.updateSiteConfig(rg, name, { healthCheckPath: on ? path : "" }), "Health check was saved.", CFG)} />
      </CapabilityContainer>
    </>
  );
}
export function ApiDefinition({ a, rg, name, reload }) {
  const [url, setUrl] = useState(a.properties?.siteConfig?.apiDefinition?.url || "");
  const [busy, save] = useSave(reload);
  return (
    <>
      {title(name, "API definition")}
      <CapabilityContainer id={CFG} title="API definition">
        <p style={{ fontSize: 13 }}>The URL of the Swagger / OpenAPI document that describes this app's API.</p>
        <Field label="API definition location"><Input value={url} placeholder="https://.../swagger.json" onChange={(_, d) => setUrl(d.value)} aria-label="API definition location" /></Field>
        <SaveBar busy={busy} onDiscard={reload} onSave={() => save(() => api.updateSiteConfig(rg, name, { apiDefinition: url ? { url } : null }), "API definition was saved.", CFG)} />
      </CapabilityContainer>
    </>
  );
}
export function ApiManagement({ a, rg, name, reload, cap = CFG }) {
  const svc = useAsync(async () => (await restJson("GET", `/subscriptions/${parseId(a.id).subscription}/providers/Microsoft.ApiManagement/service`, { query: { "api-version": "2022-08-01" } })).value || [], [a.id]);
  const [sel, setSel] = useState(a.properties?.siteConfig?.apiManagementConfig?.id || "");
  const [busy, save] = useSave(reload);
  return (
    <>
      {title(name, "API Management")}
      <CapabilityContainer id={cap} title="API Management">
        <p style={{ fontSize: 13 }}>Link this app to an API Management instance. Saving imports this app's API into the gateway (one operation per function for a Function App, a wildcard API for a Web App); unlinking removes it. Open the API in API Management to add policies such as rate limits.</p>
        {svc.loading ? <Loading /> : (
          <Field label="API Management instance">
            <Select value={sel} onChange={(_, d) => setSel(d.value)} aria-label="API Management instance">
              <option value="">None</option>{(svc.data || []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </Select>
          </Field>)}
        <SaveBar busy={busy} onDiscard={reload} onSave={() => save(() => api.updateSiteConfig(rg, name, { apiManagementConfig: sel ? { id: sel } : null }), "API Management link was saved.", cap)} />
      </CapabilityContainer>
    </>
  );
}

// ── App Service plan / Quotas ────────────────────────────────────────────────────────────
export function PlanPage({ a, name }) {
  const pid = a.properties?.serverFarmId || "";
  const p = parseId(pid);
  const plan = useAsync(() => api.getPlan(p.resourceGroup, p.name), [pid]);
  return (
    <>
      {title(name, "App Service plan")}
      {plan.loading ? <Loading /> : plan.error ? <ErrorBar error={plan.error} /> : (
        <div className="vy-props">
          <KV label="Name" value={<a href={`#/appservices/plans`}>{plan.data.name}</a>} />
          <KV label="Resource group" value={p.resourceGroup} />
          <KV label="Operating system" value={plan.data.properties?.reserved ? "Linux" : "Windows"} />
          <KV label="Pricing plan" value={`${plan.data.sku?.tier} (${plan.data.sku?.name})`} />
          <KV label="Instances (workers)" value={plan.data.sku?.capacity} />
          <KV label="Apps on this plan" value={plan.data.properties?.numberOfSites} />
        </div>)}
    </>
  );
}
export function Quotas({ a, rg, name }) {
  const u = useAsync(async () => (await restJson("GET", `${sitePath(rg, name)}/usages`, { query: q })).value || [], [rg, name]);
  return (
    <>
      {title(name, "Quotas")}
      <CapabilityContainer id="azure.appservices.webapp.quotas" title="Quotas">
        {u.loading ? <Loading /> : u.error ? <ErrorBar error={u.error} /> : (
          <table className="vy-table" aria-label="Quotas"><thead><tr><th>Name</th><th>Limit</th><th>Current value</th></tr></thead>
            <tbody>{u.data.map((r) => (
              <tr key={r.name.value}><td>{r.name.localizedValue}</td><td>{r.unit === "Bytes" ? fmtBytes(r.limit) : r.limit}</td><td>{r.unit === "Bytes" ? fmtBytes(r.currentValue) : r.currentValue}</td></tr>))}</tbody></table>)}
      </CapabilityContainer>
    </>
  );
}

// ── Authentication (config/authsettingsV2) ───────────────────────────────────────────────
export function Authentication({ a, rg, name }) {
  const auth = useAsync(async () => (await restJson("GET", `${sitePath(rg, name)}/config/authsettingsV2`, { query: q })).properties, [rg, name]);
  const [busy, save] = useSave(auth.reload);
  const on = !!auth.data?.platform?.enabled;
  return (
    <>
      {title(name, "Authentication")}
      <CapabilityContainer id="azure.appservices.webapp.authentication" title="App Service authentication">
        {auth.loading ? <Loading /> : (
          <>
            <Field label="App Service authentication">
              <Switch checked={on} aria-label="App Service authentication" disabled={busy}
                onChange={(_, d) => save(() => restJson("PUT", `${sitePath(rg, name)}/config/authsettingsV2`, { query: q, body: { properties: { platform: { enabled: d.checked } } } }), `Authentication was turned ${d.checked ? "on" : "off"}.`, "azure.appservices.webapp.authentication")} /></Field>
            {on && <div className="vy-props"><KV label="Bearer token (Vyomi issues one shared token)" value={<code>{auth.data.token}</code>} /></div>}
            <p style={{ fontSize: 12, marginTop: 8 }}>Identity providers (Microsoft Entra, Google, ...) are not wired: there is no interactive sign-in flow.</p>
          </>)}
      </CapabilityContainer>
    </>
  );
}

// ── Autoscale (Microsoft.Insights/autoscaleSettings targeting the app's plan) ────────────
export function Autoscale({ a, rg, name, reload }) {
  const planId = a.properties?.serverFarmId;
  const cur = useAsync(async () => (await listAutoscaleSettings()).find((s) => String(s.properties?.targetResourceUri).toLowerCase() === String(planId).toLowerCase()), [planId]);
  const [f, setF] = useState(null);
  const [busy, save] = useSave(cur.reload);
  const s = cur.data;
  const p0 = s?.properties?.profiles?.[0];
  const outR = (p0?.rules || []).find((r) => r.scaleAction.direction === "Increase");
  const inR = (p0?.rules || []).find((r) => r.scaleAction.direction === "Decrease");
  const v = f || (s ? { min: p0.capacity.minimum, max: p0.capacity.maximum, def: p0.capacity.default, metric: outR?.metricTrigger.metricName || "Requests", out: outR?.metricTrigger.threshold ?? "", inn: inR?.metricTrigger.threshold ?? "" }
    : { min: 1, max: 3, def: 1, metric: "Requests", out: "", inn: "" });
  const history = useAsync(async () => (s ? (await restJson("GET", `${s.id}/vyomiHistory`, { query: { "api-version": "2022-10-01" } })).value || [] : []), [s?.id, cur.data]);
  const mkRule = (dir, op, thr) => ({ metricTrigger: { metricName: v.metric, metricResourceUri: planId, timeGrain: "PT1M", statistic: "Average", timeWindow: "PT5M", timeAggregation: "Average", operator: op, threshold: Number(thr) },
    scaleAction: { direction: dir, type: "ChangeCount", value: "1", cooldown: "PT5M" } });
  const rules = [v.out !== "" && mkRule("Increase", "GreaterThan", v.out), v.inn !== "" && mkRule("Decrease", "LessThan", v.inn)].filter(Boolean);
  const AID = "azure.appservices.webapp.autoscale";
  return (
    <>
      {title(name, "Scale out (App Service plan)")}
      <CapabilityContainer id={AID} title="Autoscale">
        {cur.loading ? <Loading /> : (
          <>
            <p style={{ fontSize: 13 }}>{s ? `Custom autoscale is configured (${s.name}).` : "Autoscale is not configured: the plan uses manual scale."}</p>
            {["min", "max", "def"].map((k) => <Field key={k} label={{ min: "Minimum", max: "Maximum", def: "Default" }[k]}><Input type="number" style={{ width: 120 }} value={String(v[k])} aria-label={{ min: "Autoscale minimum", max: "Autoscale maximum", def: "Autoscale default" }[k]} onChange={(_, d) => setF({ ...v, [k]: d.value })} /></Field>)}
            <Field label="Scale on metric"><Select value={v.metric} aria-label="Autoscale metric" onChange={(_, d) => setF({ ...v, metric: d.value })}><option>Requests</option><option>CpuPercentage</option><option>Http5xx</option><option>AverageResponseTime</option></Select></Field>
            <Field label="Scale out by 1 when the 5-minute average is above"><Input type="number" style={{ width: 120 }} value={String(v.out)} aria-label="Scale out threshold" onChange={(_, d) => setF({ ...v, out: d.value })} /></Field>
            <Field label="Scale in by 1 when the 5-minute average is below"><Input type="number" style={{ width: 120 }} value={String(v.inn)} aria-label="Scale in threshold" onChange={(_, d) => setF({ ...v, inn: d.value })} /></Field>
            <p style={{ fontSize: 12 }}>Evaluated against the request series the app host really recorded (CpuPercentage is a load gauge derived from requests per second per instance).</p>
            <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
              <Button appearance="primary" disabled={busy} onClick={() => save(() => putAutoscaleSetting(parseId(planId).resourceGroup, s?.name || `${parseId(planId).name}-autoscale`, { location: a.location, properties: { targetResourceUri: planId, enabled: true, profiles: [{ name: "default", capacity: { minimum: String(v.min), maximum: String(v.max), default: String(v.def) }, rules }] } }), "Autoscale setting was saved.", AID)}>Save autoscale</Button>
              {s && <Button disabled={busy} onClick={() => save(() => deleteAutoscaleSetting(s.resourceGroup, s.name), "Autoscale setting was deleted.")}>Switch to manual scale</Button>}
            </div>
            {s && <><h4 style={{ marginTop: 16 }}>Run history</h4>
              <table className="vy-table" aria-label="Autoscale run history"><thead><tr><th>Time</th><th>From</th><th>To</th><th>Reason</th></tr></thead>
                <tbody>{(history.data || []).filter((h) => h.from !== undefined).slice().reverse().map((h, i) => <tr key={i}><td>{new Date(h.time * 1000).toLocaleString()}</td><td>{h.from}</td><td>{h.to}</td><td>{h.reason}</td></tr>)}
                  {!(history.data || []).some((h) => h.from !== undefined) && <tr><td colSpan={4}>No scale actions yet.</td></tr>}</tbody></table></>}
          </>)}
      </CapabilityContainer>
    </>
  );
}

// ── Certificates ─────────────────────────────────────────────────────────────────────────
export function Certificates({ a, rg, name }) {
  const certs = useAsync(() => CERTS.list(rg), [rg]);
  const [busy, save] = useSave(certs.reload);
  const [host, setHost] = useState("");
  const [pfx, setPfx] = useState(null);
  const [cname, setCname] = useState("");
  const CID = "azure.appservices.webapp.certificates";
  const readFile = (f) => { const r = new FileReader(); r.onload = () => setPfx(String(r.result).split(",")[1]); r.readAsDataURL(f); };
  return (
    <>
      {title(name, "Certificates")}
      <CapabilityContainer id={CID} title="Certificates">
        {certs.loading ? <Loading /> : certs.error ? <ErrorBar error={certs.error} /> : (
          <table className="vy-table" aria-label="Certificates"><thead><tr><th>Name</th><th>Host names</th><th>Thumbprint</th><th>Issuer</th><th>Expires</th><th /></tr></thead>
            <tbody>{(certs.data || []).map((c) => (
              <tr key={c.id}><td>{c.name}</td><td>{(c.properties.hostNames || []).join(", ")}</td><td><code>{c.properties.thumbprint}</code></td><td>{c.properties.issuer}</td><td>{c.properties.expirationDate}</td>
                <td><Button icon={<Delete20Regular />} aria-label={`Delete certificate ${c.name}`} onClick={() => save(() => CERTS.remove(rg, c.name), `Certificate '${c.name}' was deleted.`)} /></td></tr>))}
              {!certs.data?.length && <tr><td colSpan={6}>No certificates in this resource group.</td></tr>}</tbody></table>)}
        <h4 style={{ marginTop: 16 }}>Upload a certificate (.pfx)</h4>
        <Field label="Host name (optional)"><Input value={host} onChange={(_, d) => setHost(d.value)} aria-label="Certificate host name" /></Field>
        <Field label="PFX file"><input type="file" accept=".pfx" aria-label="PFX file" onChange={(e) => e.target.files[0] && readFile(e.target.files[0])} /></Field>
        <Button appearance="primary" disabled={busy || !pfx} onClick={() => save(() => CERTS.put(rg, `cert-${Date.now().toString(36)}`, { location: a.location, properties: { pfxBlob: pfx, password: "", hostNames: host ? [host] : [], serverFarmId: a.properties?.serverFarmId } }), "Certificate was uploaded.")}>Upload</Button>
        <h4 style={{ marginTop: 16 }}>Create an App Service managed certificate</h4>
        <Field label="Custom domain"><Input value={cname} onChange={(_, d) => setCname(d.value)} aria-label="Managed certificate domain" /></Field>
        <Button disabled={busy || !cname} onClick={() => save(() => CERTS.put(rg, `managed-${cname.replace(/[^a-z0-9]/gi, "-")}`, { location: a.location, properties: { canonicalName: cname, serverFarmId: a.properties?.serverFarmId } }), "Managed certificate was created.")}>Create</Button>
      </CapabilityContainer>
    </>
  );
}

// ── Clone App ────────────────────────────────────────────────────────────────────────────
export function CloneApp({ a, rg, name }) {
  const notify = useNotify();
  const plans = useAsync(() => api.listPlans(), []);
  const [nn, setNn] = useState(`${name}-clone`);
  const [plan, setPlan] = useState("");
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try {
      const [settings, conns] = await Promise.all([api.getAppSettings(rg, name), api.getConnectionStrings(rg, name)]);
      const { siteConfig, serverFarmId, ...props } = a.properties;
      const pid = plan || serverFarmId;
      await api.createSite(rg, nn, { location: a.location, kind: a.kind, tags: a.tags, properties: { serverFarmId: pid, httpsOnly: props.httpsOnly, siteConfig: { ...siteConfig } } });
      await api.updateAppSettings(rg, nn, settings); await api.updateConnectionStrings(rg, nn, conns);
      notify.success(`'${nn}' was created from '${name}'.`, "Clone succeeded"); location.hash = `#/appservices/${encodeURIComponent(rg)}/${encodeURIComponent(nn)}`;
    } catch (e) { notify.error(e, "Clone failed"); } finally { setBusy(false); }
  };
  return (
    <>
      {title(name, "Clone App")}
      <CapabilityContainer id="azure.appservices.webapp.clone" title="Clone app">
        <Field label="Name" required><Input value={nn} onChange={(_, d) => setNn(d.value)} aria-label="Clone name" /></Field>
        <Field label="App Service plan">
          <Select value={plan} onChange={(_, d) => setPlan(d.value)} aria-label="Clone App Service plan"><option value="">Same plan as the source</option>{(plans.data || []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</Select></Field>
        <Button appearance="primary" disabled={busy || !nn} onClick={run}>{busy ? "Cloning..." : "Clone"}</Button>
      </CapabilityContainer>
    </>
  );
}

// ── WebJobs ──────────────────────────────────────────────────────────────────────────────
export function WebJobs({ a, rg, name }) {
  const notify = useNotify();
  const sp = sitePath(rg, name);
  const jobs = useAsync(async () => {
    const [t, c] = await Promise.all(["triggeredwebjobs", "continuouswebjobs"].map((k) => restJson("GET", `${sp}/${k}`, { query: q })));
    return [...(t.value || []), ...(c.value || [])];
  }, [rg, name]);
  const [hist, setHist] = useState(null);
  const [nn, setNn] = useState(""); const [kind, setKind] = useState("triggeredwebjobs"); const [code, setCode] = useState("print('hello from a WebJob')");
  const [busy, save] = useSave(jobs.reload);
  const WID = "azure.appservices.webapp.webjobs";
  const showHistory = async (j) => setHist({ job: j.name, rows: (await restJson("GET", `${sp}/triggeredwebjobs/${j.name}/history`, { query: q })).value });
  return (
    <>
      {title(name, "WebJobs")}
      <CapabilityContainer id={WID} title="WebJobs">
        {jobs.loading ? <Loading /> : jobs.error ? <ErrorBar error={jobs.error} /> : (
          <table className="vy-table" aria-label="WebJobs"><thead><tr><th>Name</th><th>Type</th><th>Status</th><th>Actions</th></tr></thead>
            <tbody>{jobs.data.map((j) => {
              const trig = j.properties.jobType === "Triggered";
              return (<tr key={j.id}><td>{j.name}</td><td>{j.properties.jobType}</td><td>{trig ? (j.properties.latestRun?.status || "Never run") : j.properties.status}</td>
                <td style={{ display: "flex", gap: 6 }}>
                  {trig ? <><Button icon={<Play20Regular />} aria-label={`Run ${j.name}`} onClick={() => save(() => restJson("POST", `${sp}/triggeredwebjobs/${j.name}/run`, { query: q }), `WebJob '${j.name}' ran.`)}>Run</Button>
                    <Button aria-label={`Logs ${j.name}`} onClick={() => showHistory(j)}>Logs</Button></>
                    : <Button aria-label={`${j.properties.status === "Running" ? "Stop" : "Start"} ${j.name}`} onClick={() => save(() => restJson("POST", `${sp}/continuouswebjobs/${j.name}/${j.properties.status === "Running" ? "stop" : "start"}`, { query: q }), `WebJob '${j.name}' updated.`)}>{j.properties.status === "Running" ? "Stop" : "Start"}</Button>}
                  <Button icon={<Delete20Regular />} aria-label={`Delete ${j.name}`} onClick={() => save(() => restJson("DELETE", `${sp}/${trig ? "triggered" : "continuous"}webjobs/${j.name}`, { query: q }), `WebJob '${j.name}' was deleted.`)} /></td></tr>);
            })}{!jobs.data.length && <tr><td colSpan={4}>No WebJobs.</td></tr>}</tbody></table>)}
        {hist && <div style={{ marginTop: 12 }}><h4>Run history: {hist.job}</h4>{hist.rows.map((r) => <pre key={r.name} style={{ fontSize: 12 }}>{r.properties.start_time}  {r.properties.status}{"\n"}{r.properties.output}{r.properties.error || ""}</pre>)}{!hist.rows.length && <p>No runs yet.</p>}</div>}
        <h4 style={{ marginTop: 16 }}>Add WebJob</h4>
        <Field label="Name"><Input value={nn} onChange={(_, d) => setNn(d.value)} aria-label="WebJob name" /></Field>
        <Field label="Type"><RadioGroup value={kind} onChange={(_, d) => setKind(d.value)} aria-label="WebJob type"><Radio value="triggeredwebjobs" label="Triggered" /><Radio value="continuouswebjobs" label="Continuous" /></RadioGroup></Field>
        <Field label="Python script"><Textarea rows={4} value={code} onChange={(_, d) => setCode(d.value)} aria-label="WebJob script" /></Field>
        <Button appearance="primary" icon={<Add20Regular />} disabled={busy || !nn} onClick={() => save(() => restJson("PUT", `${sp}/${kind}/${nn}`, { query: q, body: { properties: { script: code, runtime: "python" } } }), `WebJob '${nn}' was added.`)}>Add</Button>
      </CapabilityContainer>
    </>
  );
}

// ── Service Connector ────────────────────────────────────────────────────────────────────
const TARGETS = [["Microsoft.Storage", "storageAccounts", "2023-01-01"], ["Microsoft.KeyVault", "vaults", "2023-02-01"], ["Microsoft.AppConfiguration", "configurationStores", "2023-03-01"],
  ["Microsoft.ServiceBus", "namespaces", "2022-10-01"], ["Microsoft.DocumentDB", "databaseAccounts", "2023-11-15"], ["Microsoft.Sql", "servers", "2023-05-01-preview"]];
export function ServiceConnector({ a, rg, name, cap = "azure.appservices.webapp.serviceconnector" }) {
  const sp = sitePath(rg, name);
  const lp = `${sp}/providers/Microsoft.ServiceLinker/linkers`;
  const lq = { "api-version": "2022-05-01" };
  const links = useAsync(async () => (await restJson("GET", lp, { query: lq })).value || [], [rg, name]);
  const targets = useAsync(async () => (await Promise.all(TARGETS.map(([p, t, v]) => armType(p, t, v).list().catch(() => [])))).flat(), []);
  const [tid, setTid] = useState(""); const [auth, setAuth] = useState("secret"); const [ln, setLn] = useState("");
  const [busy, save] = useSave(links.reload);
  const SID = cap;
  return (
    <>
      {title(name, "Service Connector")}
      <CapabilityContainer id={SID} title="Service Connector">
        {links.loading ? <Loading /> : links.error ? <ErrorBar error={links.error} /> : (
          <table className="vy-table" aria-label="Connections"><thead><tr><th>Name</th><th>Target</th><th>Auth</th><th>App settings added</th><th /></tr></thead>
            <tbody>{links.data.map((l) => (
              <tr key={l.id}><td>{l.name}</td><td>{parseId(l.properties.targetService.id).name}</td><td>{l.properties.authInfo.authType}</td><td>{l.properties.appSettings.join(", ")}</td>
                <td><Button icon={<Delete20Regular />} aria-label={`Delete connection ${l.name}`} onClick={() => save(() => restJson("DELETE", `${lp}/${l.name}`, { query: lq }), `Connection '${l.name}' was deleted.`)} /></td></tr>))}
              {!links.data.length && <tr><td colSpan={5}>No connections.</td></tr>}</tbody></table>)}
        <h4 style={{ marginTop: 16 }}>Create connection</h4>
        <Field label="Connection name"><Input value={ln} onChange={(_, d) => setLn(d.value)} aria-label="Connection name" /></Field>
        <Field label="Target service"><Select value={tid} onChange={(_, d) => setTid(d.value)} aria-label="Target service"><option value="">Select...</option>{(targets.data || []).map((t) => <option key={t.id} value={t.id}>{t.name} ({t.type.split("/").pop()})</option>)}</Select></Field>
        <Field label="Authentication"><Select value={auth} onChange={(_, d) => setAuth(d.value)} aria-label="Connection authentication"><option value="secret">Connection string / secret</option><option value="systemAssignedIdentity">System assigned managed identity</option></Select></Field>
        <Button appearance="primary" disabled={busy || !tid || !ln} onClick={() => save(() => restJson("PUT", `${lp}/${ln}`, { query: lq, body: { properties: { targetService: { type: "AzureResource", id: tid }, authInfo: { authType: auth }, clientType: "none" } } }), `Connection '${ln}' was created; its app settings were added.`)}>Create</Button>
      </CapabilityContainer>
    </>
  );
}
