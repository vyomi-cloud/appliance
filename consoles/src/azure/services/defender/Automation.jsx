/* Defender for Cloud | Workflow automation: real Microsoft.Security/automations (core/azure_security_automations_core.py).
 * A matching Security alert is delivered to the Workspace action (Log Analytics table SecurityAlert); Logic App / Event Hub
 * actions fire but are recorded Failed because the simulator has no such runtime. */
import { useState } from "react";
import { Button, Checkbox, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Select, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { listResourceGroups, getSubscription } from "../../kit/arm.js";
import { ErrorBar, fmtDate, InfoBar, Loading } from "../../kit/common.jsx";
import DefenderShell from "./DefenderShell.jsx";
import * as api from "./api.js";

function CreateDialog({ open, onClose, onDone }) {
  const notify = useNotify();
  const rgs = useAsync(() => listResourceGroups(), []);
  const wss = useAsync(() => api.listWorkspaces(), []);
  const [f, setF] = useState({ name: "", rg: "", severity: "", ws: "", enabled: true });
  const set = (p) => setF((x) => ({ ...x, ...p }));
  const rg = f.rg || rgs.data?.[0]?.name || "";
  const valid = /^[A-Za-z0-9._()-]{1,90}$/.test(f.name) && rg && f.ws;
  const save = async () => {
    try {
      await api.putAutomation(rg, f.name, { location: "eastus", properties: {
        description: "", isEnabled: f.enabled, scopes: [{ description: "Subscription", scopePath: `/subscriptions/${getSubscription()}` }],
        sources: [{ eventSource: "Alerts", ruleSets: f.severity ? [{ rules: [{ propertyJPath: "Severity", propertyType: "String", expectedValue: f.severity, operator: "GreaterThanOrEqualTo" }] }] : [] }],
        actions: [{ actionType: "Workspace", workspaceResourceId: f.ws }] } });
      notify.success(`Workflow automation '${f.name}' was created.`, "Create succeeded");
      onDone();
    } catch (e) { notify.error(e, "Create failed"); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Add workflow automation">
        <DialogBody>
          <DialogTitle>Add workflow automation</DialogTitle>
          <DialogContent>
            <Field label="Name" required><Input value={f.name} onChange={(_, d) => set({ name: d.value })} aria-label="Automation name" /></Field>
            <Field label="Resource group"><Select value={rg} onChange={(_, d) => set({ rg: d.value })} aria-label="Resource group">{(rgs.data || []).map((g) => <option key={g.name}>{g.name}</option>)}</Select></Field>
            <Field label="Trigger: Defender for Cloud security alerts with severity at least">
              <Select value={f.severity} onChange={(_, d) => set({ severity: d.value })} aria-label="Minimum severity">
                <option value="">Any severity</option><option>Low</option><option>Medium</option><option>High</option>
              </Select>
            </Field>
            <Field label="Action: send to Log Analytics workspace" required>
              <Select value={f.ws} onChange={(_, d) => set({ ws: d.value })} aria-label="Workspace"><option value="">Select a workspace</option>{(wss.data || []).map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}</Select>
            </Field>
            <Checkbox checked={f.enabled} label="Enabled" onChange={(_, d) => set({ enabled: !!d.checked })} />
          </DialogContent>
          <DialogActions><Button appearance="primary" disabled={!valid} onClick={save}>Create</Button><Button onClick={onClose}>Cancel</Button></DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

function Runs({ id }) {
  const d = useAsync(() => api.listAutomationRuns(id), [id]);
  if (d.loading && !d.data) return <Loading />;
  return (
    <Table size="small" aria-label="Automation runs">
      <TableHeader><TableRow><TableHeaderCell>Time</TableHeaderCell><TableHeaderCell>Alert</TableHeaderCell><TableHeaderCell>Action</TableHeaderCell><TableHeaderCell>Result</TableHeaderCell></TableRow></TableHeader>
      <TableBody>
        {(d.data || []).length === 0 && <TableRow><TableCell colSpan={4}>No runs yet: no alert has matched this automation.</TableCell></TableRow>}
        {(d.data || []).map((r, i) => <TableRow key={i}><TableCell>{fmtDate(r.time)}</TableCell><TableCell>{r.alertDisplayName}</TableCell><TableCell>{r.actionType}</TableCell><TableCell>{r.status}{r.error ? `: ${r.error}` : ""}</TableCell></TableRow>)}
      </TableBody>
    </Table>
  );
}

export default function Automation() {
  const notify = useNotify();
  const d = useAsync(() => api.listAutomations(), []);
  const [adding, setAdding] = useState(false);
  const [open, setOpen] = useState(null);
  const del = async (a) => { try { await api.deleteAutomation(a.id); notify.success(`Deleted '${a.name}'.`, "Delete succeeded"); d.reload(); } catch (e) { notify.error(e, "Delete failed"); } };
  return (
    <DefenderShell active="automation">
      <div className="vy-panel-title">Workflow automation</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Workflow automation commands">
        <Button appearance="primary" onClick={() => setAdding(true)}>Add workflow automation</Button>
        <Button onClick={d.reload}>Refresh</Button>
      </div>
      <InfoBar intent="info" title="What runs">A security alert that matches an enabled automation is sent to its Log Analytics workspace (table SecurityAlert). Logic App and Event Hub actions can be stored but are recorded as Failed, since the simulator has no Logic Apps or Event Hubs runtime.</InfoBar>
      <ErrorBar error={d.error} title="Could not load workflow automations" />
      {d.loading && !d.data ? <Loading /> : (
        <Table size="small" aria-label="Workflow automations">
          <TableHeader><TableRow><TableHeaderCell>Name</TableHeaderCell><TableHeaderCell>Status</TableHeaderCell><TableHeaderCell>Trigger</TableHeaderCell><TableHeaderCell>Actions</TableHeaderCell><TableHeaderCell /></TableRow></TableHeader>
          <TableBody>
            {(d.data || []).length === 0 && <TableRow><TableCell colSpan={5}>No workflow automations</TableCell></TableRow>}
            {(d.data || []).map((a) => (
              <TableRow key={a.id}>
                <TableCell><Button appearance="transparent" onClick={() => setOpen(open === a.id ? null : a.id)}>{a.name}</Button></TableCell>
                <TableCell>{a.properties.isEnabled ? "Enabled" : "Disabled"}</TableCell>
                <TableCell>{a.properties.sources.map((s) => s.eventSource).join(", ")}</TableCell>
                <TableCell>{a.properties.actions.map((x) => x.actionType).join(", ")}</TableCell>
                <TableCell><Button size="small" onClick={() => del(a)} aria-label={`Delete ${a.name}`}>Delete</Button></TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {open && <><h3>Runs</h3><Runs id={open} /></>}
      <CreateDialog open={adding} onClose={() => setAdding(false)} onDone={() => { setAdding(false); d.reload(); }} />
    </DefenderShell>
  );
}
