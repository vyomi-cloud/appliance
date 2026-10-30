/* Account settings — Password policy is real (Edit navigates to the edit page). Role
 * manager, Centralized root access, and STS sections are AWS-Organizations / multi-account
 * features Vyomi (single account) doesn't model. */
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { useAsync } from "../../../common/useAsync.js";
import { navigate } from "../../../common/router.js";
import { ErrorAlert, KeyValue } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
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
        <CapabilityContainer id="iam.organizations" title="Role manager" />
        <CapabilityContainer id="iam.organizations" title="Centralized root access for member accounts" />
        <CapabilityContainer id="iam.organizations" title="Security Token Service (STS)" />
      </SpaceBetween>
    </ContentLayout>
  );
}
