import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import { CapabilityContainer } from "../../kit/Capability.jsx";

export default function Settings() {
  return (
    <ContentLayout header={<Header variant="h1">Settings</Header>}>
      <CapabilityContainer id="aws.vpc.console-settings" title="Console preferences" />
    </ContentLayout>
  );
}
