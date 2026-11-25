/* ScopePicker: subscription > resource group > resource tree (ARM). Used by the deny-assignment dialog, Check access and custom-role
 * assignable scopes. Selecting a node yields its ARM id. */
import { useState } from "react";
import { Button, Spinner } from "@fluentui/react-components";
import { ChevronDown16Regular, ChevronRight16Regular } from "@fluentui/react-icons";
import { useAsync } from "../../../common/useAsync.js";
import { getSubscription } from "../arm.js";
import Blade from "./Blade.jsx";
import { loadResourceGroups, loadRgResources } from "./data.js";

function Row({ depth, label, id, value, onPick, expandable, open, onToggle }) {
  return (
    <div className={`row${value === id ? " sel" : ""}`} style={{ paddingLeft: 6 + depth * 18 }} role="treeitem" aria-selected={value === id} aria-label={label} onClick={() => onPick(id)}>
      {expandable ? <span onClick={(e) => { e.stopPropagation(); onToggle(); }} style={{ display: "inline-flex" }}>{open ? <ChevronDown16Regular /> : <ChevronRight16Regular />}</span> : <span style={{ width: 16 }} />}
      <span>{label}</span>
    </div>
  );
}
function RgNode({ rg, value, onPick }) {
  const [open, setOpen] = useState(false);
  const res = useAsync(async () => (open ? loadRgResources(rg.name) : []), [open, rg.name]);
  const sub = getSubscription();
  return (<>
    <Row depth={1} label={rg.name} id={`/subscriptions/${sub}/resourceGroups/${rg.name}`} value={value} onPick={onPick} expandable open={open} onToggle={() => setOpen((o) => !o)} />
    {open && (res.loading ? <div style={{ paddingLeft: 52 }}><Spinner size="tiny" /></div> : (res.data || []).map((r) => <Row key={r.id} depth={2} label={`${r.name} (${(r.type || "").split("/").pop()})`} id={r.id} value={value} onPick={onPick} />))}
  </>);
}
export function ScopeTree({ value, onPick }) {
  const sub = getSubscription();
  const rgs = useAsync(loadResourceGroups, []);
  return (
    <div className="vy-ptree" role="tree" aria-label="Scope">
      <Row depth={0} label={`Subscription (${sub})`} id={`/subscriptions/${sub}`} value={value} onPick={onPick} />
      {rgs.loading ? <Spinner size="tiny" /> : (rgs.data || []).map((rg) => <RgNode key={rg.id || rg.name} rg={rg} value={value} onPick={onPick} />)}
    </div>
  );
}
export default function ScopePicker({ value, onChange, onClose, title = "Select a scope" }) {
  const [cur, setCur] = useState(value);
  return (
    <Blade level={2} title={title} width="min(560px,100vw)" onClose={onClose} testid="scope-picker"
      footer={<><Button appearance="primary" disabled={!cur} onClick={() => onChange(cur)}>Select</Button><Button onClick={onClose}>Cancel</Button></>}>
      <p style={{ fontSize: 13 }}>Selected: <code>{cur || "none"}</code></p>
      <ScopeTree value={cur} onPick={setCur} />
    </Blade>
  );
}
