/* Step Functions state machines — not a Lambda resource; this page is the real
 * console's cross-link into Step Functions. Lists and creates REAL state machines
 * over core/stepfunctions_core.py (see core/capabilities/aws/lambda.json,
 * lambda.state-machines-link) — execute/manage them for real in the Step Functions
 * console. */
import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import Modal from "@cloudscape-design/components/modal";
import Box from "@cloudscape-design/components/box";
import Form from "@cloudscape-design/components/form";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ContentLayout from "@cloudscape-design/components/content-layout";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { fmtDate, ErrorAlert } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import * as api from "./api.js";

const DEFAULT_DEFINITION = { Comment: "A sample Lambda workflow", StartAt: "Hello", States: { Hello: { Type: "Pass", Result: "World", End: true } } };

function CreateStateMachineModal({ visible, onDismiss, onCreated }) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    if (!name.trim()) return;
    setBusy(true); setError(null);
    try {
      await api.createStateMachine(name, DEFAULT_DEFINITION);
      setName("");
      onCreated();
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Create state machine"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} onClick={submit}>Create state machine</Button>
      </SpaceBetween></Box>}>
      <Form errorText={error && <ErrorAlert error={error} />}>
        <FormField label="Name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Name" /></FormField>
      </Form>
    </Modal>
  );
}

export default function StepFunctionsStateMachines() {
  const notify = useNotify();
  const t = useAsync(() => api.listStateMachines(), []);
  const [create, setCreate] = useState(false);

  return (
    <ContentLayout header={<Header variant="h1">Step Functions state machines</Header>}>
      <SpaceBetween size="l">
        <ResourceTable
          resourceName="State machines"
          items={t.data || []}
          loading={t.loading}
          error={t.error}
          onRefresh={t.reload}
          trackBy="stateMachineArn"
          empty={{ title: "No state machines", action: <Button variant="primary" onClick={() => setCreate(true)}>Get started with a sample Lambda workflow</Button> }}
          columns={[
            { id: "name", header: "Name", isRowHeader: true, cell: (m) => m.name },
            { id: "type", header: "Type", cell: (m) => m.type },
            { id: "created", header: "Created", cell: (m) => fmtDate(m.creationDate) },
          ]}
          actions={<Button variant="primary" onClick={() => setCreate(true)}>Create state machine</Button>}
        />
        <Container header={<Header variant="h2">Build serverless workflows with state machines</Header>}>
          <Button onClick={() => setCreate(true)}>Get started</Button>
        </Container>
      </SpaceBetween>
      <CreateStateMachineModal visible={create} onDismiss={() => setCreate(false)}
        onCreated={() => { setCreate(false); notify.success("State machine created."); t.reload(); }} />
    </ContentLayout>
  );
}
