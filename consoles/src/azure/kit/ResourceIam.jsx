/* Access control (IAM) blade body shared by every Azure service blade: Check access (evaluated for
 * real by core/azure_iam_core.py), Role assignments (add/remove scoped to the resource, honouring
 * scope inheritance), Roles, Deny assignments. `a` = { id, name } of the resource. */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Select, Tab, TabList, ToolbarButton } from "@fluentui/react-components";
import { Add20Regular, Dismiss20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../common/notify.jsx";
import { useAsync } from "../../common/useAsync.js";
import BrowseGrid from "./BrowseGrid.jsx";
import { CapabilityContainer } from "./Capability.jsx";
import { KV, NotSimulatedContainer } from "./common.jsx";
import * as iam from "./iam.js";


function CheckAccess({ a, actions }) {
  const notify = useNotify();
  const [principalId, setPrincipalId] = useState("");
  const [action, setAction] = useState(actions[0]);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try { setResult(await iam.checkAccess(principalId, action, a.id)); }
    catch (e) { notify.error(e, "Check access failed"); }
    finally { setBusy(false); }
  };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, marginTop: 12 }}>
      <NotSimulatedContainer title="My access" feature="View my access" note="There is no real signed-in principal in Vyomi to view the access of — use Check access with any principal ID instead." />
      <section className="vy-section" style={{ maxWidth: 640 }}><h3>Check access</h3>
        <p style={{ fontSize: 13 }}>Evaluated for real against this resource's role assignments by core/azure_iam_core.py (explicit-deny-wins, scope inheritance).</p>
        <Field label="Principal ID" hint="Any identifier — Vyomi has no real directory to validate it against."><Input value={principalId} onChange={(_, d) => setPrincipalId(d.value)} /></Field>
        <Field label="Action">
          <Select value={action} onChange={(_, d) => setAction(d.value)}>
            {actions.map((act) => <option key={act} value={act}>{act}</option>)}
          </Select>
        </Field>
        <div style={{ marginTop: 8 }}><Button appearance="primary" disabled={!principalId || busy} onClick={go}>Check access</Button></div>
        {result && <div style={{ marginTop: 12 }}>
          <KV label="Access decision" value={result.value?.[0]?.accessDecision} />
          <KV label="Granting role(s)" value={result.value?.[0]?.roles?.join(", ") || "--"} />
        </div>}
      </section>
    </div>
  );
}

function RoleAssignments({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(iam.listRoleAssignments, []);
  const roles = useAsync(iam.listRoleDefinitions, []);
  const [add, setAdd] = useState(false);
  const scoped = (data || []).filter((r) => iam.scopeCovers(r.properties?.scope, a.id) && (r.properties?.kind || "allow") !== "deny");
  return (
    <>
      <BrowseGrid
        resourceName="role assignment" rowKey={(r) => r.name} items={scoped} loading={loading} error={error} onRefresh={reload}
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add</ToolbarButton>}
        onDelete={async (sel) => { for (const r of sel) await iam.deleteRoleAssignment(r.name); notify.success(`Removed ${sel.length} assignment${sel.length === 1 ? "" : "s"}.`, "Remove succeeded"); reload(); }}
        csvName="role-assignments.csv"
        columns={[
          { key: "name", label: "Name", value: (r) => r.properties?.principalId },
          { key: "type", label: "Type", value: () => "User/Group/SP (unverified)" },
          { key: "role", label: "Role", value: (r) => r.properties?.roleDefinitionId },
          { key: "scope", label: "Scope", value: (r) => (r.properties?.scope === a.id ? "This resource" : r.properties?.scope) },
          { key: "condition", label: "Condition", value: () => "None" },
        ]}
      />
      <Dialog open={add} onOpenChange={(_, d) => !d.open && setAdd(false)}>
        <DialogSurface aria-label="Add role assignment">
          <AddRoleAssignmentBody a={a} roleDefs={roles.data || []} onClose={() => setAdd(false)} onAdded={reload} />
        </DialogSurface>
      </Dialog>
    </>
  );
}

function AddRoleAssignmentBody({ a, roleDefs, onClose, onAdded }) {
  const notify = useNotify();
  const [principalId, setPrincipalId] = useState("");
  const [role, setRole] = useState("Reader");
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try {
      await iam.putRoleAssignment(`${a.name}-${principalId}-${role}`.replace(/[^a-zA-Z0-9-]/g, ""), {
        properties: { principalId, roleName: role, scope: a.id, kind: "allow" },
      });
      notify.success(`Role assignment added for '${principalId}'.`, "Add succeeded");
      setPrincipalId(""); onClose(); onAdded();
    } catch (e) { notify.error(e, "Failed to add role assignment"); }
    finally { setBusy(false); }
  };
  return (
    <DialogBody>
      <DialogTitle action={<Button appearance="subtle" icon={<Dismiss20Regular />} aria-label="Close" onClick={onClose} />}>Add role assignment</DialogTitle>
      <DialogContent>
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <Field label="Scope"><Input readOnly value={`This resource (${a.name})`} /></Field>
          <Field label="Role">
            <Select value={role} onChange={(_, d) => setRole(d.value)}>
              {roleDefs.map((r) => <option key={r.name} value={r.properties.roleName}>{r.properties.roleName}</option>)}
            </Select>
          </Field>
          <Field label="Principal ID" hint="Any identifier — Vyomi has no real directory to pick a member from.">
            <Input value={principalId} onChange={(_, d) => setPrincipalId(d.value)} aria-label="Principal ID" /></Field>
        </div>
      </DialogContent>
      <DialogActions>
        <Button appearance="primary" disabled={!principalId || busy} onClick={go}>Review + assign</Button>
        <Button onClick={onClose}>Cancel</Button>
      </DialogActions>
    </DialogBody>
  );
}

function Roles() {
  const { data, loading, error, reload } = useAsync(iam.listRoleDefinitions, []);
  return (
    <BrowseGrid
      resourceName="role" rowKey={(r) => r.name} items={data || []} loading={loading} error={error} onRefresh={reload}
      csvName="roles.csv"
      columns={[
        { key: "name", label: "Name", value: (r) => r.properties?.roleName },
        { key: "description", label: "Description", value: (r) => r.properties?.description || "--" },
        { key: "type", label: "Type", value: (r) => r.properties?.type },
        { key: "category", label: "Category", value: () => "General" },
        { key: "details", label: "Details", value: (r) => (r.properties?.permissions?.[0]?.actions || []).join(", ") },
      ]}
    />
  );
}

function DenyAssignments({ a }) {
  const { data, loading, error } = useAsync(iam.listRoleAssignments, []);
  const scoped = (data || []).filter((r) => r.properties?.kind === "deny" && iam.scopeCovers(r.properties?.scope, a.id));
  return (
    <BrowseGrid
      resourceName="deny assignment" rowKey={(r) => r.name} items={scoped} loading={loading} error={error}
      csvName="deny-assignments.csv"
      columns={[
        { key: "name", label: "Name", value: (r) => r.properties?.principalId },
        { key: "description", label: "Description", value: () => "--" },
        { key: "principal", label: "Principal", value: (r) => r.properties?.principalId },
        { key: "scope", label: "Scope", value: (r) => (r.properties?.scope === a.id ? "This resource" : r.properties?.scope) },
      ]}
    />
  );
}

export default function ResourceIam({ a, capId, actions }) {
  const [tab, setTab] = useState("check");
  return (
    <CapabilityContainer id={capId} title={`${a.name} | Access control (IAM)`}>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Access control (IAM) tabs">
        <Tab value="check">Check access</Tab>
        <Tab value="assignments">Role assignments</Tab>
        <Tab value="roles">Roles</Tab>
        <Tab value="deny">Deny assignments</Tab>
        <Tab value="classic">Classic administrators</Tab>
      </TabList>
      {tab === "check" && <CheckAccess a={a} actions={actions} />}
      {tab === "assignments" && <RoleAssignments a={a} />}
      {tab === "roles" && <Roles />}
      {tab === "deny" && <DenyAssignments a={a} />}
      {tab === "classic" && <NotSimulatedContainer title="Classic administrators" feature="Classic administrators" note="A legacy (pre-RBAC) co-administrator model Azure itself is retiring — not modelled." />}
    </CapabilityContainer>
  );
}
