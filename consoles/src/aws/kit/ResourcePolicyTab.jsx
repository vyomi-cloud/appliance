/* Shared AWS "resource-based policy" tab (S3 bucket policy, SQS/SNS access policy, Secrets Manager resource permissions, ECR repository
 * permissions, API Gateway / DynamoDB / Backup / EventBridge bus policy ...). One component, configured per service in kit/resourcePolicies.js.
 *   - shows the REAL stored policy (statements table + JSON) read through the service's native Get call,
 *   - Edit opens the visual editor (Effect, Principal picker, Action picker from the verbatim IAM catalog, Resources, Sid) or the JSON editor
 *     (the same line-numbered JsonEditor as IAM > Create policy, with the live Security/Errors/Warnings bar),
 *   - Save calls the service's native Put call (s3 PutBucketPolicy, sqs SetQueueAttributes Policy, sns SetTopicAttributes, secretsmanager
 *     PutResourcePolicy, ecr SetRepositoryPolicy ...), Delete the native Delete call. */
import { useMemo, useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import RadioGroup from "@cloudscape-design/components/radio-group";
import SegmentedControl from "@cloudscape-design/components/segmented-control";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Table from "@cloudscape-design/components/table";
import TokenGroup from "@cloudscape-design/components/token-group";
import { useAsync } from "../../common/useAsync.js";
import { useNotify } from "../../common/notify.jsx";
import { CapabilityContainer, saveNotice } from "./Capability.jsx";
import { ErrorAlert } from "./common.jsx";
import { ActionPicker, PrincipalPicker, useCatalogs } from "./PermissionPicker.jsx";
import { validatePolicy } from "./iamPolicy.js";
import { JsonEditor, StatusBar } from "../services/iam/PolicyEditor.jsx";
import { RESOURCE_POLICIES } from "./resourcePolicies.js";

const asArr = (v) => (v === undefined || v === null ? [] : [].concat(v));
export const EMPTY = JSON.stringify({ Version: "2012-10-17", Statement: [] }, null, 2);
const pretty = (t) => { try { return JSON.stringify(typeof t === "string" ? JSON.parse(t) : t, null, 2); } catch { return String(t || ""); } };
const uid = () => Math.random().toString(36).slice(2, 9);

// ---- statement model <-> policy JSON --------------------------------------------------------------------------------------------
const principalList = (p) => (p === "*" ? ["*"] : p && typeof p === "object" ? Object.values(p).flatMap(asArr) : []);
const principalKind = (v) => (/\.amazonaws\.com(\.cn)?$/.test(v) || /^[a-z0-9-]+\.[a-z0-9.-]+$/.test(v) && !/^\d{12}$/.test(v) && !v.startsWith("arn:") ? "Service" : "AWS");
function buildPrincipal(list) {
  if (list.length === 1 && list[0] === "*") return "*";
  const out = {};
  for (const v of list) (out[principalKind(v)] ||= []).push(v);
  for (const k of Object.keys(out)) if (out[k].length === 1) out[k] = out[k][0];
  return out;
}
export function docToStatements(text) {
  const d = typeof text === "string" ? JSON.parse(text) : text;
  const stmts = asArr(d.Statement);
  const unsupported = stmts.some((s) => s.NotAction || s.NotPrincipal || s.NotResource);
  return {
    unsupported, version: d.Version || "2012-10-17", id: d.Id,
    stmts: stmts.map((s) => ({ key: uid(), sid: s.Sid || "", effect: s.Effect || "Allow", principals: principalList(s.Principal), actions: asArr(s.Action), resources: asArr(s.Resource), condition: s.Condition })),
  };
}
export function statementsToDoc({ version, id, stmts }) {
  return JSON.stringify({
    Version: version || "2012-10-17", ...(id ? { Id: id } : {}),
    Statement: stmts.map((s) => ({
      ...(s.sid ? { Sid: s.sid } : {}), Effect: s.effect, ...(s.principals.length ? { Principal: buildPrincipal(s.principals) } : {}),
      Action: s.actions.length === 1 ? s.actions[0] : s.actions, Resource: s.resources.length === 1 ? s.resources[0] : s.resources, ...(s.condition ? { Condition: s.condition } : {}),
    })),
  }, null, 2);
}

function TokenAdder({ label, items, onChange, placeholder, children }) {
  const [v, setV] = useState("");
  const add = () => { const t = v.trim(); if (t && !items.includes(t)) onChange([...items, t]); setV(""); };
  return (
    <SpaceBetween size="xs">
      {children}
      <SpaceBetween direction="horizontal" size="xs">
        <Input value={v} onChange={({ detail }) => setV(detail.value)} onKeyDown={({ detail }) => { if (detail.key === "Enter") add(); }} placeholder={placeholder} ariaLabel={label} />
        <Button onClick={add} disabled={!v.trim()} ariaLabel={`Add ${label}`}>Add</Button>
      </SpaceBetween>
      {items.length > 0 && <TokenGroup items={items.map((x) => ({ label: x }))} onDismiss={({ detail }) => onChange(items.filter((_, i) => i !== detail.itemIndex))} ariaLabel={label} />}
    </SpaceBetween>
  );
}

function StatementForm({ st, onChange, onRemove, service, principalMode, canRemove }) {
  const set = (patch) => onChange({ ...st, ...patch });
  const own = st.actions.filter((a) => a.startsWith(service + ":") && !a.includes("*")).map((a) => a.slice(service.length + 1));
  const other = st.actions.filter((a) => !(a.startsWith(service + ":") && !a.includes("*")));
  return (
    <div style={{ border: "1px solid #e3e1de", padding: 16 }} data-testid="policy-statement">
      <SpaceBetween size="m">
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
          <FormField label="Statement ID (Sid)"><Input value={st.sid} onChange={({ detail }) => set({ sid: detail.value })} ariaLabel="Statement ID" /></FormField>
          {canRemove && <Button onClick={onRemove}>Remove statement</Button>}
        </div>
        <FormField label="Effect"><RadioGroup value={st.effect} onChange={({ detail }) => set({ effect: detail.value })} items={[{ value: "Allow", label: "Allow" }, { value: "Deny", label: "Deny" }]} /></FormField>
        {principalMode !== "none" && (
          <FormField label="Principals" description="Who the statement applies to: pick an IAM user or role, or enter an account ID, ARN or service principal such as lambda.amazonaws.com. Use * for everyone.">
            <TokenAdder label="Principal" items={st.principals} onChange={(principals) => set({ principals })} placeholder="123456789012, arn:aws:iam::..., events.amazonaws.com or *">
              <PrincipalPicker value="" onChange={(arn) => st.principals.includes(arn) || set({ principals: [...st.principals, arn] })} ariaLabel="Add IAM user or role principal" />
            </TokenAdder>
          </FormField>
        )}
        <FormField label="Actions" description={`${service}:* actions from the verbatim IAM catalog; wildcards and other services can be typed below.`}>
          <TokenAdder label="Other action" items={other} onChange={(o) => set({ actions: [...own.map((n) => `${service}:${n}`), ...o] })} placeholder={`${service}:* or another service action`}>
            <ActionPicker service={service} multiple value={own} ariaLabel="Actions" onChange={(names) => set({ actions: [...names.map((n) => `${service}:${n}`), ...other] })} />
          </TokenAdder>
        </FormField>
        <FormField label="Resources"><TokenAdder label="Resource" items={st.resources} onChange={(resources) => set({ resources })} placeholder="arn:aws:... or *" /></FormField>
        {st.condition && <Box variant="small" color="text-body-secondary">This statement has Condition keys; they are preserved when you save and can be changed in the JSON editor.</Box>}
      </SpaceBetween>
    </div>
  );
}

function Editor({ cfg, args, initial, onCancel, onSaved, saving, setSaving, error, setError }) {
  const notify = useNotify();
  const [mode, setMode] = useState("Visual");
  const parsed = useMemo(() => { try { return docToStatements(initial || EMPTY); } catch { return null; } }, [initial]);
  const [model, setModel] = useState(() => parsed && !parsed.unsupported ? parsed : null);
  const [doc, setDoc] = useState(pretty(initial || EMPTY));
  const [convErr, setConvErr] = useState(parsed ? (parsed.unsupported ? "This policy uses NotAction / NotPrincipal / NotResource, which the visual editor cannot show. Use the JSON editor." : null) : "The stored policy is not valid JSON; fix it in the JSON editor.");
  const effMode = model ? mode : "JSON";
  const switchTo = (m) => {
    if (m === mode) return;
    if (m === "JSON" && model) setDoc(statementsToDoc(model));
    if (m === "Visual") {
      try { const p = docToStatements(doc); if (p.unsupported) throw new Error("NotAction / NotPrincipal / NotResource statements are JSON-only."); setModel(p); setConvErr(null); }
      catch (e) { setConvErr(`Can't show this policy in the visual editor: ${e.message}`); return; }
    }
    setMode(m);
  };
  const text = effMode === "Visual" && model ? statementsToDoc(model) : doc;
  const prefixes = useMemo(() => { try { return asArr(JSON.parse(text).Statement).flatMap((s) => asArr(s.Action)).filter((a) => typeof a === "string" && a.includes(":")).map((a) => a.split(":")[0]); } catch { return []; } }, [text]);
  const cats = useCatalogs([cfg.service, ...prefixes]);
  const result = useMemo(() => validatePolicy(text, cats), [text, cats]);
  const save = async () => {
    try { JSON.parse(text); } catch (e) { setError(new Error(`Policy is not valid JSON: ${e.message}`)); return; }
    if (result.errors.length) { setError(new Error(result.errors[0].message)); return; }
    setSaving(true); setError(null);
    try { await cfg.save(args, text); notify.success(`${cfg.noun || "Policy"} saved.${cfg.capId ? saveNotice(cfg.capId) : ""}`); onSaved(); }
    catch (e) { setError(e); } finally { setSaving(false); }
  };
  return (
    <SpaceBetween size="m">
      <SegmentedControl selectedId={effMode} onChange={({ detail }) => switchTo(detail.selectedId)} label="Policy editor mode" options={[{ id: "Visual", text: "Visual" }, { id: "JSON", text: "JSON" }]} />
      {convErr && <Alert type="warning" statusIconAriaLabel="Warning">{convErr}</Alert>}
      {effMode === "Visual" && model ? (
        <SpaceBetween size="m">
          {model.stmts.map((st, i) => (
            <StatementForm key={st.key} st={st} service={cfg.service} principalMode={cfg.principals} canRemove
              onChange={(n) => setModel({ ...model, stmts: model.stmts.map((x, j) => (j === i ? n : x)) })} onRemove={() => setModel({ ...model, stmts: model.stmts.filter((_, j) => j !== i) })} />
          ))}
          <div><Button iconName="add-plus" onClick={() => setModel({ ...model, stmts: [...model.stmts, { key: uid(), sid: `Statement${model.stmts.length + 1}`, effect: "Allow", principals: [], actions: [], resources: cfg.defaultResources ? cfg.defaultResources(args) : [], condition: undefined }] })}>Add statement</Button></div>
          <StatusBar result={result} />
        </SpaceBetween>
      ) : <JsonEditor doc={doc} setDoc={setDoc} />}
      {error && <ErrorAlert error={error} header={`Couldn't save ${cfg.noun || "policy"}`} />}
      <SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onCancel} disabled={saving}>Cancel</Button>
        <Button variant="primary" onClick={save} loading={saving}>Save changes</Button>
      </SpaceBetween>
    </SpaceBetween>
  );
}

export default function ResourcePolicyTab({ kind, args, onChanged }) {
  const cfg = RESOURCE_POLICIES[kind];
  const notify = useNotify();
  const dep = JSON.stringify([kind, args]);
  const pol = useAsync(async () => { const t = await cfg.load(args); return t ? pretty(t) : ""; }, [dep]);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  let rows = []; let parseErr = null;
  try { if (pol.data) rows = asArr(JSON.parse(pol.data).Statement); } catch (e) { parseErr = e; }
  const rm = async () => { try { await cfg.remove(args); notify.success(`${cfg.noun || "Policy"} deleted.`); pol.reload(); onChanged && onChanged(); } catch (e) { notify.error(e); } };
  const Wrapper = cfg.capId ? CapabilityContainer : ({ children, title, description, actions }) => <Container header={<Header variant="h2" description={description} actions={actions}>{title}</Header>}>{children}</Container>;
  return (
    <div data-testid={`rpol-${kind}`}>
    <Wrapper id={cfg.capId} title={cfg.title} description={cfg.description}
      actions={editing ? null : <SpaceBetween direction="horizontal" size="xs">
        {cfg.remove && <Button disabled={!pol.data} onClick={rm}>Delete</Button>}
        <Button onClick={() => { setError(null); setEditing(true); }}>Edit</Button>
      </SpaceBetween>}>
      <ErrorAlert error={pol.error} header="Couldn't load the policy" />
      {editing ? (
        <Editor cfg={cfg} args={args} initial={pol.data} onCancel={() => setEditing(false)} onSaved={() => { setEditing(false); pol.reload(); onChanged && onChanged(); }} saving={saving} setSaving={setSaving} error={error} setError={setError} />
      ) : pol.loading ? <Box color="text-body-secondary">Loading...</Box> : !pol.data ? <Box color="text-body-secondary">{cfg.empty || "No policy to display."}</Box> : (
        <SpaceBetween size="m">
          {parseErr && <Alert type="warning">The stored policy is not valid JSON.</Alert>}
          <Table variant="embedded" items={rows.map((s, i) => ({ ...s, _i: i }))} trackBy="_i" ariaLabels={{ tableLabel: "Policy statements" }}
            columnDefinitions={[
              { id: "sid", header: "Sid", cell: (s) => s.Sid || "-" },
              { id: "effect", header: "Effect", cell: (s) => s.Effect },
              { id: "principal", header: "Principal", cell: (s) => principalList(s.Principal).join(", ") || "-" },
              { id: "action", header: "Action", cell: (s) => asArr(s.Action ?? s.NotAction).join(", ") },
              { id: "resource", header: "Resource", cell: (s) => asArr(s.Resource).join(", ") || "-" },
              { id: "condition", header: "Condition", cell: (s) => (s.Condition ? "View in JSON" : "None") },
            ]} empty={<Box textAlign="center" color="inherit">No statements</Box>} />
          <Box variant="code"><pre style={{ margin: 0, whiteSpace: "pre-wrap" }} data-testid="policy-json">{pol.data}</pre></Box>
        </SpaceBetween>
      )}
    </Wrapper>
    </div>
  );
}
