import { useState } from "react";
import Wizard from "@cloudscape-design/components/wizard";
import Header from "@cloudscape-design/components/header";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Grid from "@cloudscape-design/components/grid";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Box from "@cloudscape-design/components/box";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import * as api from "./api.js";

const TYPES = [{ value: "S", label: "String" }, { value: "N", label: "Number" }, { value: "B", label: "Binary" }];

function parseS3Url(url) {
  const m = /^s3:\/\/([^/]+)\/?(.*)$/.exec(url.trim());
  return m ? { bucket: m[1], prefix: m[2] } : { bucket: url.trim(), prefix: "" };
}

function KeyField({ label, name, setName, type, setType }) {
  return (
    <Grid gridDefinition={[{ colspan: 8 }, { colspan: 4 }]}>
      <FormField label={label}><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel={label} /></FormField>
      <FormField label={`${label} type`}>
        <Select selectedOption={TYPES.find((t) => t.value === type)} onChange={({ detail }) => setType(detail.selectedOption.value)} options={TYPES} ariaLabel={`${label} type`} />
      </FormField>
    </Grid>
  );
}

function ImportOptionsStep({ s, set, touched }) {
  const sourceErr = touched && !/^s3:\/\/[^/]+\/?.*$/.test(s.source.trim()) ? 'Source must be in the format "s3://bucket/prefix".' : null;
  return (
    <Container header={<Header variant="h2">Import details</Header>}>
      <SpaceBetween size="l">
        <FormField label="Source S3 URL" errorText={sourceErr} description="Example formats: s3://countries or s3://countries/territories/">
          <Input value={s.source} onChange={({ detail }) => set({ source: detail.value })} placeholder="s3://bucket/prefix" ariaLabel="Source S3 URL" />
        </FormField>
        <FormField label="S3 bucket owner">
          <RadioGroup value={s.owner} onChange={({ detail }) => set({ owner: detail.value })}
            items={[{ value: "This AWS account", label: "This AWS account" }, { value: "A different AWS account", label: "A different AWS account" }]} />
        </FormField>
        <FormField label="Import file compression">
          <RadioGroup value={s.compression} onChange={({ detail }) => set({ compression: detail.value })}
            items={[{ value: "No compression", label: "No compression" }, { value: "GZIP", label: "GZIP" }, { value: "ZSTD", label: "ZSTD" }]} />
        </FormField>
        <FormField label="Import file format">
          <RadioGroup value={s.format} onChange={({ detail }) => set({ format: detail.value })}
            items={[{ value: "DynamoDB JSON", label: "DynamoDB JSON" }, { value: "Amazon Ion", label: "Amazon Ion" }, { value: "CSV", label: "CSV" }]} />
        </FormField>
      </SpaceBetween>
    </Container>
  );
}

function DestinationTableStep({ s, set, touched }) {
  return (
    <Container header={<Header variant="h2">Table details</Header>}>
      <SpaceBetween size="l">
        <FormField label="Table name" errorText={touched && !s.tableName ? "Table name is required." : null}>
          <Input value={s.tableName} onChange={({ detail }) => set({ tableName: detail.value })} ariaLabel="Table name" />
        </FormField>
        <FormField label="Partition key" errorText={touched && !s.pk ? "Partition key is required." : null}>
          <KeyField label="Partition key" name={s.pk} setName={(v) => set({ pk: v })} type={s.pkType} setType={(v) => set({ pkType: v })} />
        </FormField>
        <FormField label="Sort key - optional">
          <KeyField label="Sort key" name={s.sk} setName={(v) => set({ sk: v })} type={s.skType} setType={(v) => set({ skType: v })} />
        </FormField>
      </SpaceBetween>
    </Container>
  );
}

function ReviewStep({ s }) {
  return (
    <Container header={<Header variant="h2">Review and import</Header>}>
      <SpaceBetween size="l">
        <Box variant="p">Source: <code>{s.source || "-"}</code> ({s.format}, {s.compression})</Box>
        <Box variant="p">Destination table: <code>{s.tableName || "-"}</code> (partition key: <code>{s.pk || "-"}</code>{s.sk ? <>, sort key: <code>{s.sk}</code></> : null})</Box>
      </SpaceBetween>
    </Container>
  );
}

export default function ImportFromS3() {
  const notify = useNotify();
  const [idx, setIdx] = useState(0);
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [s, setS] = useState({
    source: "", owner: "This AWS account", compression: "No compression", format: "DynamoDB JSON",
    tableName: "", pk: "", pkType: "S", sk: "", skType: "S",
  });
  const set = (patch) => setS((prev) => ({ ...prev, ...patch }));

  const finish = async () => {
    setTouched(true);
    if (!/^s3:\/\/[^/]+\/?.*$/.test(s.source.trim()) || !s.tableName || !s.pk) { setIdx(0); return; }
    setBusy(true); setError(null);
    const { bucket, prefix } = parseS3Url(s.source);
    try {
      const desc = await api.importTable({
        S3BucketSource: { S3Bucket: bucket, ...(prefix ? { S3KeyPrefix: prefix } : {}) },
        InputFormat: s.format === "Amazon Ion" ? "ION" : s.format === "CSV" ? "CSV" : "DYNAMODB_JSON",
        InputCompressionType: s.compression === "GZIP" ? "GZIP" : s.compression === "ZSTD" ? "ZSTD" : "NONE",
        TableCreationParameters: {
          TableName: s.tableName,
          AttributeDefinitions: [{ AttributeName: s.pk, AttributeType: s.pkType }, ...(s.sk ? [{ AttributeName: s.sk, AttributeType: s.skType }] : [])],
          KeySchema: [{ AttributeName: s.pk, KeyType: "HASH" }, ...(s.sk ? [{ AttributeName: s.sk, KeyType: "RANGE" }] : [])],
          BillingMode: "PAY_PER_REQUEST",
        },
      });
      if (desc.ImportStatus === "FAILED") throw Object.assign(new Error(desc.FailureMessage || "Import failed."), { code: desc.FailureCode });
      notify.success(`Imported table "${s.tableName}" from Amazon S3.`);
      navigate("dynamodb", "imports");
    } catch (e) { setError(e); setIdx(2); }
    finally { setBusy(false); }
  };

  const steps = [
    { title: "Import options", content: <ImportOptionsStep s={s} set={set} touched={touched} /> },
    { title: "Destination table", content: <DestinationTableStep s={s} set={set} touched={touched} /> },
    { title: "Review and import", content: <ReviewStep s={s} /> },
  ];

  return (
    <Box padding={{ top: "l" }}>
      <Box padding={{ horizontal: "l" }}><CapabilityBadge id="dynamodb.imports" /></Box>
      {error && <Box padding={{ horizontal: "l", bottom: "s" }}><ErrorAlert error={error} header="Couldn't import table" /></Box>}
      <Wizard
        activeStepIndex={idx}
        onNavigate={({ detail }) => setIdx(detail.requestedStepIndex)}
        onCancel={() => navigate("dynamodb", "imports")}
        onSubmit={finish}
        isLoadingNextStep={busy}
        submitButtonText="Import"
        i18nStrings={{
          stepNumberLabel: (n) => `Step ${n}`,
          collapsedStepsLabel: (n, total) => `Step ${n} of ${total}`,
          cancelButton: "Cancel", previousButton: "Previous", nextButton: "Next", optional: "optional",
        }}
        steps={steps}
      />
    </Box>
  );
}
