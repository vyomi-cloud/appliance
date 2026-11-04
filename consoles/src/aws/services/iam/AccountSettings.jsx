/* Account settings — Password policy, STS and Centralized root access (real Organizations/IAM APIs)
 * are real; the Role manager section is a registered gap (iam.organizations.role-manager). */
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { ErrorAlert, KeyValue } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import ServerCertificates from "./ServerCertificates.jsx";
import { CentralizedRootAccessPanel } from "./OrgPages.jsx";
import * as api from "./api.js";

const describeOther = (pol) => {
  if (!pol) return "No additional requirements";
  const reqs = [];
  if (pol.RequireSymbols === "true") reqs.push("at least one non-alphanumeric character");
  if (pol.RequireNumbers === "true") reqs.push("at least one number");
  if (pol.RequireUppercaseCharacters === "true") reqs.push("at least one uppercase letter");
  if (pol.RequireLowercaseCharacters === "true") reqs.push("at least one lowercase letter");
  return reqs.length ? `Requires ${reqs.join(", ")}` : "No additional requirements";
};

function StsPanel() {
  const notify = useNotify();
  const sm = useAsync(() => api.getAccountSummary(), []);
  const v = sm.data?.GlobalEndpointTokenVersion === 2 ? "v2Token" : "v1Token";
  const set = async (next) => { try { await api.setStsPreferences(next); notify.success("STS global endpoint token version updated."); sm.reload(); } catch (e) { notify.error(e); } };
  return (
    <CapabilityContainer id="iam.account-settings.sts" title="Security Token Service (STS)"
      actions={<Button onClick={() => set(v === "v1Token" ? "v2Token" : "v1Token")}>{v === "v1Token" ? "Change to version 2 tokens" : "Change to version 1 tokens"}</Button>}>
      <KeyValue columns={2} items={[
        ["Global endpoint session tokens", v === "v1Token" ? "Valid only in AWS Regions enabled by default (version 1)" : "Valid in all AWS Regions (version 2)"],
        ["Global endpoint", "https://sts.amazonaws.com"],
      ]} />
    </CapabilityContainer>
  );
}

export default function AccountSettings() {
  const p = useAsync(() => api.getAccountPasswordPolicy(), []);
  if (p.loading) return <Box padding="l">Loading…</Box>;
  if (p.error) return <ErrorAlert error={p.error} />;
  const pol = p.data;

  return (
    <ContentLayout header={<Header variant="h1">Account settings</Header>}>
      <SpaceBetween size="l">
        <KeyValue title="Password policy" actions={<Button onClick={() => navigate("iam", "account-settings", "edit-password-policy")}>Edit</Button>} columns={3} items={[
          ["Password minimum length", pol?.MinimumPasswordLength || 8],
          ["Password strength", pol ? "Custom" : "IAM default"],
          ["Other requirements", describeOther(pol)],
        ]} />
        <CapabilityContainer id="iam.organizations.role-manager" title="Role manager" />
        <CentralizedRootAccessPanel />
        <StsPanel />
        <ServerCertificates />
      </SpaceBetween>
    </ContentLayout>
  );
}
