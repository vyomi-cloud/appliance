/* Stack refactors — CreateStackRefactor/ExecuteStackRefactor really move a resource's
 * runtime state between two existing stacks (core/cloudformation_core.py); the modal
 * below is the real "Start stack refactor" flow (aws.cloudformation.stack-refactors). */
import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import Modal from "@cloudscape-design/components/modal";
import Box from "@cloudscape-design/components/box";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { ErrorAlert } from "../../kit/common.jsx";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import * as api from "./api.js";
import { statusOf } from "./Stacks.jsx";

function StartRefactorModal({ visible, onDismiss, onDone, stacks }) {
  const [sourceStack, setSourceStack] = useState(null);
  const [sourceLid, setSourceLid] = useState(null);
  const [destStack, setDestStack] = useState(null);
  const [destLid, setDestLid] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const resources = useAsync(() => (sourceStack ? api.listStackResources(sourceStack.value) : Promise.resolve([])), [sourceStack]);

  const close = () => { setSourceStack(null); setSourceLid(null); setDestStack(null); setDestLid(""); setDescription(""); setError(null); onDismiss(); };
  const start = async () => {
    setBusy(true); setError(null);
    try {
      const id = await api.createStackRefactor({
        description,
        mappings: [{ sourceStack: sourceStack.value, sourceLogicalId: sourceLid.value, destStack: destStack.value, destLogicalId: destLid || sourceLid.value }],
      });
      await api.executeStackRefactor(id);
      close();
      onDone();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  const stackOptions = stacks.map((s) => ({ label: s.StackName, value: s.StackName }));
  const resourceOptions = (resources.data || []).map((r) => ({ label: r.LogicalResourceId, value: r.LogicalResourceId }));
  const canStart = sourceStack && sourceLid && destStack && destStack.value !== sourceStack.value;

  return (
    <Modal visible={visible} onDismiss={close} size="medium" header="Start stack refactor"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={close}>Cancel</Button>
        <Button variant="primary" loading={busy} disabled={!canStart} onClick={start}>Start stack refactor</Button>
      </SpaceBetween></Box>}>
      <SpaceBetween size="l">
        <Box variant="p">Move a resource from one stack to another without replacing the underlying resource.</Box>
        {error && <ErrorAlert error={error} header="Couldn't start stack refactor" />}
        <FormField label="Source stack">
          <Select selectedOption={sourceStack} onChange={({ detail }) => { setSourceStack(detail.selectedOption); setSourceLid(null); }}
            options={stackOptions} placeholder="Choose a stack" ariaLabel="Source stack" />
        </FormField>
        <FormField label="Source resource" description="The logical resource to move">
          <Select selectedOption={sourceLid} onChange={({ detail }) => setSourceLid(detail.selectedOption)}
            options={resourceOptions} placeholder="Choose a resource" disabled={!sourceStack} loadingText="Loading resources"
            statusType={resources.loading ? "loading" : "finished"} ariaLabel="Source resource" />
        </FormField>
        <FormField label="Destination stack">
          <Select selectedOption={destStack} onChange={({ detail }) => setDestStack(detail.selectedOption)}
            options={stackOptions.filter((o) => o.value !== sourceStack?.value)} placeholder="Choose a stack" ariaLabel="Destination stack" />
        </FormField>
        <FormField label="Destination logical ID" description="Leave blank to keep the same logical ID in the destination stack.">
          <Input value={destLid} onChange={({ detail }) => setDestLid(detail.value)} placeholder={sourceLid?.value || "LogicalId"} ariaLabel="Destination logical ID" />
        </FormField>
        <FormField label="Description - optional">
          <Input value={description} onChange={({ detail }) => setDescription(detail.value)} ariaLabel="Description" />
        </FormField>
      </SpaceBetween>
    </Modal>
  );
}

export default function StackRefactors() {
  const notify = useNotify();
  const [modal, setModal] = useState(false);
  const { data = [], loading, error, reload } = useAsync(() => api.listStackRefactors(), []);
  const stacks = useAsync(() => api.listStacks(), []);
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
        actions={<Button variant="primary" disabled={(stacks.data || []).length < 2} onClick={() => setModal(true)}>Start stack refactor</Button>}
        empty={{ title: "No stack refactors for this account and Region.", subtitle: "A stack refactor moves resources between stacks without replacing them." }}
      />
      <Container header={<Header variant="h2">Getting started with stack refactor</Header>}>
        <Box variant="p">
          {(stacks.data || []).length < 2
            ? "Create at least two stacks first — a refactor moves a resource from one existing stack into another."
            : "Choose \"Start stack refactor\" to move a resource from one of your stacks into another, without deleting and recreating it."}
        </Box>
      </Container>
      <StartRefactorModal visible={modal} onDismiss={() => setModal(false)} stacks={stacks.data || []}
        onDone={() => { notify.success("Stack refactor started and executed."); reload(); }} />
    </SpaceBetween>
  );
}
