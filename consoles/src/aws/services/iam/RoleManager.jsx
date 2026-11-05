/* IAM Role manager - role inventory with last-used / unused detection from the simulator's own recorded activity,
 * trust + policy summary, dependency-checked delete of unused roles. Backed by ListRoleInventory / DeleteUnusedRoles
 * (core/iam_core.py); policy attach/detach and trust edits happen on the role detail page (stock IAM actions). */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Modal from "@cloudscape-design/components/modal";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Input from "@cloudscape-design/components/input";
import FormField from "@cloudscape-design/components/form-field";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { fmtDate } from "../../kit/common.jsx";
import * as api from "./api.js";

const STATUS = { Active: "success", New: "info", Unused: "warning", NeverUsed: "warning" };
const LABEL = { Active: "Active", New: "New (not yet evaluated)", Unused: "Unused", NeverUsed: "Never used" };

export default function RoleManager() {
  const notify = useNotify();
  const [days, setDays] = useState("90");
  const d = Math.max(1, parseInt(days, 10) || 90);
  const inv = useAsync(() => api.listRoleInventory(d), [d]);
  const [sel, setSel] = useState([]);
  const [confirm, setConfirm] = useState(false);
  const items = inv.data || [];
  const unused = items.filter((r) => r.Deletable === "true" || r.Deletable === true);
  const del = async () => {
    try {
      const res = await api.deleteUnusedRoles(sel.map((r) => r.RoleName), d);
      const ok = res.filter((x) => x.Result === "Deleted").length;
      const skipped = res.filter((x) => x.Result !== "Deleted");
      if (ok) notify.success(`${ok} role(s) deleted.`);
      skipped.forEach((x) => notify.error(`${x.RoleName}: ${x.Reason}`));
    } catch (e) { notify.error(e); }
    setConfirm(false); setSel([]); inv.reload();
  };
  return (
    <CapabilityContainer id="iam.organizations.role-manager" title="Role manager">
      <SpaceBetween size="s">
        <Box color="text-body-secondary" variant="small">
          Last used comes from activity the simulator itself recorded (for example a Lambda invocation under the role's execution role). A role with no
          recorded use older than the window is flagged unused; roles used by instance profiles or Lambda functions cannot be deleted here.
        </Box>
        <FormField label="Unused after (days)">
          <Input ariaLabel="Unused after days" type="number" value={days} onChange={({ detail }) => setDays(detail.value)} />
        </FormField>
        <ResourceTable resourceName="Roles" variant="embedded" items={items} loading={inv.loading} error={inv.error} onRefresh={inv.reload}
          trackBy="RoleName" selectionType="multi" selectedItems={sel} onSelectionChange={setSel}
          empty={{ title: "No roles" }}
          actions={<SpaceBetween direction="horizontal" size="xs">
            <Button disabled={sel.length !== 1} onClick={() => navigate("iam", "roles", sel[0].RoleName)}>Manage policies and trust</Button>
            <Button variant="primary" disabled={!sel.length} onClick={() => setConfirm(true)}>Delete selected unused roles</Button>
          </SpaceBetween>}
          columns={[
            { id: "n", header: "Role name", isRowHeader: true, cell: (r) => r.RoleName },
            { id: "s", header: "Status", cell: (r) => <StatusIndicator type={STATUS[r.Status] || "pending"}>{LABEL[r.Status] || r.Status}</StatusIndicator> },
            { id: "lu", header: "Last used", cell: (r) => (r.LastUsedDate ? `${fmtDate(r.LastUsedDate)} (${r.LastUsedService})` : "No recorded use") },
            { id: "i", header: "Idle days", cell: (r) => r.IdleDays },
            { id: "p", header: "Policies", cell: (r) => `${r.AttachedPolicyCount} managed, ${r.InlinePolicyCount} inline` },
            { id: "t", header: "Trusted entities", cell: (r) => r.TrustedPrincipals.join(", ") || "-" },
            { id: "d", header: "Used by / blockers", cell: (r) => (r.DeleteBlockers.length ? r.DeleteBlockers.join("; ") : "Safe to delete") },
          ]} />
        <Box variant="small" color="text-body-secondary">{unused.length} of {items.length} role(s) are currently safe to delete.</Box>
      </SpaceBetween>
      <Modal visible={confirm} onDismiss={() => setConfirm(false)} header="Delete selected roles"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={() => setConfirm(false)}>Cancel</Button>
          <Button variant="primary" onClick={del}>Delete</Button></SpaceBetween></Box>}>
        Deletes {sel.length} role(s) and detaches their policies. Roles that are in use, newer than the window, referenced or service-linked are skipped and reported.
      </Modal>
    </CapabilityContainer>
  );
}
