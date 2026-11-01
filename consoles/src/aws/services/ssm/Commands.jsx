/* Run Command — command history. Real ListCommands; a command completes immediately
 * (Success) since Vyomi has no SSM Agent fleet behind it — honestly, not a stub. */
import Button from "@cloudscape-design/components/button";
import Link from "@cloudscape-design/components/link";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { follow, href, navigate } from "../../../common/router.js";
import { fmtDate } from "../../kit/common.jsx";
import * as api from "./api.js";

const statusType = (s) => (s === "Success" ? "success" : s === "Cancelled" ? "stopped" : "pending");

export default function Commands() {
  const t = useAsync(() => api.listCommands(), []);
  return (
    <ResourceTable
      resourceName="Commands"
      items={t.data || []}
      loading={t.loading}
      error={t.error}
      onRefresh={t.reload}
      trackBy="CommandId"
      filterPlaceholder="Search commands"
      empty={{ title: "No commands", action: <Button onClick={() => navigate("ssm", "run-command")}>Run command</Button> }}
      columns={[
        { id: "id", header: "Command ID", isRowHeader: true, cell: (c) => <Link href={href("ssm", "commands", c.CommandId)} onFollow={follow}>{c.CommandId}</Link> },
        { id: "doc", header: "Document name", cell: (c) => c.DocumentName },
        { id: "status", header: "Status", cell: (c) => <StatusIndicator type={statusType(c.Status)}>{c.Status}</StatusIndicator> },
        { id: "targets", header: "Targets", cell: (c) => c.TargetCount },
        { id: "comment", header: "Comment", cell: (c) => c.Comment || "-" },
        { id: "req", header: "Requested at", cell: (c) => fmtDate(c.RequestedDateTime) },
      ]}
      actions={<Button variant="primary" onClick={() => navigate("ssm", "run-command")}>Run command</Button>}
    />
  );
}
