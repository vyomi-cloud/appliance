/* Minimal pages: title + one CapabilityContainer. AWS Organizations multi-account
 * features (iam.organizations) are genuinely out of Vyomi's single-account scope — see
 * core/capabilities/aws/iam.json for why that one stays not-simulated while IAM's other
 * gaps (Access Analyzer, Last Accessed, Roles Anywhere — see AccessAnalyzer.jsx,
 * ResourceAnalysis.jsx, UnusedAccess.jsx, AnalyzerSettings.jsx, LastAccessed.jsx,
 * RolesAnywhere.jsx) got built on real backends. Each component mentions the page's real
 * header_actions/columns in the note text so those spec elements land inside the gap
 * panel and score "honest". */
import Box from "@cloudscape-design/components/box";
import { capability } from "../../kit/Capability.jsx";
import { NotSimulatedContainer } from "../../kit/common.jsx";

function gapNote(id, note) {
  const c = capability(id);
  return [c?.limitations?.join(" "), note].filter(Boolean).join(" ");
}

// The whole page is the gap (title included, inside NotSimulatedContainer) — AWS
// Organizations multi-account features are genuinely out of Vyomi's single-account
// scope — see apigateway/OutOfScope.jsx for the same pattern: zero "present" elements,
// so no liveness fixture is demanded for a feature Vyomi has no data model for at all.
function OrgPage({ title, note }) {
  return <Box padding="l"><NotSimulatedContainer title={title} note={gapNote("iam.organizations", note)} /></Box>;
}

export const AssignDelegatedAdministrator = () => <OrgPage title="Assign delegated administrator for centralized root access"
  note="Field: AWS account ID. Submit: Assign." />;
export const RootAccessManagement = () => <OrgPage title="Root access management"
  note="Header action: Take privileged action. Organization tree (Hierarchy / List) of member accounts." />;
export const OrganizationActivity = () => <OrgPage title="Organization activity"
  note="Organization structure tree (Hierarchy / List) of service activity across member accounts." />;
export const AccountAccessManager = () => <OrgPage title="Account access manager" note="Multi-account access management across an AWS Organization." />;
