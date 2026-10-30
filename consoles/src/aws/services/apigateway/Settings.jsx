import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Modal from "@cloudscape-design/components/modal";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { KeyValue, ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function Settings() {
  const notify = useNotify();
  const t = useAsync(() => api.getAccount(), []);
  const [edit, setEdit] = useState(null);
  const [error, setError] = useState(null);

  return (
    <ContentLayout header={<Header variant="h1">Settings</Header>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <Container header={<Header variant="h2" actions={<Button onClick={() => setEdit(t.data?.cloudwatchRoleArn || "")}>Edit</Button>}>Logging</Header>}>
          <KeyValue items={[["CloudWatch log role ARN", t.data?.cloudwatchRoleArn || "-"]]} />
        </Container>
        <Container header={<Header variant="h2">Throttling</Header>}>
          <KeyValue items={[["Account-level throttling",
            t.data ? `Rate: ${t.data.throttleSettings.rateLimit} requests/second, Burst: ${t.data.throttleSettings.burstLimit}` : "-"]]} />
        </Container>
      </SpaceBetween>
      <Modal visible={edit !== null} onDismiss={() => setEdit(null)} header="Edit CloudWatch log role ARN"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setEdit(null)}>Cancel</Button>
          <Button variant="primary" onClick={async () => {
            try { await api.updateAccount([{ op: "replace", path: "/cloudwatchRoleArn", value: edit || null }]); notify.success("Account settings updated."); setEdit(null); t.reload(); }
            catch (e) { setError(e); }
          }}>Save changes</Button>
        </SpaceBetween></Box>}>
        <FormField label="CloudWatch log role ARN"><Input value={edit || ""} onChange={({ detail }) => setEdit(detail.value)} ariaLabel="CloudWatch log role ARN" /></FormField>
      </Modal>
    </ContentLayout>
  );
}
