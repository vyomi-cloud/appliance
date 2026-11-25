/* Form fields that open a picker instead of taking free text: PrincipalField (MemberPicker), ActionField (PermissionPicker, single),
 * ScopeField (ScopePicker). Each shows the chosen value read-only with a Select button. */
import { useState } from "react";
import { Button, Field, Input } from "@fluentui/react-components";
import MemberPicker, { Avatar } from "./MemberPicker.jsx";
import PermissionPicker from "./PermissionPicker.jsx";
import ScopePicker from "./ScopePicker.jsx";

export function PrincipalField({ label = "Principal", value, onChange, kind = "principals", required }) {
  const [open, setOpen] = useState(false);
  return (
    <Field label={label} required={required}>
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        {value ? <span style={{ display: "inline-flex", gap: 8, alignItems: "center" }} data-testid="principal-value"><Avatar name={value.name} id={value.id} />{value.name}<span className="vy-muted">({value.type})</span></span> : <span className="vy-muted">No principal selected</span>}
        <Button size="small" onClick={() => setOpen(true)}>{value ? "Change" : "Select principal"}</Button>
      </div>
      {open && <MemberPicker title="Select principal" kind={kind} multiple={false} initial={value ? [value] : []} addLabel="Select" onClose={() => setOpen(false)} onAdd={(s) => { onChange(s[0]); setOpen(false); }} />}
    </Field>
  );
}
export function ActionField({ label = "Action", value, onChange, required }) {
  const [open, setOpen] = useState(false);
  return (
    <Field label={label} required={required}>
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        {value ? <code data-testid="action-value" style={{ overflowWrap: "anywhere" }}>{value}</code> : <span className="vy-muted">No action selected</span>}
        <Button size="small" onClick={() => setOpen(true)}>{value ? "Change" : "Select action"}</Button>
      </div>
      {open && <PermissionPicker single onClose={() => setOpen(false)} onAdd={(s) => { onChange(s.actions[0] || s.data[0]); setOpen(false); }} />}
    </Field>
  );
}
export function ScopeField({ label = "Scope", value, onChange, required }) {
  const [open, setOpen] = useState(false);
  return (
    <Field label={label} required={required}>
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <Input readOnly value={value || ""} style={{ flex: 1 }} aria-label={label} />
        <Button size="small" onClick={() => setOpen(true)}>Select scope</Button>
      </div>
      {open && <ScopePicker value={value} onClose={() => setOpen(false)} onChange={(v) => { onChange(v); setOpen(false); }} />}
    </Field>
  );
}
