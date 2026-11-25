/* Access control (IAM) blade body shared by every Azure service blade: Check access (evaluated for
 * real by core/azure_iam_core.py), Role assignments (add/remove scoped to the resource, honouring
 * scope inheritance), Roles, Deny assignments. `a` = { id, name } of the resource. */
import { useState } from "react";
import { Button, Link, Tab, TabList, ToolbarButton } from "@fluentui/react-components";
import { Add20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../common/notify.jsx";
import { useAsync } from "../../common/useAsync.js";
import BrowseGrid from "./BrowseGrid.jsx";
import { CapabilityContainer } from "./Capability.jsx";
import { KV, NotSimulatedContainer } from "./common.jsx";
import * as iam from "./iam.js";
import { EnforcementPanel, EffectiveAccess, AuditPanel } from "./IamEnforcement.jsx";
import { AddCustomRoleWizard, AddRoleAssignmentWizard, ActionField, PrincipalField, RolePermissions } from "./pickers/index.js";
import Blade from "./pickers/Blade.jsx";
import { loadDirectory, loadRoles, reloadRoles } from "./pickers/data.js";
import { ClassicAdminsPanel, DenyAssignmentsPanel, MyAccess } from "./IamExtras.jsx";


function CheckAccess({ a }) {
  const notify = useNotify();
  const [principal, setPrincipal] = useState(null);
  const [action, setAction] = useState("");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try { setResult(await iam.checkAccess(principal.id, action, a.id)); }
    catch (e) { notify.error(e, "Check access failed"); }
    finally { setBusy(false); }
  };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, marginTop: 12 }}>
      <MyAccess a={a} />
      <section className="vy-section" style={{ maxWidth: 640 }}><h3>Check access</h3>
        <p style={{ fontSize: 13 }}>Evaluated for real against this resource's role assignments by core/azure_iam_core.py (explicit-deny-wins, scope inheritance).</p>
        <PrincipalField label="Find a user, group, or service principal" value={principal} onChange={setPrincipal} required />
        <ActionField label="Action to check" value={action} onChange={setAction} required />
        <div style={{ marginTop: 8 }}><Button appearance="primary" disabled={!principal || !action || busy} onClick={go}>Check access</Button></div>
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
  const names = useAsync(async () => { const [r, d] = await Promise.all([loadRoles(), loadDirectory()]); return { roles: new Map(r.map((x) => [x.id, x.roleName])), dir: new Map(d.map((x) => [x.id, x])) }; }, []);
  const [add, setAdd] = useState(false);
  const scoped = (data || []).filter((r) => iam.scopeCovers(r.properties?.scope, a.id) && (r.properties?.kind || "allow") !== "deny");
  const roleOf = (r) => r.properties?.roleName || names.data?.roles.get((r.properties?.roleDefinitionId || "").split("/").pop()) || r.properties?.roleDefinitionId;
  return (
    <>
      <BrowseGrid
        resourceName="role assignment" rowKey={(r) => r.name} items={scoped} loading={loading} error={error} onRefresh={reload}
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add role assignment</ToolbarButton>}
        onDelete={async (sel) => { for (const r of sel) await iam.deleteRoleAssignment(r.name); notify.success(`Removed ${sel.length} assignment${sel.length === 1 ? "" : "s"}.`, "Remove succeeded"); reload(); }}
        csvName="role-assignments.csv"
        columns={[
          { key: "name", label: "Name", value: (r) => names.data?.dir.get(r.properties?.principalId)?.name || r.properties?.principalId },
          { key: "type", label: "Type", value: (r) => names.data?.dir.get(r.properties?.principalId)?.type || r.properties?.principalType || "--" },
          { key: "role", label: "Role", value: roleOf },
          { key: "scope", label: "Scope", value: (r) => (r.properties?.scope === a.id ? "This resource" : r.properties?.scope) },
          { key: "condition", label: "Condition", value: (r) => (r.properties?.condition ? "View" : "None") },
        ]}
      />
      {add && <AddRoleAssignmentWizard scope={a.id} scopeLabel={`${a.name} | Access control (IAM)`} onClose={() => setAdd(false)} onAdded={reload} />}
    </>
  );
}

export function Roles({ a }) {
  const { data, loading, error, reload } = useAsync(loadRoles, []);
  const [view, setView] = useState(null);
  const [add, setAdd] = useState(false);
  return (
    <>
      <BrowseGrid
        resourceName="role" rowKey={(r) => r.id} items={data || []} loading={loading} error={error} onRefresh={() => { reloadRoles().then(reload); }}
        csvName="roles.csv" extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add custom role</ToolbarButton>}
        columns={[
          { key: "name", label: "Name", value: (r) => r.roleName },
          { key: "description", label: "Description", value: (r) => r.description || "--" },
          { key: "type", label: "Type", value: (r) => r.type },
          { key: "category", label: "Category", value: (r) => r.category },
          { key: "details", label: "Details", value: (r) => "View", render: (r) => <Link as="button" onClick={() => setView(r)} aria-label={`View ${r.roleName}`}>View</Link> },
        ]}
      />
      {view && <Blade title={view.roleName} subtitle="Role definition" width="min(820px,100vw)" onClose={() => setView(null)}><RolePermissions role={view} /></Blade>}
      {add && <AddCustomRoleWizard scope={a?.id} onClose={() => setAdd(false)} onAdded={() => reloadRoles().then(reload)} />}
    </>
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
        <Tab value="enforcement">Enforcement</Tab>
        <Tab value="effective">Effective access</Tab>
        <Tab value="audit">Audit</Tab>
      </TabList>
      {tab === "check" && <CheckAccess a={a} />}
      {tab === "assignments" && <RoleAssignments a={a} />}
      {tab === "roles" && <Roles a={a} />}
      {tab === "deny" && <DenyAssignmentsPanel a={a} />}
      {tab === "classic" && <ClassicAdminsPanel />}
      {tab === "enforcement" && <EnforcementPanel a={a} />}
      {tab === "effective" && <EffectiveAccess a={a} />}
      {tab === "audit" && <AuditPanel />}
    </CapabilityContainer>
  );
}
