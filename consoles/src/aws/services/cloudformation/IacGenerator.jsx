/* IaC generator — scanning an account's existing resources into a template is the
 * declared gap (core/capabilities/aws/cloudformation.json: aws.cloudformation.iac-generator). */
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Tabs from "@cloudscape-design/components/tabs";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { NotSimulatedContainer } from "../../kit/common.jsx";

export default function IacGenerator() {
  return (
    <ContentLayout header={<Header variant="h1">IaC generator</Header>}>
      <SpaceBetween size="l">
        <NotSimulatedContainer title="How it works" note="Scanning existing account resources into a generated template isn't modeled by Vyomi — build templates by hand in Template studio instead." />
        <Tabs tabs={[
          { id: "scan-summary", label: "Scan summary", content: (
            <SpaceBetween size="l">
              <NotSimulatedContainer title="Scans" note="Last completed scan, days until expiry, last attempted scan, resources scanned, scan status, selected scan ID (active), scan type." />
              <NotSimulatedContainer title="Scanned resources breakdown" />
            </SpaceBetween>
          ) },
          { id: "templates", label: "Templates", content: <NotSimulatedContainer title="Templates" /> },
        ]} />
      </SpaceBetween>
    </ContentLayout>
  );
}
