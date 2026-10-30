/* Create Event Function — author from scratch (the only path Vyomi's sandbox can run;
 * blueprint/container-image aren't captured in the spec either — see ui-spec notes). */
import { useState } from "react";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Form from "@cloudscape-design/components/form";
import Header from "@cloudscape-design/components/header";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Toggle from "@cloudscape-design/components/toggle";
import Checkbox from "@cloudscape-design/components/checkbox";
import ExpandableSection from "@cloudscape-design/components/expandable-section";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import Box from "@cloudscape-design/components/box";
import { follow, navigate } from "../../../common/router.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

const RUNTIMES = ["Node.js 24.x", "Node.js 22.x", "Node.js 20.x", "Python 3.14", "Python 3.13", "Python 3.12",
  "Python 3.11", "Python 3.10", "Java 25", "Java 21", "Java 17", "Java 11", "Java 8 on Amazon Linux 2",
  ".NET 10", ".NET 8", "Ruby 3.4", "Ruby 3.3", "Amazon Linux 2023", "Amazon Linux 2"];

export function runtimeId(label) {
  if (/^Python/.test(label)) return "python" + (label.match(/[\d.]+/) || ["3.12"])[0];
  if (/^Node\.js/.test(label)) return "nodejs" + (label.match(/[\d.]+x?/) || ["20.x"])[0];
  if (/^Java/.test(label)) return "java" + (label.match(/[\d]+/) || ["21"])[0];
  if (/^\.NET/.test(label)) return "dotnet" + (label.match(/[\d]+/) || ["8"])[0];
  if (/^Ruby/.test(label)) return "ruby" + (label.match(/[\d.]+/) || ["3.3"])[0];
  if (/Amazon Linux 2023/.test(label)) return "provided.al2023";
  if (/Amazon Linux 2/.test(label)) return "provided.al2";
  return label.toLowerCase().replace(/[^a-z0-9.]/g, "");
}

export default function CreateFunction() {
  const notify = useNotify();
  const [method, setMethod] = useState("Author from scratch");
  const [name, setName] = useState("");
  const [runtime, setRuntime] = useState({ value: "Node.js 24.x", label: "Node.js 24.x" });
  const [durable, setDurable] = useState(false);
  const [ec2Provider, setEc2Provider] = useState(false);
  const [arch, setArch] = useState("x86_64");
  const [roleMode, setRoleMode] = useState("Create a new role with basic Lambda permissions");
  const [existingRole, setExistingRole] = useState("");
  const [enableUrl, setEnableUrl] = useState(false);
  const [authType, setAuthType] = useState("AWS_IAM");
  const [tenantIsolation, setTenantIsolation] = useState(false);
  const [enableVpc, setEnableVpc] = useState(false);
  const [codeSigning, setCodeSigning] = useState(false);
  const [kmsEncryption, setKmsEncryption] = useState(false);
  const [enableTags, setEnableTags] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    if (!name.trim()) return;
    setBusy(true); setError(null);
    try {
      const rid = runtimeId(runtime.value);
      const role = roleMode === "Use an existing role" && existingRole
        ? existingRole : "arn:aws:iam::123456789012:role/service-role/lambda-basic-execution";
      await api.createFunction({
        FunctionName: name, Runtime: rid, Architectures: [arch], Role: role,
        Code: { Source: api.defaultSource(rid) },
      });
      if (enableUrl) await api.createFunctionUrlConfig(name, { AuthType: authType });
      notify.success(`Successfully created function "${name}"`);
      navigate("lambda", "functions", name);
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create Event Function</Header>}>
      <form onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <Form
          actions={<SpaceBetween direction="horizontal" size="xs">
            <Button formAction="none" variant="link" href="#/lambda/functions" onFollow={follow}>Cancel</Button>
            <Button variant="primary" loading={busy}>Create Event Function</Button>
          </SpaceBetween>}
          errorText={error && <ErrorAlert error={error} />}
        >
          <SpaceBetween size="l">
            <Container header={<Header variant="h3">(create method)</Header>}>
              <FormField label="Create method">
                <RadioGroup value={method} onChange={({ detail }) => setMethod(detail.value)} items={[
                  { value: "Author from scratch", label: "Author from scratch" },
                  { value: "Use a blueprint", label: "Use a blueprint", disabled: true, description: "Not available in Vyomi — author from scratch instead." },
                  { value: "Container image", label: "Container image", disabled: true, description: "Not available in Vyomi — author from scratch instead." },
                ]} />
              </FormField>
            </Container>

            <Container header={<Header variant="h2">Basic information</Header>}>
              <SpaceBetween size="l">
                <FormField label="Function name" constraintText="1 to 64 characters, unique to the Region, no spaces; a-z, A-Z, 0-9, hyphens (-), underscores (_)">
                  <Input value={name} placeholder="myFunctionName" onChange={({ detail }) => setName(detail.value)} ariaLabel="Function name" />
                </FormField>
                <FormField label="Runtime" description="Choose the language to use to write your function.">
                  <Select selectedOption={runtime} onChange={({ detail }) => setRuntime(detail.selectedOption)}
                    options={RUNTIMES.map((v) => ({ value: v, label: v }))} />
                </FormField>
                <FormField label="Permissions" description="By default Lambda creates an execution role that can upload logs to CloudWatch Logs.">
                  <Box color="text-body-secondary">lambda-basic-execution</Box>
                </FormField>
              </SpaceBetween>
            </Container>

            <Container header={<Header variant="h2">Custom settings</Header>}>
              <SpaceBetween size="l">
                <Toggle checked={durable} onChange={({ detail }) => setDurable(detail.checked)}>
                  Durable execution — Build resilient, stateful applications with automatic failure recovery.
                </Toggle>
                <Toggle checked={ec2Provider} onChange={({ detail }) => setEc2Provider(detail.checked)}>
                  EC2 capacity provider — Run Lambda on your preferred EC2 instance types instead of Lambda's serverless compute.
                </Toggle>
              </SpaceBetween>
            </Container>

            <ExpandableSection headerText="Additional settings" variant="container">
              <SpaceBetween size="l">
                <FormField label="Architecture">
                  <RadioGroup value={arch} onChange={({ detail }) => setArch(detail.value)}
                    items={[{ value: "x86_64", label: "x86_64" }, { value: "arm64", label: "arm64" }]} />
                </FormField>
                <FormField label="Execution role">
                  <RadioGroup value={roleMode} onChange={({ detail }) => setRoleMode(detail.value)} items={[
                    { value: "Create a new role with basic Lambda permissions", label: "Create a new role with basic Lambda permissions" },
                    { value: "Use an existing role", label: "Use an existing role" },
                    { value: "Create a new role from AWS policy templates", label: "Create a new role from AWS policy templates" },
                  ]} />
                </FormField>
                {roleMode === "Use an existing role" && (
                  <FormField label="Existing role">
                    <Select selectedOption={existingRole ? { value: existingRole, label: existingRole } : null}
                      onChange={({ detail }) => setExistingRole(detail.selectedOption.value)}
                      options={[{ value: "arn:aws:iam::123456789012:role/service-role/lambda-basic-execution", label: "lambda-basic-execution" }]}
                      placeholder="Choose a role" />
                  </FormField>
                )}
                <Checkbox checked={enableUrl} onChange={({ detail }) => setEnableUrl(detail.checked)}>Enable function URL</Checkbox>
                {enableUrl && (
                  <FormField label="Auth type">
                    <RadioGroup value={authType} onChange={({ detail }) => setAuthType(detail.value)}
                      items={[{ value: "AWS_IAM", label: "AWS_IAM" }, { value: "NONE", label: "NONE" }]} />
                  </FormField>
                )}
                <Checkbox checked={tenantIsolation} onChange={({ detail }) => setTenantIsolation(detail.checked)}>Tenant isolation mode</Checkbox>
                <Checkbox checked={enableVpc} onChange={({ detail }) => setEnableVpc(detail.checked)}>Enable VPC</Checkbox>
                <Checkbox checked={codeSigning} onChange={({ detail }) => setCodeSigning(detail.checked)}>Enable code signing</Checkbox>
                <Checkbox checked={kmsEncryption} onChange={({ detail }) => setKmsEncryption(detail.checked)}>Enable encryption with an AWS KMS customer managed key</Checkbox>
                <Checkbox checked={enableTags} onChange={({ detail }) => setEnableTags(detail.checked)}>Enable tags</Checkbox>
              </SpaceBetween>
            </ExpandableSection>
          </SpaceBetween>
        </Form>
      </form>
    </ContentLayout>
  );
}
