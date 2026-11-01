/* Container Apps Job resource blade: left resource menu + panels. Overview, Containers,
 * Secrets, Triggers, Execution history, Activity log, Access control (IAM), Tags, Diagnostic
 * settings, Export template and Locks are backed by native ARM calls (core/azure_app_core.py);
 * the rest render their honest capability level. */
import { useEffect, useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Link, Select, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow, ToolbarButton } from "@fluentui/react-components";
import { ArrowClockwise20Regular, Eye20Regular, Play20Regular, Stop20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { locationLabel } from "../../kit/arm.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import ResourceBlade from "../../kit/ResourceBlade.jsx";
import { Essentials, ErrorBar, Glyph, Loading, fmtDate } from "../../kit/common.jsx";
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
  { group: "Settings", items: [
    { id: "containers", label: "Containers" },
    { id: "secrets", label: "Secrets" },
    { id: "triggers", label: "Triggers" },
    { id: "identity", label: "Identity" },
    { id: "locks", label: "Locks" },
  ] },
  { group: "Execution", items: [{ id: "executionhistory", label: "Execution history" }] },
  { group: "Monitoring", items: [{ id: "logstream", label: "Log stream" }, { id: "diagnosticsettings", label: "Diagnostic settings" }] },
  { group: "Automation", items: [{ id: "exporttemplate", label: "Export template" }] },
];
const LABEL = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
const CAP = { diagnose: "azure.containerapps.job.tools", identity: "azure.containerapps.job.tools", logstream: "azure.containerapps.job.tools" };

export default function JobBlade({ params }) {
  const { rg, name } = params;
  const panel = params.panel || "overview";
  const job = useAsync(() => api.getJob(rg, name), [rg, name, panel]);
  const self = `#/containerapps/jobs/${encodeURIComponent(rg)}/${encodeURIComponent(name)}`;
  const resPath = job.data ? api.JOBS.path(rg, name) : null;
  useEffect(() => { if (job.data) remember({ name, type: "Container Apps Job", href: self }); }, [!!job.data, self]);

  let body;
  if (job.loading && !job.data) body = <Loading />;
  else if (job.error) body = <><ErrorBar error={job.error} title="Failed to load the job" /><Link href="#/containerapps/jobs">Back to Container Apps Jobs</Link></>;
  else {
    const a = job.data, reload = job.reload;
    const P = {
      overview: () => <Overview a={a} reload={reload} self={self} />,
      activitylog: () => <ActivityLog resPath={resPath} name={a.name} />,
      iam: () => <AccessControlIam resPath={resPath} name={a.name} capId="azure.containerapps.iam" />,
      tags: () => <Tags a={a} name={a.name} reload={reload} save={(tags) => api.updateJobTags(rg, a.name, tags)} />,
      containers: () => <Containers a={a} rg={rg} name={a.name} reload={reload} />,
      secrets: () => <Secrets a={a} rg={rg} name={a.name} reload={reload} />,
      triggers: () => <Triggers a={a} rg={rg} name={a.name} reload={reload} />,
      executionhistory: () => <ExecutionHistory rg={rg} name={a.name} />,
      locks: () => <Locks resPath={resPath} name={a.name} />,
      diagnosticsettings: () => <DiagnosticSettings resPath={resPath} name={a.name} />,
      exporttemplate: () => <ExportTemplate a={a} name={a.name} type="Microsoft.App/jobs" />,
    }[panel];
    body = P ? P() : <CapabilityContainer id={CAP[panel] || "azure.containerapps.job.tools"} title={`${a.name} | ${LABEL[panel] || panel}`} />;
  }

  return (
    <ResourceBlade
      title={panel === "overview" ? name : `${name} | ${LABEL[panel] || panel}`} subtitle="Container Apps Job"
      glyph={<Glyph id="containerapps" />} closeHref="#/containerapps/jobs"
      menu={MENU} active={panel} hrefFor={(id) => (id === "overview" ? self : `${self}/${id}`)}
    >
      {body}
    </ResourceBlade>
  );
}

function Overview({ a, reload, self }) {
  const notify = useNotify();
  const sub = useSubscription();
  const [del, setDel] = useState(false);
  const execs = useAsync(() => api.listExecutions(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const p = a.properties || {};
  const tags = Object.entries(a.tags || {});
  const run = async () => {
    try { await api.startJob(a.resourceGroup, a.name); notify.success(`Job '${a.name}' was started.`, "Run succeeded"); execs.reload(); }
    catch (e) { notify.error(e, "Run failed"); }
  };
  return (
    <>
      <div className="vy-cmdbar" role="toolbar" aria-label="Overview commands">
        <ToolbarButton icon={<Play20Regular />} onClick={run}>Run now</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={() => { reload(); execs.reload(); }}>Refresh</ToolbarButton>
      </div>
      <Essentials
        left={[
          ["Resource group", <Link href="#/resourcegroups">{a.resourceGroup}</Link>],
          ["Location", locationLabel(a.location)],
          ["Subscription", sub.displayName || sub.id],
          ["Container Apps Environment", <Link href={`#/containerapps/environments/${a.resourceGroup}/${api.envName(p.environmentId)}`}>{api.envName(p.environmentId)}</Link>],
        ]}
        right={[
          ["Trigger type", p.configuration?.triggerType],
          ["Replica timeout", `${p.configuration?.replicaTimeout}s`],
          ["Provisioning state", p.provisioningState],
          ["Tags", <span>{tags.length ? tags.map(([k, v]) => `${k} : ${v}`).join(", ") : ""} <Link href={`${self}/tags`}>{tags.length ? "Edit" : "Add tags"}</Link></span>],
        ]}
      />
      <section className="vy-section" style={{ marginTop: 12 }}><h3>Execution history</h3>
        <MiniTable columns={["Execution", "Status", "Start time", "End time"]} empty="No executions yet"
          rows={(execs.data || []).slice(0, 5).map((e) => <tr key={e.name}><td>{e.name}</td><td>{e.properties?.status}</td><td>{fmtDate(e.properties?.startTime)}</td><td>{fmtDate(e.properties?.endTime)}</td></tr>)} />
      </section>
      <DeleteDialog open={del} onClose={() => setDel(false)} resourceType="container apps job" names={[a.name]}
        onConfirm={async () => {
          await api.deleteJob(a.resourceGroup, a.name);
          forget(self);
          notify.success(`Job '${a.name}' was deleted.`, "Delete succeeded");
          navigate("containerapps", "jobs");
        }} />
      <div className="vy-cmdbar" role="toolbar" aria-label="Delete command"><ToolbarButton onClick={() => setDel(true)}>Delete</ToolbarButton></div>
    </>
  );
}

function Containers({ a, rg, name, reload }) {
  const notify = useNotify();
  const c0 = (a.properties?.template?.containers || [])[0] || {};
  const [f, setF] = useState({ image: c0.image || "", cpu: String(c0.resources?.cpu || 0.5) });
  const [busy, setBusy] = useState(false);
  useEffect(() => setF({ image: c0.image || "", cpu: String(c0.resources?.cpu || 0.5) }), [a]);
  const save = async () => {
    setBusy(true);
    try {
      await api.createJob(rg, name, { location: a.location, properties: { ...a.properties, template: { containers: [{ ...c0, image: f.image, resources: { cpu: Number(f.cpu), memory: api.memFor(Number(f.cpu)) } }] } } });
      notify.success(`Container for '${name}' was updated.`, "Save succeeded");
      reload();
    } catch (e) { notify.error(e, "Save failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">{name} | Containers</div>
      <section className="vy-section"><h3>Container details</h3>
        <Field label="Image" required><Input value={f.image} onChange={(_, d) => setF((x) => ({ ...x, image: d.value }))} aria-label="Image" style={{ width: "100%" }} /></Field>
        <Field label="CPU and Memory">
          <Select value={f.cpu} onChange={(_, d) => setF((x) => ({ ...x, cpu: d.value }))} aria-label="CPU and Memory">
            {api.CPU_CHOICES.map((c) => <option key={c} value={c}>{c} CPU cores, {api.memFor(c)} memory</option>)}
          </Select>
        </Field>
      </section>
      <Button appearance="primary" disabled={!f.image || busy} onClick={save}>{busy ? "Saving..." : "Save"}</Button>
    </>
  );
}

function Secrets({ a, rg, name, reload }) {
  const notify = useNotify();
  const secrets = a.properties?.configuration?.secrets || [];
  const [adding, setAdding] = useState(false);
  const [f, setF] = useState({ name: "", value: "" });
  const [revealed, setRevealed] = useState(null);
  const [busy, setBusy] = useState(false);
  const save = async (next) => { await api.createJob(rg, name, { location: a.location, properties: { ...a.properties, configuration: { ...a.properties.configuration, secrets: next } } }); reload(); };
  const add = async () => {
    setBusy(true);
    try { await save([...secrets, { name: f.name, value: f.value }]); notify.success(`Secret '${f.name}' was added.`, "Save succeeded"); setAdding(false); setF({ name: "", value: "" }); }
    catch (e) { notify.error(e, "Save failed"); }
    finally { setBusy(false); }
  };
  const reveal = async () => { try { setRevealed(await api.listJobSecretValues(rg, name)); } catch (e) { notify.error(e, "Show value failed"); } };
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

function Triggers({ a, rg, name, reload }) {
  const notify = useNotify();
  const cfg = a.properties?.configuration || {};
  const [f, setF] = useState({
    triggerType: cfg.triggerType || "Manual", timeout: String(cfg.replicaTimeout ?? 1800), retries: String(cfg.replicaRetryLimit ?? 0),
    cron: cfg.scheduleTriggerConfig?.cronExpression || "*/5 * * * *",
    parallelism: String((cfg.manualTriggerConfig || cfg.scheduleTriggerConfig)?.parallelism ?? 1),
    completions: String((cfg.manualTriggerConfig || cfg.scheduleTriggerConfig)?.replicaCompletionCount ?? 1),
  });
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      const next = { triggerType: f.triggerType, replicaTimeout: Number(f.timeout), replicaRetryLimit: Number(f.retries), secrets: cfg.secrets, registries: cfg.registries };
      if (f.triggerType === "Manual") next.manualTriggerConfig = { parallelism: Number(f.parallelism), replicaCompletionCount: Number(f.completions) };
      if (f.triggerType === "Schedule") next.scheduleTriggerConfig = { cronExpression: f.cron, parallelism: Number(f.parallelism), replicaCompletionCount: Number(f.completions) };
      await api.createJob(rg, name, { location: a.location, properties: { ...a.properties, configuration: next } });
      notify.success("Trigger settings were saved.", "Save succeeded");
      reload();
    } catch (e) { notify.error(e, "Save failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">{name} | Triggers</div>
      <section className="vy-section"><h3>Trigger</h3>
        <Field label="Trigger type">
          <Select value={f.triggerType} onChange={(_, d) => setF((x) => ({ ...x, triggerType: d.value }))} aria-label="Trigger type">
            <option value="Manual">Manual</option><option value="Schedule">Schedule</option><option value="Event">Event</option>
          </Select>
        </Field>
        {f.triggerType === "Schedule" && <Field label="Cron expression"><Input value={f.cron} onChange={(_, d) => setF((x) => ({ ...x, cron: d.value }))} aria-label="Cron expression" /></Field>}
        <Field label="Parallelism"><Input type="number" value={f.parallelism} onChange={(_, d) => setF((x) => ({ ...x, parallelism: d.value }))} aria-label="Parallelism" /></Field>
        <Field label="Replica completion count"><Input type="number" value={f.completions} onChange={(_, d) => setF((x) => ({ ...x, completions: d.value }))} aria-label="Replica completion count" /></Field>
        <Field label="Replica timeout (seconds)"><Input type="number" value={f.timeout} onChange={(_, d) => setF((x) => ({ ...x, timeout: d.value }))} aria-label="Replica timeout (seconds)" /></Field>
        <Field label="Replica retry limit"><Input type="number" value={f.retries} onChange={(_, d) => setF((x) => ({ ...x, retries: d.value }))} aria-label="Replica retry limit" /></Field>
      </section>
      <Button appearance="primary" disabled={busy} onClick={save}>{busy ? "Saving..." : "Save"}</Button>
    </>
  );
}

function ExecutionHistory({ rg, name }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listExecutions(rg, name), [rg, name]);
  const stop = async (exec) => { try { await api.stopExecution(rg, name, exec); notify.success(`Execution '${exec}' was stopped.`, "Stop succeeded"); reload(); } catch (e) { notify.error(e, "Stop failed"); } };
  return (
    <>
      <div className="vy-panel-title">{name} | Execution history</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Execution history commands">
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
      </div>
      {loading ? <Loading /> : error ? <ErrorBar error={error} /> : (
        <Table size="small" aria-label="Execution history">
          <TableHeader><TableRow><TableHeaderCell>Name</TableHeaderCell><TableHeaderCell>Status</TableHeaderCell><TableHeaderCell>Start time</TableHeaderCell><TableHeaderCell>End time</TableHeaderCell><TableHeaderCell /></TableRow></TableHeader>
          <TableBody>
            {(data || []).map((e) => (
              <TableRow key={e.name}>
                <TableCell>{e.name}</TableCell><TableCell>{e.properties?.status}</TableCell>
                <TableCell>{fmtDate(e.properties?.startTime)}</TableCell><TableCell>{fmtDate(e.properties?.endTime)}</TableCell>
                <TableCell>{e.properties?.status === "Running" && <Button size="small" icon={<Stop20Regular />} onClick={() => stop(e.name)}>Stop</Button>}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {!loading && !(data || []).length && <p className="vy-muted" style={{ fontSize: 13 }}>No executions yet.</p>}
    </>
  );
}
