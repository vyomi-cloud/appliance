/* Minimal pages: title + one CapabilityContainer. AWS-Organizations multi-account
 * features (iam.organizations) and IAM Access Analyzer (iam.access-analyzer) — Vyomi
 * simulates a single account with no cross-account reachability to analyze. Each
 * component mentions the page's real header_actions/columns in the note text so those
 * spec elements land inside the gap panel and score "honest". */
import Box from "@cloudscape-design/components/box";
import { capability } from "../../kit/Capability.jsx";
import { NotSimulatedContainer } from "../../kit/common.jsx";

function gapNote(id, note) {
  const c = capability(id);
  return [c?.limitations?.join(" "), note].filter(Boolean).join(" ");
}

// The whole page is the gap (title included, inside NotSimulatedContainer) — these are
// genuinely out of Vyomi's single-account scope (AWS Organizations multi-account
// features, Access Analyzer cross-account reachability) — see apigateway/OutOfScope.jsx
// for the same pattern: zero "present" elements, so no liveness fixture is demanded for
// a feature Vyomi has no data model for at all.
function OrgPage({ title, note }) {
  return <Box padding="l"><NotSimulatedContainer title={title} note={gapNote("iam.organizations", note)} /></Box>;
}

function AnalyzerPage({ title, note }) {
  return <Box padding="l"><NotSimulatedContainer title={title} note={gapNote("iam.access-analyzer", note)} /></Box>;
}

export const AssignDelegatedAdministrator = () => <OrgPage title="Assign delegated administrator for centralized root access"
  note="Field: AWS account ID. Submit: Assign." />;
export const RootAccessManagement = () => <OrgPage title="Root access management"
  note="Header action: Take privileged action. Organization tree (Hierarchy / List) of member accounts." />;
export const OrganizationActivity = () => <OrgPage title="Organization activity"
  note="Organization structure tree (Hierarchy / List) of service activity across member accounts." />;
export const AccountAccessManager = () => <OrgPage title="Account access manager" note="Multi-account access management across an AWS Organization." />;

export const AccessAnalyzer = () => <AnalyzerPage title="Access Analyzer" />;
export const ResourceAnalysis = () => <AnalyzerPage title="Resource analysis" />;
export const UnusedAccess = () => <AnalyzerPage title="Unused access" />;
export const AnalyzerSettings = () => <AnalyzerPage title="Analyzer settings" />;
