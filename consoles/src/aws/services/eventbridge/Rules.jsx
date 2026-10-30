import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import Link from "@cloudscape-design/components/link";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { Status } from "../../kit/common.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href } from "../../../common/router.js";
import * as api from "./api.js";

export const ruleType = (r) => (r.ScheduleExpression ? "Schedule" : "Event pattern");

export function RulesTable({ eventBusName = "default", resourceName = "Event pattern rules", variant = "container", createHref, filterPlaceholder = "Find rules" }) {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const { data = [], loading, error, reload } = useAsync(() => api.listRules(eventBusName), [eventBusName]);

  const toggle = async () => {
    const enable = sel.every((r) => r.State !== "ENABLED");
    try {
      await Promise.all(sel.map((r) => (enable ? api.enableRule(r.Name, eventBusName) : api.disableRule(r.Name, eventBusName))));
      notify.success(`${enable ? "Enabled" : "Disabled"} ${sel.length} rule${sel.length === 1 ? "" : "s"}.`);
      setSel([]); reload();
    } catch (e) { notify.error(e); }
  };
  const del = async () => {
    try {
      await Promise.all(sel.map((r) => api.deleteRule(r.Name, eventBusName)));
      notify.success(`Deleted ${sel.length} rule${sel.length === 1 ? "" : "s"}.`);
      setSel([]); reload();
    } catch (e) { notify.error(e); }
  };

  return (
    <ResourceTable
      variant={variant}
      resourceName={resourceName}
      items={data}
      loading={loading}
      error={error}
      onRefresh={reload}
      selectionType="multi"
      selectedItems={sel}
      onSelectionChange={setSel}
      trackBy="Name"
      filterPlaceholder={filterPlaceholder}
      columns={[
        { id: "name", header: "Name", isRowHeader: true, sortingField: "Name", cell: (r) => <Link href={href("eventbridge", "rules", r.Name)} onFollow={follow}>{r.Name}</Link> },
        { id: "status", header: "Status", cell: (r) => <Status ok={r.State === "ENABLED"} type={r.State === "ENABLED" ? "success" : "stopped"}>{r.State === "ENABLED" ? "Enabled" : "Disabled"}</Status> },
        { id: "type", header: "Type", cell: ruleType },
        { id: "bus", header: "Event bus", cell: (r) => r.EventBusName },
        { id: "arn", header: "ARN", cell: (r) => r.Arn },
        { id: "description", header: "Description", cell: (r) => r.Description || "-" },
      ]}
      actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button disabled={!sel.length} onClick={del}>Delete</Button>
          <Button disabled={!sel.length} onClick={toggle}>{sel.length && sel.every((r) => r.State !== "ENABLED") ? "Enable" : "Disable"}</Button>
          <Button disabled={sel.length !== 1} href={sel.length === 1 ? href("eventbridge", "rules", sel[0].Name, "edit") : undefined} onFollow={follow}>Edit</Button>
          {createHref && <Button variant="primary" href={createHref} onFollow={follow}>Create rule</Button>}
        </SpaceBetween>
      }
      empty={{ title: "No rules", subtitle: "No rules to display.", action: createHref && <Button href={createHref} onFollow={follow}>Create rule</Button> }}
    />
  );
}

export default function Rules() {
  return <RulesTable eventBusName="default" resourceName="Rules" variant="full-page" createHref={href("eventbridge", "create-rule")} />;
}
