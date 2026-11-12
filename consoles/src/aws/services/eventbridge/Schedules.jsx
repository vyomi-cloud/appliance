import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import Link from "@cloudscape-design/components/link";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { fmtDate, Status } from "../../kit/common.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href } from "../../../common/router.js";
import * as api from "./api.js";

const targetLabel = (t) => {
  const arn = t?.Arn || "";
  if (arn.includes(":sqs:")) return `SQS: ${arn.split(":").pop()}`;
  if (arn.includes(":sns:")) return `SNS: ${arn.split(":").pop()}`;
  if (arn.includes(":lambda:")) return `Lambda: ${arn.split(":").pop()}`;
  return arn || "-";
};

export default function Schedules() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const { data = [], loading, error, reload } = useAsync(() => api.listSchedules());

  const toggle = async () => {
    const s = sel[0];
    const enable = s.State !== "ENABLED";
    const full = await api.getSchedule(s.Name, s.GroupName);
    await api.updateSchedule(s.Name, { ...full, State: enable ? "ENABLED" : "DISABLED" });
    notify.success(`${enable ? "Enabled" : "Disabled"} schedule ${s.Name}.`); setSel([]); reload();
  };
  const del = async () => {
    await Promise.all(sel.map((s) => api.deleteSchedule(s.Name, s.GroupName)));
    notify.success(`Deleted ${sel.length} schedule${sel.length === 1 ? "" : "s"}.`); setSel([]); reload();
  };

  return (
      <ResourceTable
        resourceName="Schedules"
        description={<CapabilityBadge id="eventbridge.scheduler.firing" />}
        items={data}
        loading={loading}
        error={error}
        onRefresh={reload}
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        trackBy="Name"
        filterPlaceholder="Find schedules"
        columns={[
          { id: "name", header: "Schedule name", isRowHeader: true, cell: (s) => <Link href={`${href("eventbridge", "create-schedule")}?name=${encodeURIComponent(s.Name)}&group=${encodeURIComponent(s.GroupName)}`} onFollow={follow}>{s.Name}</Link> },
          { id: "status", header: "Status", cell: (s) => <Status ok={s.State === "ENABLED"}>{s.State === "ENABLED" ? "Enabled" : "Disabled"}</Status> },
          { id: "group", header: "Group name", cell: (s) => s.GroupName },
          { id: "target", header: "Target", cell: (s) => targetLabel(s.Target) },
          { id: "modified", header: "Last modified", cell: (s) => fmtDate(s.LastModificationDate) },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={!sel.length} onClick={del}>Delete</Button>
            <Button disabled={sel.length !== 1} onClick={toggle}>{sel.length === 1 && sel[0].State === "ENABLED" ? "Disable" : "Enable"}</Button>
            <Button disabled={sel.length !== 1} href={sel.length === 1 ? `${href("eventbridge", "create-schedule")}?name=${encodeURIComponent(sel[0].Name)}&group=${encodeURIComponent(sel[0].GroupName)}` : undefined} onFollow={follow}>Edit</Button>
            <Button variant="primary" href={href("eventbridge", "create-schedule")} onFollow={follow}>Create schedule</Button>
          </SpaceBetween>
        }
        empty={{ title: "No schedules", subtitle: "No schedules", action: <Button href={href("eventbridge", "create-schedule")} onFollow={follow}>Create schedule</Button> }}
      />
  );
}
