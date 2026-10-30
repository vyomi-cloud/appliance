/* Create role — 3-step wizard. "AWS service" use cases map to canned trust policies;
 * other trusted-entity types (account/web identity/SAML/custom) take a real JSON/ARN. */
import { useState } from "react";
import Wizard from "@cloudscape-design/components/wizard";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Textarea from "@cloudscape-design/components/textarea";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Select from "@cloudscape-design/components/select";
import Table from "@cloudscape-design/components/table";
import ExpandableSection from "@cloudscape-design/components/expandable-section";
import Checkbox from "@cloudscape-design/components/checkbox";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Box from "@cloudscape-design/components/box";
import TagEditor from "@cloudscape-design/components/tag-editor";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

const SERVICE_USE_CASES = {
  "EC2": "ec2.amazonaws.com", "Lambda": "lambda.amazonaws.com", "ECS Task": "ecs-tasks.amazonaws.com",
  "EC2 - Auto Scaling": "autoscaling.amazonaws.com", "API Gateway": "apigateway.amazonaws.com",
  "CloudFormation": "cloudformation.amazonaws.com", "Step Functions": "states.amazonaws.com", "Glue": "glue.amazonaws.com",
};

const trustDoc = (s) => {
  if (s.entityType === "service") {
    return JSON.stringify({ Version: "2012-10-17", Statement: [{ Effect: "Allow", Principal: { Service: SERVICE_USE_CASES[s.useCase] || "ec2.amazonaws.com" }, Action: "sts:AssumeRole" }] }, null, 2);
  }
  if (s.entityType === "account") {
    return JSON.stringify({ Version: "2012-10-17", Statement: [{ Effect: "Allow", Principal: { AWS: s.accountId || "123456789012" }, Action: "sts:AssumeRole" }] }, null, 2);
  }
  if (s.entityType === "custom") return s.customPolicy;
  return JSON.stringify({ Version: "2012-10-17", Statement: [{ Effect: "Allow", Principal: { Federated: s.providerArn || "arn:aws:iam::123456789012:oidc-provider/example.com" }, Action: "sts:AssumeRoleWithWebIdentity" }] }, null, 2);
};

function TrustStep({ s, set }) {
  return (
    <SpaceBetween size="l">
      <Container header={<Header variant="h2">Trusted entity type</Header>}>
        <RadioGroup value={s.entityType} onChange={({ detail }) => set({ entityType: detail.value })}
          items={[
            { value: "service", label: "AWS service" }, { value: "account", label: "AWS account" },
            { value: "web", label: "Web identity" }, { value: "saml", label: "SAML 2.0 federation" }, { value: "custom", label: "Custom trust policy" },
          ]} />
      </Container>
      {s.entityType === "service" && (
        <Container header={<Header variant="h2">Use case</Header>}>
          <FormField label="Service or use case" constraintText="Service or use case is required.">
            <Select selectedOption={s.useCase ? { value: s.useCase, label: s.useCase } : null}
              onChange={({ detail }) => set({ useCase: detail.selectedOption.value })}
              options={Object.keys(SERVICE_USE_CASES).map((k) => ({ value: k, label: k }))} placeholder="Choose a service or use case" />
          </FormField>
        </Container>
      )}
      {s.entityType === "account" && (
        <Container header={<Header variant="h2">Account ID</Header>}>
          <FormField label="Account ID"><Input value={s.accountId} onChange={({ detail }) => set({ accountId: detail.value })} ariaLabel="Account ID" /></FormField>
        </Container>
      )}
      {(s.entityType === "web" || s.entityType === "saml") && (
        <Container header={<Header variant="h2">Identity provider</Header>}>
          <FormField label="Provider ARN"><Input value={s.providerArn} onChange={({ detail }) => set({ providerArn: detail.value })} ariaLabel="Provider ARN" /></FormField>
        </Container>
      )}
      {s.entityType === "custom" && (
        <Container header={<Header variant="h2">Custom trust policy</Header>}>
          <FormField label="Custom trust policy"><Textarea rows={12} value={s.customPolicy} onChange={({ detail }) => set({ customPolicy: detail.value })} spellcheck={false} /></FormField>
        </Container>
      )}
    </SpaceBetween>
  );
}

function PermissionsStep({ s, set, policies }) {
  return (
    <SpaceBetween size="l">
      <Container header={<Header variant="h2">Permissions policies</Header>}>
        <Table variant="embedded" items={policies} trackBy="Arn" selectionType="multi"
          selectedItems={policies.filter((p) => s.selectedPolicies.includes(p.Arn))}
          onSelectionChange={({ detail }) => set({ selectedPolicies: detail.selectedItems.map((p) => p.Arn) })}
          columnDefinitions={[{ id: "name", header: "Policy name", cell: (p) => p.PolicyName }, { id: "type", header: "Type", cell: () => "Managed" }, { id: "desc", header: "Description", cell: (p) => p.Description || "-" }]}
          empty={<Box textAlign="center" color="inherit"><b>No policies</b></Box>} />
      </Container>
      <ExpandableSection headerText="Set permissions boundary - optional">
        <Checkbox checked={s.useBoundary} onChange={({ detail }) => set({ useBoundary: detail.checked })}>Use a permissions boundary to control the maximum role permissions</Checkbox>
        {s.useBoundary && (
          <FormField label="Policy">
            <Select selectedOption={s.boundaryArn ? { value: s.boundaryArn, label: policies.find((p) => p.Arn === s.boundaryArn)?.PolicyName } : null}
              onChange={({ detail }) => set({ boundaryArn: detail.selectedOption.value })}
              options={policies.map((p) => ({ value: p.Arn, label: p.PolicyName }))} placeholder="Choose a policy" />
          </FormField>
        )}
      </ExpandableSection>
    </SpaceBetween>
  );
}

function NameReviewStep({ s, set, goto }) {
  return (
    <SpaceBetween size="l">
      <Container header={<Header variant="h2">Role details</Header>}>
        <SpaceBetween size="m">
          <FormField label="Role name" constraintText="Maximum 64 characters. Use alphanumeric and '+=,.@-_' characters.">
            <Input value={s.roleName} onChange={({ detail }) => set({ roleName: detail.value })} ariaLabel="Role name" />
          </FormField>
          <FormField label="Description" constraintText="Maximum 1000 characters.">
            <Textarea value={s.description} onChange={({ detail }) => set({ description: detail.value })} ariaLabel="Description" />
          </FormField>
        </SpaceBetween>
      </Container>
      <Container header={<Header variant="h2" actions={<a onClick={() => goto(0)} style={{ cursor: "pointer" }}>Edit</a>}>Step 1: Select trusted entities</Header>}>
        <Box variant="code"><pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{trustDoc(s)}</pre></Box>
      </Container>
      <Container header={<Header variant="h2" actions={<a onClick={() => goto(1)} style={{ cursor: "pointer" }}>Edit</a>}>Step 2: Add permissions</Header>}>
        <Table variant="embedded" items={s.selectedPolicies.map((arn) => ({ name: arn, type: "Managed", as: "Permissions policy" }))}
          columnDefinitions={[{ id: "n", header: "Policy name", cell: (r) => r.name }, { id: "t", header: "Type", cell: (r) => r.type }, { id: "a", header: "Attached as", cell: (r) => r.as }]}
          empty={<Box textAlign="center" color="inherit"><b>No policies</b></Box>} />
      </Container>
      <Container header={<Header variant="h2">Add tags - optional</Header>}>
        <FormField label="Tags"><TagEditor tags={s.tags} onChange={({ detail }) => set({ tags: detail.tags })} /></FormField>
      </Container>
    </SpaceBetween>
  );
}

export default function CreateRole() {
  const notify = useNotify();
  const [idx, setIdx] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const data = useAsync(() => api.listPolicies(), []);
  const [s, setS] = useState({
    entityType: "service", useCase: "EC2", accountId: "", providerArn: "",
    customPolicy: '{\n  "Version": "2012-10-17",\n  "Statement": []\n}',
    selectedPolicies: [], useBoundary: false, boundaryArn: "",
    roleName: "", description: "", tags: [],
  });
  const set = (patch) => setS((prev) => ({ ...prev, ...patch }));
  if (data.loading) return <Box padding="l">Loading…</Box>;
  const policies = data.data;

  const finish = async () => {
    setBusy(true); setError(null);
    try {
      await api.createRole({
        RoleName: s.roleName, Description: s.description, AssumeRolePolicyDocument: trustDoc(s),
      });
      for (const arn of s.selectedPolicies) await api.attachRolePolicy(s.roleName, arn);
      if (s.useBoundary && s.boundaryArn) await api.putRolePermissionsBoundary(s.roleName, s.boundaryArn);
      const tags = s.tags.filter((t) => !t.markedForRemoval && t.key);
      if (tags.length) await api.tagRole(s.roleName, tags);
      notify.success(`Role "${s.roleName}" created.`);
      navigate("iam", "roles", s.roleName);
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  const steps = [
    { title: "Select trusted entity", content: <TrustStep s={s} set={set} /> },
    { title: "Add permissions", content: <PermissionsStep s={s} set={set} policies={policies} /> },
    { title: "Name, review, and create", content: <>
      {error && <Box padding={{ bottom: "s" }}><ErrorAlert error={error} header="Couldn't create role" /></Box>}
      <NameReviewStep s={s} set={set} goto={setIdx} />
    </> },
  ];

  return (
    <Box padding={{ top: "l" }}>
      <Wizard
        activeStepIndex={idx}
        onNavigate={({ detail }) => setIdx(detail.requestedStepIndex)}
        onCancel={() => navigate("iam", "roles")}
        onSubmit={finish}
        isLoadingNextStep={busy}
        submitButtonText="Create role"
        i18nStrings={{ stepNumberLabel: (n) => `Step ${n}`, collapsedStepsLabel: (n, total) => `Step ${n} of ${total}`, cancelButton: "Cancel", previousButton: "Previous", nextButton: "Next", optional: "optional" }}
        steps={steps}
      />
    </Box>
  );
}
