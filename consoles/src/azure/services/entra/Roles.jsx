/* Roles and administrators | All roles — built-in + custom directory roles, backed by
 * the same Azure RBAC engine (core/azure_iam_core.py) the test_azure_rbac_core.py
 * conformance check proves, with role definitions assignable at the tenant-root scope. */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, ToolbarButton } from "@fluentui/react-components";
import { Add20Regular, ArrowDownload20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { NotSimulatedContainer } from "../../kit/common.jsx";
import EntraShell from "./EntraShell.jsx";
import * as api from "./api.js";
import { downloadCsv } from "./csv.js";

const COLUMNS = [
  { key: "role", label: "Role", value: (r) => r.properties.roleName },
  { key: "description", label: "Description", value: (r) => r.properties.description },
  { key: "privileged", label: "Privileged", value: (r) => (r.properties.privileged ? "Yes" : "No") },
  { key: "assignments", label: "Assignments", value: (r) => r.assignmentCount },
  { key: "type", label: "Type", value: (r) => (r.properties.type === "CustomRole" ? "Custom" : "Built-in") },
];

export default function Roles() {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listRoleDefinitions(), []);
  const [newRole, setNewRole] = useState(false);
  const [roleName, setRoleName] = useState("");
  const [desc, setDesc] = useState("");

  const create = async () => {
    await api.createCustomRole(roleName, desc);
    notify.success(`Created role ${roleName}.`, "New custom role");
    setNewRole(false); setRoleName(""); setDesc("");
    reload();
  };

  return (
    <EntraShell active="roles" title="Roles and administrators | All roles">
      <div className="vy-page">
        <BrowseGrid
          resourceName="role"
          rowKey={(r) => r.name}
          items={data || []}
          loading={loading}
          error={error}
          onRefresh={reload}
          onDelete={async (sel) => {
            const custom = sel.filter((r) => r.properties.type === "CustomRole");
            for (const r of custom) await api.deleteRoleDefinition(r.properties.roleName);
            notify.success(`Deleted ${custom.length} custom role${custom.length === 1 ? "" : "s"}.`, "Delete succeeded");
            reload();
          }}
          csvName="roles.csv"
          columns={COLUMNS}
          extraCommands={<>
            <ToolbarButton icon={<Add20Regular />} onClick={() => setNewRole(true)}>New custom role</ToolbarButton>
            <ToolbarButton icon={<ArrowDownload20Regular />} onClick={() => downloadCsv("role-assignments.csv", COLUMNS, data || [])} disabled={!data?.length}>Download assignments</ToolbarButton>
          </>}
        />
        <NotSimulatedContainer title="More commands" feature="Delete custom role, Preview features, Got feedback?"
          note="Delete custom role is available from the grid's Delete command (select a custom role first — built-in roles can't be removed). Preview features. Got feedback? are not simulated in Vyomi." />
      </div>
      <Dialog open={newRole} onOpenChange={(_, d) => setNewRole(d.open)}>
        <DialogSurface aria-label="New custom role">
          <DialogBody>
            <DialogTitle>New custom role</DialogTitle>
            <DialogContent>
              <Field label="Role name" required><Input value={roleName} onChange={(_, d) => setRoleName(d.value)} /></Field>
              <Field label="Description"><Input value={desc} onChange={(_, d) => setDesc(d.value)} /></Field>
            </DialogContent>
            <DialogActions>
              <Button appearance="primary" disabled={!roleName.trim()} onClick={create}>Create</Button>
              <Button onClick={() => setNewRole(false)}>Cancel</Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </EntraShell>
  );
}
