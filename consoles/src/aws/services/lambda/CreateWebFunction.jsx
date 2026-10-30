/* Create Web Function — a function plus a Function URL, created together. */
import { useState } from "react";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Form from "@cloudscape-design/components/form";
import Header from "@cloudscape-design/components/header";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import RadioGroup from "@cloudscape-design/components/radio-group";
import ExpandableSection from "@cloudscape-design/components/expandable-section";
import Table from "@cloudscape-design/components/table";
import TagEditor from "@cloudscape-design/components/tag-editor";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import Box from "@cloudscape-design/components/box";
import { follow, navigate } from "../../../common/router.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";
import { runtimeId } from "./CreateFunction.jsx";

const AUTH_TYPES = ["AWS_IAM", "NONE"];

export default function CreateWebFunction() {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [runtime, setRuntime] = useState({ value: "Node.js 24.x", label: "Node.js 24.x" });
  const [codeSource, setCodeSource] = useState("Hello World template");
  const [endpointName, setEndpointName] = useState("");
  const [description, setDescription] = useState("");
  const [type, setType] = useState("Home-Region");
  const [authType, setAuthType] = useState(null);
  const [autoDeploy, setAutoDeploy] = useState("Latest revision");
  const [envVars, setEnvVars] = useState([]);
  const [tags, setTags] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    if (!name.trim() || !endpointName.trim() || !authType) return;
    setBusy(true); setError(null);
    try {
      const rid = runtimeId(runtime.value);
      await api.createFunction({
        FunctionName: name, Runtime: rid, Description: description,
        Code: { Source: api.defaultSource(rid) },
        Environment: { Variables: Object.fromEntries(envVars.filter((v) => v.key).map((v) => [v.key, v.value])) },
        Tags: Object.fromEntries(tags.filter((t) => t.key).map((t) => [t.key, t.value])),
      });
      await api.createFunctionUrlConfig(name, { AuthType: authType });
      notify.success(`Successfully created Web Function "${endpointName}"`);
      navigate("lambda", "functions", name);
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create Web Function</Header>}>
      <form onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <Form
          actions={<SpaceBetween direction="horizontal" size="xs">
            <Button formAction="none" variant="link" href="#/lambda/web-functions" onFollow={follow}>Cancel</Button>
            <Button variant="primary" loading={busy}>Create Web Function</Button>
          </SpaceBetween>}
          errorText={error && <ErrorAlert error={error} />}
        >
          <SpaceBetween size="l">
            <Container header={<Header variant="h2">Basic information</Header>}>
              <SpaceBetween size="l">
                <FormField label="Function name" constraintText="2 to 64 characters; can't start or end with - or _; a-z, A-Z, 0-9, -, _">
                  <Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Function name" />
                </FormField>
                <FormField label="Runtime" description="Select the runtime environment for your function code.">
                  <Select selectedOption={runtime} onChange={({ detail }) => setRuntime(detail.selectedOption)}
                    options={["Node.js 24.x", "Python 3.12", "Ruby 3.4"].map((v) => ({ value: v, label: v }))} />
                </FormField>
              </SpaceBetween>
            </Container>

            <Container header={<Header variant="h2">Code source</Header>}>
              <FormField label="Code source">
                <RadioGroup value={codeSource} onChange={({ detail }) => setCodeSource(detail.value)} items={[
                  { value: "Hello World template", label: "Hello World template" },
                  { value: "Upload ZIP file", label: "Upload ZIP file" },
                  { value: "Amazon S3", label: "Amazon S3" },
                ]} />
              </FormField>
            </Container>

            <Container header={<Header variant="h2">Endpoint configuration</Header>}>
              <SpaceBetween size="l">
                <FormField label="Endpoint name" constraintText="2 to 64 characters; can't start or end with - or _">
                  <Input value={endpointName} onChange={({ detail }) => setEndpointName(detail.value)} ariaLabel="Endpoint name" />
                </FormField>
                <FormField label="Description - optional" constraintText="0 to 256 characters">
                  <Input value={description} onChange={({ detail }) => setDescription(detail.value)} ariaLabel="Description" />
                </FormField>
                <FormField label="Type">
                  <RadioGroup value={type} onChange={({ detail }) => setType(detail.value)} items={[
                    { value: "Home-Region", label: "Home-Region" }, { value: "Multi-Region", label: "Multi-Region" }, { value: "Per-Region", label: "Per-Region" },
                  ]} />
                </FormField>
                <FormField label="Authentication type">
                  <Select selectedOption={authType ? { value: authType, label: authType } : null}
                    onChange={({ detail }) => setAuthType(detail.selectedOption.value)}
                    options={AUTH_TYPES.map((v) => ({ value: v, label: v }))}
                    placeholder="Select an authentication type" />
                </FormField>
                <FormField label="Auto deployment">
                  <RadioGroup value={autoDeploy} onChange={({ detail }) => setAutoDeploy(detail.value)}
                    items={[{ value: "Latest revision", label: "Latest revision" }, { value: "Disabled", label: "Disabled" }]} />
                </FormField>
              </SpaceBetween>
            </Container>

            <ExpandableSection headerText="Additional configurations - optional" variant="container">
              <SpaceBetween size="l">
                <FormField label="Encryption"><Box color="text-body-secondary">AWS managed key (default)</Box></FormField>
                <FormField label="Environment variables">
                  <Table
                    items={envVars}
                    columnDefinitions={[
                      { id: "k", header: "Key", cell: (v, i) => <Input value={v.key} onChange={({ detail }) => setEnvVars(envVars.map((x, j) => j === i ? { ...x, key: detail.value } : x))} ariaLabel="Key" /> },
                      { id: "v", header: "Value", cell: (v, i) => <Input value={v.value} onChange={({ detail }) => setEnvVars(envVars.map((x, j) => j === i ? { ...x, value: detail.value } : x))} ariaLabel="Value" /> },
                    ]}
                    empty={<Box textAlign="center">No environment variables</Box>}
                    footer={<SpaceBetween direction="horizontal" size="xs">
                      <Button onClick={() => setEnvVars([...envVars, { key: "", value: "" }])}>Add environment variable</Button>
                      {envVars.length > 0 && <Button onClick={() => setEnvVars(envVars.slice(0, -1))}>Remove</Button>}
                    </SpaceBetween>}
                  />
                </FormField>
                <FormField label="Tags - optional" description="Key / Value pairs; up to 50 tags">
                  <TagEditor tags={tags} onChange={({ detail }) => setTags(detail.tags)}
                    i18nStrings={{ addButton: "Add new tag", removeButton: "Remove", keyHeader: "Key", valueHeader: "Value", emptyTags: "No tags associated with the resource." }} />
                </FormField>
              </SpaceBetween>
            </ExpandableSection>
          </SpaceBetween>
        </Form>
      </form>
    </ContentLayout>
  );
}
