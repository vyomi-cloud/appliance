/* Command detail — real GetCommandInvocation/ListCommandInvocations per target. */
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Table from "@cloudscape-design/components/table";
import Spinner from "@cloudscape-design/components/spinner";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, fmtDate, KeyValue } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

const statusType = (s) => (s === "Success" ? "success" : s === "Cancelled" ? "stopped" : "pending");

export default function CommandDetail({ params }) {
  const commandId = params.id;
  const notify = useNotify();
  const d = useAsync(() => Promise.all([api.listCommands(), api.listCommandInvocations(commandId)]), [commandId]);
  if (d.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (d.error) return <ErrorAlert error={d.error} />;
  const [commands, invocations] = d.data;
  const c = commands.find((x) => x.CommandId === commandId);
  if (!c) return <ErrorAlert error={{ code: "InvalidCommandId", message: `Command ${commandId} not found.` }} />;
  return (
    <ContentLayout header={<Header variant="h1" actions={
      <Button disabled={c.Status !== "InProgress" && c.Status !== "Pending"} onClick={async () => { await api.cancelCommand(commandId); notify.success("Command cancellation requested."); d.reload(); }}>Cancel command</Button>
    }>{commandId}</Header>}>
      <SpaceBetween size="l">
        <KeyValue title="Command details" columns={4} items={[
          ["Document name", c.DocumentName], ["Status", <StatusIndicator key="s" type={statusType(c.Status)}>{c.Status}</StatusIndicator>],
          ["Target count", c.TargetCount], ["Completed count", c.CompletedCount],
          ["Requested at", fmtDate(c.RequestedDateTime)], ["Comment", c.Comment || "-"],
          ["Timeout (seconds)", c.TimeoutSeconds],
        ]} />
        <CapabilityContainer id="ssm.runcommand" title="Targets and outputs" counter={`(${invocations.length})`}>
          <Table variant="embedded" items={invocations} trackBy="InstanceId"
            columnDefinitions={[
              { id: "i", header: "Instance ID", cell: (x) => x.InstanceId },
              { id: "s", header: "Status", cell: (x) => <StatusIndicator type={statusType(x.Status)}>{x.Status}</StatusIndicator> },
              { id: "o", header: "Output", cell: (x) => (x.CommandPlugins || [])[0]?.Output || "(no output — Vyomi has no SSM Agent fleet behind this command)" },
            ]}
            empty={<Box textAlign="center" color="inherit"><b>No targets</b></Box>} />
        </CapabilityContainer>
      </SpaceBetween>
    </ContentLayout>
  );
}
