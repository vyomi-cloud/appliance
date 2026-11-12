/* Invocation summary — real history of every hook invocation (core/cloudformation_core.py:
 * _run_hooks, native ListHookResults). Vyomi aggregates every targeted stack's invocations
 * on one page when no TargetId is given; real AWS scopes ListHookResults to a single stack
 * or change set (core/capabilities/aws/cloudformation.json: aws.cloudformation.hooks). */
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Button from "@cloudscape-design/components/button";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { fmtDate } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { href, follow } from "../../../common/router.js";
import * as api from "./api.js";

export default function InvocationSummary() {
  const { data = [], loading, error, reload } = useAsync(() => api.listHookResults(), []);
  const createHookButton = <Button variant="primary" href={href("cloudformation", "hooks", "list")} onFollow={follow}>Create a Hook</Button>;
  return (
    <ContentLayout header={<Header variant="h1">Invocation summary</Header>}>
      <ResourceTable
        resourceName="Invocation summary"
        items={data}
        trackBy="InvocationId"
        loading={loading}
        error={error}
        onRefresh={reload}
        filterPlaceholder="Find invocations"
        columns={[
          { id: "id", header: "Invocation ID", isRowHeader: true, cell: (i) => i.InvocationId },
          { id: "target", header: "Target", cell: (i) => `${i.TargetType}: ${i.TargetId}` },
          { id: "mode", header: "Mode", cell: (i) => (i.HookFailureMode === "FAIL" ? "Fail" : "Warn") },
          { id: "time", header: "Invocation time", cell: (i) => fmtDate(i.InvocationTime) },
          { id: "result", header: "Result message", cell: (i) => (
              <StatusIndicator type={i.HookStatus === "HOOK_COMPLETE_SUCCEEDED" ? "success" : "error"}>
                {i.HookTypeName}: {i.HookStatusReason}
              </StatusIndicator>
            ) },
        ]}
        actions={createHookButton}
        empty={{ title: "No Hook invocations in this Region", action: createHookButton }}
      />
    </ContentLayout>
  );
}
