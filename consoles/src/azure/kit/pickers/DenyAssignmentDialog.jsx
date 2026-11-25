/* Add deny assignment (Vyomi extension: the real portal only lists deny assignments; here they are stored with kind=deny and enforced
 * explicit-deny-wins by core/azure_iam_core.py). Principal, scope and denied actions all come from pickers. */
import { useState } from "react";
import { Button, Field, Input, Textarea } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import Blade from "./Blade.jsx";
import { PrincipalField, ScopeField } from "./Fields.jsx";
import PermissionPicker from "./PermissionPicker.jsx";
import * as iam from "../iam.js";

export default function DenyAssignmentDialog({ scope, onClose, onAdded }) {
  const notify = useNotify();
  const [name, setName] = useState(""); const [desc, setDesc] = useState("");
  const [principal, setPrincipal] = useState(null); const [sc, setSc] = useState(scope);
  const [actions, setActions] = useState([]); const [pick, setPick] = useState(false); const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try {
      await iam.putRoleAssignment(crypto.randomUUID(), { properties: { kind: "deny", principalId: principal.id, principalType: principal.principalType, scope: sc, denyActions: actions, description: desc || name, denyAssignmentName: name } });
      notify.success(`Deny assignment '${name}' added.`, "Add deny assignment"); onAdded?.(); onClose();
    } catch (e) { notify.error(e, "Failed to add deny assignment"); } finally { setBusy(false); }
  };
  return (
    <Blade title="Add deny assignment" onClose={onClose} width="min(760px,100vw)" testid="add-deny"
      footer={<><Button appearance="primary" disabled={busy || !name || !principal || !actions.length} onClick={go}>Add</Button><Button onClick={onClose}>Cancel</Button></>}>
      <div style={{ display: "flex", flexDirection: "column", gap: 14, paddingTop: 12 }}>
        <Field label="Deny assignment name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Deny assignment name" /></Field>
        <Field label="Description"><Textarea value={desc} onChange={(_, d) => setDesc(d.value)} aria-label="Description" /></Field>
        <PrincipalField label="Deny to" value={principal} onChange={setPrincipal} required />
        <ScopeField value={sc} onChange={setSc} required />
        <Field label="Denied actions" required>
          <div><Button size="small" onClick={() => setPick(true)}>+ Add denied actions</Button>
            <table className="vy-pick-grid" style={{ marginTop: 6 }}><tbody>{actions.map((a) => <tr key={a}><td><code>{a}</code></td><td style={{ width: 80 }}><Button size="small" appearance="subtle" onClick={() => setActions((x) => x.filter((y) => y !== a))}>Remove</Button></td></tr>)}</tbody></table></div>
        </Field>
      </div>
      {pick && <PermissionPicker onClose={() => setPick(false)} onAdd={(s) => { setActions((x) => [...new Set([...x, ...s.actions, ...s.data])]); setPick(false); }} />}
    </Blade>
  );
}
