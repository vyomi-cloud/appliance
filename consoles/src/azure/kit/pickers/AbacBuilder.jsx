/* AbacBuilder: the "Conditions (optional)" tab. Add condition -> "Add action" (the role's condition-capable data actions, expanded from the
 * verbatim Microsoft.Storage catalog) + "Build expression" (attribute source Environment/Resource/Request, attribute, operator, value;
 * AND/OR; Group/Ungroup) with a Visual and a Code view. The generated code uses the subset core/iam_engine/azure_eval.py evaluates. */
import { useState } from "react";
import { Button, Checkbox, Input, Select, Tab, TabList } from "@fluentui/react-components";
import { Add20Regular, Delete16Regular } from "@fluentui/react-icons";
import { useAsync } from "../../../common/useAsync.js";
import Blade from "./Blade.jsx";
import { ABAC_ATTRIBUTES, ABAC_OPERATORS, conditionCode, loadProviderCatalog } from "./data.js";

const wild = (p) => new RegExp("^" + p.split("*").map((x) => x.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join(".*") + "$", "i");
/** The role's Microsoft.Storage blob data actions (wildcards expanded against the catalog), minus its notDataActions. */
export async function conditionActions(role) {
  const cat = await loadProviderCatalog("Microsoft.Storage").catch(() => null);
  const all = Object.keys(cat?.dataActions || {});
  const out = new Set();
  for (const p of role?.dataActions || []) { const re = wild(p); all.filter((a) => re.test(a)).forEach((a) => out.add(a)); }
  for (const p of role?.notDataActions || []) { const re = wild(p); all.filter((a) => re.test(a)).forEach((a) => out.delete(a)); }
  return [...out].filter((a) => /\/blobs\//i.test(a)).sort();
}
export const roleSupportsConditions = async (role) => !!role && (await conditionActions(role)).length > 0;

const newExpr = () => ({ kind: "expr", join: "AND", source: "Resource", name: ABAC_ATTRIBUTES[0].name, label: ABAC_ATTRIBUTES[0].label, type: "String", operator: "StringEquals", valueKind: "value", value: "" });
const bySource = (s) => ABAC_ATTRIBUTES.filter((a) => a.source === s);
const ID = (e) => `${e.source}|${e.label}`;

function ExprRow({ e, i, selected, onSel, onChange, onRemove }) {
  const set = (p) => onChange({ ...e, ...p });
  const attrs = bySource(e.source);
  const needsValue = !/^(Not)?Exists$/.test(e.operator);
  return (
    <tr data-testid="abac-expr">
      <td><Checkbox checked={selected} onChange={onSel} aria-label={`Select expression ${i + 1}`} /></td>
      <td>{i === 0 ? "" : <Select size="small" aria-label="Join" value={e.join} onChange={(_, d) => set({ join: d.value })}><option>AND</option><option>OR</option></Select>}</td>
      <td><Select size="small" aria-label="Attribute source" value={e.source} onChange={(_, d) => { const a = bySource(d.value)[0]; set({ source: d.value, name: a.name, label: a.label, type: a.type, keyed: a.keyed, operator: ABAC_OPERATORS[a.type][0] }); }}>
        {["Environment", "Resource", "Request"].map((s) => <option key={s}>{s}</option>)}</Select></td>
      <td><Select size="small" aria-label="Attribute" value={ID(e)} onChange={(_, d) => { const a = attrs.find((x) => ID(x) === d.value); set({ name: a.name, label: a.label, type: a.type, keyed: a.keyed, operator: ABAC_OPERATORS[a.type][0] }); }}>
        {attrs.map((a) => <option key={ID(a)} value={ID(a)}>{a.label}</option>)}</Select>
        {e.keyed && <Input size="small" style={{ marginTop: 4 }} placeholder="Key (case-sensitive)" aria-label="Tag key" value={e.key || ""} onChange={(_, d) => set({ key: d.value })} />}</td>
      <td><Select size="small" aria-label="Operator" value={e.operator} onChange={(_, d) => set({ operator: d.value })}>{ABAC_OPERATORS[e.type].map((o) => <option key={o}>{o}</option>)}</Select></td>
      <td>{needsValue && (e.type === "Boolean"
        ? <Select size="small" aria-label="Value" value={String(e.value || "true")} onChange={(_, d) => set({ value: d.value })}><option>true</option><option>false</option></Select>
        : <Input size="small" aria-label="Value" placeholder={/^ForAny|^ForAll/.test(e.operator) ? "comma separated" : "Value"} value={e.value || ""} onChange={(_, d) => set({ value: d.value })} />)}</td>
      <td><Button size="small" appearance="subtle" icon={<Delete16Regular />} aria-label={`Delete expression ${i + 1}`} onClick={onRemove} /></td>
    </tr>
  );
}

/** value = { actions: string[], nodes: [...] } ; onChange(value). Renders inline (the tab body). */
export default function AbacBuilder({ role, value, onChange }) {
  const acts = useAsync(() => conditionActions(role), [role?.id]);
  const [open, setOpen] = useState(false);
  const [view, setView] = useState("visual");
  const [sel, setSel] = useState(new Set());
  const [pick, setPick] = useState([]);
  const nodes = value?.nodes || [];
  const code = conditionCode(value?.actions || [], nodes);
  const upd = (p) => onChange({ actions: value?.actions || [], nodes, ...p });
  const flat = nodes.map((n, i) => ({ n, i }));
  const group = () => { const idx = [...sel].sort((a, b) => a - b); if (idx.length < 2) return; const items = idx.map((i) => nodes[i]); const first = idx[0];
    upd({ nodes: nodes.map((n, i) => (i === first ? { kind: "group", join: n.join, items: items.map((x, k) => (k === 0 ? { ...x, join: "AND" } : x)) } : sel.has(i) ? null : n)).filter(Boolean) }); setSel(new Set()); };
  const ungroup = () => { const out = []; nodes.forEach((n, i) => { if (sel.has(i) && n.kind === "group") n.items.forEach((x, k) => out.push(k === 0 ? { ...x, join: n.join } : x)); else out.push(n); }); upd({ nodes: out }); setSel(new Set()); };
  if (acts.loading) return <p>Checking whether this role supports conditions...</p>;
  if (!acts.data?.length) return <div className="vy-info" data-testid="abac-unsupported">Conditions are not supported for this role. Conditions can be added to roles that grant Azure Blob Storage data actions, for example Storage Blob Data Reader.</div>;
  return (
    <div data-testid="abac-builder">
      <p style={{ fontSize: 13 }}>Add conditions to refine the role assignment so it grants access only when an attribute expression is true. Conditions apply to the actions you choose; other actions are unaffected.</p>
      {!value?.actions?.length && !nodes.length ? <Button appearance="primary" icon={<Add20Regular />} onClick={() => { setPick([]); setOpen(true); }}>Add condition</Button> : (
        <>
          <TabList selectedValue={view} onTabSelect={(_, d) => setView(d.value)} aria-label="Condition view"><Tab value="visual">Visual</Tab><Tab value="code">Code</Tab></TabList>
          {view === "code" ? <pre className="vy-code" style={{ marginTop: 12 }} data-testid="abac-code">{code || "(add an action and at least one expression)"}</pre> : (
            <div style={{ marginTop: 12 }}>
              <h3 style={{ fontSize: 14 }}>Add action <span className="vy-req">*</span></h3>
              <div className="vy-chip-row" style={{ marginBottom: 8 }}>{(value?.actions || []).map((a) => <code key={a} style={{ background: "var(--colorNeutralBackground3)", padding: "2px 6px" }}>{a}</code>)}</div>
              <Button size="small" onClick={() => { setPick(value?.actions || []); setOpen(true); }}>Add action</Button>
              <h3 style={{ fontSize: 14, marginTop: 16 }}>Build expression</h3>
              <div style={{ display: "flex", gap: 8, margin: "6px 0" }}>
                <Button size="small" icon={<Add20Regular />} onClick={() => upd({ nodes: [...nodes, newExpr()] })}>Add expression</Button>
                <Button size="small" disabled={sel.size < 2} onClick={group}>Group</Button>
                <Button size="small" disabled={!sel.size} onClick={ungroup}>Ungroup</Button>
              </div>
              <table className="vy-pick-grid" aria-label="Expressions"><thead><tr><th /><th>Operator</th><th>Attribute source</th><th>Attribute</th><th>Function</th><th>Value</th><th /></tr></thead>
                <tbody>{flat.map(({ n, i }) => n.kind === "group" ? (
                  <tr key={i}><td><Checkbox checked={sel.has(i)} onChange={() => setSel((s) => { const k = new Set(s); k.has(i) ? k.delete(i) : k.add(i); return k; })} aria-label={`Select group ${i + 1}`} /></td>
                    <td>{i ? n.join : ""}</td><td colSpan={5}>Group: {n.items.map((x) => `${x.label} ${x.operator} ${x.value ?? ""}`).join(" AND ")}</td></tr>
                ) : <ExprRow key={i} e={n} i={i} selected={sel.has(i)} onSel={() => setSel((s) => { const k = new Set(s); k.has(i) ? k.delete(i) : k.add(i); return k; })}
                  onChange={(x) => upd({ nodes: nodes.map((y, j) => (j === i ? x : y)) })} onRemove={() => upd({ nodes: nodes.filter((_, j) => j !== i) })} />)}</tbody></table>
              <Button size="small" appearance="subtle" style={{ marginTop: 8 }} onClick={() => onChange(null)}>Remove condition</Button>
            </div>)}
        </>)}
      {open && <Blade level={2} title="Add action" subtitle="Select the data actions this condition applies to" width="min(820px,100vw)" onClose={() => setOpen(false)}
        footer={<><Button appearance="primary" disabled={!pick.length} onClick={() => { upd({ actions: pick, nodes: nodes.length ? nodes : [newExpr()] }); setOpen(false); }}>Select</Button><Button onClick={() => setOpen(false)}>Cancel</Button></>}>
        <table className="vy-pick-grid" style={{ marginTop: 12 }} aria-label="Condition actions"><tbody>{acts.data.map((a) => (
          <tr key={a}><td style={{ width: 32 }}><Checkbox checked={pick.includes(a)} onChange={() => setPick((p) => (p.includes(a) ? p.filter((x) => x !== a) : [...p, a]))} aria-label={a} /></td><td><code>{a}</code></td></tr>))}</tbody></table>
      </Blade>}
    </div>
  );
}
