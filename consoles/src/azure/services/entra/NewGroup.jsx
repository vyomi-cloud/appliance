/* New Group — a single-page flyout form (the real portal has no multi-step wizard here).
 * Owners/Members pickers are real: Vyomi tracks group ownership as initial membership
 * (it has no separate owner relation), so picks here land as real group members. */
import { useState } from "react";
import { Dropdown, Input, Option, Radio, RadioGroup, Textarea } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import CreateWizard, { FormRow, FormSection } from "../../kit/CreateWizard.jsx";
import { Glyph } from "../../kit/common.jsx";
import * as api from "./api.js";
import { PickerDialog } from "./Picker.jsx";

export default function NewGroup() {
  const notify = useNotify();
  const users = useAsync(() => api.listUsers(), []);
  const [groupType, setGroupType] = useState("Security");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [assignableToRole, setAssignableToRole] = useState("No");
  const [membershipType, setMembershipType] = useState("Assigned");
  const [owners, setOwners] = useState([]);
  const [members, setMembers] = useState([]);
  const [picker, setPicker] = useState(null);

  const validate = () => (name.trim() ? [] : ["Group name is required."]);

  const create = async () => {
    const g = await api.createGroup({
      displayName: name, description: description || undefined,
      groupTypes: groupType === "Microsoft 365" ? ["Unified"] : [],
      mailEnabled: groupType === "Microsoft 365", securityEnabled: groupType === "Security",
      isAssignableToRole: assignableToRole === "Yes",
    });
    for (const u of [...owners, ...members]) await api.addMember(g.id, u.id);
    notify.success(`Created group ${name}.`, "Group created");
    navigate("entra", "groups", "all");
  };

  return (
    <>
      <CreateWizard title="New Group" glyph={<Glyph id="entra" />} closeHref="#/entra/groups/all" onCreate={create}
        tabs={[{
          id: "basics", label: "Basics", validate,
          content: (
            <FormSection title="New Group">
              <FormRow label="Group type" required>
                <Dropdown value={groupType} selectedOptions={[groupType]} onOptionSelect={(_, d) => setGroupType(d.optionValue)} style={{ width: 240 }}>
                  <Option value="Security">Security</Option>
                  <Option value="Microsoft 365">Microsoft 365</Option>
                </Dropdown>
              </FormRow>
              <FormRow label="Group name" required><Input value={name} onChange={(_, d) => setName(d.value)} style={{ width: 300 }} /></FormRow>
              <FormRow label="Group description"><Textarea value={description} onChange={(_, d) => setDescription(d.value)} style={{ width: 360 }} /></FormRow>
              <FormRow label="Microsoft Entra roles can be assigned to the group">
                <RadioGroup value={assignableToRole} onChange={(_, d) => setAssignableToRole(d.value)} layout="horizontal">
                  <Radio value="Yes" label="Yes" /><Radio value="No" label="No" />
                </RadioGroup>
              </FormRow>
              <FormRow label="Membership type">
                <Dropdown value={membershipType} selectedOptions={[membershipType]} onOptionSelect={(_, d) => setMembershipType(d.optionValue)} style={{ width: 240 }}>
                  <Option value="Assigned">Assigned</Option>
                  <Option value="Dynamic User">Dynamic User</Option>
                  <Option value="Dynamic Device">Dynamic Device</Option>
                </Dropdown>
              </FormRow>
              <FormRow label="Owners">
                <a href="#" onClick={(e) => { e.preventDefault(); setPicker("owners"); }}>{owners.length ? `${owners.length} owner(s) selected` : "No owners selected"}</a>
              </FormRow>
              <FormRow label="Members">
                <a href="#" onClick={(e) => { e.preventDefault(); setPicker("members"); }}>{members.length ? `${members.length} member(s) selected` : "No members selected"}</a>
              </FormRow>
            </FormSection>
          ),
        }]}
        review={() => (
          <FormSection title="New Group">
            <FormRow label="Group name">{name}</FormRow>
            <FormRow label="Group type">{groupType}</FormRow>
          </FormSection>
        )}
      />
      <PickerDialog open={picker === "owners"} onClose={() => setPicker(null)} title="Add owners"
        options={(users.data || []).map((u) => ({ id: u.id, label: u.displayName }))} onPick={setOwners} />
      <PickerDialog open={picker === "members"} onClose={() => setPicker(null)} title="Add members"
        options={(users.data || []).map((u) => ({ id: u.id, label: u.displayName }))} onPick={setMembers} />
    </>
  );
}
