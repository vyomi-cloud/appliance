/* Credential report — real GenerateCredentialReport + GetCredentialReport, base64
 * decoded and downloaded as a .csv Blob. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Container from "@cloudscape-design/components/container";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { useNotify } from "../../../common/notify.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import * as api from "./api.js";

export default function CredentialReport() {
  const notify = useNotify();
  const [busy, setBusy] = useState(false);

  const download = async () => {
    setBusy(true);
    try {
      await api.generateCredentialReport();
      const r = await api.getCredentialReport();
      const csv = atob(r.Content);
      const blob = new Blob([csv], { type: "text/csv" });
      const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "credential_report.csv"; a.click();
      notify.success("Credential report downloaded.");
    } catch (e) { notify.error(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Credentials report of IAM users in this account</Header>}>
      <Container header={<Header variant="h2" actions={<CapabilityBadge id="iam.credential-report" />}>Credentials report</Header>}>
        <SpaceBetween size="m">
          <Box color="text-body-secondary">Download a report of all IAM users in your account and the status of their various credentials.</Box>
          <Button variant="primary" loading={busy} onClick={download}>Download credentials report</Button>
        </SpaceBetween>
      </Container>
    </ContentLayout>
  );
}
