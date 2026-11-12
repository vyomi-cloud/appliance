/* Service control policies (SCPs) — real create/list/delete on the AWS Organizations wire. */
import OrgPolicyList from "./OrgPolicyList.jsx";

export default function ServiceControlPolicies() {
  return <OrgPolicyList type="SERVICE_CONTROL_POLICY" resourceName="Service control policies (SCPs)" base="service-control-policies" />;
}
