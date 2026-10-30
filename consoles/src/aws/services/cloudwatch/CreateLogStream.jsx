import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Form from "@cloudscape-design/components/form";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function CreateLogStream({ params }) {
  const group = params.name;
  const notify = useNotify();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    if (!name) return;
    setBusy(true); setError(null);
    try {
      await api.createLogStream(group, name);
      notify.success(`Log stream ${name} was created.`);
      navigate("cloudwatch", "logs", group);
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create log stream</Header>}>
      <form onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <Form actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button formAction="none" variant="link" onClick={() => navigate("cloudwatch", "logs", group)}>Cancel</Button>
            <Button formAction="submit" variant="primary" loading={busy} disabled={!name}>Create</Button>
          </SpaceBetween>
        }>
          <SpaceBetween size="l">
            {error && <ErrorAlert error={error} />}
            <Container header={<Header variant="h2">Create log stream</Header>}>
              <FormField label="Log stream name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Log stream name" autoFocus /></FormField>
            </Container>
          </SpaceBetween>
        </Form>
      </form>
    </ContentLayout>
  );
}
