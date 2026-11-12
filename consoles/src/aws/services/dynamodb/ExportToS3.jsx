import { useState } from "react";
import Form from "@cloudscape-design/components/form";
import Header from "@cloudscape-design/components/header";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import RadioGroup from "@cloudscape-design/components/radio-group";
import ExpandableSection from "@cloudscape-design/components/expandable-section";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import Box from "@cloudscape-design/components/box";
import ContentLayout from "@cloudscape-design/components/content-layout";
import { useNotify } from "../../../common/notify.jsx";
import { follow, navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { ErrorAlert } from "../../kit/common.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import * as api from "./api.js";

// "s3://bucket/prefix" -> {bucket, prefix}; the spec's own help text format.
function parseS3Url(url) {
  const m = /^s3:\/\/([^/]+)\/?(.*)$/.exec(url.trim());
  return m ? { bucket: m[1], prefix: m[2] } : { bucket: url.trim(), prefix: "" };
}

export default function ExportToS3() {
  const notify = useNotify();
  const tables = useAsync(() => api.listTables(), []);
  const [table, setTable] = useState("");
  const [dest, setDest] = useState("");
  const [owner, setOwner] = useState("This AWS account");
  const [exportType, setExportType] = useState("Point-in-time export");
  const [fromTime, setFromTime] = useState("Current time");
  const [format, setFormat] = useState("DynamoDB JSON");
  const [sse, setSse] = useState("Amazon S3 key (SSE-S3)");
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const destErr = touched && !/^s3:\/\/[^/]+\/?.*$/.test(dest.trim()) ? 'Destination must be in the format "s3://bucket/prefix".' : null;

  const submit = async () => {
    setTouched(true);
    if (!table || destErr || !dest.trim()) return;
    setBusy(true); setError(null);
    const { bucket, prefix } = parseS3Url(dest);
    try {
      const exp = await api.exportTableToPointInTime({
        TableName: table,
        S3Bucket: bucket,
        ...(prefix ? { S3Prefix: prefix } : {}),
        ExportType: exportType === "Incremental data export" ? "INCREMENTAL_EXPORT" : "FULL_EXPORT",
        ExportFormat: format === "Amazon Ion" ? "ION" : "DYNAMODB_JSON",
        S3SseAlgorithm: sse === "AWS KMS key (SSE-KMS)" ? "KMS" : "AES256",
      });
      if (exp.ExportStatus === "FAILED") throw Object.assign(new Error(exp.FailureMessage || "Export failed."), { code: exp.FailureCode });
      notify.success(`Exporting table "${table}" to Amazon S3.`);
      navigate("dynamodb", "exports");
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1" actions={<CapabilityBadge id="dynamodb.exports" />}>Export table to Amazon S3</Header>}>
      <form onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <Form errorText={error && <ErrorAlert error={error} />} actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button formAction="none" variant="link" href="#/dynamodb/exports" onFollow={follow}>Cancel</Button>
            <Button variant="primary" loading={busy}>Export</Button>
          </SpaceBetween>
        }>
          <SpaceBetween size="l">
            <Container header={<Header variant="h2">Export details</Header>}>
              <SpaceBetween size="l">
                <FormField label="Source table" errorText={touched && !table ? "Source table is required." : null}
                  description="Note that you can't export archived tables to Amazon S3.">
                  <Select selectedOption={table ? { value: table, label: table } : null}
                    options={(tables.data || []).map((t) => ({ value: t, label: t }))}
                    onChange={({ detail }) => setTable(detail.selectedOption.value)} placeholder="Choose a table" ariaLabel="Source table" />
                </FormField>
                <FormField label="Destination S3 bucket" errorText={destErr} description="Format: s3://bucket/prefix">
                  <Input value={dest} onChange={({ detail }) => setDest(detail.value)} placeholder="s3://bucket/prefix" ariaLabel="Destination S3 bucket" />
                </FormField>
                <FormField label="S3 bucket owner">
                  <RadioGroup value={owner} onChange={({ detail }) => setOwner(detail.value)}
                    items={[{ value: "This AWS account", label: "This AWS account" }, { value: "A different AWS account", label: "A different AWS account" }]} />
                </FormField>
              </SpaceBetween>
            </Container>

            <ExpandableSection headerText="Filter table data - optional">
              <Box color="text-body-secondary">No filters applied. The full table is exported.</Box>
            </ExpandableSection>

            <Container header={<Header variant="h2">Export settings</Header>}>
              <SpaceBetween size="l">
                <FormField label="Export type">
                  <RadioGroup value={exportType} onChange={({ detail }) => setExportType(detail.value)}
                    items={[{ value: "Point-in-time export", label: "Point-in-time export" }, { value: "Incremental data export", label: "Incremental data export" }]} />
                </FormField>
                <FormField label="Export from a specific point in time">
                  <RadioGroup value={fromTime} onChange={({ detail }) => setFromTime(detail.value)}
                    items={[{ value: "Current time", label: "Current time" }, { value: "Export from an earlier point in time", label: "Export from an earlier point in time" }]} />
                </FormField>
              </SpaceBetween>
            </Container>

            <ExpandableSection headerText="Additional settings">
              <SpaceBetween size="l">
                <FormField label="Exported file format">
                  <RadioGroup value={format} onChange={({ detail }) => setFormat(detail.value)}
                    items={[{ value: "DynamoDB JSON", label: "DynamoDB JSON" }, { value: "Amazon Ion", label: "Amazon Ion" }]} />
                </FormField>
                <FormField label="Encryption key type">
                  <RadioGroup value={sse} onChange={({ detail }) => setSse(detail.value)}
                    items={[{ value: "Amazon S3 key (SSE-S3)", label: "Amazon S3 key (SSE-S3)" }, { value: "AWS KMS key (SSE-KMS)", label: "AWS KMS key (SSE-KMS)" }]} />
                </FormField>
              </SpaceBetween>
            </ExpandableSection>
          </SpaceBetween>
        </Form>
      </form>
    </ContentLayout>
  );
}
