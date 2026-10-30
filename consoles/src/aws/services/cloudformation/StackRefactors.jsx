/* Stack refactors — ListStackRefactors is real (always empty, since Vyomi never creates
 * one); starting a refactor (moving resources between stacks) is the declared gap
 * (core/capabilities/aws/cloudformation.json: aws.cloudformation.stack-refactors). */
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { NotSimulated } from "../../kit/common.jsx";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import * as api from "./api.js";
import { statusOf } from "./Stacks.jsx";

export default function StackRefactors() {
  const notify = useNotify();
  const { data = [], loading, error, reload } = useAsync(() => api.listStackRefactors(), []);
  return (
    <SpaceBetween size="l">
      <ResourceTable
        resourceName="Stack refactors"
        items={data}
        trackBy="StackRefactorId"
        loading={loading}
        error={error}
        onRefresh={reload}
        filterPlaceholder="Find stack refactors"
        columns={[
          { id: "id", header: "Stack refactor Id", isRowHeader: true, cell: (r) => r.StackRefactorId },
          { id: "s", header: "Status", cell: (r) => statusOf(r.Status) },
          { id: "e", header: "Execution status", cell: (r) => r.ExecutionStatus },
          { id: "d", header: "Description", cell: (r) => r.Description || "-" },
          { id: "sr", header: "Status reason", cell: (r) => r.StatusReason || "-" },
          { id: "er", header: "Execution status reason", cell: (r) => r.ExecutionStatusReason || "-" },
        ]}
        actions={<Button variant="primary" onClick={() => notify.info("Start stack refactor is not simulated in Vyomi.")}>Start stack refactor</Button>}
        empty={{ title: "No stack refactors for this account and Region.", subtitle: "A stack refactor moves resources between stacks without replacing them." }}
      />
      <Container header={<Header variant="h2">Getting started with stack refactor</Header>}>
        <NotSimulated feature="Starting a stack refactor" note="Moving resources between stacks without replacing them isn't modeled by Vyomi. Delete and recreate the resource in its target stack instead." />
      </Container>
    </SpaceBetween>
  );
}
