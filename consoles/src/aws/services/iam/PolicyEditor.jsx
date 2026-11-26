/* Real AWS-style policy editor for IAM > Create policy: Visual (service > actions > resources > request conditions, many statements)
 * and JSON (line-numbered textarea + "Edit statement" side panel), with a live Security/Errors/Warnings/Suggestions status bar.
 * Everything selectable comes from the verbatim IAM catalogs (see kit/PermissionPicker.jsx); the visual model is turned into IAM JSON by kit/iamPolicy.js. */
import { useMemo, useRef, useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Checkbox from "@cloudscape-design/components/checkbox";
import ExpandableSection from "@cloudscape-design/components/expandable-section";
import Input from "@cloudscape-design/components/input";
import Link from "@cloudscape-design/components/link";
import Popover from "@cloudscape-design/components/popover";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import { ServicePicker, useCatalog, useCatalogs, serviceLabel } from "../../kit/PermissionPicker.jsx";
import { IAM_SERVICES } from "../../kit/iamServices.js";
import {
  LEVELS, LEVEL_ALL_LABEL, actionNames, byLevel, resourceTypesFor, actionsForType, arnTemplate, anyInAccountArn, conditionKeysFor, conditionOperators,
  GLOBAL_COND_KEYS, newStatement, statementsToPolicy, validatePolicy,
} from "../../kit/iamPolicy.js";

const grid = { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: "10px 24px" };
const rule = { borderTop: "1px solid #e3e1de", paddingTop: 12, marginTop: 12 };
const upd = (st, patch) => ({ ...st, ...patch });

function ActionInfo({ name, a, cat, service }) {
  return (
    <Popover header={`${service}:${name}`} triggerType="text" position="right" size="medium" dismissButton={false}
      content={<SpaceBetween size="xxs">
        <Box variant="small">Access level: <b>{(LEVELS.find(([l]) => l === a.l) || [])[1] || a.l}</b></Box>
        <Box variant="small">Resource types: <b>{(a.r || []).length ? a.r.join(", ") : "none (all resources)"}</b></Box>
        <Box variant="small">Condition keys: {(a.k || []).length ? (a.k || []).join(", ") : "none"}</Box>
        {a.d ? <Box variant="small">Dependent actions exist for this action.</Box> : null}
      </SpaceBetween>}>Info</Popover>
  );
}

function ActionsSection({ st, cat, set }) {
  const [filter, setFilter] = useState("");
  const [openLv, setOpenLv] = useState({});
  const [manualOpen, setManualOpen] = useState(false);
  const [manual, setManual] = useState("");
  const svc = st.service, name = serviceLabel(svc);
  const toggle = (n, on) => set({ actions: on ? [...new Set([...st.actions, n])] : st.actions.filter((x) => x !== n) });
  const f = filter.trim();
  const renderGrid = (lv) => byLevel(cat, lv, filter).map((n) => (
    <div key={n} style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "nowrap" }}>
      <Checkbox checked={st.allActions || st.actions.includes(n)} disabled={st.allActions} onChange={({ detail }) => toggle(n, detail.checked)}>{n}</Checkbox>
      <ActionInfo name={n} a={cat.actions[n]} cat={cat} service={svc} />
    </div>
  ));
  return (
    <ExpandableSection variant="footer" defaultExpanded headerText="Actions allowed" headerDescription={`Specify actions from the service to be ${st.effect === "Allow" ? "allowed" : "denied"}.`} headingTagOverride="h3">
      <SpaceBetween size="m">
        <div style={{ display: "flex", gap: 24, justifyContent: "space-between", flexWrap: "wrap" }}>
          <div style={{ flex: "1 1 360px", maxWidth: 560 }}>
            <Input type="search" value={filter} onChange={({ detail }) => setFilter(detail.value)} placeholder="Filter Actions" ariaLabel="Filter Actions" clearAriaLabel="Clear" />
          </div>
          <div><Box variant="awsui-key-label">Effect</Box>
            <RadioGroup direction="horizontal" value={st.effect} onChange={({ detail }) => set({ effect: detail.value })} items={[{ value: "Allow", label: "Allow" }, { value: "Deny", label: "Deny" }]} ariaLabel="Effect" /></div>
        </div>
        <SpaceBetween size="xs">
          <Box>Manual actions | <Link onFollow={() => setManualOpen(!manualOpen)}>Add actions</Link></Box>
          {manualOpen && (
            <SpaceBetween direction="horizontal" size="xs">
              <Input value={manual} onChange={({ detail }) => setManual(detail.value)} placeholder={`${svc}:Get*`} ariaLabel="Manual action" />
              <Button disabled={!manual.includes(":") && !manual} onClick={() => { const v = manual.includes(":") ? manual : `${svc}:${manual}`; set({ manual: [...new Set([...st.manual, v])] }); setManual(""); }}>Add action</Button>
            </SpaceBetween>
          )}
          {st.manual.map((m) => <Box key={m} variant="code">{m} <Link onFollow={() => set({ manual: st.manual.filter((x) => x !== m) })} ariaLabel={`Remove ${m}`}>Remove</Link></Box>)}
          <Checkbox checked={st.allActions} onChange={({ detail }) => set({ allActions: detail.checked })}>All {name} actions ({svc}:*)</Checkbox>
        </SpaceBetween>
        {f ? (
          <SpaceBetween size="s">
            {LEVELS.map(([lv, label]) => { const g = byLevel(cat, lv, filter); return g.length ? <div key={lv}><Box variant="h4">{label}</Box><div style={{ ...grid, marginTop: 8 }}>{renderGrid(lv)}</div></div> : null; })}
            {LEVELS.every(([lv]) => !byLevel(cat, lv, filter).length) && <Box color="text-body-secondary">No actions match "{filter}".</Box>}
          </SpaceBetween>
        ) : (
          <div>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <Box>Access level</Box>
              <Box><Link onFollow={() => setOpenLv(Object.fromEntries(LEVELS.map(([l]) => [l, true])))}>Expand all</Link> | <Link onFollow={() => setOpenLv({})}>Collapse all</Link></Box>
            </div>
            {LEVELS.map(([lv, label]) => {
              const names = byLevel(cat, lv); if (!names.length) return null;
              const sel = names.filter((n) => st.allActions || st.actions.includes(n)).length;
              return (
                <ExpandableSection key={lv} variant="footer" headingTagOverride="h4" expanded={!!openLv[lv]} onChange={({ detail }) => setOpenLv({ ...openLv, [lv]: detail.expanded })} headerText={`${label} (${names.length})`}>
                  <SpaceBetween size="s">
                    <Checkbox checked={sel === names.length} indeterminate={sel > 0 && sel < names.length} disabled={st.allActions}
                      onChange={({ detail }) => set({ actions: detail.checked ? [...new Set([...st.actions, ...names])] : st.actions.filter((x) => !names.includes(x)) })}>{LEVEL_ALL_LABEL[lv]}</Checkbox>
                    <div style={grid}>{renderGrid(lv)}</div>
                  </SpaceBetween>
                </ExpandableSection>
              );
            })}
          </div>
        )}
      </SpaceBetween>
    </ExpandableSection>
  );
}

function ResourceRow({ st, cat, type, applies, set }) {
  const [adding, setAdding] = useState(false);
  const [arn, setArn] = useState("");
  const tpl = arnTemplate(cat, type);
  const hasAcct = tpl.includes("${Account}");
  const arns = st.arns[type] || [];
  const unspecified = !arns.length && !st.anyAcct[type] && !st.anyRes[type];
  const startAdd = () => { setArn(tpl.replace(/\$\{Partition\}/g, "aws").replace(/\$\{Region\}/g, "us-east-1").replace(/\$\{Account\}/g, "123456789012")); setAdding(true); };
  return (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(110px, 190px) 1fr 150px", gap: 16, alignItems: "start", padding: "8px 0" }} data-testid={`res-row-${type}`}>
      <Box variant="strong">{type} <Popover triggerType="text" header={type} content={<Box variant="small">ARN format: {tpl}</Box>} dismissButton={false}>Info</Popover></Box>
      <SpaceBetween size="xxs">
        {unspecified && <Box>You have not specified resource with type <b>{type}</b>.</Box>}
        {unspecified && applies.length > 0 && (
          <div style={{ background: "#fffce9", padding: "4px 8px" }}><StatusIndicator type="warning">Specified {type} resource ARN for the <b>{applies[0]}</b>{applies.length > 1 ? ` and ${applies.length - 1} more actions.` : " action."}</StatusIndicator></div>
        )}
        {st.anyAcct[type] && <Box variant="code">{anyInAccountArn(cat, type)}</Box>}
        {st.anyRes[type] && <Box variant="code">*</Box>}
        {arns.map((a) => <Box key={a} variant="code">{a} <Link onFollow={() => set({ arns: { ...st.arns, [type]: arns.filter((x) => x !== a) } })} ariaLabel={`Remove ${a}`}>Remove</Link></Box>)}
        {adding ? (
          <SpaceBetween direction="horizontal" size="xs">
            <Input value={arn} onChange={({ detail }) => setArn(detail.value)} ariaLabel={`${type} ARN`} />
            <Button disabled={!arn} onClick={() => { set({ arns: { ...st.arns, [type]: [...new Set([...arns, arn])] } }); setAdding(false); }}>Add ARN</Button>
            <Button variant="link" onClick={() => setAdding(false)}>Cancel</Button>
          </SpaceBetween>
        ) : <Box><Link onFollow={startAdd}>Add ARNs</Link> to restrict access.</Box>}
      </SpaceBetween>
      <Checkbox checked={hasAcct ? !!st.anyAcct[type] : !!st.anyRes[type]}
        onChange={({ detail }) => set(hasAcct ? { anyAcct: { ...st.anyAcct, [type]: detail.checked } } : { anyRes: { ...st.anyRes, [type]: detail.checked } })}>{hasAcct ? "Any in this account" : "Any"}</Checkbox>
    </div>
  );
}

function ResourcesSection({ st, cat, set }) {
  const concrete = st.allActions ? actionNames(cat) : st.actions;
  const types = resourceTypesFor(cat, concrete);
  return (
    <ExpandableSection variant="footer" headerText="Resources" headerDescription="Specify resource ARNs for these actions." headingTagOverride="h3" defaultExpanded={st.resMode === "specific"}>
      <SpaceBetween size="s">
        <RadioGroup value={st.resMode} onChange={({ detail }) => set({ resMode: detail.value })} ariaLabel="Resources" items={[{ value: "all", label: "All" }, { value: "specific", label: "Specific" }]} />
        {st.resMode === "specific" && !concrete.length && <Box color="text-body-secondary">Select actions to see the resource types they apply to.</Box>}
        {st.resMode === "specific" && types.map((t) => t === "*"
          ? <Box key={t} color="text-body-secondary">Some selected actions do not support resource-level permissions; they apply to all resources (*).</Box>
          : <ResourceRow key={t} st={st} cat={cat} type={t} applies={actionsForType(cat, concrete, t).sort()} set={set} />)}
      </SpaceBetween>
    </ExpandableSection>
  );
}

function ConditionsSection({ st, cat, set }) {
  const concrete = st.allActions ? actionNames(cat) : st.actions;
  const keys = [...conditionKeysFor(cat, concrete), ...Object.entries(GLOBAL_COND_KEYS).map(([key, type]) => ({ key, type }))];
  const keyOpts = keys.map((k) => ({ value: k.key, label: k.key, description: k.type }));
  const setCond = (id, patch) => set({ conds: st.conds.map((c) => (c.id === id ? { ...c, ...patch } : c)) });
  return (
    <ExpandableSection variant="footer" headerText={<span>Request conditions - <i>optional</i></span>} headerDescription="Actions on resources are allowed or denied only when these conditions are met." headingTagOverride="h3" defaultExpanded={!!(st.mfa || st.ipOn || st.conds.length)}>
      <SpaceBetween size="s">
        <Checkbox checked={st.mfa} onChange={({ detail }) => set({ mfa: detail.checked })} description="Filters access if MFA was used to validate the temporary security credentials that made the request">User is MFA Authenticated</Checkbox>
        <Checkbox checked={st.ipOn} onChange={({ detail }) => set({ ipOn: detail.checked })} description="Filters access by the requester's IP address">Requested from IP</Checkbox>
        {st.ipOn && <Input value={st.ip} onChange={({ detail }) => set({ ip: detail.value })} placeholder="203.0.113.0/24, 198.51.100.7" ariaLabel="Requested from IP" />}
        {st.conds.map((c) => {
          const type = (keys.find((k) => k.key === c.key) || {}).type;
          const ops = conditionOperators(type).map((o) => ({ value: o, label: o }));
          return (
            <div key={c.id} style={{ display: "grid", gridTemplateColumns: "minmax(200px,2fr) minmax(160px,1fr) minmax(160px,2fr) auto", gap: 8 }} data-testid="cond-row">
              <Select ariaLabel="Condition key" placeholder="Choose a condition key" filteringType="auto" options={keyOpts} selectedOption={keyOpts.find((o) => o.value === c.key) || null}
                onChange={({ detail }) => { const t = (keys.find((k) => k.key === detail.selectedOption.value) || {}).type; setCond(c.id, { key: detail.selectedOption.value, op: conditionOperators(t)[0] }); }} />
              <Select ariaLabel="Condition operator" options={ops} selectedOption={ops.find((o) => o.value === c.op) || null} disabled={!c.key} onChange={({ detail }) => setCond(c.id, { op: detail.selectedOption.value })} />
              <Input ariaLabel="Condition value" value={c.value} onChange={({ detail }) => setCond(c.id, { value: detail.value })} placeholder={type === "Bool" ? "true" : "Value"} />
              <Button iconName="remove" variant="icon" ariaLabel="Remove condition" onClick={() => set({ conds: st.conds.filter((x) => x.id !== c.id) })} />
            </div>
          );
        })}
        <div><Button iconName="add-plus" onClick={() => set({ conds: [...st.conds, { id: Math.random().toString(36).slice(2, 8), key: "", op: "", value: "" }] })}>Add another condition</Button></div>
      </SpaceBetween>
    </ExpandableSection>
  );
}

function StatementCard({ st, onChange, onCopy, onRemove, canRemove }) {
  const { cat, loading, missing } = useCatalog(st.service);
  const set = (patch) => onChange(upd(st, patch));
  const name = serviceLabel(st.service);
  return (
    <div style={{ border: "1px solid #e3e1de", background: "#fff", padding: 20 }} data-testid="statement-card">
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start" }}>
        <div>
          <Box variant="h2">{st.service ? name : "Select a service"}</Box>
          <Box color="text-body-secondary">{st.service ? `Set permissions for ${name}` : "Specify what actions can be performed on specific resources in a service."}</Box>
        </div>
        <SpaceBetween direction="horizontal" size="xs">
          {st.service && <Button iconName="copy" ariaLabel="Duplicate statement" onClick={onCopy} />}
          {canRemove && <Button iconName="remove" ariaLabel="Remove statement" onClick={onRemove} />}
        </SpaceBetween>
      </div>
      {!st.service ? (
        <Box padding={{ top: "m" }}>
          <div style={{ maxWidth: 520 }}>
            <Box variant="awsui-key-label">Service</Box>
            <ServicePicker value={null} onChange={(s) => set({ service: s, actions: [], manual: [], allActions: false, arns: {}, anyAcct: {}, anyRes: {} })} />
          </div>
        </Box>
      ) : loading ? <Box padding="m"><StatusIndicator type="loading">Loading {name} actions</StatusIndicator></Box>
        : missing ? <Box padding="m"><StatusIndicator type="error">The IAM catalog for {name} could not be loaded.</StatusIndicator></Box>
        : (
          <div style={{ marginTop: 12 }}>
            <Box color="text-body-secondary" padding={{ bottom: "s" }}>Specify what actions can be performed on specific resources in {name}.</Box>
            <ActionsSection st={st} cat={cat} set={set} />
            <div style={rule}><ResourcesSection st={st} cat={cat} set={set} /></div>
            <div style={rule}><ConditionsSection st={st} cat={cat} set={set} /></div>
          </div>
        )}
    </div>
  );
}

export function StatusBar({ result }) {
  const [open, setOpen] = useState(false);
  const cell = (label, n, type) => <StatusIndicator type={n && type ? type : "pending"}>{label}: {n}</StatusIndicator>;
  const all = [["Security", result.security], ["Error", result.errors], ["Warning", result.warnings], ["Suggestion", result.suggestions]];
  const msgs = all.flatMap(([k, l]) => l.map((m) => [k, m]));
  return (
    <div data-testid="policy-status" style={{ background: "#fff", padding: "8px 16px", border: "1px solid #e3e1de" }}>
      <SpaceBetween direction="horizontal" size="xl">
        {cell("Security", result.security.length, "warning")}
        {cell("Errors", result.errors.length, "error")}
        {cell("Warnings", result.warnings.length, "warning")}
        <Link onFollow={() => setOpen(!open)}>{cell("Suggestions", result.suggestions.length, "info")}</Link>
      </SpaceBetween>
      {(open || result.errors.length > 0) && msgs.length > 0 && (
        <Box padding={{ top: "xs" }}><SpaceBetween size="xxs">{msgs.filter(([k]) => open || k === "Error").map(([k, m], i) => <Box key={i} variant="small" color={k === "Error" ? "text-status-error" : "inherit"}>{k}: {m.message}</Box>)}</SpaceBetween></Box>
      )}
    </div>
  );
}

/** Visual editor body. stmts/setStmts are owned by CreatePolicy so Visual<->JSON stays in sync. */
export function VisualEditor({ stmts, setStmts }) {
  const cats = useCatalogs(stmts.map((s) => s.service).filter(Boolean));
  const doc = useMemo(() => statementsToPolicy(stmts, cats), [stmts, cats]);
  const result = useMemo(() => validatePolicy(doc, cats), [doc, cats]);
  const change = (i, st) => setStmts(stmts.map((x, j) => (j === i ? st : x)));
  return (
    <SpaceBetween size="m">
      {stmts.map((st, i) => (
        <StatementCard key={st.id} st={st} onChange={(n) => change(i, n)} canRemove={stmts.length > 1}
          onCopy={() => setStmts([...stmts.slice(0, i + 1), { ...st, id: Math.random().toString(36).slice(2, 9), conds: st.conds.map((c) => ({ ...c })) }, ...stmts.slice(i + 1)])}
          onRemove={() => setStmts(stmts.filter((_, j) => j !== i))} />
      ))}
      <div><Button iconName="add-plus" onClick={() => setStmts([...stmts, newStatement()])}>Add more permissions</Button></div>
      <StatusBar result={result} />
    </SpaceBetween>
  );
}

/* ---------------- JSON editor + Edit statement panel ---------------- */
const edit = (doc, fn) => { const d = JSON.parse(doc); const arr = Array.isArray(d.Statement) ? d.Statement : (d.Statement = [d.Statement]); fn(arr, d); return JSON.stringify(d, null, 2); };
const asArr = (v) => (v === undefined ? [] : [].concat(v));

function EditPanel({ doc, setDoc }) {
  const [sel, setSel] = useState(0);
  const [svc, setSvc] = useState(null);
  const [q, setQ] = useState("");
  const [aq, setAq] = useState("");
  const [picked, setPicked] = useState([]);
  const [err, setErr] = useState(null);
  const [rt, setRt] = useState(""); const [arn, setArn] = useState("");
  const [ck, setCk] = useState(null); const [cop, setCop] = useState(null); const [cv, setCv] = useState("");
  let parsed = null; try { parsed = JSON.parse(doc); } catch { /* invalid JSON: panel disabled below */ }
  const stmtList = parsed ? asArr(parsed.Statement) : [];
  const cur = stmtList[sel] || null;
  const stmtSvc = svc || (cur && asArr(cur.Action).map((a) => String(a).split(":")[0]).find((p) => IAM_SERVICES.some(([x]) => x === p))) || null;
  const { cat } = useCatalog(stmtSvc);
  const run = (fn) => { try { setDoc(edit(doc, fn)); setErr(null); } catch (e) { setErr(`Fix the JSON first: ${e.message}`); } };
  const items = IAM_SERVICES.filter(([p, n]) => !q || n.toLowerCase().includes(q.toLowerCase()) || p.includes(q.toLowerCase()));
  const names = cat ? actionNames(cat).filter((n) => !aq || n.toLowerCase().includes(aq.toLowerCase())).sort() : [];
  const resTypes = cat ? resourceTypesFor(cat, actionNames(cat)).filter((t) => t !== "*") : [];
  const keyOpts = cat ? conditionKeysFor(cat, []).map((k) => ({ value: k.key, label: k.key, description: k.type })) : [];
  const stmtOpts = stmtList.map((s, i) => ({ value: String(i), label: s.Sid || `Statement${i + 1}` }));
  const h = { fontWeight: 700, marginTop: 14, marginBottom: 6 };
  return (
    <div data-testid="edit-statement" style={{ width: 340, flex: "0 0 340px", borderLeft: "1px solid #e3e1de", padding: 12, maxHeight: 520, overflowY: "auto", background: "#fff" }}>
      <Box variant="h3">Edit statement</Box>
      {!parsed ? <Box color="text-body-secondary">Fix the JSON to use the statement editor.</Box> : (
        <SpaceBetween size="s">
          <Select ariaLabel="Statement" selectedOption={stmtOpts[sel] || null} options={stmtOpts} onChange={({ detail }) => { setSel(Number(detail.selectedOption.value)); setSvc(null); }} />
          {err && <Box color="text-status-error" variant="small">{err}</Box>}
          <div style={h}>Add actions</div>
          {!svc ? (
            <>
              <Box variant="awsui-key-label">Choose a service</Box>
              <Input type="search" value={q} onChange={({ detail }) => setQ(detail.value)} placeholder="Search services" ariaLabel="Search services" />
              <Box variant="awsui-key-label">Available</Box>
              <div style={{ maxHeight: 170, overflowY: "auto" }}>
                {items.map(([p, n]) => <div key={p}><Link onFollow={() => { setSvc(p); setPicked([]); setAq(""); }} variant="primary" fontSize="body-m">{n}</Link></div>)}
              </div>
            </>
          ) : (
            <SpaceBetween size="xs">
              <Box><Link onFollow={() => setSvc(null)}>Back to services</Link> / <b>{serviceLabel(svc)}</b></Box>
              <Input type="search" value={aq} onChange={({ detail }) => setAq(detail.value)} placeholder="Filter actions" ariaLabel="Filter actions" />
              <Checkbox checked={picked.includes("*")} onChange={({ detail }) => setPicked(detail.checked ? ["*"] : [])}>All {serviceLabel(svc)} actions ({svc}:*)</Checkbox>
              <div style={{ maxHeight: 170, overflowY: "auto" }}>
                {names.map((n) => <div key={n}><Checkbox checked={picked.includes(n)} onChange={({ detail }) => setPicked(detail.checked ? [...picked.filter((x) => x !== "*"), n] : picked.filter((x) => x !== n))}>{n}</Checkbox></div>)}
              </div>
              <Button disabled={!picked.length} onClick={() => { run((arr) => { const s = arr[sel]; s.Action = [...new Set([...asArr(s.Action), ...picked.map((n) => `${svc}:${n}`)])]; }); setPicked([]); }}>Add actions</Button>
            </SpaceBetween>
          )}
          <div style={h}>Add a resource</div>
          <Select ariaLabel="Resource type" placeholder={cat ? "Choose a resource type" : "Choose a service first"} disabled={!cat} options={resTypes.map((t) => ({ value: t, label: t, description: arnTemplate(cat, t) }))}
            selectedOption={rt ? { value: rt, label: rt } : null} onChange={({ detail }) => { setRt(detail.selectedOption.value); setArn(arnTemplate(cat, detail.selectedOption.value).replace(/\$\{Partition\}/g, "aws").replace(/\$\{Account\}/g, "123456789012").replace(/\$\{Region\}/g, "us-east-1")); }} />
          <Input value={arn} onChange={({ detail }) => setArn(detail.value)} ariaLabel="Resource ARN" placeholder="arn:aws:s3:::my-bucket" />
          <Button disabled={!arn} onClick={() => { run((a) => { const s = a[sel]; s.Resource = [...new Set([...asArr(s.Resource).filter((r) => r !== "*"), arn])]; }); setArn(""); setRt(""); }}>Add</Button>
          <div style={h}>Add a condition</div>
          <Select ariaLabel="Condition key" filteringType="auto" placeholder={cat ? "Choose a condition key" : "Choose a service first"} disabled={!cat} options={keyOpts} selectedOption={ck ? keyOpts.find((o) => o.value === ck.key) : null}
            onChange={({ detail }) => { const k = detail.selectedOption; const op = conditionOperators(cat.conditionKeys[k.value])[0]; setCk({ key: k.value }); setCop(op); }} />
          {ck && <Select ariaLabel="Condition operator" selectedOption={{ value: cop, label: cop }} options={conditionOperators(cat.conditionKeys[ck.key]).map((o) => ({ value: o, label: o }))} onChange={({ detail }) => setCop(detail.selectedOption.value)} />}
          <Input value={cv} onChange={({ detail }) => setCv(detail.value)} ariaLabel="Condition value" placeholder="Value" />
          <Button disabled={!ck || !cv} onClick={() => { run((a) => { const s = a[sel]; (s.Condition ||= {})[cop] = { ...(s.Condition[cop] || {}), [ck.key]: cv }; }); setCk(null); setCv(""); }}>Add</Button>
        </SpaceBetween>
      )}
    </div>
  );
}

export function JsonEditor({ doc, setDoc }) {
  const gutter = useRef(null);
  let prefixes = [];
  try { const d = JSON.parse(doc); prefixes = asArr(d.Statement).flatMap((s) => asArr(s?.Action ?? s?.NotAction)).filter((a) => typeof a === "string" && a.includes(":")).map((a) => a.split(":")[0]); } catch { /* invalid JSON */ }
  const cats = useCatalogs(prefixes);
  const result = useMemo(() => validatePolicy(doc, cats), [doc, cats]);
  const lines = doc.split("\n").length;
  const mono = { fontFamily: "Menlo, Monaco, Consolas, monospace", fontSize: 13, lineHeight: "20px" };
  return (
    <SpaceBetween size="s">
      <div style={{ display: "flex", border: "1px solid #e3e1de" }}>
        <div style={{ flex: 1, display: "flex", minWidth: 0, background: "#fff" }}>
          <pre ref={gutter} aria-hidden="true" style={{ ...mono, margin: 0, padding: "8px 8px", textAlign: "right", color: "#7d8998", background: "#fafafa", overflow: "hidden", height: 520, userSelect: "none", minWidth: 44 }}>{Array.from({ length: lines }, (_, i) => i + 1).join("\n")}</pre>
          <textarea aria-label="Policy document" spellCheck={false} value={doc} onChange={(e) => setDoc(e.target.value)} onScroll={(e) => { if (gutter.current) gutter.current.scrollTop = e.target.scrollTop; }}
            style={{ ...mono, flex: 1, height: 520, border: 0, outline: "none", resize: "none", padding: 8, whiteSpace: "pre", overflow: "auto", minWidth: 0 }} />
        </div>
        <EditPanel doc={doc} setDoc={setDoc} />
      </div>
      {result.expansions.length > 0 && <Box variant="small" color="text-body-secondary" data-testid="expansions">{result.expansions.map((e) => `${e.pattern} matches ${e.count} action${e.count === 1 ? "" : "s"}`).join("; ")}</Box>}
      <StatusBar result={result} />
    </SpaceBetween>
  );
}
