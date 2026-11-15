/* Shared pieces of the Infer + Tune pages: the real console's page header (title + Info), the "How it works" card, S3/model pickers. */
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import ExpandableSection from "@cloudscape-design/components/expandable-section";
import Header from "@cloudscape-design/components/header";
import Link from "@cloudscape-design/components/link";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import { useAsync } from "../../../../common/useAsync.js";
import * as base from "../api.js";
import { fmtDate } from "../../../kit/common.jsx";

export const when = (v) => (v ? fmtDate(v) : "-");

export const Page = ({ title, description, children }) => (
  <ContentLayout header={<Header variant="h1" info={<Link variant="info">Info</Link>} description={description}>{title}</Header>}>
    <SpaceBetween size="l">{children}</SpaceBetween>
  </ContentLayout>
);

/** "How it works": steps = [{title, body, action?}] in equal columns. */
export const HowItWorks = ({ steps }) => (
  <Container header={<Header variant="h2">How it works</Header>}>
    <ColumnLayout columns={steps.length} variant="text-grid">
      {steps.map((s) => (
        <SpaceBetween size="xs" key={s.title}>
          <Box variant="h4">{s.title}</Box>
          <Box color="text-body-secondary">{s.body}</Box>
          {s.action}
        </SpaceBetween>
      ))}
    </ColumnLayout>
  </Container>
);

export const jobStatus = (s) => (
  <StatusIndicator type={["Completed", "InService", "Registered", "AVAILABLE", "ACTIVE", "Active"].includes(s) ? "success" : ["Failed", "Expired", "NotRegistered"].includes(s) ? "error" : ["Stopped", "Stopping"].includes(s) ? "stopped" : "in-progress"}>{s}</StatusIndicator>
);

export const providerOf = (modelId) => {
  const p = String(modelId || "").replace(/^arn:.*\//, "").replace(/^(us|eu|apac|global)\./, "").split(".")[0];
  return ({ anthropic: "Anthropic", amazon: "Amazon", meta: "Meta", cohere: "Cohere", mistral: "Mistral AI" })[p] || p || "-";
};
export const modelOf = (arnOrId) => String(arnOrId || "").replace(/^arn:.*\//, "");

const REGIONS = { "us-east-1": "US East (N. Virginia)", "us-east-2": "US East (Ohio)", "us-west-2": "US West (Oregon)", "eu-north-1": "Europe (Stockholm)", "eu-west-3": "Europe (Paris)", "eu-south-1": "Europe (Milan)",
  "eu-south-2": "Europe (Spain)", "eu-west-1": "Europe (Ireland)", "eu-central-1": "Europe (Frankfurt)", "ap-northeast-1": "Asia Pacific (Tokyo)", "ap-northeast-2": "Asia Pacific (Seoul)",
  "ap-south-1": "Asia Pacific (Mumbai)", "ap-southeast-1": "Asia Pacific (Singapore)", "ap-southeast-2": "Asia Pacific (Sydney)" };
export const regionOf = (arn) => (String(arn).match(/^arn:aws[a-z-]*:bedrock:([a-z0-9-]+):/) || [])[1];
export const regionName = (r) => `${REGIONS[r] || r} ${r}`;

/** Foundation-model picker over ListFoundationModels (ids only; the real console lists every enabled model). */
export function useModelOptions() {
  const t = useAsync(() => base.listModels(), []);
  const opts = (t.data || []).filter((m) => (m.outputModalities || []).includes("TEXT")).map((m) => ({ label: m.modelName, value: m.modelId, description: m.modelId, tags: [m.providerName] }));
  return { options: opts, loading: t.loading };
}
export const ModelSelect = ({ value, onChange, ariaLabel = "Model", options, loading }) => (
  <Select selectedOption={options.find((o) => o.value === value) || null} onChange={({ detail }) => onChange(detail.selectedOption.value)} options={options}
    statusType={loading ? "loading" : "finished"} placeholder="Choose a model" ariaLabel={ariaLabel} filteringType="auto" />
);

export const CreateButton = ({ children, onClick, primary = true, disabled }) => <Button variant={primary ? "primary" : "normal"} onClick={onClick} disabled={disabled}>{children}</Button>;
export { ExpandableSection };

import { useState } from "react";
import Modal from "@cloudscape-design/components/modal";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import { ErrorAlert } from "../../../kit/common.jsx";

/** A create wizard in one modal: calls `onSubmit` (the real API), shows the modeled error inline, closes on success. */
export function CreateModal({ visible, onDismiss, header, submitLabel = "Create", onSubmit, disabled, children, size = "medium" }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const go = async () => {
    setBusy(true); setError(null);
    try { await onSubmit(); onDismiss(); } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible={visible} onDismiss={onDismiss} header={header} size={size}
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button><Button variant="primary" loading={busy} disabled={disabled} onClick={go}>{submitLabel}</Button></SpaceBetween></Box>}>
      <SpaceBetween size="m">
        {error && <ErrorAlert error={error} header="Request failed" />}
        {children}
      </SpaceBetween>
    </Modal>
  );
}

export const Field = ({ label, description, constraint, value, onChange, placeholder, type }) => (
  <FormField label={label} description={description} constraintText={constraint}>
    <Input value={value} onChange={({ detail }) => onChange(detail.value)} placeholder={placeholder} type={type} ariaLabel={label} />
  </FormField>
);
