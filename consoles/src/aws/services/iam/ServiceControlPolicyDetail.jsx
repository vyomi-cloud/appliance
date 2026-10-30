/* Service control policy detail — real DescribeOrgPolicy (Vyomi-only wire call, see
 * core/iam_core.py); the service access report needs CloudTrail, which Vyomi doesn't
 * simulate, so that section stays an honest gap. */
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ContentLayout from "@cloudscape-design/components/content-layout";
import CopyToClipboard from "@cloudscape-design/components/copy-to-clipboard";
import Header from "@cloudscape-design/components/header";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Spinner from "@cloudscape-design/components/spinner";
import { useAsync } from "../../../common/useAsync.js";
import { ErrorAlert, KeyValue } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

export default function ServiceControlPolicyDetail({ params }) {
  const name = decodeURIComponent(params.name);
  const p = useAsync(() => api.listOrgPolicies().then((all) => all.find((x) => x.Name === name)), [name]);
  if (p.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (p.error) return <ErrorAlert error={p.error} />;
  const policy = p.data;
  if (!policy) return <ErrorAlert error={{ code: "NotFound", message: `Policy ${name} not found.` }} />;

  let pretty = policy.Content;
  try { pretty = JSON.stringify(JSON.parse(policy.Content), null, 2); } catch { /* leave as-is */ }

  return (
    <ContentLayout header={<Header variant="h1" actions={<Button>Edit in AWS Organizations</Button>}>{policy.Name}</Header>}>
      <SpaceBetween size="l">
        <KeyValue title="Details" columns={2} items={[
          ["ARN", policy.Arn], ["SCP ID", policy.Id],
          ["Description", policy.Description || "-"], ["Attached to number of entities", "0"],
        ]} />
        <CapabilityContainer id="iam.organizations" title="Service access report" />
        <CapabilityContainer id="iam.organizations.policies" title="Policy JSON" actions={<CopyToClipboard variant="icon" textToCopy={pretty} copyButtonAriaLabel="Copy" copySuccessText="Copied" copyErrorText="Couldn't copy" />}>
          <Box variant="code" fontSize="body-s"><pre style={{ whiteSpace: "pre-wrap", margin: 0 }}>{pretty}</pre></Box>
        </CapabilityContainer>
      </SpaceBetween>
    </ContentLayout>
  );
}
