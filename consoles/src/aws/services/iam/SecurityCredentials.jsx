/* "My security credentials" — the account (root) user's credentials page reached from the
 * Dashboard quick link. Root MFA, root access keys and X.509 certificates are real (the same
 * sections as an IAM user's Security credentials tab, targeting the root principal - see
 * core/iam_core.py ROOT_USER); only CloudFront key pairs are a gap. */
import Box from "@cloudscape-design/components/box";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { useAsync } from "../../../common/useAsync.js";
import { ErrorAlert, KeyValue, NotSimulatedContainer } from "../../kit/common.jsx";
import { MfaSection, AccessKeysSection } from "./UserDetail.jsx";
import { SigningCertsSection } from "./CredentialSections.jsx";
import * as api from "./api.js";

const ACCOUNT_ID = "123456789012";

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
        <MfaSection userName="root" />
        <AccessKeysSection userName="root" />
        <NotSimulatedContainer title="CloudFront key pairs" note="CloudFront signed-URL key pairs for the account root user are legacy and not issued by Vyomi." />
        <SigningCertsSection userName="root" />
      </SpaceBetween>
    </ContentLayout>
  );
}
