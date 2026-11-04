/* Create new user — a CreateWizard over the real Microsoft Graph users API, including
 * group/role assignment at creation time (the "Groups and roles" table on the
 * Assignments step is real: picks apply over the native wire once the user exists). */
import { useState } from "react";
import {
  Button, Checkbox, Dropdown, Input, Option, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow, ToolbarButton,
} from "@fluentui/react-components";
import { Add20Regular, Delete16Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import CreateWizard, { FormRow, FormSection } from "../../kit/CreateWizard.jsx";
import { Glyph } from "../../kit/common.jsx";
import * as api from "./api.js";
import { PickerDialog } from "./Picker.jsx";

export default function CreateUser() {
  const notify = useNotify();
  const groups = useAsync(() => api.listGroups(), []);
  const roles = useAsync(() => api.listRoleDefinitions(), []);
  const [upn, setUpn] = useState("");
  const [deriveNickname, setDeriveNickname] = useState(true);
  const [mailNickname, setMailNickname] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [autoGen, setAutoGen] = useState(true);
  const [password, setPassword] = useState("");
  const [genPwd] = useState(() => api.genPassword());
  const [accountEnabled, setAccountEnabled] = useState(true);
  const [firstName, setFirstName] = useState(""); const [lastName, setLastName] = useState("");
  const [userType, setUserType] = useState("Member");
  const [jobTitle, setJobTitle] = useState(""); const [companyName, setCompanyName] = useState(""); const [department, setDepartment] = useState("");
  const [email, setEmail] = useState(""); const [mobilePhone, setMobilePhone] = useState("");
  const [usageLocation, setUsageLocation] = useState("");
  const [assignments, setAssignments] = useState([]);   // [{id,label,kind:'group'|'role'}]
  const [picker, setPicker] = useState(null);

  const effectiveNickname = deriveNickname ? upn.split("@")[0] : mailNickname;
  const effectivePassword = autoGen ? genPwd : password;

  const basicsErrors = () => {
    const errs = [];
    if (!upn.trim()) errs.push("User principal name is required.");
    if (!displayName.trim()) errs.push("Display name is required.");
    if (!autoGen && !password.trim()) errs.push("Password is required.");
    return errs;
  };

  const create = async () => {
    const user = await api.createUser({
      userPrincipalName: upn, displayName, mailNickname: effectiveNickname, accountEnabled,
      passwordProfile: { password: effectivePassword, forceChangePasswordNextSignIn: true },
      givenName: firstName || undefined, surname: lastName || undefined, userType,
      jobTitle: jobTitle || undefined, companyName: companyName || undefined, department: department || undefined,
      mail: email || undefined, mobilePhone: mobilePhone || undefined, usageLocation: usageLocation || undefined,
    });
    for (const a of assignments) {
      if (a.kind === "group") await api.addMember(a.id, user.id);
      else await api.assignRole(a.id, user.id);
    }
    notify.success(`Created user ${displayName}.`, "User created");
    navigate("entra", "users", user.id);
  };

  return (
    <>
      <CreateWizard
        title="Create new user" glyph={<Glyph id="entra" />} closeHref="#/entra/users"
        onCreate={create}
        tabs={[
          {
            id: "basics", label: "Basics", validate: basicsErrors,
            content: (
              <FormSection title="Identity">
                <FormRow label="User principal name" required htmlFor="upn" info="Username and domain">
                  <Input id="upn" value={upn} onChange={(_, d) => setUpn(d.value)} placeholder={`user@${api.DEFAULT_DOMAIN}`} style={{ width: 360 }} />
                </FormRow>
                <FormRow label="Mail nickname">
                  <Input value={effectiveNickname} disabled={deriveNickname} onChange={(_, d) => setMailNickname(d.value)} style={{ width: 300 }} />
                  <div><Checkbox label="Derive from user principal name" checked={deriveNickname} onChange={(_, d) => setDeriveNickname(d.checked)} /></div>
                </FormRow>
                <FormRow label="Display name" required htmlFor="dn">
                  <Input id="dn" value={displayName} onChange={(_, d) => setDisplayName(d.value)} style={{ width: 300 }} />
                </FormRow>
                <FormRow label="Password" required>
                  <Input type="text" value={effectivePassword} disabled={autoGen} onChange={(_, d) => setPassword(d.value)} style={{ width: 300 }} />
                  <div><Checkbox label="Auto-generate password" checked={autoGen} onChange={(_, d) => setAutoGen(d.checked)} /></div>
                </FormRow>
                <FormRow label="Account enabled">
                  <Checkbox checked={accountEnabled} onChange={(_, d) => setAccountEnabled(d.checked)} />
                </FormRow>
              </FormSection>
            ),
          },
          {
            id: "properties", label: "Properties",
            content: (
              <>
                <FormSection title="Identity">
                  <FormRow label="First name"><Input value={firstName} onChange={(_, d) => setFirstName(d.value)} style={{ width: 280 }} /></FormRow>
                  <FormRow label="Last name"><Input value={lastName} onChange={(_, d) => setLastName(d.value)} style={{ width: 280 }} /></FormRow>
                  <FormRow label="User type">
                    <Dropdown value={userType} selectedOptions={[userType]} onOptionSelect={(_, d) => setUserType(d.optionValue)} style={{ width: 200 }}>
                      <Option value="Member">Member</Option>
                      <Option value="Guest">Guest</Option>
                    </Dropdown>
                  </FormRow>
                </FormSection>
                <FormSection title="Job Information">
                  <FormRow label="Job title"><Input value={jobTitle} onChange={(_, d) => setJobTitle(d.value)} style={{ width: 280 }} /></FormRow>
                  <FormRow label="Company name"><Input value={companyName} onChange={(_, d) => setCompanyName(d.value)} style={{ width: 280 }} /></FormRow>
                  <FormRow label="Department"><Input value={department} onChange={(_, d) => setDepartment(d.value)} style={{ width: 280 }} /></FormRow>
                </FormSection>
                <FormSection title="Contact Information">
                  <FormRow label="Email"><Input value={email} onChange={(_, d) => setEmail(d.value)} style={{ width: 280 }} /></FormRow>
                  <FormRow label="Mobile phone"><Input value={mobilePhone} onChange={(_, d) => setMobilePhone(d.value)} style={{ width: 280 }} /></FormRow>
                </FormSection>
                <FormSection title="Settings">
                  <FormRow label="Usage location"><Input value={usageLocation} onChange={(_, d) => setUsageLocation(d.value)} placeholder="United States" style={{ width: 240 }} /></FormRow>
                </FormSection>
              </>
            ),
          },
          {
            id: "assignments", label: "Assignments",
            content: (
              <FormSection title="Assignments">
                <FormRow label="Groups and roles">
                  <div className="vy-cmdbar" role="toolbar" aria-label="Assignments commands">
                    <ToolbarButton icon={<Add20Regular />} onClick={() => setPicker("group")}>Add group</ToolbarButton>
                    <ToolbarButton icon={<Add20Regular />} onClick={() => setPicker("role")}>Add role</ToolbarButton>
                  </div>
                  <Table size="small" style={{ marginTop: 8 }}>
                    <TableHeader><TableRow><TableHeaderCell>Name</TableHeaderCell><TableHeaderCell>Type</TableHeaderCell><TableHeaderCell /></TableRow></TableHeader>
                    <TableBody>
                      {assignments.map((a) => (
                        <TableRow key={a.kind + a.id}>
                          <TableCell>{a.label}</TableCell>
                          <TableCell>{a.kind === "group" ? "Group" : "Role"}</TableCell>
                          <TableCell><Button appearance="subtle" icon={<Delete16Regular />} onClick={() => setAssignments((xs) => xs.filter((x) => x !== a))} aria-label={`Remove ${a.label}`} /></TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </FormRow>
              </FormSection>
            ),
          },
        ]}
        review={() => (
          <>
            <FormSection title="Basics">
              <FormRow label="User principal name">{upn}</FormRow>
              <FormRow label="Display name">{displayName}</FormRow>
            </FormSection>
            <FormSection title="Properties">
              <FormRow label="User type">{userType}</FormRow>
            </FormSection>
            <FormSection title="Assignments">
              <FormRow label="Groups and roles">{assignments.length ? assignments.map((a) => a.label).join(", ") : "None"}</FormRow>
            </FormSection>
          </>
        )}
      />
      <PickerDialog open={picker === "group"} onClose={() => setPicker(null)} title="Add group"
        options={(groups.data || []).map((g) => ({ id: g.id, label: g.displayName }))}
        onPick={(picked) => setAssignments((xs) => [...xs, ...picked.map((p) => ({ ...p, kind: "group" }))])} />
      <PickerDialog open={picker === "role"} onClose={() => setPicker(null)} title="Add role"
        options={(roles.data || []).map((r) => ({ id: r.properties.roleName, label: r.properties.roleName }))}
        onPick={(picked) => setAssignments((xs) => [...xs, ...picked.map((p) => ({ ...p, kind: "role" }))])} />
    </>
  );
}
