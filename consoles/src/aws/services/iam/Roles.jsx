/* Roles list — real ListRoles/DeleteRole + the Roles Anywhere trust-anchor/profile
 * control plane (see RolesAnywhere.jsx). */
import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import Link from "@cloudscape-design/components/link";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { navigate, follow } from "../../../common/router.js";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import RolesAnywherePanel from "./RolesAnywhere.jsx";
import * as api from "./api.js";

function trustedEntities(doc) {
  try {
    const d = typeof doc === "string" ? JSON.parse(doc) : doc;
    const stmts = Array.isArray(d?.Statement) ? d.Statement : [d?.Statement].filter(Boolean);
    const principals = stmts.map((s) => s?.Principal).filter(Boolean);
    if (!principals.length) return "-";
    const p = principals[0];
    if (p.Service) return "AWS service: " + ([].concat(p.Service).join(", "));
    if (p.AWS) return "AWS account: " + ([].concat(p.AWS).join(", "));
    if (p.Federated) return "Federated: " + ([].concat(p.Federated).join(", "));
    return JSON.stringify(p);
  } catch { return "-"; }
}

export default function Roles() {
  const notify = useNotify();
  const r = useAsync(() => api.listRoles(), []);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);

  return (
    <SpaceBetween size="l">
      <ResourceTable
        resourceName="Roles"
        items={r.data || []}
        loading={r.loading}
        error={r.error}
        onRefresh={r.reload}
        trackBy="RoleName"
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Search"
        empty={{ title: "No resources to display" }}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
            <Button variant="primary" onClick={() => navigate("iam", "create-role")}>Create role</Button>
          </SpaceBetween>
        }
        columns={[
          { id: "name", header: "Role name", isRowHeader: true, cell: (x) => <Link href={`#/iam/roles/${x.RoleName}`} onFollow={follow}>{x.RoleName}</Link> },
          { id: "trust", header: "Trusted entities", cell: (x) => trustedEntities(x.AssumeRolePolicyDocument) },
          { id: "last", header: "Last activity", cell: () => "-" },
        ]}
      />
      <RolesAnywherePanel roles={r.data || []} />
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="role"
        names={sel.map((x) => x.RoleName)}
        onConfirm={async () => { for (const x of sel) await api.deleteRole(x.RoleName); notify.success("Role(s) deleted."); setSel([]); r.reload(); }} />
    </SpaceBetween>
  );
}
