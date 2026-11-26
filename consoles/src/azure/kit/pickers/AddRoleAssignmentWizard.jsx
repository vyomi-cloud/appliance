/* Add role assignment wizard (Microsoft docs flow): Role | Members | Conditions | Review + assign.
 * Writes one ARM PUT .../providers/Microsoft.Authorization/roleAssignments/{guid} per selected member. */
import { useMemo, useState } from "react";
import { Button, Field, Radio, RadioGroup, Tab, TabList, Textarea } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import Blade from "./Blade.jsx";
import RolePicker from "./RolePicker.jsx";
import MemberPicker, { Avatar } from "./MemberPicker.jsx";
import AbacBuilder, { roleSupportsConditions } from "./AbacBuilder.jsx";
import { conditionCode, roleDefinitionId } from "./data.js";
import * as iam from "../iam.js";

const guid = () => (crypto.randomUUID ? crypto.randomUUID() : "00000000-0000-4000-8000-" + Date.now().toString(16).padStart(12, "0"));
export const buildAssignmentBody = ({ role, member, scope, description, condition }) => ({
  properties: {
    roleDefinitionId: roleDefinitionId(scope, role), principalId: member.id, principalType: member.principalType, scope,
    ...(description ? { description } : {}), ...(condition ? { condition, conditionVersion: "2.0" } : {}),
    roleName: role.roleName, kind: "allow",   // roleName: what core/azure_iam_core.py resolves the role by
  },
});

export default function AddRoleAssignmentWizard({ scope, scopeLabel, initialRole, onClose, onAdded }) {
  const notify = useNotify();
  const [tab, setTab] = useState(initialRole ? "members" : "role");
  const [role, setRole] = useState(initialRole || null);
  const [assignTo, setAssignTo] = useState("principals");
  const [members, setMembers] = useState([]);
  const [desc, setDesc] = useState("");
  const [abac, setAbac] = useState(null);
  const [pick, setPick] = useState(false);
  const [busy, setBusy] = useState(false);
  const supports = useAsync(() => roleSupportsConditions(role), [role?.id]);
  const condition = useMemo(() => conditionCode(abac?.actions || [], abac?.nodes || []), [abac]);
  const order = ["role", "members", "conditions", "review"];
  const ok = !!role && members.length > 0;
  const go = async () => {
    setBusy(true);
    try {
      for (const m of members) await iam.putRoleAssignment(guid(), buildAssignmentBody({ role, member: m, scope, description: desc, condition }));
      notify.success(`Added ${members.length} role assignment${members.length === 1 ? "" : "s"} (${role.roleName}).`, "Add role assignment");
      onAdded?.(); onClose();
    } catch (e) { notify.error(e, "Failed to add role assignment"); } finally { setBusy(false); }
  };
  const next = () => setTab(order[Math.min(order.indexOf(tab) + 1, 3)]);
  const prev = () => setTab(order[Math.max(order.indexOf(tab) - 1, 0)]);
  return (
    <Blade title="Add role assignment" subtitle={scopeLabel} onClose={onClose} testid="add-role-assignment" label="Add role assignment"
      footer={<>
        {tab === "review" ? <Button appearance="primary" disabled={!ok || busy} onClick={go}>Review + assign</Button>
          : <Button appearance="primary" disabled={!ok} onClick={() => setTab("review")}>Review + assign</Button>}
        <Button disabled={tab === "role"} onClick={prev}>Previous</Button>
        <Button disabled={tab === "review"} onClick={next}>Next</Button>
      </>}>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} style={{ marginTop: 8 }} aria-label="Add role assignment steps">
        <Tab value="role">Role</Tab><Tab value="members">Members</Tab><Tab value="conditions">Conditions</Tab><Tab value="review">Review + assign</Tab>
      </TabList>
      <div style={{ paddingTop: 12 }}>
        {tab === "role" && <RolePicker value={role} onChange={(r) => { setRole(r); setAbac(null); }} />}
        {tab === "members" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 860 }}>
            <p style={{ fontSize: 13, margin: 0 }}>Selected role: <b>{role ? role.roleName : "none"}</b></p>
            <Field label="Assign access to">
              <RadioGroup value={assignTo} onChange={(_, d) => { setAssignTo(d.value); setMembers([]); }} aria-label="Assign access to">
                <Radio value="principals" label="User, group, or service principal" /><Radio value="mi" label="Managed identity" />
              </RadioGroup>
            </Field>
            <Field label="Members" required>
              <div><Button onClick={() => setPick(true)} data-testid="select-members">+ Select members</Button></div>
              {members.length > 0 && <table className="vy-pick-grid" style={{ marginTop: 8 }} aria-label="Selected members"><thead><tr><th>Name</th><th>Object ID</th><th>Type</th><th /></tr></thead>
                <tbody>{members.map((m) => <tr key={m.id}><td><span style={{ display: "inline-flex", gap: 8, alignItems: "center" }}><Avatar name={m.name} id={m.id} />{m.name}</span></td><td>{m.id}</td><td>{m.type}</td>
                  <td><Button size="small" appearance="subtle" onClick={() => setMembers((s) => s.filter((x) => x.id !== m.id))}>Remove</Button></td></tr>)}</tbody></table>}
            </Field>
            <Field label="Description"><Textarea value={desc} onChange={(_, d) => setDesc(d.value)} placeholder="Optional description" aria-label="Description" /></Field>
          </div>)}
        {tab === "conditions" && (role ? <AbacBuilder role={role} value={abac} onChange={setAbac} /> : <p>Select a role first.</p>)}
        {tab === "review" && (
          <div style={{ maxWidth: 860 }} data-testid="ra-review">
            <table className="vy-pick-grid"><tbody>
              <tr><th style={{ width: 180 }}>Role</th><td>{role?.roleName || "--"}</td></tr>
              <tr><th>Scope</th><td>{scope}</td></tr>
              <tr><th>Members</th><td>{members.map((m) => `${m.name} (${m.type})`).join(", ") || "--"}</td></tr>
              <tr><th>Description</th><td>{desc || "No description"}</td></tr>
              <tr><th>Condition</th><td>{condition ? <pre className="vy-code" style={{ margin: 0 }}>{condition}</pre> : supports.data ? "None" : "Not supported for this role"}</td></tr>
            </tbody></table>
          </div>)}
      </div>
      {pick && <MemberPicker kind={assignTo} initial={members} onClose={() => setPick(false)} onAdd={(s) => { setMembers(s); setPick(false); }} />}
    </Blade>
  );
}
