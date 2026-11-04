/* Tasks blade (AKS, API Management, App Configuration, App Service, Cognitive Services): task templates, tasks and their runs.
 * A task is a real Microsoft.Logic/workflows record whose scheduled runs call the simulator's ARM (core/azure_tasks_core.py). */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Select } from "@fluentui/react-components";
import { useNotify } from "../../common/notify.jsx";
import { restJson } from "../../common/wire.js";
import { useAsync } from "../../common/useAsync.js";
import { ErrorBar, Loading, fmtDate } from "./common.jsx";
import { parseId } from "./arm.js";

const Q = { "api-version": "2019-05-01" };

export default function TasksPanel({ a }) {
  const notify = useNotify();
  const { subscription: sub, resourceGroup: rg } = parseId(a.id);
  const base = `/subscriptions/${sub}/resourceGroups/${rg}/providers/Microsoft.Logic`;
  const tpls = useAsync(() => restJson("GET", `/subscriptions/${sub}/providers/Microsoft.Logic/vyomiTaskTemplates`, { query: { ...Q, resourceType: (a.id.match(/\/providers\/([^/]+\/[^/]+)/i) || [])[1] } }), [a.id]);
  const wfs = useAsync(async () => {
    const all = (await restJson("GET", `${base}/workflows`, { query: Q })).value || [];
    return all.filter((w) => w.tags?.["vyomi-task-target"]?.toLowerCase() === a.id.toLowerCase());
  }, [a.id]);
  const [pick, setPick] = useState(null);
  const [form, setForm] = useState({});
  const [sel, setSel] = useState(null);
  const runs = useAsync(() => (sel ? restJson("GET", `${base}/workflows/${sel}/runs`, { query: Q }).then((r) => r.value || []) : Promise.resolve([])), [sel, wfs.data]);
  const [err, setErr] = useState(null);
  const act = async (fn, ok) => { try { setErr(null); await fn(); if (ok) notify.success(ok, "Done"); wfs.reload(); runs.reload(); } catch (e) { setErr(e); } };
  const open = (t) => { setPick(t); setErr(null); setForm({ name: `task-${t.id}-${a.name}`.slice(0, 80), frequency: t.recurrence.frequency, interval: t.recurrence.interval, hour: t.recurrence.schedule?.hours?.[0] ?? "", minute: t.recurrence.schedule?.minutes?.[0] ?? 0, ...Object.fromEntries(t.params.map((p) => [p.name, p.default ?? ""])) }); };
  const create = () => act(async () => {
    const rec = { frequency: form.frequency, interval: Number(form.interval) };
    if (form.frequency === "Day" && form.hour !== "") rec.schedule = { hours: [Number(form.hour)], minutes: [Number(form.minute || 0)] };
    await restJson("POST", `${base}/vyomiCreateTask`, { query: Q, body: { templateId: pick.id, resourceId: a.id, name: form.name, recurrence: rec, parameters: Object.fromEntries(pick.params.map((p) => [p.name, form[p.name]])) } });
    setPick(null);
  }, "Task created.");
  if (tpls.loading && !tpls.data) return <Loading />;
  const lastRun = (w) => w._last;
  return (
    <div>
      <p className="vy-muted" style={{ fontSize: 13 }}>Tasks are Logic App workflows (Microsoft.Logic/workflows) created from a template. Each run calls this simulator's Azure Resource Manager, so the effect is real; reports are kept in the run output (no e-mail connector).</p>
      {err && <ErrorBar error={err} title="Task operation failed" />}
      <section className="vy-section">
        <h3>Task templates</h3>
        <table className="vy-grid" aria-label="Task templates"><thead><tr><th>Template</th><th>Description</th><th /></tr></thead>
          <tbody>{(tpls.data?.value || []).map((t) => (
            <tr key={t.id}><td>{t.title}</td><td>{t.description}</td><td><Button size="small" onClick={() => open(t)} aria-label={`Create task from ${t.title}`}>Create task</Button></td></tr>))}
            {!(tpls.data?.value || []).length && <tr><td colSpan={3} className="vy-muted">No templates for this resource type.</td></tr>}</tbody></table>
      </section>
      <section className="vy-section">
        <h3>Tasks</h3>
        <table className="vy-grid" aria-label="Tasks"><thead><tr><th>Name</th><th>Template</th><th>Schedule</th><th>State</th><th /></tr></thead>
          <tbody>{(wfs.data || []).map((w) => {
            const rc = w.properties.definition.triggers.Recurrence.recurrence;
            return (
              <tr key={w.name}><td><a href="#" onClick={(e) => { e.preventDefault(); setSel(w.name); }}>{w.name}</a></td><td>{w.tags["vyomi-task-template"]}</td>
                <td>{`every ${rc.interval} ${rc.frequency.toLowerCase()}${rc.schedule ? ` at ${String(rc.schedule.hours[0]).padStart(2, "0")}:${String(rc.schedule.minutes?.[0] || 0).padStart(2, "0")} UTC` : ""}`}</td>
                <td>{w.properties.state}</td>
                <td style={{ whiteSpace: "nowrap" }}>
                  <Button size="small" onClick={() => act(async () => { await restJson("POST", `${base}/workflows/${w.name}/triggers/Recurrence/run`, { query: Q }); setSel(w.name); }, "Run completed.")} disabled={w.properties.state !== "Enabled"}>Run now</Button>{" "}
                  <Button size="small" onClick={() => act(() => restJson("POST", `${base}/workflows/${w.name}/${w.properties.state === "Enabled" ? "disable" : "enable"}`, { query: Q }))}>{w.properties.state === "Enabled" ? "Disable" : "Enable"}</Button>{" "}
                  <Button size="small" onClick={() => act(async () => { await restJson("DELETE", `${base}/workflows/${w.name}`, { query: Q }); if (sel === w.name) setSel(null); }, "Task deleted.")}>Delete</Button></td></tr>);
          })}
            {!(wfs.data || []).length && <tr><td colSpan={5} className="vy-muted">No tasks yet. Create one from a template above.</td></tr>}</tbody></table>
      </section>
      {sel && (
        <section className="vy-section">
          <h3>Runs of {sel}</h3>
          <table className="vy-grid" aria-label="Task runs"><thead><tr><th>Started</th><th>Status</th><th>Actions</th></tr></thead>
            <tbody>{(runs.data || []).map((r) => (
              <tr key={r.name}><td>{fmtDate(r.properties.startTime)}</td><td>{r.properties.status}{r.properties.error ? ` — ${r.properties.error.code}: ${r.properties.error.message}` : ""}</td>
                <td>{Object.entries(r.properties.vyomiActions || {}).map(([n, x]) => `${n}: ${x.status}${x.response ? ` (HTTP ${x.response.statusCode})` : ""}`).join("; ")}</td></tr>))}
              {!(runs.data || []).length && <tr><td colSpan={3} className="vy-muted">No runs yet.</td></tr>}</tbody></table>
        </section>
      )}
      <Dialog open={!!pick} onOpenChange={(_, d) => !d.open && setPick(null)}>
        <DialogSurface aria-label="Create task">
          <DialogBody>
            <DialogTitle>{pick?.title}</DialogTitle>
            <DialogContent>
              {err && <ErrorBar error={err} title="Could not create the task" />}
              <Field label="Task name"><Input value={form.name || ""} onChange={(_, d) => setForm({ ...form, name: d.value })} /></Field>
              <Field label="Frequency"><Select value={form.frequency} onChange={(_, d) => setForm({ ...form, frequency: d.value })}>{["Minute", "Hour", "Day", "Week"].map((x) => <option key={x}>{x}</option>)}</Select></Field>
              <Field label="Interval"><Input type="number" value={String(form.interval ?? 1)} onChange={(_, d) => setForm({ ...form, interval: d.value })} /></Field>
              {form.frequency === "Day" && <Field label="At hour (UTC, blank = every interval)"><Input type="number" value={String(form.hour ?? "")} onChange={(_, d) => setForm({ ...form, hour: d.value })} /></Field>}
              {(pick?.params || []).map((p) => (
                <Field key={p.name} label={p.label}>{p.enum
                  ? <Select value={form[p.name]} onChange={(_, d) => setForm({ ...form, [p.name]: d.value })}>{p.enum.map((x) => <option key={x}>{x}</option>)}</Select>
                  : <Input value={form[p.name] || ""} onChange={(_, d) => setForm({ ...form, [p.name]: d.value })} />}</Field>))}
            </DialogContent>
            <DialogActions><Button appearance="primary" onClick={create}>Create</Button><Button onClick={() => setPick(null)}>Cancel</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </div>
  );
}
