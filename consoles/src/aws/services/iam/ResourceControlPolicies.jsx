/* Resource control policies (RCPs) — real create/list/delete on the AWS Organizations wire. */
import OrgPolicyList from "./OrgPolicyList.jsx";

export default function ResourceControlPolicies() {
  return <OrgPolicyList type="RESOURCE_CONTROL_POLICY" resourceName="Resource control policies (RCPs)" base="resource-control-policies" />;
}
