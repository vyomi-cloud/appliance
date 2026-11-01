/* Container App resource blade: left resource menu + panels. Overview, Containers, Revisions,
 * Revision management, Scale, Ingress, Custom domains (validation only), Secrets,
 * Authentication, Identity, Activity log, Access control (IAM), Tags, Diagnostic settings,
 * Export template and Locks are backed by native ARM calls (core/azure_app_core.py); the rest
 * render their honest capability level via CapabilityContainer. */
import { useEffect, useState } from "react";
import {
  Button, Checkbox, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input,
  Link, Radio, RadioGroup, Select, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow,
  ToolbarButton,
} from "@fluentui/react-components";
import { Add20Regular, ArrowClockwise20Regular, Delete20Regular, Eye20Regular, Play20Regular, Stop20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { locationLabel } from "../../kit/arm.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import ResourceBlade from "../../kit/ResourceBlade.jsx";
import { Essentials, ErrorBar, Glyph, Loading, NotSimulatedContainer, fmtDate } from "../../kit/common.jsx";
import { remember, forget } from "../../kit/recent.js";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";
import { AccessControlIam, ActivityLog, DiagnosticSettings, ExportTemplate, Locks, MiniTable, Tags } from "./Shared.jsx";

export const MENU = [
  { id: "overview", label: "Overview" },
  { id: "activitylog", label: "Activity log" },
  { id: "iam", label: "Access control (IAM)" },
  { id: "tags", label: "Tags" },
  { id: "diagnose", label: "Diagnose and solve problems" },
  { id: "events", label: "Events" },
  { group: "Application", items: [
    { id: "containers", label: "Containers" },
    { id: "revisions", label: "Revisions" },
    { id: "revisionmanagement", label: "Revision management" },
    { id: "scale", label: "Scale" },
  ] },
  { group: "Networking", items: [
    { id: "ingress", label: "Ingress" },
    { id: "customdomains", label: "Custom domains" },
    { id: "networking", label: "Networking" },
  ] },
  { group: "Settings", items: [
    { id: "secrets", label: "Secrets" },
    { id: "authentication", label: "Authentication" },
    { id: "identity", label: "Identity" },
    { id: "dapr", label: "Dapr configuration" },
    { id: "serviceconnector", label: "Service Connector" },
    { id: "console", label: "Console" },
    { id: "continuousdeployment", label: "Continuous deployment" },
    { id: "locks", label: "Locks" },
  ] },
  { group: "Monitoring", items: [
    { id: "metrics", label: "Metrics" },
    { id: "alerts", label: "Alerts" },
    { id: "logstream", label: "Log stream" },
    { id: "diagnosticsettings", label: "Diagnostic settings" },
  ] },
  { group: "Automation", items: [{ id: "exporttemplate", label: "Export template" }] },
  { group: "Help", items: [{ id: "resourcehealth", label: "Resource health" }, { id: "supportrequest", label: "New support request" }] },
];
const LABEL = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
const CAP = {
  diagnose: "azure.containerapps.app.tools", events: "azure.containerapps.app.tools",
  resourcehealth: "azure.containerapps.app.tools", supportrequest: "azure.containerapps.app.tools",
  networking: "azure.containerapps.app.networking", dapr: "azure.containerapps.app.networking",
  serviceconnector: "azure.containerapps.app.networking", console: "azure.containerapps.app.networking",
  continuousdeployment: "azure.containerapps.app.networking",
  metrics: "azure.containerapps.app.monitoring", alerts: "azure.containerapps.app.monitoring", logstream: "azure.containerapps.app.monitoring",
};

export default function ContainerAppBlade({ params }) {
  const { rg, name } = params;
  const panel = params.panel || "overview";
  const app = useAsync(() => api.getApp(rg, name), [rg, name, panel]);
  const self = `#/containerapps/${encodeURIComponent(rg)}/${encodeURIComponent(name)}`;
  const resPath = app.data ? api.APPS.path(rg, name) : null;
  useEffect(() => { if (app.data) remember({ name, type: "Container App", href: self }); }, [!!app.data, self]);

  let body;
  if (app.loading && !app.data) body = <Loading />;
  else if (app.error) body = <><ErrorBar error={app.error} title="Failed to load the container app" /><Link href="#/containerapps">Back to Container Apps</Link></>;
  else {
    const a = app.data, reload = app.reload;
    const P = {
      overview: () => <Overview a={a} reload={reload} self={self} />,
      activitylog: () => <ActivityLog resPath={resPath} name={a.name} />,
      iam: () => <AccessControlIam resPath={resPath} name={a.name} capId="azure.containerapps.iam" />,
      tags: () => <Tags a={a} name={a.name} reload={reload} save={(tags) => api.updateAppTags(rg, a.name, tags)} />,
      containers: () => <Containers a={a} rg={rg} name={a.name} reload={reload} />,
      revisions: () => <Revisions rg={rg} name={a.name} mode={a.properties?.configuration?.activeRevisionsMode} />,
      revisionmanagement: () => <RevisionManagement a={a} rg={rg} name={a.name} reload={reload} />,
      scale: () => <Scale a={a} rg={rg} name={a.name} reload={reload} />,
      ingress: () => <Ingress a={a} rg={rg} name={a.name} reload={reload} />,
      customdomains: () => <CustomDomains rg={rg} name={a.name} />,
      secrets: () => <Secrets a={a} rg={rg} name={a.name} reload={reload} />,
      authentication: () => <Authentication rg={rg} name={a.name} />,
      identity: () => <Identity a={a} rg={rg} name={a.name} reload={reload} />,
      locks: () => <Locks resPath={resPath} name={a.name} />,
      diagnosticsettings: () => <DiagnosticSettings resPath={resPath} name={a.name} />,
      exporttemplate: () => <ExportTemplate a={a} name={a.name} type="Microsoft.App/containerApps" />,
    }[panel];
    body = P ? P() : <CapabilityContainer id={CAP[panel] || "azure.containerapps.app.tools"} title={`${a.name} | ${LABEL[panel] || panel}`} />;
  }

  return (
    <ResourceBlade
      title={panel === "overview" ? name : `${name} | ${LABEL[panel] || panel}`} subtitle="Container App"
      glyph={<Glyph id="containerapps" />} closeHref="#/containerapps"
      menu={MENU} active={panel} hrefFor={(id) => (id === "overview" ? self : `${self}/${id}`)}
    >
      {body}
    </ResourceBlade>
  );
}

// ── Overview ─────────────────────────────────────────────────────────────────────────────
function Overview({ a, reload, self }) {
  const notify = useNotify();
  const sub = useSubscription();
  const [del, setDel] = useState(false);
  const revs = useAsync(() => api.listRevisions(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const p = a.properties || {};
  const ing = p.configuration?.ingress;
  const tags = Object.entries(a.tags || {});
  const act = async (fn, label) => {
    try { await fn(); notify.success(`'${a.name}' ${label}.`, `${label[0].toUpperCase()}${label.slice(1)}`); reload(); }
    catch (e) { notify.error(e, `${label} failed`); }
  };
  return (
    <>
      <div className="vy-cmdbar" role="toolbar" aria-label="Overview commands">
        <ToolbarButton icon={<Play20Regular />} disabled={p.runningStatus === "Running"} onClick={() => act(() => api.startApp(a.resourceGroup, a.name), "started")}>Start</ToolbarButton>
        <ToolbarButton icon={<Stop20Regular />} disabled={p.runningStatus === "Stopped"} onClick={() => act(() => api.stopApp(a.resourceGroup, a.name), "stopped")}>Stop</ToolbarButton>
        <ToolbarButton icon={<Delete20Regular />} onClick={() => setDel(true)}>Delete</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={() => { reload(); revs.reload(); }}>Refresh</ToolbarButton>
      </div>
      <Essentials
        left={[
          ["Resource group", <Link href="#/resourcegroups">{a.resourceGroup}</Link>],
          ["Status", p.runningStatus],
          ["Location", locationLabel(a.location)],
          ["Subscription", sub.displayName || sub.id],
          ["Container Apps Environment", <Link href={`#/containerapps/environments/${a.resourceGroup}/${api.envName(p.managedEnvironmentId)}`}>{api.envName(p.managedEnvironmentId)}</Link>],
        ]}
        right={[
          ["Application Url", ing?.fqdn ? <a href={`https://${ing.fqdn}`} target="_blank" rel="noreferrer">https://{ing.fqdn}</a> : "--"],
          ["Latest revision", p.latestRevisionName],
          ["Active revisions mode", p.configuration?.activeRevisionsMode || "Single"],
          ["Tags", <span>{tags.length ? tags.map(([k, v]) => `${k} : ${v}`).join(", ") : ""} <Link href={`${self}/tags`}>{tags.length ? "Edit" : "Add tags"}</Link></span>],
        ]}
      />
      <section className="vy-section" style={{ marginTop: 12 }}><h3>Revisions</h3>
        <MiniTable columns={["Revision", "Active", "Created", "Traffic %", "Replicas"]} empty="No revisions"
          rows={(revs.data || []).map((r) => (
            <tr key={r.name}>
              <td><Link href={`${self}/revisions`}>{r.name}</Link></td>
              <td>{r.properties?.active ? "True" : "False"}</td>
              <td>{fmtDate(r.properties?.createdTime)}</td>
              <td>{r.properties?.trafficWeight ?? 0}</td>
              <td>{r.properties?.replicas ?? 0}</td>
            </tr>
          ))} />
      </section>
      <DeleteDialog open={del} onClose={() => setDel(false)} resourceType="container app" names={[a.name]}
        onConfirm={async () => {
          await api.deleteApp(a.resourceGroup, a.name);
          forget(self);
          notify.success(`Container app '${a.name}' was deleted.`, "Delete succeeded");
          navigate("containerapps");
        }} />
    </>
  );
}

// ── Containers ───────────────────────────────────────────────────────────────────────────
function Containers({ a, rg, name, reload }) {
  const notify = useNotify();
  const c0 = (a.properties?.template?.containers || [])[0] || {};
  const [f, setF] = useState({ name: c0.name || name, image: c0.image || "", cpu: String(c0.resources?.cpu || 0.5), env: [...(c0.env || []).filter((e) => !e.secretRef), { name: "", value: "" }] });
  const [busy, setBusy] = useState(false);
  useEffect(() => setF({ name: c0.name || name, image: c0.image || "", cpu: String(c0.resources?.cpu || 0.5), env: [...(c0.env || []).filter((e) => !e.secretRef), { name: "", value: "" }] }), [a]);
  const save = async () => {
    setBusy(true);
    try {
      const secretEnv = (c0.env || []).filter((e) => e.secretRef);
      await api.updateApp(rg, name, { location: a.location, properties: { ...a.properties,
        template: { ...a.properties.template, containers: [{ ...c0, name: f.name, image: f.image, resources: { cpu: Number(f.cpu), memory: api.memFor(Number(f.cpu)) },
          env: [...f.env.filter((e) => e.name).map((e) => ({ name: e.name, value: e.value })), ...secretEnv] }] } } });
      notify.success(`Container '${f.name}' was updated; a new revision was created.`, "Save succeeded");
      reload();
    } catch (e) { notify.error(e, "Save failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">{name} | Containers</div>
      <section className="vy-section"><h3>Container details</h3>
        <Field label="Name"><Input value={f.name} onChange={(_, d) => setF((x) => ({ ...x, name: d.value }))} aria-label="Container name" /></Field>
        <Field label="Image" required><Input value={f.image} onChange={(_, d) => setF((x) => ({ ...x, image: d.value }))} aria-label="Image" style={{ width: "100%" }} /></Field>
        <Field label="CPU and Memory">
          <Select value={f.cpu} onChange={(_, d) => setF((x) => ({ ...x, cpu: d.value }))} aria-label="CPU and Memory">
            {api.CPU_CHOICES.map((c) => <option key={c} value={c}>{c} CPU cores, {api.memFor(c)} memory</option>)}
          </Select>
        </Field>
      </section>
      <section className="vy-section"><h3>Environment variables</h3>
        <table className="vy-grid" style={{ maxWidth: 700 }}>
          <thead><tr><th>Name</th><th>Value</th></tr></thead>
          <tbody>
            {f.env.map((v, i) => (
              <tr key={i}>
                <td><Input size="small" value={v.name} onChange={(_, d) => setF((x) => { const xs = [...x.env]; xs[i] = { ...xs[i], name: d.value }; if (i === xs.length - 1 && d.value) xs.push({ name: "", value: "" }); return { ...x, env: xs }; })} aria-label={`Environment variable name ${i + 1}`} /></td>
                <td><Input size="small" value={v.value} onChange={(_, d) => setF((x) => { const xs = [...x.env]; xs[i] = { ...xs[i], value: d.value }; return { ...x, env: xs }; })} aria-label={`Environment variable value ${i + 1}`} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <div style={{ display: "flex", gap: 8 }}>
        <Button appearance="primary" disabled={!f.image || busy} onClick={save}>{busy ? "Saving..." : "Save"}</Button>
      </div>
    </>
  );
}

// ── Revisions ────────────────────────────────────────────────────────────────────────────
function Revisions({ rg, name, mode }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listRevisions(rg, name), [rg, name]);
  const [sel, setSel] = useState(null);
  const act = async (fn, label) => {
    try { await fn(); notify.success(`Revision '${sel}' ${label}.`, `${label[0].toUpperCase()}${label.slice(1)}`); reload(); }
    catch (e) { notify.error(e, `${label} failed`); }
  };
  return (
    <>
      <div className="vy-panel-title">{name} | Revisions</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Revisions commands">
        <ToolbarButton disabled={!sel} onClick={() => act(() => api.activateRevision(rg, name, sel), "activated")}>Activate</ToolbarButton>
        <ToolbarButton disabled={!sel || mode === "Single"} onClick={() => act(() => api.deactivateRevision(rg, name, sel), "deactivated")}>Deactivate</ToolbarButton>
        <ToolbarButton disabled={!sel} onClick={() => act(() => api.restartRevision(rg, name, sel), "restarted")}>Restart</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
      </div>
      {loading ? <Loading /> : error ? <ErrorBar error={error} /> : (
        <Table size="small" aria-label="Revisions">
          <TableHeader><TableRow>
            <TableHeaderCell style={{ width: 32 }} /><TableHeaderCell>Revision</TableHeaderCell><TableHeaderCell>Active</TableHeaderCell>
            <TableHeaderCell>Created</TableHeaderCell><TableHeaderCell>Traffic %</TableHeaderCell><TableHeaderCell>Replicas</TableHeaderCell>
            <TableHeaderCell>Provisioning status</TableHeaderCell><TableHeaderCell>Running status</TableHeaderCell><TableHeaderCell>Health state</TableHeaderCell>
          </TableRow></TableHeader>
          <TableBody>
            {(data || []).map((r) => (
              <TableRow key={r.name} aria-selected={sel === r.name}>
                <TableCell><Radio checked={sel === r.name} onChange={() => setSel(r.name)} aria-label={`Select ${r.name}`} /></TableCell>
                <TableCell>{r.name}</TableCell><TableCell>{r.properties?.active ? "True" : "False"}</TableCell>
                <TableCell>{fmtDate(r.properties?.createdTime)}</TableCell><TableCell>{r.properties?.trafficWeight ?? 0}</TableCell>
                <TableCell>{r.properties?.replicas ?? 0}</TableCell><TableCell>{r.properties?.provisioningState}</TableCell>
                <TableCell>{r.properties?.runningState}</TableCell><TableCell>{r.properties?.healthState}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {!loading && !(data || []).length && <p className="vy-muted" style={{ fontSize: 13 }}>No revisions.</p>}
    </>
  );
}

// ── Revision management ─────────────────────────────────────────────────────────────────
function RevisionManagement({ a, rg, name, reload }) {
  const notify = useNotify();
  const revs = useAsync(() => api.listRevisions(rg, name), [rg, name]);
  const [weights, setWeights] = useState({});
  const [busy, setBusy] = useState(false);
  const mode = a.properties?.configuration?.activeRevisionsMode || "Single";
  useEffect(() => { setWeights(Object.fromEntries((revs.data || []).map((r) => [r.name, r.properties?.trafficWeight ?? 0]))); }, [revs.data]);
  const setMode = async (m) => {
    try {
      await api.updateApp(rg, name, { location: a.location, properties: { ...a.properties, configuration: { ...a.properties.configuration, activeRevisionsMode: m } } });
      notify.success(`Active revisions mode set to '${m}'.`, "Save succeeded");
      reload();
    } catch (e) { notify.error(e, "Save failed"); }
  };
  const total = Object.values(weights).reduce((s, v) => s + (Number(v) || 0), 0);
  const saveTraffic = async () => {
    setBusy(true);
    try {
      const traffic = Object.entries(weights).map(([revisionName, weight]) => ({ revisionName, weight: Number(weight) || 0 }));
      await api.updateApp(rg, name, { location: a.location, properties: { ...a.properties, configuration: { ...a.properties.configuration, ingress: { ...a.properties.configuration.ingress, traffic } } } });
      notify.success("Traffic split was saved.", "Save succeeded");
      reload(); revs.reload();
    } catch (e) { notify.error(e, "Save failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">{name} | Revision management</div>
      <section className="vy-section"><h3>Revision mode</h3>
        <RadioGroup value={mode} onChange={(_, d) => setMode(d.value)} aria-label="Revision mode">
          <Radio value="Single" label="Single: Only one revision active at a time" />
          <Radio value="Multiple" label="Multiple: Several revisions active at a time" />
        </RadioGroup>
      </section>
      <section className="vy-section"><h3>Traffic split</h3>
        <Table size="small" aria-label="Traffic split">
          <TableHeader><TableRow><TableHeaderCell>Revision</TableHeaderCell><TableHeaderCell>Active</TableHeaderCell><TableHeaderCell>Traffic %</TableHeaderCell></TableRow></TableHeader>
          <TableBody>
            {(revs.data || []).map((r) => (
              <TableRow key={r.name}>
                <TableCell>{r.name}</TableCell><TableCell>{r.properties?.active ? "True" : "False"}</TableCell>
                <TableCell><Input size="small" type="number" value={String(weights[r.name] ?? 0)} onChange={(_, d) => setWeights((w) => ({ ...w, [r.name]: d.value }))} aria-label={`Traffic % ${r.name}`} style={{ width: 80 }} /></TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        <p style={{ fontSize: 13, marginTop: 6 }}>Total: {total}%{total !== 100 && " (must add up to 100%)"}</p>
        <Button appearance="primary" style={{ marginTop: 8 }} disabled={busy || total !== 100} onClick={saveTraffic}>{busy ? "Saving..." : "Save"}</Button>
      </section>
    </>
  );
}

// ── Scale ────────────────────────────────────────────────────────────────────────────────
function Scale({ a, rg, name, reload }) {
  const notify = useNotify();
  const scale = a.properties?.template?.scale || {};
  const [f, setF] = useState({ min: String(scale.minReplicas ?? 0), max: String(scale.maxReplicas ?? 10) });
  const [rules, setRules] = useState(scale.rules || []);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setF({ min: String(scale.minReplicas ?? 0), max: String(scale.maxReplicas ?? 10) }); setRules(scale.rules || []); }, [a]);
  const addRule = () => setRules((r) => [...r, { name: `http-rule-${r.length + 1}`, http: { metadata: { concurrentRequests: "10" } } }]);
  const save = async () => {
    setBusy(true);
    try {
      await api.updateApp(rg, name, { location: a.location, properties: { ...a.properties, template: { ...a.properties.template, scale: { minReplicas: Number(f.min), maxReplicas: Number(f.max), rules } } } });
      notify.success("Scale settings were saved.", "Save succeeded");
      reload();
    } catch (e) { notify.error(e, "Save failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">{name} | Scale</div>
      <section className="vy-section"><h3>Scale</h3>
        <Field label="Min replicas"><Input type="number" value={f.min} onChange={(_, d) => setF((x) => ({ ...x, min: d.value }))} aria-label="Min replicas" /></Field>
        <Field label="Max replicas"><Input type="number" value={f.max} onChange={(_, d) => setF((x) => ({ ...x, max: d.value }))} aria-label="Max replicas" /></Field>
      </section>
      <section className="vy-section"><h3>Scale rules</h3>
        <div className="vy-cmdbar" role="toolbar" aria-label="Scale rules commands">
          <ToolbarButton icon={<Add20Regular />} onClick={addRule}>Add</ToolbarButton>
        </div>
        <MiniTable columns={["Rule name", "Type", "Concurrent requests"]} empty="No scale rules configured"
          rows={rules.map((r, i) => <tr key={i}><td>{r.name}</td><td>HTTP</td><td>{r.http?.metadata?.concurrentRequests}</td></tr>)} />
      </section>
      <Button appearance="primary" disabled={busy} onClick={save}>{busy ? "Saving..." : "Save"}</Button>
    </>
  );
}

// ── Ingress ──────────────────────────────────────────────────────────────────────────────
function Ingress({ a, rg, name, reload }) {
  const notify = useNotify();
  const ing = a.properties?.configuration?.ingress;
  const [f, setF] = useState({ enabled: !!ing, type: ing?.external ? "external" : "internal", port: String(ing?.targetPort || 80), transport: ing?.transport?.toLowerCase() || "auto", allowInsecure: !!ing?.allowInsecure });
  const [busy, setBusy] = useState(false);
  useEffect(() => setF({ enabled: !!ing, type: ing?.external ? "external" : "internal", port: String(ing?.targetPort || 80), transport: ing?.transport?.toLowerCase() || "auto", allowInsecure: !!ing?.allowInsecure }), [a]);
  const save = async () => {
    setBusy(true);
    try {
      await api.updateApp(rg, name, { location: a.location, properties: { ...a.properties, configuration: { ...a.properties.configuration,
        ingress: f.enabled ? { external: f.type === "external", targetPort: Number(f.port), transport: f.transport, allowInsecure: f.allowInsecure, traffic: ing?.traffic } : null } } });
      notify.success("Ingress settings were saved.", "Save succeeded");
      reload();
    } catch (e) { notify.error(e, "Save failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">{name} | Ingress</div>
      <section className="vy-section">
        <Field label="Ingress"><Checkbox checked={f.enabled} onChange={(_, d) => setF((x) => ({ ...x, enabled: !!d.checked }))} label="Enabled" /></Field>
        {f.enabled && (
          <>
            <Field label="Ingress traffic">
              <RadioGroup value={f.type} onChange={(_, d) => setF((x) => ({ ...x, type: d.value }))} aria-label="Ingress traffic">
                <Radio value="external" label="Accepting traffic from anywhere" />
                <Radio value="internal" label="Limited to Container Apps Environment" />
              </RadioGroup>
            </Field>
            <Field label="Target port"><Input type="number" value={f.port} onChange={(_, d) => setF((x) => ({ ...x, port: d.value }))} aria-label="Target port" /></Field>
            <Field label="Transport">
              <Select value={f.transport} onChange={(_, d) => setF((x) => ({ ...x, transport: d.value }))} aria-label="Transport">
                <option value="auto">Auto</option><option value="http">HTTP</option><option value="http2">HTTP/2</option><option value="tcp">TCP</option>
              </Select>
            </Field>
            <Field label="Insecure connections"><Checkbox checked={f.allowInsecure} onChange={(_, d) => setF((x) => ({ ...x, allowInsecure: !!d.checked }))} label="Allow insecure connections" /></Field>
            {ing?.fqdn && <p style={{ fontSize: 13 }}>FQDN: <a href={`https://${ing.fqdn}`} target="_blank" rel="noreferrer">{ing.fqdn}</a></p>}
          </>
        )}
      </section>
      <Button appearance="primary" disabled={busy} onClick={save}>{busy ? "Saving..." : "Save"}</Button>
    </>
  );
}

// ── Custom domains ───────────────────────────────────────────────────────────────────────
// listCustomHostNameAnalysis validates a hostname for real (core/azure_app_core.py); binding
// the domain + managed certificate to the app is not modelled (azure.containerapps.app.customdomains).
function CustomDomains({ rg, name }) {
  const notify = useNotify();
  const [hostname, setHostname] = useState("");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const validate = async () => {
    setBusy(true);
    try { setResult((await api.validateCustomHostname(rg, name, hostname)).body ?? await api.validateCustomHostname(rg, name, hostname)); }
    catch (e) { notify.error(e, "Validation failed"); }
    finally { setBusy(false); }
  };
  return (
    <CapabilityContainer id="azure.containerapps.app.customdomains" title="Custom domains">
      <Field label="Custom domain" required><Input value={hostname} onChange={(_, d) => setHostname(d.value)} aria-label="Custom domain" placeholder="www.example.com" /></Field>
      <Button appearance="primary" disabled={!hostname || busy} onClick={validate}>{busy ? "Validating..." : "Validate"}</Button>
      {result && (
        <table className="vy-grid" style={{ marginTop: 12 }}>
          <tbody>
            <tr><td>Host name</td><td>{result.hostName}</td></tr>
            <tr><td>Verified</td><td>{result.isHostnameAlreadyVerified ? "Yes" : "No"}</td></tr>
            <tr><td>CNAME record needed</td><td>{(result.cnameRecords || [])[0]}</td></tr>
          </tbody>
        </table>
      )}
    </CapabilityContainer>
  );
}

// ── Secrets ──────────────────────────────────────────────────────────────────────────────
function Secrets({ a, rg, name, reload }) {
  const notify = useNotify();
  const secrets = a.properties?.configuration?.secrets || [];
  const [adding, setAdding] = useState(false);
  const [f, setF] = useState({ name: "", value: "" });
  const [revealed, setRevealed] = useState(null);
  const [busy, setBusy] = useState(false);
  const save = async (next) => {
    await api.updateApp(rg, name, { location: a.location, properties: { ...a.properties, configuration: { ...a.properties.configuration, secrets: next } } });
    reload();
  };
  const add = async () => {
    setBusy(true);
    try { await save([...secrets, { name: f.name, value: f.value }]); notify.success(`Secret '${f.name}' was added.`, "Save succeeded"); setAdding(false); setF({ name: "", value: "" }); }
    catch (e) { notify.error(e, "Save failed"); }
    finally { setBusy(false); }
  };
  const reveal = async () => { try { setRevealed(await api.listAppSecretValues(rg, name)); } catch (e) { notify.error(e, "Show value failed"); } };
  return (
    <>
      <div className="vy-panel-title">{name} | Secrets</div>
      <BrowseGrid
        resourceName="secret" items={secrets} loading={false} onRefresh={reload}
        onCreate={() => setAdding(true)}
        onDelete={async (rows) => { await save(secrets.filter((s) => !rows.some((r) => r.name === s.name))); notify.success("Secret(s) removed.", "Delete succeeded"); }}
        extraCommands={<ToolbarButton icon={<Eye20Regular />} onClick={reveal}>Show value</ToolbarButton>}
        columns={[{ key: "name", label: "Key" }, { key: "value", label: "Value", value: (s) => revealed?.find((r) => r.name === s.name)?.value || "******" }]}
      />
      <Dialog open={adding} onOpenChange={(_, d) => !d.open && setAdding(false)}>
        <DialogSurface aria-label="Add secret">
          <DialogBody>
            <DialogTitle>Add secret</DialogTitle>
            <DialogContent>
              <Field label="Key" required><Input value={f.name} onChange={(_, d) => setF((x) => ({ ...x, name: d.value }))} aria-label="Key" /></Field>
              <Field label="Value" required><Input type="password" value={f.value} onChange={(_, d) => setF((x) => ({ ...x, value: d.value }))} aria-label="Value" /></Field>
            </DialogContent>
            <DialogActions>
              <Button appearance="primary" disabled={!f.name || !f.value || busy} onClick={add}>{busy ? "Adding..." : "Add"}</Button>
              <Button onClick={() => setAdding(false)}>Cancel</Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

// ── Authentication ───────────────────────────────────────────────────────────────────────
function Authentication({ rg, name }) {
  const notify = useNotify();
  const { data, loading, reload } = useAsync(() => api.listAuthConfigs(rg, name), [rg, name]);
  const cur = (data || [])[0];
  const [action, setAction] = useState(cur?.properties?.globalValidation?.unauthenticatedClientAction || "AllowAnonymous");
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (cur) setAction(cur.properties?.globalValidation?.unauthenticatedClientAction || "AllowAnonymous"); }, [cur]);
  const save = async () => {
    setBusy(true);
    try {
      await api.putAuthConfig(rg, name, "current", { properties: { platform: { enabled: action !== "AllowAnonymous" }, globalValidation: { unauthenticatedClientAction: action } } });
      notify.success("Authentication settings were saved.", "Save succeeded");
      reload();
    } catch (e) { notify.error(e, "Save failed"); }
    finally { setBusy(false); }
  };
  if (loading) return <Loading />;
  return (
    <>
      <div className="vy-panel-title">{name} | Authentication</div>
      <section className="vy-section"><h3>Authentication settings</h3>
        <Field label="Unauthenticated requests">
          <RadioGroup value={action} onChange={(_, d) => setAction(d.value)} aria-label="Unauthenticated requests">
            <Radio value="AllowAnonymous" label="Allow unauthenticated access" />
            <Radio value="RedirectToLoginPage" label="Require authentication" />
          </RadioGroup>
        </Field>
      </section>
      <div className="vy-cmdbar" style={{ gap: 8 }}><Button appearance="primary" disabled={busy} onClick={save}>{busy ? "Saving..." : "Save"}</Button></div>
      <NotSimulatedContainer title="Identity providers" feature="Identity provider configuration (Microsoft Entra ID, Google, Facebook, GitHub, Apple, X, OpenID Connect)"
        note="Vyomi stores the platform enabled flag and the unauthenticated action for real (az containerapp auth update); it does not run a real login redirect or validate provider tokens." />
    </>
  );
}

// ── Identity ─────────────────────────────────────────────────────────────────────────────
function Identity({ a, rg, name, reload }) {
  const notify = useNotify();
  const ident = a.identity || { type: "None" };
  const on = /systemassigned/i.test(ident.type || "");
  const [busy, setBusy] = useState(false);
  const toggle = async (enable) => {
    setBusy(true);
    try {
      await api.updateAppIdentity(rg, name, { type: enable ? "SystemAssigned" : "None" });
      notify.success(`System assigned managed identity was turned ${enable ? "on" : "off"} for '${name}'.`, "Save succeeded");
      reload();
    } catch (e) { notify.error(e, "Save failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">{name} | Identity</div>
      <section className="vy-section"><h3>System assigned</h3>
        <Field label="Status">
          <RadioGroup value={on ? "On" : "Off"} onChange={(_, d) => toggle(d.value === "On")} aria-label="Status">
            <Radio value="On" label="On" disabled={busy} /><Radio value="Off" label="Off" disabled={busy} />
          </RadioGroup>
        </Field>
        {on && (
          <table className="vy-grid" style={{ marginTop: 8 }}>
            <tbody><tr><td>Object (principal) ID</td><td>{ident.principalId}</td></tr><tr><td>Tenant ID</td><td>{ident.tenantId}</td></tr></tbody>
          </table>
        )}
      </section>
      <NotSimulatedContainer title="User assigned managed identities" feature="User assigned managed identities" />
    </>
  );
}
