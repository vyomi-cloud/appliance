/* Azure Access control (IAM) tabs, Fluent-native:
 *   ActivityPanel  Activity Log events for role assignments / definitions / PIM requests / managed identities (+ gate denials): GET /api/iam/azure/events
 *   PimPanel       Privileged Identity Management style schedules at a scope: eligible (roleEligibilitySchedules), active (roleAssignmentScheduleInstances),
 *                  Add eligible assignment, Activate (SelfActivate with duration + justification), Deactivate */
import { useState } from "react";
import { Button, Field, Input, Select } from "@fluentui/react-components";
import { restJson } from "../../common/wire.js";
import { useAsync } from "../../common/useAsync.js";
import { EVENT_COPY, OUTCOMES, OUTCOME_LABEL, eventTime } from "../../common/iamEvents.js";
import { useIamEvents } from "../../common/iamEventsHooks.js";
import BrowseGrid from "./BrowseGrid.jsx";
import { ErrorBar, InfoBar } from "./common.jsx";

const NS = "Microsoft.Authorization";
const PIM_V = "2020-10-01";
const guid = () => (crypto.randomUUID ? crypto.randomUUID() : "00000000-0000-4000-8000-" + String(Date.now()).padStart(12, "0").slice(-12));
const wrap = (v) => <span style={{ wordBreak: "break-all" }}>{v || "-"}</span>;

export function ActivityPanel() {
  const copy = EVENT_COPY.azure;
  const [draft, setDraft] = useState({ name: "", principal: "", resource: "", outcome: "all" });
  const [f, setF] = useState(draft);
  const ev = useIamEvents("azure", f);
  return (
    <div style={{ marginTop: 12 }} data-testid="iam-events-panel">
      <div style={{ display: "flex", gap: 12, alignItems: "flex-end", marginBottom: 8, flexWrap: "wrap" }}>
        <Field label="Operation"><Input value={draft.name} aria-label="Filter by operation" onChange={(_, d) => setDraft({ ...draft, name: d.value })} /></Field>
        <Field label="Caller"><Input value={draft.principal} aria-label="Filter by caller" onChange={(_, d) => setDraft({ ...draft, principal: d.value })} /></Field>
        <Field label="Resource"><Input value={draft.resource} aria-label="Filter by resource" onChange={(_, d) => setDraft({ ...draft, resource: d.value })} /></Field>
        <Field label="Status"><Select value={draft.outcome} aria-label="Filter by status" onChange={(_, d) => { const n = { ...draft, outcome: d.value }; setDraft(n); setF(n); }}>
          <option value="all">All</option>{OUTCOMES.map((o) => <option key={o} value={o}>{OUTCOME_LABEL[o]}</option>)}</Select></Field>
        <Button onClick={() => setF(draft)}>Apply</Button>
        <Button as="a" href={ev.api.exportUrl(f, "json")} target="_blank">Export JSON</Button>
      </div>
      <InfoBar>{copy.info}</InfoBar>
      <BrowseGrid resourceName="event" rowKey={(r) => r.id} items={ev.data?.events || []} loading={ev.loading} error={ev.error} onRefresh={ev.reload} csvName="iam-activity-log.csv"
        columns={[
          { key: "time", label: "Time", value: (r) => eventTime(r) },
          { key: "op", label: "Operation name", value: (r) => r.native?.operationName?.value || r.name, render: (r) => wrap(r.native?.operationName?.value || r.name) },
          { key: "status", label: "Status", value: (r) => r.native?.status?.value || OUTCOME_LABEL[r.outcome] || r.outcome },
          { key: "caller", label: "Event initiated by", value: (r) => r.principal, render: (r) => wrap(r.principal) },
          { key: "resource", label: "Resource", value: (r) => r.resource, render: (r) => wrap(r.resource) },
        ]} />
    </div>
  );
}

const hours = (a, b) => (a && b ? `${a.replace("T", " ").slice(0, 16)} to ${b.replace("T", " ").slice(0, 16)}` : a ? `from ${a.slice(0, 16)}` : "no end");

export function PimPanel({ a }) {
  const scope = a.id.replace(/\/$/, "");
  const base = `${scope}/providers/${NS}`;
  const q = { "api-version": PIM_V };
  const st = useAsync(async () => {
    const [elig, act, defs] = await Promise.all([
      restJson("GET", `${base}/roleEligibilitySchedules`, { query: q }),
      restJson("GET", `${base}/roleAssignmentScheduleInstances`, { query: q }),
      restJson("GET", `${base}/roleDefinitions`, { query: { "api-version": "2022-04-01" } }).catch(() => ({ value: [] })),
    ]);
    const names = Object.fromEntries((defs.value || []).map((d) => [String(d.id).toLowerCase(), d.properties?.roleName || d.name]));
    return { elig: elig.value || [], act: (act.value || []).filter((r) => (r.properties?.assignmentType || "") === "Activated"), names };
  }, [scope]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [hrs, setHrs] = useState("1");
  const [why, setWhy] = useState("");
  const [addP, setAddP] = useState("");
  const [addR, setAddR] = useState("");
  const run = async (fn) => { setBusy(true); setErr(null); try { await fn(); await st.refresh(); } catch (e) { setErr(e); } finally { setBusy(false); } };
  const role = (p) => st.data?.names[String(p.roleDefinitionId || "").toLowerCase()] || String(p.roleDefinitionId || "").split("/").pop();
  const activate = (r) => run(() => restJson("PUT", `${base}/roleAssignmentScheduleRequests/${guid()}`, { query: q, body: { properties: {
    requestType: "SelfActivate", principalId: r.properties.principalId, roleDefinitionId: r.properties.roleDefinitionId, justification: why || "Activated from the portal",
    linkedRoleEligibilityScheduleId: r.name || r.id, scheduleInfo: { startDateTime: new Date().toISOString(), expiration: { type: "AfterDuration", duration: `PT${Math.max(1, Number(hrs) || 1)}H` } } } } }));
  const deactivate = (r) => run(() => restJson("PUT", `${base}/roleAssignmentScheduleRequests/${guid()}`, { query: q, body: { properties: {
    requestType: "SelfDeactivate", principalId: r.properties.principalId, roleDefinitionId: r.properties.roleDefinitionId } } }));
  const addEligible = () => run(() => restJson("PUT", `${base}/roleEligibilityScheduleRequests/${guid()}`, { query: q, body: { properties: {
    requestType: "AdminAssign", principalId: addP.trim(), roleDefinitionId: addR.includes("/") ? addR.trim() : `${scope.split("/providers/")[0]}/providers/${NS}/roleDefinitions/${addR.trim()}`,
    scheduleInfo: { startDateTime: new Date().toISOString(), expiration: { type: "NoExpiration" } } } } }));
  return (
    <div style={{ marginTop: 12 }} data-testid="iam-pim-panel">
      <InfoBar>Eligible assignments grant nothing until activated. An activation creates a time-bound active assignment (default maximum 8 hours) that the access evaluation honours and that ends by itself. Approval, MFA and ticketing are not simulated.</InfoBar>
      {(st.error || err) && <ErrorBar error={st.error || err} />}
      <h3>Eligible assignments</h3>
      <div style={{ display: "flex", gap: 12, alignItems: "flex-end", marginBottom: 8, flexWrap: "wrap" }}>
        <Field label="Activation hours"><Input value={hrs} aria-label="Activation hours" onChange={(_, d) => setHrs(d.value)} style={{ width: 90 }} /></Field>
        <Field label="Justification"><Input value={why} aria-label="Justification" onChange={(_, d) => setWhy(d.value)} /></Field>
      </div>
      <BrowseGrid resourceName="eligible assignment" rowKey={(r) => r.id} items={st.data?.elig || []} loading={st.loading} onRefresh={st.reload} csvName="pim-eligible.csv"
        columns={[
          { key: "principal", label: "Principal", value: (r) => r.properties.principalId, render: (r) => wrap(r.properties.principalId) },
          { key: "role", label: "Role", value: (r) => role(r.properties) },
          { key: "window", label: "Eligibility window", value: (r) => hours(r.properties.startDateTime, r.properties.endDateTime) },
          { key: "act", label: "Action", value: () => "Activate", render: (r) => <Button size="small" disabled={busy} onClick={() => activate(r)} aria-label={`Activate ${role(r.properties)}`}>Activate</Button> },
        ]} />
      <div style={{ display: "flex", gap: 12, alignItems: "flex-end", margin: "12px 0", flexWrap: "wrap" }}>
        <Field label="Principal object id"><Input value={addP} aria-label="Eligible principal id" onChange={(_, d) => setAddP(d.value)} /></Field>
        <Field label="Role definition (id or GUID)"><Input value={addR} aria-label="Eligible role definition" onChange={(_, d) => setAddR(d.value)} /></Field>
        <Button disabled={busy || !addP || !addR} onClick={addEligible}>Add eligible assignment</Button>
      </div>
      <h3>Active (activated) assignments</h3>
      <BrowseGrid resourceName="active assignment" rowKey={(r) => r.id} items={st.data?.act || []} loading={st.loading} onRefresh={st.reload} csvName="pim-active.csv"
        columns={[
          { key: "principal", label: "Principal", value: (r) => r.properties.principalId, render: (r) => wrap(r.properties.principalId) },
          { key: "role", label: "Role", value: (r) => role(r.properties) },
          { key: "end", label: "Ends", value: (r) => r.properties.endDateTime || "" },
          { key: "deact", label: "Action", value: () => "Deactivate", render: (r) => <Button size="small" disabled={busy} onClick={() => deactivate(r)} aria-label={`Deactivate ${role(r.properties)}`}>Deactivate</Button> },
        ]} />
    </div>
  );
}
