/* The "extra" Access control (IAM) tabs shared by every Azure blade:
 *  - DenyAssignmentsPanel: deny assignments (kind=deny in the shared RBAC store, explicit-deny-wins
 *    in core/azure_iam_core.py) whose scope covers the resource;
 *  - ClassicAdminsPanel: the subscription's classic (co-)administrators, a real read of
 *    Microsoft.Authorization/classicAdministrators (read-only, like the retired real API);
 *  - MyAccess: the one simulated signed-in principal's access on this resource, evaluated for real
 *    with checkAccess. */
import { useState } from "react";
import { Button } from "@fluentui/react-components";
import { restJson } from "../../common/wire.js";
import { useAsync } from "../../common/useAsync.js";
import BrowseGrid from "./BrowseGrid.jsx";
import { CapabilityContainer } from "./Capability.jsx";
import { ErrorBar, KV, Loading } from "./common.jsx";
import { getSubscription } from "./arm.js";
import * as iam from "./iam.js";

export const CALLER = "11111111-1111-1111-1111-111111111111";
const SAMPLE = ["Microsoft.Authorization/roleAssignments/write", "Microsoft.Resources/subscriptions/resourceGroups/read", "Microsoft.Resources/subscriptions/resourceGroups/write", "Microsoft.Resources/subscriptions/resourceGroups/delete"];

export function DenyAssignmentsPanel({ a }) {
  const { data, loading, error, reload } = useAsync(iam.listRoleAssignments, []);
  const scoped = (data || []).filter((r) => r.properties?.kind === "deny" && iam.scopeCovers(r.properties?.scope, a.id));
  return (
    <div style={{ marginTop: 12 }}>
      <BrowseGrid
        resourceName="deny assignment" rowKey={(r) => r.name} items={scoped} loading={loading} error={error} onRefresh={reload}
        csvName="deny-assignments.csv"
        columns={[
          { key: "name", label: "Name", value: (r) => r.name },
          { key: "description", label: "Description", value: (r) => r.properties?.description || "--" },
          { key: "principal", label: "Principal", value: (r) => r.properties?.principalId },
          { key: "scope", label: "Scope", value: (r) => (r.properties?.scope === a.id ? "This resource" : r.properties?.scope) },
        ]}
      />
      <p className="vy-muted" style={{ fontSize: 12 }}>Deny assignments are created with <code>az role assignment create</code> / the Authorization API (properties.kind = "deny"); the portal itself only lists them, as here.</p>
    </div>
  );
}

export function ClassicAdminsPanel() {
  const { data, loading, error, reload } = useAsync(async () => (await restJson("GET", `/subscriptions/${getSubscription()}/providers/Microsoft.Authorization/classicAdministrators`, { query: { "api-version": "2015-06-01" } })).value || [], []);
  return (
    <div style={{ marginTop: 12 }}>
      <CapabilityContainer id="azure.common.classic_administrators" title="Classic administrators">
        <BrowseGrid
          resourceName="classic administrator" rowKey={(r) => r.name} items={data || []} loading={loading} error={error} onRefresh={reload}
          csvName="classic-administrators.csv"
          columns={[
            { key: "name", label: "Name", value: (r) => r.properties?.emailAddress },
            { key: "role", label: "Role", value: (r) => (r.properties?.role || "").split(";").join(", ") },
            { key: "scope", label: "Scope", value: () => "Subscription" },
          ]}
        />
      </CapabilityContainer>
    </div>
  );
}

export function MyAccess({ a }) {
  const [open, setOpen] = useState(false);
  const { data, loading, error } = useAsync(async () => {
    if (!open) return null;
    const all = await iam.listRoleAssignments();
    const mine = all.filter((r) => r.properties?.principalId === CALLER && iam.scopeCovers(r.properties?.scope, a.id));
    const decisions = [];
    for (const act of SAMPLE) { const r = await iam.checkAccess(CALLER, act, a.id); decisions.push([act, r.value?.[0]?.accessDecision, (r.value?.[0]?.roles || []).join(", ")]); }
    return { mine, decisions };
  }, [open, a.id]);
  return (
    <section className="vy-section"><h3>My access</h3>
      <p style={{ fontSize: 13 }}>Vyomi has one simulated signed-in principal ({CALLER}); this is its access to {a.name}, evaluated by the real checkAccess engine.</p>
      <Button onClick={() => setOpen((v) => !v)}>{open ? "Hide my access" : "View my access"}</Button>
      {open && (loading ? <Loading /> : error ? <ErrorBar error={error} /> : data && (
        <div style={{ marginTop: 8 }}>
          <KV label="Role assignments covering this resource" value={data.mine.map((r) => r.properties?.roleName || r.properties?.roleDefinitionId).join(", ") || "None"} />
          {data.decisions.map(([act, d, roles]) => <KV key={act} label={act} value={`${d}${roles ? ` (${roles})` : ""}`} />)}
        </div>
      ))}
    </section>
  );
}
