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
import { ErrorAlert } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import Composer from "./Composer.jsx";
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

  const [pl, setPl] = useState({ repo: "", branch: "main", fn: "", handler: "app.handler", token: "" });
  const setP = (k) => ({ detail }) => setPl((x) => ({ ...x, [k]: detail.value }));
  const submitPipeline = async () => {
    setBusy(true); setError(null);
    try {
      const repo = pl.repo.startsWith("http") || pl.repo.startsWith("vyomi/") ? pl.repo : `vyomi/${pl.repo || name}`;
      await api.createApplication({ Name: name, Description: description, Template: "CI/CD pipeline application",
        Pipeline: { Repository: repo, Branch: pl.branch, FunctionName: pl.fn || name, Handler: pl.handler, ...(pl.token ? { GitHubToken: pl.token } : {}) } });
      notify.success(`Successfully created application "${name}" with its Source, Build and Deploy pipeline`);
      navigate("lambda", "applications");
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };
  const cicdTab = (
    <CapabilityContainer id="lambda.application.cicd-pipeline" title="CI/CD pipeline application">
      <form onSubmit={(e) => { e.preventDefault(); if (name.trim()) submitPipeline(); }}>
        <Form actions={<Button variant="primary" loading={busy} disabled={!name.trim()}>Create application</Button>} errorText={error && <ErrorAlert error={error} />}>
          <Container header={<Header variant="h2">Pipeline</Header>}>
            <SpaceBetween size="l">
              <FormField label="Application name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Pipeline application name" /></FormField>
              <FormField label="Source repository" description="vyomi/<name> creates a repository inside Vyomi seeded with a working function; or https://github.com/owner/repo (a personal access token is needed for private repos)."><Input value={pl.repo} onChange={setP("repo")} placeholder={`vyomi/${name || "my-app"}`} ariaLabel="Source repository" /></FormField>
              <FormField label="Branch"><Input value={pl.branch} onChange={setP("branch")} ariaLabel="Pipeline branch" /></FormField>
              <FormField label="Function name"><Input value={pl.fn} onChange={setP("fn")} placeholder={name} ariaLabel="Pipeline function name" /></FormField>
              <FormField label="Handler"><Input value={pl.handler} onChange={setP("handler")} ariaLabel="Pipeline handler" /></FormField>
              <FormField label="GitHub personal access token - optional"><Input type="password" value={pl.token} onChange={setP("token")} ariaLabel="GitHub personal access token" /></FormField>
            </SpaceBetween>
          </Container>
        </Form>
      </form>
    </CapabilityContainer>
  );
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
        { id: "cicd", label: "CI/CD pipeline application", content: cicdTab },
        { id: "serverless", label: "Serverless application", content: serverlessApplicationTab },
        { id: "composer", label: "Build with Infrastructure Composer", content: <CapabilityContainer id="lambda.application.infrastructure-composer" title="Build with Infrastructure Composer"><Composer /></CapabilityContainer> },
      ]} />
    </ContentLayout>
  );
}
