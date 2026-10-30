import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Link from "@cloudscape-design/components/link";
import Select from "@cloudscape-design/components/select";
import Toggle from "@cloudscape-design/components/toggle";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Box from "@cloudscape-design/components/box";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { fmtDate } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import * as api from "./api.js";

const ACTIVE_STATUSES = ["CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE", "ROLLBACK_COMPLETE",
  "CREATE_FAILED", "DELETE_FAILED", "CREATE_IN_PROGRESS", "UPDATE_IN_PROGRESS", "DELETE_IN_PROGRESS",
  "REVIEW_IN_PROGRESS", "UPDATE_ROLLBACK_FAILED"];
const STATUS_TYPE = (s) => (s?.endsWith("COMPLETE") && !s.includes("ROLLBACK") ? "success" : s?.includes("FAILED") ? "error" : s?.includes("PROGRESS") ? "in-progress" : "info");

export function statusOf(s) {
  return <StatusIndicator type={STATUS_TYPE(s)}>{s}</StatusIndicator>;
}

export default function Stacks() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [filterActive, setFilterActive] = useState(true);
  const [viewNested, setViewNested] = useState(true);
  const { data = [], loading, error, reload } = useAsync(
    () => api.listStacks(filterActive ? ACTIVE_STATUSES : undefined),
    [filterActive],
  );

  const runStackAction = async (id) => {
    const name = sel[0].StackName;
    try {
      if (id === "drift") { await api.detectStackDrift(name); notify.success(`Drift detection started for "${name}".`); navigate("cloudformation", "stacks", name); }
      if (id === "view-drift") navigate("cloudformation", "stacks", name);
      if (id === "termination") { await api.updateTerminationProtection(name, sel[0].EnableTerminationProtection !== "true"); notify.success(`Termination protection ${sel[0].EnableTerminationProtection === "true" ? "disabled" : "enabled"} for "${name}".`); reload(); }
      if (id === "changeset") { location.hash = `#/cloudformation/stacks/${encodeURIComponent(name)}?tab=changesets`; }
      if (id === "rollback") { await api.continueUpdateRollback(name); notify.success(`Continuing rollback for "${name}".`); reload(); }
    } catch (e) { notify.error(e); }
  };

  return (
    <>
      <ResourceTable
        resourceName="Stacks"
        items={data}
        trackBy="StackId"
        loading={loading}
        error={error}
        onRefresh={reload}
        selectionType="single"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Search by stack name"
        columns={[
          { id: "name", header: "Stack name", isRowHeader: true, sortingField: "StackName", cell: (s) => <Link href={href("cloudformation", "stacks", s.StackName)} onFollow={follow}>{s.StackName}</Link> },
          { id: "status", header: "Status", cell: (s) => statusOf(s.StackStatus) },
          { id: "created", header: "Created time", cell: (s) => fmtDate(s.CreationTime) },
          { id: "description", header: "Description", cell: (s) => s.TemplateDescription || "-" },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs" alignItems="center">
            <Select selectedOption={{ value: filterActive ? "Active" : "All", label: filterActive ? "Active" : "All" }}
              onChange={({ detail }) => setFilterActive(detail.selectedOption.value === "Active")}
              options={[{ value: "Active", label: "Active" }, { value: "All", label: "All" }]} ariaLabel="Filter status" />
            <Toggle checked={viewNested} onChange={({ detail }) => setViewNested(detail.checked)}>View nested</Toggle>
            <Button disabled={sel.length !== 1} onClick={() => setDel(true)}>Delete stack</Button>
            <Button disabled={sel.length !== 1} onClick={() => navigate("cloudformation", "stacks", sel[0]?.StackName || "", "update")}>Update stack</Button>
            <ButtonDropdown disabled={sel.length !== 1} onItemClick={({ detail }) => runStackAction(detail.id)} items={[
              { id: "view-drift", text: "View drift results" }, { id: "drift", text: "Detect drift" },
              { id: "termination", text: "Edit termination protection" }, { id: "changeset", text: "Create change set for current stack" },
              { id: "rollback", text: "Continue update rollback" },
            ]}>Stack actions</ButtonDropdown>
            <Button variant="primary" href={href("cloudformation", "create")} onFollow={follow}>Create stack</Button>
          </SpaceBetween>
        }
        empty={{ title: "No stacks to display", subtitle: "Create a stack to get started.", action: <Button href={href("cloudformation", "create")} onFollow={follow}>Create stack</Button> }}
      />
      <DeleteModal
        visible={del}
        resourceType="stack"
        names={sel.map((s) => s.StackName)}
        confirmText="delete"
        onDismiss={() => setDel(false)}
        onConfirm={async () => {
          await api.deleteStack(sel[0].StackName);
          notify.success(`Deletion of stack "${sel[0].StackName}" has been initiated.`);
          setSel([]); reload();
        }}
      />
    </>
  );
}
