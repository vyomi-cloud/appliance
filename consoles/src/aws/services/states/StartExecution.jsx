import { useState } from "react";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Form from "@cloudscape-design/components/form";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Textarea from "@cloudscape-design/components/textarea";
import Button from "@cloudscape-design/components/button";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

const smArn = (name) => `arn:aws:states:us-east-1:000000000000:stateMachine:${name}`;

export default function StartExecution({ params }) {
  const name = params.name;
  const notify = useNotify();
  const [execName, setExecName] = useState("");
  const [input, setInput] = useState("{}");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const r = await api.startExecution({ stateMachineArn: smArn(name), ...(execName.trim() ? { name: execName.trim() } : {}), input });
      notify.success(`Started execution "${r.executionArn.split(":").pop()}".`);
      navigate("states", "state-machines", name, "executions", r.executionArn.split(":").pop());
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">New execution</Header>}>
      <form onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <Form errorText={error && <ErrorAlert error={error} />} actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button formAction="none" variant="link" href={href("states", "state-machines", name)} onFollow={follow}>Cancel</Button>
            <Button variant="primary" loading={busy}>Start execution</Button>
          </SpaceBetween>
        }>
          <Container header={<Header variant="h2">New execution</Header>}>
            <SpaceBetween size="l">
              <FormField label="Name" description="A unique name is generated if left blank.">
                <Input value={execName} onChange={({ detail }) => setExecName(detail.value)} placeholder="Enter an execution name" ariaLabel="Name" />
              </FormField>
              <FormField label="Input" description="JSON input for the execution.">
                <Textarea rows={10} spellcheck={false} value={input} onChange={({ detail }) => setInput(detail.value)} ariaLabel="Input" />
              </FormField>
            </SpaceBetween>
          </Container>
        </Form>
      </form>
    </ContentLayout>
  );
}
