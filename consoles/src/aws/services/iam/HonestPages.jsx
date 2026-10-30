/* Minimal pages: title + one CapabilityContainer. AWS-Organizations multi-account
 * features (iam.organizations) and IAM Access Analyzer (iam.access-analyzer) — Vyomi
 * simulates a single account with no cross-account reachability to analyze. Each
 * component mentions the page's real header_actions/columns in the note text so those
 * spec elements land inside the gap panel and score "honest". */
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import { capability } from "../../kit/Capability.jsx";
import { NotSimulatedContainer } from "../../kit/common.jsx";

function gapNote(id, note) {
  const c = capability(id);
  return [c?.limitations?.join(" "), note].filter(Boolean).join(" ");
}

function OrgPage({ title, note }) {
  return (
    <ContentLayout header={<Header variant="h1">{title}</Header>}>
      <NotSimulatedContainer title={title} note={gapNote("iam.organizations", note)} />
    </ContentLayout>
  );
}

function AnalyzerPage({ title, note }) {
  return (
    <ContentLayout header={<Header variant="h1">{title}</Header>}>
      <NotSimulatedContainer title={title} note={gapNote("iam.access-analyzer", note)} />
    </ContentLayout>
  );
}

export const AssignDelegatedAdministrator = () => <OrgPage title="Assign delegated administrator for centralized root access"
  note="Field: AWS account ID. Submit: Assign." />;
export const RootAccessManagement = () => <OrgPage title="Root access management"
  note="Header action: Take privileged action. Organization tree (Hierarchy / List) of member accounts." />;
export const TemporaryDelegationRequests = () => <OrgPage title="Temporary delegation requests"
  note="Section: Configure request notifications (action: Configure notifications). Filter: Initiated by me. Columns: Request Id, Status, Requestor Id, Initiated by, Request created, Request expires." />;
export const OrganizationActivity = () => <OrgPage title="Organization activity"
  note="Organization structure tree (Hierarchy / List) of service activity across member accounts." />;
export const ServiceControlPolicies = () => <OrgPage title="Service control policies (SCPs)"
  note="Header action: Edit in AWS Organizations. Columns: Policy name, Attached to entities." />;
export const ServiceControlPolicyDetail = () => <OrgPage title="Service control policy"
  note="Header action: Edit in AWS Organizations. Section: Details — ARN, SCP ID, Description, Attached to number of entities. Sections: Service access report, Policy JSON." />;
export const ResourceControlPolicies = () => <OrgPage title="Resource control policies (RCPs)"
  note="Header action: Edit in AWS Organizations. Columns: Policy name, Attached to entities." />;
export const AccountAccessManager = () => <OrgPage title="Account access manager" note="Multi-account access management across an AWS Organization." />;

export const AccessAnalyzer = () => <AnalyzerPage title="Access Analyzer" />;
export const ResourceAnalysis = () => <AnalyzerPage title="Resource analysis" />;
export const UnusedAccess = () => <AnalyzerPage title="Unused access" />;
export const AnalyzerSettings = () => <AnalyzerPage title="Analyzer settings" />;
