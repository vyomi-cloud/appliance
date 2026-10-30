import { useState } from "react";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Form from "@cloudscape-design/components/form";
import Header from "@cloudscape-design/components/header";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Textarea from "@cloudscape-design/components/textarea";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Tabs from "@cloudscape-design/components/tabs";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import { follow, navigate } from "../../../common/router.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, NotSimulatedContainer } from "../../kit/common.jsx";
import * as api from "./api.js";

const TEMPLATES = ["From scratch", "Serverless API backend", "File processing", "Scheduled job", "Notifications processing", "Queue processing"];

export default function CreateApplication() {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [template, setTemplate] = useState("From scratch");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    if (!name.trim()) return;
    setBusy(true); setError(null);
    try {
      await api.createApplication({ Name: name, Description: description, Template: template });
      notify.success(`Successfully created application "${name}"`);
      navigate("lambda", "applications");
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  const serverlessApplicationTab = (
    <form onSubmit={(e) => { e.preventDefault(); submit(); }}>
      <Form
        actions={<SpaceBetween direction="horizontal" size="xs">
          <Button formAction="none" variant="link" href="#/lambda/applications" onFollow={follow}>Cancel</Button>
          <Button variant="primary" loading={busy}>Create application</Button>
        </SpaceBetween>}
        errorText={error && <ErrorAlert error={error} />}
      >
        <SpaceBetween size="l">
          <Container header={<Header variant="h2">Templates</Header>}>
            <FormField label="Template">
              <RadioGroup value={template} onChange={({ detail }) => setTemplate(detail.value)}
                items={TEMPLATES.map((t) => ({ value: t, label: t }))} />
            </FormField>
          </Container>
          <Container header={<Header variant="h2">Application settings</Header>}>
            <SpaceBetween size="l">
              <FormField label="Name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Name" /></FormField>
              <FormField label="Description - optional"><Textarea value={description} onChange={({ detail }) => setDescription(detail.value)} ariaLabel="Description" /></FormField>
            </SpaceBetween>
          </Container>
        </SpaceBetween>
      </Form>
    </form>
  );

  return (
    <ContentLayout header={<Header variant="h1">Create application</Header>}>
      <Tabs tabs={[
        { id: "cicd", label: "CI/CD pipeline application", content: <NotSimulatedContainer title="CI/CD pipeline application" feature="Lambda application CI/CD pipelines" note="A CI/CD pipeline application wires a CodePipeline/CodeBuild/CodeDeploy pipeline around a stack — Vyomi has no CI/CD pipeline core. Use the Serverless application tab." /> },
        { id: "serverless", label: "Serverless application", content: serverlessApplicationTab },
        { id: "composer", label: "Build with Infrastructure Composer", content: <NotSimulatedContainer title="Build with Infrastructure Composer" feature="AWS Infrastructure Composer" note="Infrastructure Composer is a visual drag-and-drop canvas for authoring a SAM template — Vyomi has no visual template designer. Use the Serverless application tab." /> },
      ]} />
    </ContentLayout>
  );
}
