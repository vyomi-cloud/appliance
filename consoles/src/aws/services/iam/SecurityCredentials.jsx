/* "My security credentials" — root-account page reached only from the Dashboard quick
 * link. Account details are real (same account id/alias as the Dashboard); Vyomi models
 * no distinct root principal, so MFA / access keys / CloudFront key pairs / X.509 certs
 * on THIS page are not simulated (there's nothing beyond the IAM users already shown
 * elsewhere to authenticate as "root"). */
import Box from "@cloudscape-design/components/box";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { useAsync } from "../../../common/useAsync.js";
import { ErrorAlert, KeyValue } from "../../kit/common.jsx";
import { NotSimulatedContainer } from "../../kit/common.jsx";
import * as api from "./api.js";

const ACCOUNT_ID = "123456789012";
const NOTE = "Vyomi simulates IAM users and roles, not a distinct root principal — there is no separate root identity to hold MFA devices, access keys, CloudFront key pairs or X.509 certificates.";

export default function SecurityCredentials() {
  const d = useAsync(() => api.listAccountAliases(), []);
  if (d.loading) return <Box padding="l">Loading…</Box>;
  if (d.error) return <ErrorAlert error={d.error} />;
  const alias = (d.data || [])[0];

  return (
    <ContentLayout header={<Header variant="h1">My security credentials</Header>}>
      <SpaceBetween size="l">
        <KeyValue title="Account details" columns={2} actions={<span>Actions</span>} items={[
          ["Account name", alias || ACCOUNT_ID], ["Email address", "-"], ["AWS account ID", ACCOUNT_ID], ["Canonical user ID", "-"],
        ]} />
        <NotSimulatedContainer title="Multi-factor authentication (MFA)" note={NOTE} />
        <NotSimulatedContainer title="Access keys" note={NOTE} />
        <NotSimulatedContainer title="CloudFront key pairs" note={NOTE} />
        <NotSimulatedContainer title="X.509 Signing certificates" note={NOTE} />
      </SpaceBetween>
    </ContentLayout>
  );
}
