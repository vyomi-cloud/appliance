import { useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Button from "@cloudscape-design/components/button";
import Link from "@cloudscape-design/components/link";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { Status } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href } from "../../../common/router.js";
import * as api from "./api.js";

export default function ScheduledRules() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const { data = [], loading, error, reload } = useAsync(async () => (await api.listRules("default")).filter((r) => r.ScheduleExpression));

  const toggle = async () => {
    const enable = sel.every((r) => r.State !== "ENABLED");
    await Promise.all(sel.map((r) => (enable ? api.enableRule(r.Name, "default") : api.disableRule(r.Name, "default"))));
    notify.success(`${enable ? "Enabled" : "Disabled"} ${sel.length} rule${sel.length === 1 ? "" : "s"}.`); setSel([]); reload();
  };
  const del = async () => {
    await Promise.all(sel.map((r) => api.deleteRule(r.Name, "default")));
    notify.success(`Deleted ${sel.length} scheduled rule${sel.length === 1 ? "" : "s"}.`); setSel([]); reload();
  };

  return (
      <SpaceBetween size="l">
        <Alert header="Scheduled rules are legacy">New schedules should use EventBridge Scheduler, which supports one-time, rate- and cron-based schedules with flexible time windows. <Link href={href("eventbridge", "schedules")} onFollow={follow}>Go to Scheduled rules</Link> is now Scheduler.</Alert>
        <ResourceTable
          resourceName="Scheduled rules"
          items={data}
          loading={loading}
          error={error}
          onRefresh={reload}
          selectionType="multi"
          selectedItems={sel}
          onSelectionChange={setSel}
          trackBy="Name"
          columns={[
            { id: "name", header: "Name", isRowHeader: true, cell: (r) => <Link href={href("eventbridge", "rules", r.Name)} onFollow={follow}>{r.Name}</Link> },
            { id: "status", header: "Status", cell: (r) => <Status ok={r.State === "ENABLED"}>{r.State === "ENABLED" ? "Enabled" : "Disabled"}</Status> },
            { id: "type", header: "Type", cell: () => "Schedule" },
            { id: "bus", header: "Event bus", cell: (r) => r.EventBusName },
            { id: "arn", header: "ARN", cell: (r) => r.Arn },
            { id: "description", header: "Description", cell: (r) => r.Description || "-" },
          ]}
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              <Button disabled={!sel.length} onClick={del}>Delete</Button>
              <Button disabled={!sel.length} onClick={toggle}>{sel.length && sel.every((r) => r.State !== "ENABLED") ? "Enable" : "Disable"}</Button>
              <Button disabled={sel.length !== 1} href={sel.length === 1 ? href("eventbridge", "rules", sel[0].Name, "edit") : undefined} onFollow={follow}>Edit</Button>
              <Button variant="primary" href={href("eventbridge", "create-scheduled-rule")} onFollow={follow}>Create scheduled rule</Button>
            </SpaceBetween>
          }
          empty={{ title: "No scheduled rules", subtitle: "No scheduled rules to display.", action: <Button href={href("eventbridge", "create-scheduled-rule")} onFollow={follow}>Create scheduled rule</Button> }}
        />
      </SpaceBetween>
  );
}
