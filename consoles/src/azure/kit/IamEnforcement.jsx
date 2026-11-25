/* Azure Access control (IAM) tabs for enforcement, Fluent-native, shared by every blade that uses ResourceIam:
 *   EnforcementPanel  Off / Audit / Enforce for this resource (+ where the effective mode is inherited from) and the service
 *   EffectiveAccess   Check access, evaluated by the faithful engine: POST /api/iam/azure/evaluate -> decision + matched role assignments
 *   AuditPanel        read-only recent decisions with a "Would deny" badge for audit mode
 * `a` = { id, name } of the resource (ARM id). The "service" key is the resource provider namespace taken from the id. */
import { useState } from "react";
import { Badge, Button, Field, Input, Radio, RadioGroup, Select, Spinner } from "@fluentui/react-components";
import { MODES, MODE_LABEL, MODE_HELP, SOURCE_LABEL, auditLabel, filterAudit, reasonText } from "../../common/iamEnforce.js";
import { useAudit, useEnforcement, useIamApi } from "../../common/iamEnforceHooks.js";
import BrowseGrid from "./BrowseGrid.jsx";
import { ActionField, PrincipalField } from "./pickers/index.js";
import { ErrorBar, InfoBar, KV } from "./common.jsx";

const CLOUD = "azure";
export const providerOf = (id) => (/\/providers\/([^/]+)/i.exec(id || "") || [])[1] || "";
const BADGE = { off: "informative", audit: "warning", enforce: "success" };
export const ModeBadge = ({ mode }) => <Badge appearance="filled" color={BADGE[mode] || "informative"}>{MODE_LABEL[mode] || mode}</Badge>;

function ModeRadios({ value, onChange, disabled, inherit, label }) {
  return (
    <RadioGroup layout="horizontal" aria-label={label} value={value} disabled={disabled} onChange={(_, d) => onChange(d.value)}>
      {inherit && <Radio value="inherit" label="Inherit" />}
      {MODES.map((m) => <Radio key={m} value={m} label={MODE_LABEL[m]} />)}
    </RadioGroup>
  );
}

export function EnforcementPanel({ a }) {
  const e = useEnforcement(CLOUD);
  const svc = providerOf(a.id);
  if (e.loading) return <div style={{ padding: 16 }}><Spinner size="small" label="Loading..." /></div>;
  if (e.error && !e.settings) return <ErrorBar error={e.error} title="Could not load enforcement settings" />;
  const eff = e.resolve(svc, a.id);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, marginTop: 12 }} data-testid="iam-enforce-panel">
      <section className="vy-section" style={{ maxWidth: 720 }}><h3>Enforcement for this resource</h3>
        <p style={{ fontSize: 13 }}>Evaluate role assignments, deny assignments and conditions on every request to this resource. Off by default.</p>
        <KV label="Effective mode" value={<span style={{ display: "inline-flex", gap: 8, alignItems: "center" }}><ModeBadge mode={eff.mode} /> set by {SOURCE_LABEL[eff.source]}</span>} />
        <p className="vy-muted" style={{ fontSize: 12 }}>{MODE_HELP[eff.mode]}</p>
        <Field label="Resource override" hint="Inherit follows the resource provider, space and global settings.">
          <ModeRadios label="Resource enforcement mode" value={e.settings.resources[a.id] || "inherit"} inherit disabled={e.saving} onChange={(m) => e.set("resource", a.id, m)} /></Field>
      </section>
      {svc && <section className="vy-section" style={{ maxWidth: 720 }}><h3>{svc} (all resources)</h3>
        <Field label="Provider setting" hint="Applies to every resource of this provider without its own override."><ModeRadios label={`${svc} enforcement mode`} value={e.settings.services[svc] || "inherit"} inherit disabled={e.saving} onChange={(m) => e.set("service", svc, m)} /></Field></section>}
      <section className="vy-section" style={{ maxWidth: 720 }}><h3>Space defaults</h3>
        <Field label="This space"><ModeRadios label="Space enforcement mode" value={e.settings.space} disabled={e.saving} onChange={(m) => e.set("space", null, m)} /></Field>
        <Field label="Global"><ModeRadios label="Global enforcement mode" value={e.settings.global} disabled={e.saving} onChange={(m) => e.set("global", null, m)} /></Field>
      </section>
      {e.error && <ErrorBar error={e.error} title="Could not save" />}
    </div>
  );
}

export function EffectiveAccess({ a }) {
  const api = useIamApi(CLOUD);
  const [principal, setPrincipal] = useState(null);
  const [action, setAction] = useState("");
  const [isData, setIsData] = useState(false);
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true); setErr(null); setRes(null);
    try { setRes(await api.evaluate({ principal: { object_id: principal.id, type: principal.principalType }, action, resource: a.id, data: isData })); }
    catch (e) { setErr(e); } finally { setBusy(false); }
  };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, marginTop: 12 }}>
      <section className="vy-section" style={{ maxWidth: 720 }}><h3>Effective access</h3>
        <p style={{ fontSize: 13 }}>Check whether a principal can perform an action on {a.name}, using the engine that enforces requests (scope inheritance, deny assignments, not-actions, conditions).</p>
        <PrincipalField label="Principal" value={principal} onChange={setPrincipal} required />
        <ActionField label="Action or data action" value={action} onChange={(v, d) => { setAction(v); setIsData(!!d); }} required />
        <div style={{ marginTop: 8 }}><Button appearance="primary" disabled={!principal || !action || busy} onClick={run}>Check access</Button></div>
      </section>
      {err && <ErrorBar error={err} title="Evaluation failed" />}
      {res && <section className="vy-section" style={{ maxWidth: 720 }} data-testid="iam-eval-result"><h3>Result</h3>
        <KV label="Access decision" value={<Badge appearance="filled" color={res.allowed ? "success" : "danger"}>{res.allowed ? "Allowed" : "Denied"}</Badge>} />
        <KV label="Reason" value={reasonText(res)} />
        <KV label="Matched" value={(res.matched || []).length ? "" : "No role assignment matched (implicit deny)."} />
        {(res.matched || []).map((m, i) => <KV key={i} label={`${m.source} (${m.effect})`} value={<code style={{ wordBreak: "break-all" }}>{m.id}</code>} />)}
      </section>}
    </div>
  );
}

const wrapCell = (v) => <span title={v} style={{ display: "block", minWidth: 0, maxWidth: "100%", overflowWrap: "anywhere", wordBreak: "break-all" }}>{v}</span>;

export function AuditPanel({ limit = 100 }) {
  const au = useAudit(CLOUD, limit);
  const [mode, setMode] = useState("all");
  const [dec, setDec] = useState("all");
  const rows = filterAudit(au.data || [], { mode, decision: dec });
  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ display: "flex", gap: 12, alignItems: "flex-end", marginBottom: 8 }}>
        <Field label="Mode"><Select value={mode} onChange={(_, d) => setMode(d.value)} aria-label="Filter by mode"><option value="all">All modes</option>{MODES.map((m) => <option key={m} value={m}>{MODE_LABEL[m]}</option>)}</Select></Field>
        <Field label="Decision"><Select value={dec} onChange={(_, d) => setDec(d.value)} aria-label="Filter by decision"><option value="all">All decisions</option><option value="allow">Allowed</option><option value="deny">Denied or would deny</option><option value="would_deny">Would deny (audit)</option></Select></Field>
      </div>
      <InfoBar>Last {limit} decisions, read-only. In Audit mode a denial is logged as "Would deny" and the request is not blocked.</InfoBar>
      <BrowseGrid resourceName="decision" rowKey={(r) => `${r.ts}|${r.action}|${r.principal}|${r.resource}`} items={rows} loading={au.loading} error={au.error} onRefresh={au.reload}
        csvName="iam-audit.csv"
        columns={[
          { key: "ts", label: "Time", value: (r) => r.ts },
          { key: "principal", label: "Principal", value: (r) => r.principal, render: (r) => wrapCell(r.principal) },
          { key: "action", label: "Action", value: (r) => r.action, render: (r) => wrapCell(r.action) },
          { key: "resource", label: "Resource", value: (r) => r.resource, render: (r) => wrapCell(r.resource) },
          { key: "mode", label: "Mode", value: (r) => MODE_LABEL[r.mode] || r.mode },
          { key: "decision", label: "Decision", value: (r) => auditLabel(r) },
          { key: "reason", label: "Reason", value: (r) => r.reason },
        ]} />
    </div>
  );
}
