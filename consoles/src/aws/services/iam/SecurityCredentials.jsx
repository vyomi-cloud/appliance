/* "My security credentials" — the account (root) user's credentials page reached from the
 * Dashboard quick link. Root MFA, root access keys and X.509 certificates are real (the same
 * sections as an IAM user's Security credentials tab, targeting the root principal - see
 * core/iam_core.py ROOT_USER); CloudFront key pairs are real too (core/cloudfront_keys_core.py). */
import Box from "@cloudscape-design/components/box";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { useAsync } from "../../../common/useAsync.js";
import { ErrorAlert, KeyValue } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { MfaSection, AccessKeysSection } from "./UserDetail.jsx";
import { SigningCertsSection } from "./CredentialSections.jsx";
import CloudFrontKeys from "./CloudFrontKeys.jsx";
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
        <CloudFrontKeys />
        <SigningCertsSection userName="root" />
      </SpaceBetween>
    </ContentLayout>
  );
}
